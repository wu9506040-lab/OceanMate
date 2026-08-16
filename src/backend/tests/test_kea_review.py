"""KEA 内部 API（approve_case / reject_case）测试 — Day 18 P2-final 反向同步。

Day 18 P2-final 改动：
- 移除聊天审核命令识别（运营去飞书多维表格 review_decisions 表改 decision）
- approve_case / reject_case 改为内部 API，被 /admin/sync-bit 或飞书多维表格 webhook 反向同步调用
- 仍保留写 Chroma + SQLite + 多维表格 sync_review_decision 的完整链路

覆盖：
- approve_case：强制写 Chroma + embedding_meta + review_decisions 留痕
- approve_case：幂等（重复审核 → already_approved）
- approve_case：友好降级（缺 case_id / case 不存在 / 无 DB）
- reject_case：记录到 review_decisions 不写 Chroma
- reject_case：缺 case_id 友好降级
- webhook _fmt_kea_approve / _fmt_kea_reject：内部调用时仍渲染友好反馈
"""

from pathlib import Path

import pytest

from app.agents.kea import KEATool
from app.implementations.feishu.webhook import FeishuWebhookHandler
from app.models import Case, Merchant


# === 通用 fixtures ===

@pytest.fixture
def tmp_chroma_dir(tmp_path):
    """临时 Chroma 数据目录（避免污染 data/chroma/）。"""
    d = tmp_path / "chroma"
    d.mkdir()
    return d


@pytest.fixture
def kea(repos, tmp_chroma_dir):
    """KEA 默认实例（DB + Chroma）。"""
    return KEATool(
        case_repo=repos["case"],
        chroma_path=tmp_chroma_dir,
        embedding_meta_repo=repos["case"].db,
    )


@pytest.fixture
def kea_no_db(tmp_chroma_dir):
    """KEA 无 DB 实例（仅 RAG 检索）。"""
    return KEATool(chroma_path=tmp_chroma_dir)


@pytest.fixture
def pending_case(repos):
    """创造一个 pending_review 状态的 case（confidence 0.85）。"""
    merchant = Merchant(id="m_review_001", country="BR", tier="standard")
    repos["merchant"].create(merchant)
    case = Case(
        id="case_review_pending_001",
        problem_desc="BR Pix 风控拦截 ERR_X_PIX_001",
        diagnosis="Pix 风控规则 R002 触发",
        resolution="建议商户走备用通道 Boleto",
        country="BR",
        channel="Pix",
        error_code="ERR_X_PIX_001",
        problem_type="支付失败",
        confidence=0.85,
        merchant_id="m_review_001",
    )
    repos["case"].create(case)
    return case


# === approve_case 测试 ===

class TestApproveCase:
    """approve_case：人工审核通过 → 强制写 Chroma + embedding_meta + review_decisions。"""

    def test_approve_writes_chroma_and_meta(self, kea, pending_case):
        """审核通过 → 写 Chroma faq_vec + embedding_meta + review_decisions 三层。"""
        result = kea.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_operator_001",
        })

        # 1. 返回值
        assert result["intent"] == "approve_case"
        assert result["approved"] is True
        assert result["case_id"] == pending_case.id
        assert result["chroma_id"].startswith("faq_")
        assert result["confidence"] == 0.85
        assert result["faq_vec_count"] >= 1
        assert result["reviewer"] == "ou_operator_001"

        # 2. embedding_meta 写入了
        rows = kea._db.query(
            """SELECT * FROM embedding_meta WHERE source_id = :sid""",
            {"sid": pending_case.id},
        )
        assert len(rows) == 1
        assert rows[0]["source_table"] == "cases"
        assert rows[0]["collection_name"] == "faq_vec"

        # 3. review_decisions 留痕
        reviews = kea._db.query(
            """SELECT * FROM review_decisions WHERE case_id = :cid""",
            {"cid": pending_case.id},
        )
        assert len(reviews) == 1
        assert reviews[0]["decision"] == "已通过"
        assert reviews[0]["reviewer"] == "ou_operator_001"

        # 4. Chroma 真的能召回
        rag = kea._ensure_rag()
        docs = rag.retrieve(
            "BR Pix 风控",
            top_k=5,
            collection_name="faq_vec",
        )
        assert any(doc.id == result["chroma_id"] for doc in docs)

    def test_approve_idempotent_already_approved(self, kea, pending_case):
        """重复 approve 同一 case → already_approved，不重复写。"""
        r1 = kea.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_op_1",
        })
        r2 = kea.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_op_2",
        })

        assert r1["approved"] is True
        assert r2["approved"] is False
        assert r2.get("already_approved") is True
        assert r2["case_id"] == pending_case.id

        # embedding_meta 仍只有 1 条（无重复）
        rows = kea._db.query(
            """SELECT * FROM embedding_meta WHERE source_id = :sid""",
            {"sid": pending_case.id},
        )
        assert len(rows) == 1

    def test_approve_missing_case_id_returns_error(self, kea):
        """缺 case_id → 友好错误。"""
        result = kea.execute({"intent": "approve_case"})
        assert result["intent"] == "approve_case"
        assert result.get("approved") is False
        assert "case_id 必填" in result["trace"]["error"]

    def test_approve_nonexistent_case_returns_error(self, kea):
        """case 不存在 → 友好 not_found。"""
        result = kea.execute({
            "intent": "approve_case",
            "case_id": "case_not_exist_999",
        })
        assert result.get("approved") is False
        assert "不存在" in result["trace"]["error"]

    def test_approve_without_db_returns_friendly_error(self, kea_no_db):
        """无 case_repo 注入 → 友好降级。"""
        result = kea_no_db.execute({
            "intent": "approve_case",
            "case_id": "case_xxx",
        })
        assert result.get("approved") is False
        assert "未注入" in result["trace"]["error"]


# === reject_case 测试 ===

class TestRejectCase:
    """reject_case：人工审核拒绝 → 记录 review_decisions，不写 Chroma。"""

    def test_reject_records_decision_without_writing_chroma(self, kea, pending_case):
        """拒绝 → 记录 review_decisions，但 Chroma faq_vec 不增。"""
        result = kea.execute({
            "intent": "reject_case",
            "case_id": pending_case.id,
            "reviewer": "ou_op_001",
            "reason": "证据不足",
        })

        # 1. 返回值
        assert result["intent"] == "reject_case"
        assert result["rejected"] is True
        assert result["case_id"] == pending_case.id
        assert result["reason"] == "证据不足"
        assert result["reviewer"] == "ou_op_001"

        # 2. review_decisions 留痕
        reviews = kea._db.query(
            """SELECT * FROM review_decisions WHERE case_id = :cid""",
            {"cid": pending_case.id},
        )
        assert len(reviews) == 1
        assert reviews[0]["decision"] == "已拒绝"
        assert reviews[0]["note"] == "证据不足"

        # 3. Chroma faq_vec 没写入
        rows = kea._db.query(
            """SELECT * FROM embedding_meta WHERE source_id = :sid""",
            {"sid": pending_case.id},
        )
        assert len(rows) == 0

        # 4. trace 明确标记 written_to_chroma=False
        assert result["trace"]["written_to_chroma"] is False

    def test_reject_nonexistent_case_still_records(self, kea):
        """拒绝不存在的 case → 仍然记录（防重复审）。"""
        result = kea.execute({
            "intent": "reject_case",
            "case_id": "case_ghost_xxx",
            "reviewer": "ou_op",
        })
        assert result["rejected"] is True
        reviews = kea._db.query(
            """SELECT * FROM review_decisions WHERE case_id = :cid""",
            {"cid": "case_ghost_xxx"},
        )
        assert len(reviews) == 1

    def test_reject_missing_case_id_returns_error(self, kea):
        """缺 case_id → 友好错误。"""
        result = kea.execute({"intent": "reject_case"})
        assert result.get("rejected") is False
        assert "case_id 必填" in result["trace"]["error"]


# === webhook _fmt_kea_approve / _fmt_kea_reject 测试 ===

class TestFmtKeaApproveReject:
    """FeishuWebhookHandler._fmt_kea_approve / _fmt_kea_reject 单元测试。

    Day 18 P2-final：approve_case / reject_case 不再被聊天路由触发（运营去多维表格审核）。
    但保留 _fmt_kea_approve / _fmt_kea_reject 作为内部 API 渲染 — 用于：
    - /admin/sync-bit endpoint 同步后向运营反馈（v1 简化为 log，v2 可扩展为 bot 推消息）
    - 单元测试覆盖
    """

    def test_fmt_approve_success(self):
        """approve 成功 → 「✅ case_001 已通过审核，已加入知识库，当前 faq_vec 共 3 条」"""
        data = {
            "intent": "approve_case",
            "approved": True,
            "case_id": "case_001",
            "faq_vec_count": 3,
            "reviewer": "ou_op",
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "approve_case"})
        assert "✅ case_001 已通过审核" in reply
        assert "faq_vec 共 3 条" in reply
        assert "审核人：ou_op" in reply

    def test_fmt_approve_failure_returns_warning(self):
        """approve 失败 → 「⚠️ 审核未通过：xxx」。"""
        data = {
            "intent": "approve_case",
            "approved": False,
            "trace": {"error": "案例不存在"},
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "approve_case"})
        assert "⚠️" in reply
        assert "案例不存在" in reply

    def test_fmt_reject_success(self):
        """reject 成功 → 「❌ case_002 已拒绝（证据不足）...」。"""
        data = {
            "intent": "reject_case",
            "rejected": True,
            "case_id": "case_002",
            "reason": "证据不足",
            "reviewer": "ou_op",
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "reject_case"})
        assert "❌ case_002" in reply
        assert "证据不足" in reply
        assert "不会进入知识库" in reply

    def test_fmt_reject_failure_returns_warning(self):
        """reject 失败 → 「⚠️ 审核未完成：xxx」。"""
        data = {
            "intent": "reject_case",
            "rejected": False,
            "error": "DB 未就绪",
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "reject_case"})
        assert "⚠️" in reply
        assert "DB 未就绪" in reply

"""KEA list_review_history + list_candidates 过滤测试 — Day 18 P2-final 数字员工闭环第 5 段。

覆盖：
- list_review_history：按 decision 分组（approved / rejected / auto_promoted / pending_review）
- list_review_history：decision 过滤、limit、空表
- list_candidates 过滤掉 review_decisions 里有任何决策的 case（避免重复审核）
- decided_at_ms 是整秒（% 1000 == 0）
- webhook _fmt_kea_list_candidates / _fmt_kea_list_review_history 渲染
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agents.kea import KEATool
from app.implementations.feishu.webhook import FeishuWebhookHandler
from app.models import Case, Merchant


@pytest.fixture
def tmp_chroma_dir(tmp_path):
    d = tmp_path / "chroma"
    d.mkdir()
    return d


@pytest.fixture
def merchant(repos):
    m = Merchant(id="m_rev_test", country="BR", tier="standard")
    repos["merchant"].create(m)
    return m


@pytest.fixture
def kea(repos, tmp_chroma_dir):
    return KEATool(
        case_repo=repos["case"],
        chroma_path=tmp_chroma_dir,
        embedding_meta_repo=repos["case"].db,
    )


@pytest.fixture
def high_conf_case_a(repos, merchant):
    c = Case(
        id="case_rev_a_001", problem_desc="BR Pix 风控拦截",
        diagnosis="风控 R002", resolution="备用通道 Boleto",
        country="BR", channel="Pix", error_code="ERR_PIX_001",
        problem_type="支付失败", confidence=0.85,
        merchant_id="m_rev_test",
    )
    repos["case"].create(c)
    return c


@pytest.fixture
def high_conf_case_b(repos, merchant):
    c = Case(
        id="case_rev_b_001", problem_desc="NL MC 13.1 拒付",
        diagnosis="MC 13.1", resolution="补 RDR 申诉",
        country="NL", channel="Mastercard", error_code="13.1",
        problem_type="拒付", confidence=0.92,
        merchant_id="m_rev_test",
    )
    repos["case"].create(c)
    return c


@pytest.fixture
def low_conf_case(repos, merchant):
    """低置信度 — 应被 list_candidates 跳过（< 0.85）。"""
    c = Case(
        id="case_rev_low_001", problem_desc="MX OXXO 退款慢",
        diagnosis="OXXO 退款", resolution="联系银行",
        country="MX", channel="OXXO", error_code="ERR_REFUND_001",
        problem_type="退款", confidence=0.6,
        merchant_id="m_rev_test",
    )
    repos["case"].create(c)
    return c


# === list_review_history 单元测试 ===

class TestListReviewHistory:
    """KEA._list_review_history 必须正确分组 + 过滤。"""

    def test_empty_table_returns_zero(self, kea):
        """空表 → count=0，所有分组都是空 list。"""
        result = kea.execute({"intent": "list_review_history"})
        assert result["intent"] == "list_review_history"
        assert result["count"] == 0
        assert result["by_decision"] == {
            "已通过": [], "已拒绝": [], "自动入审": [], "待审核": [],
        }

    def test_groups_by_decision(self, kea, high_conf_case_a, high_conf_case_b, repos):
        """3 条不同决策 → by_decision 各分组正确计数。"""
        # 直接写 review_decisions 表（不走 KEA 完整链路，模拟历史数据）
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer, note, chroma_id, confidence)
               VALUES (:cid, :d, :r, :n, :ch, :cf)""",
            {"cid": "case_rev_a_001", "d": "已通过", "r": "lead", "n": "", "ch": "faq_xxx", "cf": 0.85},
        )
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer, note, chroma_id, confidence)
               VALUES (:cid, :d, :r, :n, :ch, :cf)""",
            {"cid": "case_rev_b_001", "d": "已拒绝", "r": "lead", "n": "证据不足", "ch": "", "cf": 0.92},
        )
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer, note, chroma_id, confidence)
               VALUES (:cid, :d, :r, :n, :ch, :cf)""",
            {"cid": "case_rev_low_001", "d": "待审核", "r": "auto", "n": "", "ch": "", "cf": 0.6},
        )

        result = kea.execute({"intent": "list_review_history"})
        assert result["count"] == 3
        assert len(result["by_decision"]["已通过"]) == 1
        assert len(result["by_decision"]["已拒绝"]) == 1
        assert len(result["by_decision"]["待审核"]) == 1

    def test_decision_filter(self, kea, repos):
        """decision_filter='已拒绝' → 只返 已拒绝。"""
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer) VALUES (:cid, :d, :r)""",
            {"cid": "case_a", "d": "已通过", "r": "lead"},
        )
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer) VALUES (:cid, :d, :r)""",
            {"cid": "case_b", "d": "已拒绝", "r": "lead"},
        )
        result = kea.execute({"intent": "list_review_history", "decision": "已拒绝"})
        assert result["count"] == 1
        assert result["by_decision"]["已拒绝"][0]["case_id"] == "case_b"
        assert result["by_decision"]["已通过"] == []

    def test_limit_respected(self, kea, repos):
        """limit=2 → 最多返 2 条。"""
        for i in range(5):
            repos["case"].db.execute(
                """INSERT INTO review_decisions (case_id, decision, reviewer) VALUES (:cid, :d, :r)""",
                {"cid": f"case_{i}", "d": "approved", "r": "lead"},
            )
        result = kea.execute({"intent": "list_review_history", "limit": 2})
        assert result["count"] == 2

    def test_decision_record_has_required_fields(self, kea, repos):
        """每条记录必须含 case_id / reviewer / confidence / decided_at。"""
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer, confidence, chroma_id)
               VALUES (:cid, :d, :r, :cf, :ch)""",
            {"cid": "case_x", "d": "approved", "r": "lead", "cf": 0.85, "ch": "faq_xxx"},
        )
        result = kea.execute({"intent": "list_review_history"})
        rec = result["by_decision"]["approved"][0]
        assert rec["case_id"] == "case_x"
        assert rec["reviewer"] == "lead"
        assert rec["confidence"] == 0.85
        assert "decided_at" in rec


# === list_candidates 过滤测试 ===

class TestListCandidatesFilterRejected:
    """list_candidates 必须过滤掉 review_decisions 里有任何决策的 case。"""

    def test_rejected_case_not_in_candidates(self, kea, repos):
        """case 已被 reject → 不再出现在 list_candidates。"""
        c = Case(
            id="case_rejected_001", problem_desc="已拒案例",
            diagnosis="x", resolution="y",
            country="BR", channel="Pix", error_code="E1",
            problem_type="支付失败", confidence=0.88,
        )
        repos["case"].create(c)
        # 写一条 rejected 决策
        repos["case"].db.execute(
            """INSERT INTO review_decisions (case_id, decision, reviewer)
               VALUES (:cid, :d, :r)""",
            {"cid": "case_rejected_001", "d": "rejected", "r": "lead"},
        )

        result = kea.execute({"intent": "list_candidates"})
        case_ids = [cd["case_id"] for cd in result["candidates"]]
        assert "case_rejected_001" not in case_ids

    def test_approved_case_not_in_candidates(self, kea, repos):
        """case 已被 approve（写 embedding_meta）→ 不出现在 list_candidates。"""
        c = Case(
            id="case_approved_001", problem_desc="已通过",
            diagnosis="x", resolution="y",
            country="BR", channel="Pix", error_code="E2",
            problem_type="支付失败", confidence=0.95,
        )
        repos["case"].create(c)
        # approved 会写 embedding_meta（已有 _get_embedding_meta 过滤）
        repos["case"].db.execute(
            """INSERT INTO embedding_meta (source_table, source_id, chroma_id, collection_name)
               VALUES (:st, :sid, :cid, :cn)""",
            {"st": "cases", "sid": "case_approved_001", "cid": "faq_xxx", "cn": "faq_vec"},
        )

        result = kea.execute({"intent": "list_candidates"})
        case_ids = [cd["case_id"] for cd in result["candidates"]]
        assert "case_approved_001" not in case_ids

    def test_low_confidence_still_filtered(self, kea, low_conf_case):
        """低置信度 case → 不出现在 list_candidates。"""
        result = kea.execute({"intent": "list_candidates"})
        case_ids = [cd["case_id"] for cd in result["candidates"]]
        assert "case_rev_low_001" not in case_ids


# === decided_at 整秒化测试 ===

class TestDecidedAtIsIntegerSeconds:
    """_sync_review_decision_to_bitable 必须传整秒毫秒时间戳。"""

    def test_decided_at_ms_is_integer_seconds(self, tmp_chroma_dir, repos):
        """decided_at_ms % 1000 == 0（无小数毫秒位）。"""
        fe = MagicMock()
        fe.sync_review_decision = MagicMock(return_value=True)
        kea = KEATool(
            case_repo=repos["case"],
            chroma_path=tmp_chroma_dir,
            embedding_meta_repo=repos["case"].db,
            frontend=fe,
        )
        c = Case(
            id="case_dt_001", problem_desc="时间测试",
            diagnosis="x", resolution="y",
            country="BR", channel="Pix", error_code="E3",
            problem_type="支付失败", confidence=0.85,
        )
        repos["case"].create(c)
        kea.execute({"intent": "promote_to_faq", "case_id": "case_dt_001"})

        # 取出调用参数
        payload = fe.sync_review_decision.call_args[0][0]
        assert payload["decided_at"] % 1000 == 0, (
            f"decided_at 应是整秒，实际={payload['decided_at']}"
        )

    def test_decided_at_iso_no_microseconds(self, tmp_chroma_dir, repos):
        """decided_at_iso 不含小数秒。"""
        fe = MagicMock()
        fe.sync_review_decision = MagicMock(return_value=True)
        kea = KEATool(
            case_repo=repos["case"],
            chroma_path=tmp_chroma_dir,
            embedding_meta_repo=repos["case"].db,
            frontend=fe,
        )
        c = Case(
            id="case_dt_002", problem_desc="时间测试2",
            diagnosis="x", resolution="y",
            country="BR", channel="Pix", error_code="E4",
            problem_type="支付失败", confidence=0.85,
        )
        repos["case"].create(c)
        kea.execute({"intent": "promote_to_faq", "case_id": "case_dt_002"})

        payload = fe.sync_review_decision.call_args[0][0]
        # ISO 字符串不应有小数位
        assert "." not in payload["decided_at_iso"]


# === webhook 渲染测试 ===

class TestFmtKeaListCandidates:
    """_fmt_kea_list_candidates 真正渲染候选清单（不是只一行总数）。"""

    def test_renders_case_id_and_problem(self):
        data = {
            "intent": "list_candidates",
            "count": 2,
            "candidates": [
                {
                    "case_id": "case_test_001", "problem_desc": "BR Pix 拦截 ERR_PIX",
                    "problem_type": "支付失败", "country": "BR", "channel": "Pix",
                    "confidence": 0.85, "created_at": "2026-08-16T14:30:00",
                },
                {
                    "case_id": "case_test_002", "problem_desc": "NL 13.1 拒付",
                    "problem_type": "拒付", "country": "NL", "channel": "Mastercard",
                    "confidence": 0.88, "created_at": "2026-08-16T14:32:00",
                },
            ],
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "list_candidates"})
        assert "case_test_001" in reply
        assert "case_test_002" in reply
        assert "BR Pix" in reply
        assert "85%" in reply
        assert "待审核" in reply or "📚" in reply
        # 关键：不能再只返一行总数
        assert "找到 2 个高置信度候选待升级" not in reply

    def test_empty_list_friendly_message(self):
        """空候选池 → 友好提示。"""
        data = {"intent": "list_candidates", "count": 0, "candidates": []}
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "list_candidates"})
        assert "没有待审核" in reply or "0" in reply


class TestFmtKeaListReviewHistory:
    """_fmt_kea_list_review_history 按 4 段渲染。"""

    def test_renders_4_sections(self):
        data = {
            "intent": "list_review_history",
            "count": 4,
            "by_decision": {
                "已通过": [{"case_id": "c1", "reviewer": "lead", "confidence": 0.85,
                              "decided_at": "2026-08-16 14:30:00"}],
                "已拒绝": [{"case_id": "c2", "reviewer": "lead", "confidence": 0.7,
                              "decided_at": "2026-08-16 14:31:00"}],
                "自动入审": [{"case_id": "c3", "reviewer": "auto", "confidence": 0.92,
                                   "decided_at": "2026-08-16 14:32:00"}],
                "待审核": [{"case_id": "c4", "reviewer": "auto", "confidence": 0.85,
                                    "decided_at": "2026-08-16 14:33:00"}],
            },
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "list_review_history"})
        assert "✅ 已通过" in reply
        assert "❌ 已拒绝" in reply
        assert "🤖 自动入审" in reply
        assert "🟡 待审核" in reply
        assert "c1" in reply
        assert "c2" in reply

    def test_empty_returns_simple_message(self):
        data = {
            "intent": "list_review_history",
            "count": 0,
            "by_decision": {"approved": [], "rejected": [], "auto_promoted": [], "pending_review": []},
        }
        reply = FeishuWebhookHandler._fmt_kea(data, {"sub_intent": "list_review_history"})
        assert "暂无记录" in reply
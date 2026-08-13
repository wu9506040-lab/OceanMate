"""KEATool SOP 测试 — Day 6 SOP-KEA-001/002。

覆盖：
- SOP-KEA-001-A：promote_to_faq 完整链路（cases 表 → Chroma → embedding_meta）
- SOP-KEA-001-B：promote 重复检测（已 promote 的 case 不再 promote）
- SOP-KEA-001-C：search_faq 命中（RAG retrieve + case join）
- SOP-KEA-001-D：list_candidates 列高置信度未沉淀的 case
- SOP-KEA-002-A：缺 case_id → 友好提示
- SOP-KEA-002-B：case 不存在 → 友好 not_found
- SOP-KEA-002-C：Chroma 写入失败 → 友好降级
- SOP-KEA-002-D：search 知识库空 → []
- 接口合规 + ToolRegistry 注册

详见 docs/sop/SOP-KEA.md。
"""

import pytest
from pathlib import Path

from app.agents.kea import KEATool
from app.interfaces.base_tool import BaseTool
from app.models import Case


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
def merchant_setup(repos):
    """cases 表 FK → merchants.id，先建 merchant。"""
    from app.models import Merchant
    merchant = Merchant(
        id="m_test_001",
        country="BR",
        industry="fashion",
        avg_amount=85.0,
        tier="vip",
    )
    repos["merchant"].create(merchant)
    return "m_test_001"


@pytest.fixture
def sample_case(merchant_setup):
    """标准测试案例（高置信度，足以 promote）。自动创建依赖 merchant。"""
    return Case(
        id="case_demo_001",
        problem_desc="BR Visa 拒付 ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        diagnosis="风控规则 R001 触发",
        resolution="建议商户提供 CVV + 3DS 验证",
        country="BR",
        channel="Visa",
        error_code="ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        problem_type="拒付",
        confidence=0.92,
        merchant_id=merchant_setup,  # 用 fixture 创建的 ID
    )


@pytest.fixture
def populated_db(repos):
    """塞 5 条测试用例到 DB（覆盖不同 problem_type + confidence）。"""
    # 先建一个 merchant（cases FK）
    from app.models import Merchant
    merchant = Merchant(id="m_test_001", country="BR", tier="standard")
    repos["merchant"].create(merchant)

    cases = [
        Case(id="case_demo_high_001", problem_desc="BR Visa 拒付高置信案例",
             diagnosis="风控 R001", resolution="加 3DS", country="BR", channel="Visa",
             error_code="ERR_X_001", problem_type="拒付", confidence=0.95,
             merchant_id="m_test_001"),
        Case(id="case_demo_high_002", problem_desc="US PayPal 失败案例",
             diagnosis="卡组织维护", resolution="24h 后重试", country="US", channel="PayPal",
             error_code="ERR_X_002", problem_type="支付失败", confidence=0.88,
             merchant_id="m_test_001"),
        Case(id="case_demo_med_001", problem_desc="中等置信度案例",
             diagnosis="未知", resolution="未知", country="CN", channel="UnionPay",
             error_code="ERR_X_003", problem_type="退款异常", confidence=0.55,
             merchant_id="m_test_001"),
        Case(id="case_demo_high_003", problem_desc="BR Pix 案例",
             diagnosis="Pix 风控", resolution="走备用通道", country="BR", channel="Pix",
             error_code="ERR_X_004", problem_type="支付失败", confidence=0.91,
             merchant_id="m_test_001"),
        Case(id="case_demo_high_004", problem_desc="Webhook 失败案例",
             diagnosis="回调超时", resolution="重试机制", country="US", channel="Visa",
             error_code="ERR_X_005", problem_type="Webhook回调", confidence=0.86,
             merchant_id="m_test_001"),
    ]
    for c in cases:
        repos["case"].create(c)
    return cases


# === 接口合规 ===

class TestKEAToolInterface:
    """BaseTool 接口合规。"""

    def test_is_base_tool_subclass(self):
        assert issubclass(KEATool, BaseTool)

    def test_name_and_description(self):
        tool = KEATool()
        assert tool.name == "knowledge_evolution"
        assert "知识" in tool.description and ("FAQ" in tool.description or "案例" in tool.description)

    def test_intent_enum_in_input_schema(self):
        schema = KEATool().input_schema
        intent_prop = schema["properties"]["intent"]
        assert "promote_to_faq" in intent_prop["enum"]
        assert "search_faq" in intent_prop["enum"]
        assert "list_candidates" in intent_prop["enum"]

    def test_mcp_tool_spec_export(self):
        spec = KEATool().to_mcp_tool_spec()
        assert spec["name"] == "knowledge_evolution"
        assert "capabilities" in spec
        assert spec["capabilities"]["async_supported"] is True


# === SOP-KEA-001-A · promote_to_faq 完整链路 ===

class TestPromoteHappyPath:
    """SOP-KEA-001-A：promote 写入 cases → Chroma → embedding_meta。"""

    def test_promote_writes_all_three_layers(self, kea, sample_case):
        """promote 完整链路：case 表存在 + 写入 Chroma + 写入 embedding_meta。"""
        # Arrange：先存 case 进 DB（实际是 PDA 诊断结果）
        kea.case_repo.create(sample_case)

        # Act
        result = kea.execute({
            "intent": "promote_to_faq",
            "case_id": sample_case.id,
        })

        # Assert：返回值
        assert result["intent"] == "promote_to_faq"
        assert result["promoted"] is True
        assert result["case_id"] == sample_case.id
        assert result["chroma_id"].startswith("faq_")
        assert result["count"] == 1

        # Assert：embedding_meta 表真有记录
        rows = kea._db.query(
            """SELECT * FROM embedding_meta WHERE source_id = :sid""",
            {"sid": sample_case.id},
        )
        assert len(rows) == 1
        assert rows[0]["source_table"] == "cases"
        # Day 14 P1-6：沉淀目标集合改为 faq_vec（与原始案例库 cases_vec 分离）
        assert rows[0]["collection_name"] == "faq_vec"

        # Assert：Chroma 真的有这个文档
        rag = kea._ensure_rag()
        docs = rag.retrieve(
            "BR Visa 拒付",
            top_k=5,
            collection_name="faq_vec",
        )
        # 至少有一条结果（HashEmbedding 相似度弱，但能召回同一个）
        assert any(doc.id == result["chroma_id"] for doc in docs)

    def test_promote_dedupe_prevents_double_promote(self, kea, sample_case):
        """重复 promote 同一 case → 不写入第二条 embedding_meta。"""
        kea.case_repo.create(sample_case)

        r1 = kea.execute({"intent": "promote_to_faq", "case_id": sample_case.id})
        r2 = kea.execute({"intent": "promote_to_faq", "case_id": sample_case.id})

        assert r1["promoted"] is True
        assert r2["promoted"] is False
        assert "已升级" in r2["trace"]["error"]
        assert r2["trace"]["already"] is True
        assert r2["trace"]["existing_chroma_id"] == r1["chroma_id"]

        # embedding_meta 中仍只有 1 条
        rows = kea._db.query(
            """SELECT * FROM embedding_meta WHERE source_id = :sid""",
            {"sid": sample_case.id},
        )
        assert len(rows) == 1


# === SOP-KEA-001-B · search_faq 检索 ===

class TestSearchFAQ:
    """SOP-KEA-001-B：搜索并 join cases 表富信息。"""

    def test_search_finds_promoted_faq(self, kea, sample_case):
        """promote 后 search 应能命中。"""
        kea.case_repo.create(sample_case)
        kea.execute({"intent": "promote_to_faq", "case_id": sample_case.id})

        result = kea.execute({
            "intent": "search_faq",
            "query": "Visa 拒付 BR",
            "top_k": 5,
        })
        assert result["intent"] == "search_faq"
        assert result["count"] >= 1
        assert result["faqs"][0]["case_id"] == sample_case.id
        # join 回 case 表
        assert result["faqs"][0]["case_info"] is not None
        assert result["faqs"][0]["case_info"]["country"] == "BR"
        assert "3DS" in result["faqs"][0]["case_info"]["resolution"]

    def test_search_with_country_filter(self, kea, populated_db):
        """国家级过滤生效。"""
        # promote 两条
        kea.execute({"intent": "promote_to_faq", "case_id": "case_demo_high_001"})
        kea.execute({"intent": "promote_to_faq", "case_id": "case_demo_high_002"})

        result = kea.execute({
            "intent": "search_faq",
            "query": "支付问题",
            "top_k": 10,
            "country": "BR",
        })
        # 所有返回的 faqs country 应都是 BR
        assert result["count"] >= 1
        assert all(f["country"] == "BR" for f in result["faqs"])

    def test_search_returns_empty_when_kb_empty(self, kea_no_db):
        """知识库空 → search 返 []（不抛异常）。"""
        result = kea_no_db.execute({
            "intent": "search_faq",
            "query": "任何问题",
        })
        assert result["count"] == 0
        assert result["faqs"] == []
        assert "no_match" in result["trace"]["empty_reason"]


# === SOP-KEA-001-C · list_candidates ===

class TestListCandidates:
    """SOP-KEA-001-C：列高置信度未 promote 的候选。"""

    def test_lists_only_high_confidence(self, kea, populated_db):
        """默认阈值 0.85 → 仅返回 ≥ 0.85 的候选。"""
        result = kea.execute({"intent": "list_candidates"})
        assert result["intent"] == "list_candidates"
        # 5 条中 confidence ≥ 0.85 的有 4 条（0.95, 0.88, 0.91, 0.86）
        assert result["count"] == 4
        assert all(c["confidence"] >= 0.85 for c in result["candidates"])

    def test_filters_out_already_promoted(self, kea, populated_db):
        """已 promote 的 case 不再出现在候选列表。"""
        # 先 promote 一条
        kea.execute({"intent": "promote_to_faq", "case_id": "case_demo_high_001"})

        result = kea.execute({"intent": "list_candidates"})
        # 4-1 = 3 条
        assert result["count"] == 3
        ids = [c["case_id"] for c in result["candidates"]]
        assert "case_demo_high_001" not in ids

    def test_custom_confidence_threshold(self, kea, populated_db):
        """自定义阈值（0.5）→ 应包含所有 confidence ≥ 0.5 的 case。"""
        result = kea.execute({
            "intent": "list_candidates",
            "min_confidence": 0.5,
        })
        # 5 条全中（最低 confidence=0.55）
        assert result["count"] == 5


# === SOP-KEA-002 · 逆向（友好降级） ===

class TestFriendlyDegradation:
    """SOP-KEA-002：所有失败场景必须用户友好。"""

    def test_missing_case_id_returns_friendly_error(self, kea):
        result = kea.execute({"intent": "promote_to_faq"})
        assert result["promoted"] is False
        assert result["count"] == 0
        assert "case_id 必填" in result["trace"]["error"]

    def test_nonexistent_case_returns_not_found(self, kea):
        result = kea.execute({
            "intent": "promote_to_faq",
            "case_id": "case_does_not_exist",
        })
        assert result["promoted"] is False
        assert "不存在" in result["trace"]["error"]
        assert "检查 case_id" in result["trace"]["hint"]

    def test_promote_without_db_returns_friendly_error(self, kea_no_db):
        """无 CaseRepository → 友好降级（不抛 raw exception）。"""
        result = kea_no_db.execute({
            "intent": "promote_to_faq",
            "case_id": "any_case_id",
        })
        assert result["promoted"] is False
        assert "CaseRepository" in result["trace"]["error"]

    def test_list_without_db_returns_friendly_error(self, kea_no_db):
        """无 CaseRepository + list_candidates → 友好降级。"""
        result = kea_no_db.execute({"intent": "list_candidates"})
        assert result["count"] == 0
        assert "CaseRepository" in result["trace"]["error"]

    def test_search_missing_query_returns_friendly_error(self, kea):
        result = kea.execute({"intent": "search_faq"})
        assert result["count"] == 0
        assert "query 必填" in result["trace"]["error"]

    def test_unknown_intent_raises_value_error(self, kea):
        """未知 intent → ValueError（Tool 输入校验失败）。"""
        with pytest.raises(ValueError, match="Unknown intent"):
            kea.execute({"intent": "nonsense"})

    def test_invalid_input_rejected_by_jsonschema(self, kea):
        """jsonschema 校验失败。"""
        from jsonschema import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            kea.execute({"intent": 123})


# === 端到端：Orchestrator → KEA ===

class TestKEAEnd2End:
    """Orchestrator + KEA 集成（Day 6 完成）。"""

    def test_orchestrator_routes_to_kea_via_keyword(self, kea, merchant_setup, sample_case):
        """关键词 'FAQ' → knowledge_evolution → KEA 真实 promote 链路。

        注：Orchestrator 创建时自带 KEA()（无 DB）。
        这里手动构造一个有 DB 的 KEA 注入，确保完整链路可测。
        """
        from app.agents.orchestrator import Orchestrator
        # 先把 sample_case 写入 DB
        kea.case_repo.create(sample_case)

        orch = Orchestrator()
        orch.register_tool(kea)

        result = orch.route(
            "FAQ 怎么用",
            merchant_context={
                "case_id": "case_demo_001",  # sample_case.id
            },
        )
        assert result["intent"] == "knowledge_evolution"
        assert result["tool_name"] == "knowledge_evolution"
        assert result["trace"]["sub_intent"] == "promote_to_faq"
        assert result["tool_result"]["success"] is True
        data = result["tool_result"]["data"]
        assert data["promoted"] is True
        assert data["case_id"] == "case_demo_001"

    def test_orchestrator_kea_no_db_friendly_error(self):
        """Orchestrator 默认 KEA（无 DB）→ promote 友好降级（success=True 但 promoted=False）。"""
        from app.agents.orchestrator import Orchestrator
        orch = Orchestrator()
        orch.register_tool(KEATool())  # 无 DB

        result = orch.route(
            "FAQ 怎么用",
            merchant_context={"case_id": "case_demo_001"},
        )
        assert result["intent"] == "knowledge_evolution"
        assert result["tool_result"]["success"] is True  # 没异常 = success，但数据里 promoted=False
        data = result["tool_result"]["data"]
        assert data["promoted"] is False
        # trace.error 应含 "CaseRepository" 或 "必填"
        assert "CaseRepository" in data["trace"]["error"] or "必填" in data["trace"]["error"] or "不存在" in data["trace"]["error"]  # type: ignore[operator]  # noqa

    def test_orchestrator_kea_with_full_setup(self, kea, merchant_setup):
        """完整 setup：cases 表有 → KEA promote 成功。"""
        sample = Case(
            id="case_orch_test",
            problem_desc="US 支付失败 ERR_TEST",
            diagnosis="卡组织维护",
            resolution="重试",
            country="US",
            channel="Visa",
            error_code="ERR_TEST",
            problem_type="支付失败",
            confidence=0.93,
            merchant_id="m_test_001",
        )
        kea.case_repo.create(sample)
        result = kea.execute({
            "intent": "promote_to_faq",
            "case_id": sample.id,
        })
        assert result["promoted"] is True

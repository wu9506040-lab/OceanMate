"""MSATool SOP 测试 — Day 4 SOP-MSA-001/002。

覆盖：
- SOP-MSA-001（happy）：画像完整 → PWR 返回 ≥1 个推荐
- SOP-MSA-001 进阶：BR Pix（高匹配）
- SOP-MSA-002：画像不完整 → 主动反问
- SOP-MSA-002 进阶：collect_profile 显式采集流程
- BaseTool 接口合规
- ToolRegistry 注册

详见 docs/sop/SOP-MSA.md。
"""

import pytest

from app.agents.msa import MSATool
from app.interfaces.base_tool import BaseTool, ToolRegistry


@pytest.fixture
def msa():
    """MSATool 默认实例（懒加载 RAG）。"""
    return MSATool()


class TestMSAToolInterface:
    """BaseTool 接口合规。"""

    def test_is_base_tool_subclass(self):
        assert issubclass(MSATool, BaseTool)

    def test_name_and_description(self):
        tool = MSATool()
        assert tool.name == "merchant_success"
        assert "MSA" in tool.description or "商户" in tool.description
        assert "PWR" in tool.description or "支付方式" in tool.description

    def test_intent_enum_in_input_schema(self):
        schema = MSATool().input_schema
        intent_prop = schema["properties"]["intent"]
        assert "recommend_payment_methods" in intent_prop["enum"]
        assert "collect_profile" in intent_prop["enum"]

    def test_mcp_tool_spec_export(self):
        spec = MSATool().to_mcp_tool_spec()
        assert spec["name"] == "merchant_success"
        assert "capabilities" in spec
        assert spec["capabilities"]["idempotent"] is False  # 依赖上下文


class TestMSARecommendHappyPath:
    """SOP-MSA-001：画像完整 → PWR 推荐。"""

    def test_us_b2c_fashion_returns_visa_mastercard_paypal(self, msa):
        """US B2C fashion 客单价 $85 → 期望命中 Visa/Mastercard/PayPal 至少一种。"""
        result = msa.execute({
            "intent": "recommend_payment_methods",
            "merchant_context": {
                "merchant_id": "m_001",
                "country": "US",
                "industry": "fashion",
                "avg_amount": 85.0,
                "target_users": "B2C",
            },
            "user_query": "我想做美国站时尚电商，客单价 85 美元",
        })

        # 1. 关键字段
        assert result["intent"] == "recommend_payment_methods"
        assert result["profile_completeness"] == 1.0
        assert result["follow_up_questions"] == []

        # 2. 推荐结果非空（seed 数据 9 条 + US 至少有 Visa/Mastercard/PayPal）
        assert len(result["recommendations"]) >= 1

        # 3. 每条推荐有完整字段
        for r in result["recommendations"]:
            assert "method" in r
            assert "evidence_id" in r
            assert r["evidence_id"].startswith("pm_demo_")
            assert "rationale" in r

        # 4. 方法名至少能命中 1 个 US 方法
        methods = {r["method"] for r in result["recommendations"]}
        assert methods & {"Visa", "Mastercard", "PayPal", "ACH"}, (
            f"US 应至少命中 1 个本地支付方式，实际: {methods}"
        )

        # 5. response 非空（含 LLM 总结或 Mock 兜底）
        assert len(result["response"]) > 0

    def test_br_returns_pix_priority(self, msa):
        """BR → 应该把 Pix 排前面（Pix 是 BR 主流）。"""
        result = msa.execute({
            "intent": "recommend_payment_methods",
            "merchant_context": {
                "country": "BR",
                "industry": "fashion",
                "avg_amount": 150.0,
                "target_users": "B2C",
            },
            "user_query": "BR 时尚电商，客单价 $150",
        })

        assert len(result["recommendations"]) >= 1
        # 至少能找到一个 BR 方法（Pix / Boleto / Visa BR）
        methods = [r["method"] for r in result["recommendations"]]
        assert "Pix" in methods or "Boleto" in methods, (
            f"BR 应包含 Pix/Boleto，实际: {methods}"
        )


class TestMSARecommendMissingProfile:
    """SOP-MSA-002：画像不完整 → 主动反问。"""

    def test_missing_all_required_fields_returns_questions(self, msa):
        """空画像 → 4 个追问 + profile_completeness=0。"""
        result = msa.execute({
            "intent": "recommend_payment_methods",
            "merchant_context": {},
            "user_query": "帮我选支付方式",
        })

        assert result["profile_completeness"] == 0.0
        assert result["recommendations"] == []  # 不进入 RAG
        assert len(result["follow_up_questions"]) == 4
        fields = {q["field"] for q in result["follow_up_questions"]}
        assert fields == {"country", "industry", "avg_amount", "target_users"}

        # response 引导用户
        assert "国家" in result["response"] or "支付方式" in result["response"]

    def test_partial_profile_returns_only_missing_questions(self, msa):
        """只填 country → 追问剩下 3 个。"""
        result = msa.execute({
            "intent": "recommend_payment_methods",
            "merchant_context": {"country": "US"},
            "user_query": "US 站",
        })

        assert result["profile_completeness"] == 0.25
        assert len(result["follow_up_questions"]) == 3
        fields = {q["field"] for q in result["follow_up_questions"]}
        assert "country" not in fields  # 已填的不再问
        assert fields == {"industry", "avg_amount", "target_users"}

    def test_three_fields_filled_only_asks_one(self, msa):
        """只缺一个字段 → 追问 1 个。"""
        result = msa.execute({
            "intent": "recommend_payment_methods",
            "merchant_context": {
                "country": "US",
                "industry": "electronics",
                "avg_amount": 200.0,
                # 缺 target_users
            },
            "user_query": "US 电子产品",
        })

        assert result["profile_completeness"] == 0.75
        assert len(result["follow_up_questions"]) == 1
        assert result["follow_up_questions"][0]["field"] == "target_users"


class TestMSACollectProfile:
    """SOP-MSA-002 进阶：collect_profile 显式采集。"""

    def test_collect_profile_empty(self, msa):
        result = msa.execute({
            "intent": "collect_profile",
            "merchant_context": {},
            "user_query": "我想做美国站",
        })
        assert result["intent"] == "collect_profile"
        assert result["profile_completeness"] == 0.0
        assert len(result["follow_up_questions"]) == 4

    def test_collect_profile_complete(self, msa):
        result = msa.execute({
            "intent": "collect_profile",
            "merchant_context": {
                "country": "US",
                "industry": "fashion",
                "avg_amount": 100.0,
                "target_users": "B2C",
            },
            "user_query": "继续",
        })
        assert result["profile_completeness"] == 1.0
        assert result["follow_up_questions"] == []
        assert "已完整" in result["response"] or "完整" in result["response"]


class TestMSAValidation:
    """参数校验。"""

    def test_missing_intent_raises(self, msa):
        with pytest.raises(ValueError):
            msa.validate_input({"user_query": "test"})

    def test_missing_user_query_raises(self, msa):
        with pytest.raises(ValueError):
            msa.validate_input({"intent": "recommend_payment_methods"})

    def test_invalid_intent_raises(self, msa):
        with pytest.raises(ValueError):
            msa.execute({
                "intent": "nonexistent_intent",
                "user_query": "test",
            })

    def test_invalid_country_length_raises(self, msa):
        """country 必须 2 位（与 PDATool 一致）。"""
        with pytest.raises(ValueError):
            msa.validate_input({
                "intent": "recommend_payment_methods",
                "merchant_context": {"country": "USA"},  # 3 位
                "user_query": "test",
            })


class TestMSARegistry:
    """ToolRegistry 集成。"""

    def test_register_and_list(self):
        registry = ToolRegistry()
        registry.register(MSATool())
        assert "merchant_success" in registry
        assert len(registry) == 1

    def test_safe_execute_returns_unified_result(self, msa):
        """safe_execute 统一返回 {success, data/error_code/error_message}。"""
        registry = ToolRegistry()
        registry.register(msa)

        # 成功路径
        result = registry.safe_execute("merchant_success", {
            "intent": "recommend_payment_methods",
            "merchant_context": {
                "country": "US", "industry": "fashion",
                "avg_amount": 50.0, "target_users": "B2C",
            },
            "user_query": "test",
        })
        assert result["success"] is True
        assert result["data"]["profile_completeness"] == 1.0

        # 失败路径（参数缺失）
        bad = registry.safe_execute("merchant_success", {"intent": "collect_profile"})
        assert bad["success"] is False
        assert bad["error_code"] == "TOOL_PARAM_INVALID"
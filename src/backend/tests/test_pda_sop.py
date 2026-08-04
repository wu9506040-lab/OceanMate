"""PDATool SOP 测试 — Day 2 SOP 矩阵补完。

3 个 SOP：
- SOP-PDA-001：BR/Visa 命中知识库 → 返回证据链（happy path）
- SOP-PDA-002：错误码不在数据集 → 友好降级（root_causes 含兜底）
- SOP-PDA-003：LLM 调用失败 → 自动降级 MockLLMProvider（trace.degraded=True）

详见 docs/sop/SOP-PDA.md。
"""

import pytest

from app.agents.pda import PDATool
from app.interfaces.base_tool import BaseTool, ToolRegistry


class TestPDAToolInterface:
    """BaseTool 接口合规检查。"""

    def test_is_base_tool_subclass(self):
        assert issubclass(PDATool, BaseTool)

    def test_name_and_description(self):
        tool = PDATool()
        assert tool.name == "payment_diagnosis"
        assert "诊断" in tool.description
        assert "跨境支付" in tool.description

    def test_schemas_are_valid_json_schema(self):
        tool = PDATool()
        in_s = tool.input_schema
        out_s = tool.output_schema
        # 必须是 dict 且 type=object
        assert isinstance(in_s, dict) and in_s["type"] == "object"
        assert isinstance(out_s, dict) and out_s["type"] == "object"
        # 必填字段存在
        assert "merchant_id" in in_s["required"]
        assert "country" in in_s["required"]
        assert "channel" in in_s["required"]
        assert "error_code" in in_s["required"]
        # 输出必填
        for f in ("problem_type", "root_causes", "evidence_chain", "confidence"):
            assert f in out_s["required"]

    def test_mcp_tool_spec_export(self):
        """to_mcp_tool_spec() 输出 MCP 标准 dict。"""
        spec = PDATool().to_mcp_tool_spec()
        assert spec["name"] == "payment_diagnosis"
        assert "inputSchema" in spec
        assert "outputSchema" in spec
        assert "capabilities" in spec
        assert spec["capabilities"]["idempotent"] is True

    def test_capabilities(self):
        cap = PDATool().capabilities
        assert cap["async_supported"] is True
        assert cap["idempotent"] is True


class TestPDAToolExecute:
    """业务执行路径。"""

    def test_happy_path_br_visa(self):
        """SOP-PDA-Happy：BR / Visa 风控拦截场景。"""
        tool = PDATool()
        params = {
            "merchant_id": "m_001",
            "country": "BR",
            "channel": "Visa",
            "error_code": "ERR_DEMO_RISK_BLOCK_BR_VISA_001",
            "affected_orders": ["O001", "O002"],
        }
        result = tool.execute(params)

        # 关键字段非空
        assert result["problem_type"] in ("支付失败", "拒付", "退款异常", "Webhook 回调失败")
        assert len(result["root_causes"]) >= 1
        assert len(result["evidence_chain"]) >= 1  # 至少命中风控规则
        assert len(result["recommended_actions"]) >= 1
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["next_agent"] == "Ticket Routing Agent"

        # 证据链含 type 字段
        ev = result["evidence_chain"][0]
        assert ev["type"] in ("risk_rule", "channel_status", "config_snapshot")
        assert "id" in ev and "source" in ev

        # trace 透传
        assert "evidence_count" in result["trace"]

    def test_happy_path_with_missing_evidence(self):
        """SOP-PDA-002：知识库无匹配 → 友好降级提示。"""
        tool = PDATool()
        params = {
            "merchant_id": "m_002",
            "country": "ZZ",  # 不存在的国家
            "channel": "UnknownChannel",
            "error_code": "ERR_NONEXISTENT",
        }
        result = tool.execute(params)

        # 1. 仍返回结构化结果（不抛异常）
        assert "problem_type" in result
        assert "root_causes" in result
        assert "evidence_chain" in result
        assert "confidence" in result

        # 2. problem_type 兜底为合法值
        assert result["problem_type"] in ("支付失败", "拒付", "退款异常", "Webhook 回调失败")

        # 3. risk_rule / channel_status 不应命中（无匹配）
        for ev in result["evidence_chain"]:
            assert ev["type"] != "risk_rule", "无匹配场景不应有风险规则证据"
            assert ev["type"] != "channel_status", "无匹配场景不应有通道状态证据"
        # 注：config_snapshot 含 GLOBAL 配置，会始终命中（这是设计）

        # 4. root_causes 非空且用户友好（无堆栈/无"系统错误"）
        assert len(result["root_causes"]) >= 1
        all_text = " ".join(result["root_causes"])
        assert "Traceback" not in all_text
        assert "系统错误" not in all_text
        assert "Exception" not in all_text
        # 关键文案：提到证据 ID 或说明原因，不裸抛
        assert any(
            kw in all_text for kw in ("未匹配", "Demo", "config_snapshot", "risk_rule", "OP")
        ), f"root_causes 应有友好说明，实际: {result['root_causes']}"

        # 5. recommended_actions 仍给出下一步（即使不确定）
        assert len(result["recommended_actions"]) >= 1

    def test_sop_pda_003_llm_failure_degrades_to_mock(self):
        """SOP-PDA-003：LLM 调用失败 → 自动降级 MockLLMProvider。"""
        from legacy.agents.payment_diagnosis.service import PaymentDiagnosisService
        from legacy.agents.payment_diagnosis.evidence_store import EvidenceStore

        # 注入一个会抛异常的 fake LLM provider
        class FailingLLM:
            def generate_diagnosis(self, **kwargs):
                raise RuntimeError("模拟 LLM 调用失败（如 DashScope 超时）")

        service = PaymentDiagnosisService(
            evidence_store=EvidenceStore(),
            llm_provider=FailingLLM(),
        )
        tool = PDATool(service=service)

        params = {
            "merchant_id": "m_003",
            "country": "BR",
            "channel": "Visa",
            "error_code": "ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        }

        # 关键：execute 不应抛异常，应自动降级并返回成功结果
        result = tool.execute(params)

        # 验证降级生效
        assert result["problem_type"] in ("支付失败", "拒付", "退款异常", "Webhook 回调失败")
        assert len(result["root_causes"]) >= 1
        assert "trace" in result
        assert result["trace"].get("degraded") is True
        assert result["trace"].get("original_llm") == "FailingLLM"
        assert "degraded_reason" in result["trace"]

    def test_sop_pda_003_no_infinite_loop_when_already_mock(self):
        """SOP-PDA-003 边界：当前 LLM 已是 MockLLMProvider 时，降级失败不再递归。"""
        from legacy.agents.payment_diagnosis.service import PaymentDiagnosisService
        from legacy.agents.payment_diagnosis.llm_provider import MockLLMProvider
        from legacy.agents.payment_diagnosis.evidence_store import EvidenceStore

        # 注入一个会抛异常的 fake，但底层 service 的 llm 已是 MockLLMProvider
        class StillFailingLLM(MockLLMProvider):
            def generate_diagnosis(self, **kwargs):
                raise RuntimeError("Mock 也失败（边界测试）")

        service = PaymentDiagnosisService(
            evidence_store=EvidenceStore(),
            llm_provider=StillFailingLLM(),  # 继承自 MockLLMProvider 但会抛
        )
        tool = PDATool(service=service)

        params = {
            "merchant_id": "m_x", "country": "BR", "channel": "Visa",
            "error_code": "ERR_X",
        }

        # 此时降级循环检测会生效 → 直接抛出原始异常（不会无限递归）
        with pytest.raises(RuntimeError) as exc_info:
            tool.execute(params)
        assert "Mock 也失败" in str(exc_info.value)


class TestPDAToolValidation:
    """参数校验（jsonschema 驱动）。"""

    def test_missing_required_field_raises(self):
        """缺 country → validate_input 抛 ValueError。"""
        tool = PDATool()
        with pytest.raises(ValueError) as exc_info:
            tool.validate_input({"merchant_id": "m1", "channel": "Visa", "error_code": "E1"})
        assert "参数校验失败" in str(exc_info.value)

    def test_country_length_enforced(self):
        """country 必须 2 位。"""
        tool = PDATool()
        with pytest.raises(ValueError):
            tool.validate_input({
                "merchant_id": "m1", "country": "BRA",  # 3 位
                "channel": "Visa", "error_code": "E1",
            })


class TestPDAToolRegistry:
    """ToolRegistry 注册路径（评审展示 MCP tool_spec 用）。"""

    def test_register_and_list(self):
        registry = ToolRegistry()
        registry.register(PDATool())
        assert "payment_diagnosis" in registry
        assert len(registry) == 1

        specs = registry.list_tools()
        assert len(specs) == 1
        assert specs[0]["name"] == "payment_diagnosis"

    def test_safe_execute_returns_unified_result(self):
        """safe_execute 统一返回 {success, data/error_code/error_message}。"""
        registry = ToolRegistry()
        registry.register(PDATool())

        # 成功路径
        result = registry.safe_execute("payment_diagnosis", {
            "merchant_id": "m1", "country": "BR", "channel": "Visa",
            "error_code": "ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        })
        assert result["success"] is True
        assert "data" in result
        assert result["data"]["problem_type"] == "支付失败"

        # 失败路径（参数缺失）
        bad = registry.safe_execute("payment_diagnosis", {"merchant_id": "m1"})
        assert bad["success"] is False
        assert bad["error_code"] == "TOOL_PARAM_INVALID"

        # 未知 Tool
        missing = registry.safe_execute("nonexistent", {})
        assert missing["success"] is False
        assert missing["error_code"] == "TOOL_NOT_FOUND"
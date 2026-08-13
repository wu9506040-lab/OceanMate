"""PDATool - 支付诊断 Tool（OP 命题方向 ② · Demo 核心）。

迁移策略：
- 复用 legacy.agents.payment_diagnosis 全部业务逻辑（schemas / service / evidence_store / llm_provider）
- 仅在 BaseTool 层面做"参数解析 + 调 service + 返回 dict"包装
- legacy 代码不删（CLAUDE.md §禁止删除文件）

BaseTool 要求：name / description / input_schema / output_schema / execute
MCP 兼容：to_mcp_tool_spec() 输出 MCP 标准 dict
"""

from __future__ import annotations

from typing import Optional

from app.interfaces.base_tool import BaseTool

# 复用老的业务逻辑（legacy 不删，导入即可）
from legacy.agents.payment_diagnosis.service import PaymentDiagnosisService
from legacy.agents.payment_diagnosis.schemas import (
    DiagnoseRequest,
    ProblemRecord,
)


class PDATool(BaseTool):
    """支付诊断 Tool — MCP tool_spec 兼容。

    输入参数（input_schema）：
        merchant_id       商户 ID（必填）
        country           ISO 国家码，2 位大写（必填）
        channel           支付渠道（必填）
        error_code        错误码（必填）
        affected_orders   受影响订单号列表（可选）

    输出（output_schema）：
        problem_type       问题类型（支付失败/拒付/退款异常/Webhook 回调失败）
        root_causes        根因列表（人话描述）
        evidence_chain     证据链（每条可追溯到 risk_rule / channel_status / config_snapshot）
        recommended_actions 推荐处理步骤
        confidence         置信度 0-1
        next_agent         下一跳 Agent（固定为 Ticket Routing Agent）
    """

    name = "payment_diagnosis"
    description = (
        "诊断跨境支付失败 / 拒付 / 退款异常 / Webhook 回调失败问题。"
        "融合风控规则、通道状态、商户配置三类证据，输出带证据链的根因 + 推荐动作 + 置信度。"
        "对位 OP 命题方向 ②。"
    )

    def __init__(self, service: Optional[PaymentDiagnosisService] = None):
        """初始化 PDATool。

        Args:
            service: 注入业务服务（默认新建一个；测试时可注入 mock）
        """
        self.service = service or PaymentDiagnosisService()

    # === MCP tool_spec schemas ===

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "merchant_id": {
                    "type": "string",
                    "description": "商户 ID（Demo 占位：<DEMO_MERCHANT_ID>）",
                },
                "country": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 6,
                    "pattern": "^[A-Z]{2}$|^GLOBAL$",
                    "description": "ISO 国家码 2 位（US/BR/CN...）或 'GLOBAL'（如 MC 4-digit 拒付码 4837/4863 适用于全球）",
                },
                "channel": {
                    "type": "string",
                    "description": "支付渠道，如 Visa / Mastercard / PayPal",
                },
                "error_code": {
                    "type": "string",
                    "description": "错误码（如 CB_13.1 / ERR_xxx）。场景类问题（延迟/不稳定）可传空串",
                },
                "query_text": {
                    "type": "string",
                    "description": "商户原始提问原文（用于知识库语义检索，Day 14 P0-1）",
                },
                "affected_orders": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "受影响的订单号列表",
                },
            },
            "required": ["merchant_id", "country", "channel", "error_code"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "problem_type": {
                    "type": "string",
                    "description": "支付失败 / 拒付 / 退款异常 / Webhook 回调失败",
                },
                "root_causes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "根因列表（人话描述）",
                },
                "evidence_chain": {
                    "type": "array",
                    "description": "证据链（每条含 type / id / source / description）",
                },
                "recommended_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "推荐处理步骤",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "置信度 0-1",
                },
                "next_agent": {
                    "type": "string",
                    "description": "下一跳 Agent",
                },
            },
            "required": [
                "problem_type", "root_causes", "evidence_chain",
                "recommended_actions", "confidence", "next_agent",
            ],
        }

    @property
    def capabilities(self) -> dict:
        return {
            "async_supported": True,
            "idempotent": True,       # 相同输入产生相同诊断（除 LLM 随机性外）
            "requires_auth": False,
        }

    # === 业务执行 ===

    def execute(self, params: dict) -> dict:
        """执行诊断（带 LLM 降级策略）。

        异常处理（SOP-PDA-003）：
        - params 缺少必填字段 → jsonschema.ValidationError（由 BaseTool.validate_input 提前拦截）
        - evidence_store 找不到任何证据 → 仍返回结构化结果，root_causes 含兜底说明
        - LLM 调用失败 → 自动降级 MockLLMProvider 重试，trace 标记 degraded=True

        Returns:
            符合 output_schema 的 dict（额外含 trace 子字段，便于评审演示）
        """
        result = self._diagnose_with_fallback(params)
        return result

    def _diagnose_with_fallback(self, params: dict) -> dict:
        """调 service，LLM 失败时自动降级 MockLLMProvider。"""
        try:
            return self._diagnose(params)
        except Exception as llm_err:
            # 若当前 LLM 已是 MockLLMProvider，不再降级（避免无限循环）
            from legacy.agents.payment_diagnosis.llm_provider import MockLLMProvider
            if isinstance(self.service.llm, MockLLMProvider):
                raise

            # 降级：临时替换为 MockLLMProvider，重试一次
            original_llm = self.service.llm
            self.service.llm = MockLLMProvider()
            try:
                result = self._diagnose(params)
                # 在 trace 中标记降级（评审可演示：商户口中"AI 不会挂"）
                result["trace"]["degraded"] = True
                result["trace"]["original_llm"] = type(original_llm).__name__
                result["trace"]["degraded_reason"] = str(llm_err)
                return result
            finally:
                self.service.llm = original_llm

    def _diagnose(self, params: dict) -> dict:
        """单次诊断调用（不含降级逻辑）。"""
        req = DiagnoseRequest(
            problem_record=ProblemRecord(
                merchant_id=params["merchant_id"],
                country=params["country"],
                channel=params["channel"],
                error_code=params["error_code"],
                affected_orders=params.get("affected_orders", []),
                query_text=params.get("query_text", ""),
            )
        )

        resp = self.service.diagnose(req)

        d = resp.diagnosis
        return {
            "problem_type": d.problem_type,
            "root_causes": d.root_causes,
            "evidence_chain": [e.model_dump() for e in d.evidence_chain],
            "recommended_actions": d.recommended_actions,
            "confidence": d.confidence,
            "next_agent": d.next_agent,
            "error_image_path": resp.trace.get("error_image_path", ""),  # Day 9 拒付码配图
            "trace": resp.trace,
        }
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

    Day 15 Fix D：（channel × error_code）差异化诊断
    - 之前：Visa 13.1 与 MC 4837 答案几乎一致（actions 模板相同，仅 image/name 不同）
    - 现在：根据 (channel, error_code) 注入「reason name + 业务规则 + 差异化 actions」
    - 例：13.1 → "商品/服务未收" → 物流/签收凭证 + Visa RDR
    - 例：4837 → "未授权" → 风控/3DS + Mastercard Collaboration
    """

    # === Day 15 Fix D：（channel × error_code）差异化规则表 ===
    # 关键发现：Visa 13.1 vs MC 4837 在知识库文本里 "consumer dispute" / "RDR" 模板相同，
    # 导致 LLM 输出的 actions 几乎一样；商户视角"答案一样"。修复：注入**业务语义维度**不同的 actions。
    #
    # 分类：
    #   not_received: 13.1 / 13.3 / 15.x (Visa 商品/服务未收) → 强调 物流/签收/交付凭证
    #   not_authorized: 4837 / 4863 / 10.4 (MC 未授权) → 强调 3DS/风控/CVM
    #   fraud: 10.1 / 10.2 / 10.4 (Visa/MC 欺诈) → 强调 早拦截 + 风控收紧
    #   recurring: 4841 / 4834 (MC 订阅/分期) → 强调 MDP/Cancellation 流程
    #
    # 模板只在 Mock 路径生效（Qwen 也有机会调这个表作为 Fallback Knowledge）。
    _CODE_RULES = {
        # Visa 13.1: 商品/服务未收
        ("Visa", "13.1"): {
            "reason_name": "Merchandise/Services Not Received",
            "category": "not_received",
            "specific_actions": [
                "准备物流签收记录、投递证明、买家沟通截图",
                "如数字商品：附登录日志、下载记录、激活时间",
                "开通 Visa RDR 提前拦截同类争议",
            ],
        },
        ("Visa", "13.3"): {
            "reason_name": "Not As Described or Defective",
            "category": "not_received",
            "specific_actions": [
                "准备商品详情页描述、退换货政策、产品对比图",
                "附质检报告 / 故障视频",
                "开通 Visa RDR 拦截",
            ],
        },
        # MC 4837: 未授权
        ("Mastercard", "4837"): {
            "reason_name": "No Cardholder Authorization",
            "category": "not_authorized",
            "specific_actions": [
                "复核 3DS/SecureCode 验证记录（是否在交易中触发）",
                "排查 Card-on-File 存储与 CVV 校验配置",
                "开通 Mastercard Collaboration 拦截（CFR 平台）",
            ],
        },
        ("Mastercard", "4863"): {
            "reason_name": "Cardholder Does Not Recognize Transaction",
            "category": "not_authorized",
            "specific_actions": [
                "提供 BIN + 末四位 + 交易描述截图",
                "排查商户名称是否清晰（避免显示为陌生名称）",
                "开通 Mastercard Collaboration",
            ],
        },
        # 欺诈类
        ("Visa", "10.1"): {
            "reason_name": "EMV Liability Shift Counterfeit Fraud",
            "category": "fraud",
            "specific_actions": [
                "确认 3DS 覆盖率（按地区合规要求）",
                "扩展 Verifi RDR / CDRN 拦截范围",
                "收紧高风险国家 BIN 段交易限额",
            ],
        },
        # MC 订阅/分期
        ("Mastercard", "4841"): {
            "reason_name": "Canceled Recurring or Digital Goods",
            "category": "recurring",
            "specific_actions": [
                "提供订阅取消确认页 + 退款记录",
                "核对 Mastercard Digital Goods 规则（需 pre-arbitration）",
                "排查 Merchant Category Code (MCC) 是否准确",
            ],
        },
    }

    # Fallback: 只按 error_code 前缀匹配（channel 未知时）
    _CODE_PATTERN_RULES = {
        "13.1": "Visa",    # 商品/服务未收
        "13.3": "Visa",
        "13.5": "Visa",
        "4837": "Mastercard",  # 未授权
        "4863": "Mastercard",
        "4841": "Mastercard",  # 订阅取消
        "10.1": "Visa",     # 欺诈
        "10.2": "Visa",
        "10.4": "Mastercard",
    }

    @classmethod
    def _enrich_with_code_specific_actions(cls, params: dict, result: dict) -> dict:
        """Day 15 Fix D：注入 (channel, error_code) 差异化 actions。

        解决「Visa 13.1 vs MC 4837 答案一样」问题。

        步骤：
        1. 从 params.channel / params.error_code 查 _CODE_RULES 找到具体规则
        2. 找不到 → 按 code 前缀匹配 _CODE_PATTERN_RULES 拿 channel hint
        3. 找到规则 → 在 result.recommended_actions 前置「specific_actions」前 2 条
        4. 在 result.root_causes 前置「reason_name + 业务含义」1 条
        5. 在 result.evidence_chain 头部插 1 条 code-specific 证据（让商户看到"我们认得这个码"）
        6. 在 trace 标记 enriched 字段（评审可演示）
        """
        channel = (params.get("channel") or "").strip()
        error_code = (params.get("error_code") or "").strip()
        if not error_code or not error_code.upper().startswith("CB_"):
            return result  # 仅针对拒付码增强
        code_short = error_code[3:]  # 13.1 / 4837

        # 1. 精确匹配 (channel, error_code)
        rule = cls._CODE_RULES.get((channel, code_short))
        if not rule:
            # 2. 模糊匹配（按 error_code 联想到 channel）
            hinted_channel = cls._CODE_PATTERN_RULES.get(code_short) or channel
            rule = cls._CODE_RULES.get((hinted_channel, code_short))

        if not rule:
            return result  # 无规则 → 不增强

        # 3. 前置差异化 actions（前 2 条，避免覆盖 LLM 已有的「订单详情/物流/退款」通用建议）
        specific = rule.get("specific_actions", [])
        existing_actions = list(result.get("recommended_actions") or [])
        # 去重：只保留 LLM 没写的
        new_actions = [a for a in specific if a not in existing_actions]
        result["recommended_actions"] = new_actions[:2] + existing_actions

        # 4. 前置 reason name 根因
        reason_name = rule.get("reason_name", "")
        category = rule.get("category", "")
        if reason_name:
            cat_label = {
                "not_received": "商品/服务未收到",
                "not_authorized": "未获得持卡人授权",
                "fraud": "疑似欺诈",
                "recurring": "订阅/分期问题",
            }.get(category, "")
            # 把英文 reason name 翻译成人话（避免商户看到 13.1 / 4837 数字对应不上）
            new_root = f"拒付原因码 {code_short}「{reason_name}」（{cat_label}）"
            existing_roots = list(result.get("root_causes") or [])
            if new_root not in existing_roots:
                result["root_causes"] = [new_root] + existing_roots[:2]

        # 5. 前置 code-specific 证据（让 chain 质量提升）
        if reason_name:
            ev = {
                "type": "code_specific_rule",
                "id": f"cb_specific_{code_short.replace('.', '_')}",
                "source": "pda_internal_rule_table",
                "description": f"{channel} {code_short} 专属诊断：{reason_name}。"
                              f"对应业务场景：{cat_label}。"
                              f"差异化建议：{'; '.join(specific[:2])}",
            }
            existing_ev = list(result.get("evidence_chain") or [])
            result["evidence_chain"] = [ev] + existing_ev

        # 6. trace 标记
        result.setdefault("trace", {})["code_specific_enriched"] = {
            "channel": channel,
            "error_code": code_short,
            "reason_name": reason_name,
            "category": category,
            "injected_actions_count": len(new_actions[:2]),
        }

        return result

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
        result = {
            "problem_type": d.problem_type,
            "root_causes": d.root_causes,
            "evidence_chain": [e.model_dump() for e in d.evidence_chain],
            "recommended_actions": d.recommended_actions,
            "confidence": d.confidence,
            "next_agent": d.next_agent,
            "error_image_path": resp.trace.get("error_image_path", ""),  # Day 9 拒付码配图
            "trace": resp.trace,
        }
        # Day 15 Fix D：(channel, error_code) 差异化诊断
        # 解决 Visa 13.1 vs MC 4837 答案几乎一样的硬伤
        result = self._enrich_with_code_specific_actions(params, result)
        return result
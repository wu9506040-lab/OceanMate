"""Orchestrator - 商户成功 AI 中枢（意图分流 + Tool 编排）。

设计（PoC 精简版 · Day 4 + Day 14 P1-1）：
- 关键词匹配（白名单）→ LLM 兜底（Qwen chat_structured）
- 单 query 单意图（最常见）
- 显式 unknown intent → 友好提示

未来扩展（Day 5+）：
- ReAct 模式（思考 → 行动 → 观察 → 循环）
- 多意图拆分（同一 query 命中多种）
- 上下文管理（多轮对话）
- AtoA 自动链式编排（Day 14 P1-3）
"""

from __future__ import annotations

import logging
from typing import Optional

from app.interfaces.base_tool import ToolRegistry, BaseTool
from app.interfaces.base_llm import BaseLLMGateway
from app.implementations.llm.qwen_gateway import MockLLMGateway, QwenGateway
from app.agents.orchestrator.chain_config import get_next_chain_rule


# Day 14 P1-3：链式触发最大深度（防止死循环）
MAX_CHAIN_DEPTH = 5


logger = logging.getLogger(__name__)


# === 意图识别（关键词白名单） ===

INTENT_KEYWORDS = {
    "payment_diagnosis": [
        "失败", "错误码", "ERR_", "拒付", "退款异常",
        "Webhook 回调", "3DS 失败", "风控拦截", "无法支付",
    ],
    "merchant_success": [
        "支付方式", "选什么", "推荐", "PWR",
        "国家", "客单价", "B2B", "B2C", "接入",
        "想做", "准备做", "开拓",
    ],
    "ticket_routing": [
        "工单", "派单", "SLA", "状态", "T0",
        "已分配", "已派", "转人工", "客服",
    ],
    "knowledge_evolution": [
        "FAQ", "知识库", "怎么操作", "如何接入",
        "文档", "教程", "Merchange Console",
    ],
}

# MSA 子意图识别（基于商户画像完整度）
MSA_SUB_INTENT_BY_PROFILE = {
    "complete": "recommend_payment_methods",
    "incomplete": "collect_profile",
}

# Day 14 P1-1：LLM fallback 调用的 prompt 模板
LLM_INTENT_PROMPT_TEMPLATE = """你是跨境支付商户成功 AI 中枢的意图分类器。请判断用户消息属于以下哪种意图：

- payment_diagnosis：支付失败 / 错误码 / 拒付 / 退款异常 / 风控拦截 等诊断类
- merchant_success：支付方式推荐 / 商户画像采集 / 选什么方案 等商户成功类
- ticket_routing：工单状态 / 派单 / SLA / 转人工 / 客服 等工单类
- knowledge_evolution：FAQ 查询 / 知识库 / 文档 / 教程 / 如何操作 等知识类
- unknown：都不属于

用户消息："{query}"

请严格按照以下 JSON Schema 输出（不要任何额外文字）：
{{"intent": "<以上5个之一>", "confidence": <0.0-1.0的浮点数>, "reason": "<一句话解释>"}}"""


class Orchestrator:
    """商户成功 AI 中枢。

    使用：
        orch = Orchestrator()
        orch.register_tool(PDATool())
        orch.register_tool(MSATool())
        result = orch.route(user_query="...")

    Day 14 P1-1 新增：
        orch = Orchestrator(use_llm_fallback=False)  # 关闭 LLM fallback（仅关键词模式）
    """

    def __init__(
        self,
        llm: Optional[BaseLLMGateway] = None,
        registry: Optional[ToolRegistry] = None,
        use_llm_fallback: bool = True,
        chain_mode: str = "auto",  # Day 14 P1-3: "auto" 自动链式 / "single" 单步
    ):
        # 优先 Qwen，无 key 时降级 Mock（与原行为一致）
        if llm is not None:
            self.llm = llm
        else:
            try:
                self.llm = QwenGateway()
            except Exception:
                self.llm = MockLLMGateway()
        self.registry = registry or ToolRegistry()
        self.use_llm_fallback = use_llm_fallback
        self.chain_mode = chain_mode

    def register_tool(self, tool: BaseTool) -> None:
        self.registry.register(tool)

    def list_tools(self) -> list[dict]:
        """列出已注册 Tool 的 MCP tool_spec（评审展示）。"""
        return self.registry.list_tools()

    def route(
        self,
        user_query: str,
        merchant_context: Optional[dict] = None,
    ) -> dict:
        """主入口：识别意图 → 调对应 Tool → 可选链式触发下一 Tool → 返回。

        Day 14 P1-3 新增 chain_mode="auto" 自动链式触发（如 PDA → TRA → KEA）。

        Returns:
            {
                "intent": "payment_diagnosis" | ...,
                "tool_name": "...",
                "tool_result": {...},           # safe_execute 返回的 wrapped {success, data, ...}
                "trace": {
                    "matched_keywords": [...],
                    "llm_used": bool,
                    "llm_intent": str | None,
                    "llm_confidence": float | None,
                }
                "chain": [                     # Day 14 P1-3
                    {"step": 1, "tool": "payment_diagnosis", "result": {...}},
                    {"step": 2, "tool": "ticket_routing", "result": {...}},
                ]
            }
        """
        ctx = {"user_query": user_query, **(merchant_context or {})}

        # Step 1: 关键词匹配
        intent, matched = self._classify_intent(user_query)

        # Step 2: 关键词未命中 + 启用 LLM fallback → 调 LLM 兜底
        llm_used = False
        llm_intent = None
        llm_confidence = None
        if intent == "unknown" and self.use_llm_fallback:
            llm_intent, llm_confidence = self._classify_intent_with_llm(user_query)
            if llm_intent and llm_intent in INTENT_KEYWORDS:
                intent = llm_intent
                matched = []  # LLM fallback 时关键词为空
                llm_used = True
            elif llm_intent == "unknown":
                llm_used = True  # LLM 也认不出，保持 unknown

        # Step 3: 按意图构造 params 并调 Tool
        if intent == "payment_diagnosis":
            result = self._route_pda(user_query, ctx, matched)
        elif intent == "merchant_success":
            result = self._route_msa(user_query, ctx, matched)
        elif intent == "ticket_routing":
            result = self._route_tra(user_query, ctx, matched)
        elif intent == "knowledge_evolution":
            result = self._route_kea(user_query, ctx, matched)
        else:
            result = self._unknown_response(user_query, matched)

        # Step 4: 把 LLM fallback 信息追加到 trace（Day 14 P1-1）
        result["trace"]["llm_used"] = llm_used
        if llm_used:
            result["trace"]["llm_intent"] = llm_intent
            result["trace"]["llm_confidence"] = llm_confidence

        # Step 5: Day 14 P1-3 自动链式触发
        if self.chain_mode == "auto":
            result = self._maybe_chain(result, ctx, depth=1)

        return result

    def _maybe_chain(self, result: dict, ctx: dict, depth: int) -> dict:
        """链式触发：根据当前 Tool 的 CHAIN_RULES 决定是否调下一 Tool。

        限制：
        - 最大深度 MAX_CHAIN_DEPTH（防死循环）
        - 链路 trigger 不命中 → 不链式
        - 下一 Tool 未注册 → 跳过链式（记录到 trace.chain_skipped）

        递归设计：
        - 始终在原 result 上 append "chain" 步骤
        - 递归调用时，把"刚执行的 next_wrapped"包装成临时 prev，递归
        - 最终返回原 result（保留所有原始字段：intent/trace 等）
        """
        if depth > MAX_CHAIN_DEPTH:
            logger.warning(f"[Orchestrator] 链式触发达到最大深度 {MAX_CHAIN_DEPTH}，停止")
            result.setdefault("trace", {})["chain_max_depth"] = depth
            return result

        # 从最后一次链式步骤或原始 result 取当前 tool_name + data
        current_tool, prev_data = self._peek_chain_state(result)
        chain_rule = get_next_chain_rule(current_tool) if current_tool else None
        if not chain_rule:
            return result

        # trigger 命中检查
        if not chain_rule["trigger"](prev_data):
            return result

        # 构造下一 Tool params
        next_params = chain_rule["params_builder"](prev_data, ctx)
        next_tool = chain_rule["next_tool"]

        # 下一 Tool 是否注册
        if next_tool not in self.registry:
            result.setdefault("trace", {})["chain_skipped"] = f"{next_tool} 未注册"
            return result

        logger.info(
            f"[Orchestrator] 链式触发 step={depth}: {current_tool} → {next_tool} "
            f"(trigger 命中, params keys: {list(next_params.keys())})"
        )

        # 执行下一 Tool
        next_wrapped = self.registry.safe_execute(next_tool, next_params)
        next_step = {
            "step": depth + 1,
            "tool": next_tool,
            "result": next_wrapped,
            "triggered_by": current_tool,
        }
        result.setdefault("chain", []).append(next_step)

        # 递归：基于刚执行的 next_wrapped 判断是否继续链式
        # 不修改 result，只递归检查
        return self._maybe_chain(result, ctx, depth=depth + 1)

    @staticmethod
    def _peek_chain_state(result: dict) -> tuple[Optional[str], dict]:
        """从 result 里取出"当前 Tool 名称 + data"用于链式判断。

        优先从最后一步 chain 取（链中段），否则从 result.tool_result 取（链头）。
        """
        chain = result.get("chain", [])
        if chain:
            last_step = chain[-1]
            last_wrapped = last_step.get("result", {})
            last_data = last_wrapped.get("data", {}) if last_wrapped.get("success") else {}
            return last_step.get("tool"), last_data
        # 链头：用原始 tool_result
        wrapped = result.get("tool_result", {})
        data = wrapped.get("data", {}) if wrapped.get("success") else {}
        return result.get("tool_name"), data

    # === 意图分类 ===

    def _classify_intent(self, query: str) -> tuple[str, list[str]]:
        """关键词匹配 + LLM 兜底决策，返回 (best_intent, all_matched_keywords)。

        Day 14 P1-1 改造：
        - 关键词命中 ≥1 → 返回关键词结果（不变）
        - 关键词命中 0 → 调 LLM 分类（返回的 intent 是 LLM 结果）

        注：本方法被 route() 调用时已做 LLM 兜底，这里实际只跑关键词。
        单独抽出来便于测试 + 未来扩展（如多轮对话复用关键词结果）。
        """
        scores = {}
        matched_by_intent = {}
        for intent, kws in INTENT_KEYWORDS.items():
            hits = [k for k in kws if k in query]
            if hits:
                scores[intent] = len(hits)
                matched_by_intent[intent] = hits

        if not scores:
            return "unknown", []

        # 取最高分；同分按 INTENT_KEYWORDS 顺序
        best_intent = max(
            scores,
            key=lambda i: (scores[i], -list(INTENT_KEYWORDS.keys()).index(i)),
        )
        return best_intent, matched_by_intent.get(best_intent, [])

    def _classify_intent_with_llm(self, query: str) -> tuple[str, Optional[float]]:
        """LLM 兜底分类（Day 14 P1-1）。

        Returns:
            (intent, confidence) — 失败时返回 ("unknown", None)
        """
        prompt = LLM_INTENT_PROMPT_TEMPLATE.format(query=query)
        try:
            result = self.llm.chat_structured(
                messages=[{"role": "user", "content": prompt}],
                output_schema={
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string"},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["intent", "confidence"],
                },
                model="qwen-turbo",  # 分类任务用 turbo 即可，省 token
            )
            intent = result.get("intent", "unknown")
            confidence = result.get("confidence")
            logger.info(
                f"[Orchestrator] LLM fallback intent='{intent}', confidence={confidence}, reason='{result.get('reason', '')}'"
            )
            # 校验 intent 在合法列表
            if intent not in INTENT_KEYWORDS and intent != "unknown":
                logger.warning(f"[Orchestrator] LLM 返回非法 intent '{intent}'，降级 unknown")
                return "unknown", confidence
            return intent, confidence
        except Exception as e:
            logger.warning(f"[Orchestrator] LLM 兜底失败，降级 unknown: {e}")
            return "unknown", None

    # === 路由到各 Tool ===

    def _route_pda(self, query: str, ctx: dict, matched: list[str]) -> dict:
        """路由到 PDATool。"""
        if "payment_diagnosis" not in self.registry:
            return self._tool_not_available("payment_diagnosis")

        # PDA 需要 country/channel/error_code，商户 ctx 可能不全
        params = {
            "merchant_id": ctx.get("merchant_id", "unknown"),
            "country": ctx.get("country", "ZZ"),
            "channel": ctx.get("channel", "unknown"),
            "error_code": ctx.get("error_code", "ERR_UNKNOWN"),
            "affected_orders": ctx.get("affected_orders", []),
        }
        wrapped = self.registry.safe_execute("payment_diagnosis", params)
        # safe_execute 返回 {success, data, error_code, error_message}
        data = wrapped.get("data", {}) if wrapped.get("success") else {}
        error_image_path = data.get("error_image_path", "") if isinstance(data, dict) else ""
        return {
            "intent": "payment_diagnosis",
            "tool_name": "payment_diagnosis",
            "tool_result": wrapped,   # 保留 safe_execute 包装（前端能看 success）
            "error_image_path": error_image_path,  # 顶层暴露
            "trace": {"matched_keywords": matched, "params": params},
        }

    def _route_msa(self, query: str, ctx: dict, matched: list[str]) -> dict:
        """路由到 MSATool（决定 recommend vs collect_profile）。"""
        if "merchant_success" not in self.registry:
            return self._tool_not_available("merchant_success")

        # 根据画像完整度决定 MSA 子意图
        required = ("country", "industry", "avg_amount", "target_users")
        is_complete = all(ctx.get(f) for f in required)
        sub_intent = (
            "recommend_payment_methods" if is_complete else "collect_profile"
        )

        params = {
            "intent": sub_intent,
            "merchant_context": ctx,
            "user_query": query,
        }
        result = self.registry.safe_execute("merchant_success", params)
        return {
            "intent": "merchant_success",
            "tool_name": "merchant_success",
            "tool_result": result,
            "trace": {
                "matched_keywords": matched,
                "sub_intent": sub_intent,
                "is_profile_complete": is_complete,
            },
        }

    def _route_tra(self, query: str, ctx: dict, matched: list[str]) -> dict:
        """路由到 TRATool（Day 5 已实现）。

        自动选 intent：
        - ctx 含 ticket_id → query_status（商户问现有工单状态）
        - ctx 含 problem_type → route_ticket（典型 PDA → TRA 链）
        - 都没有 → 默认 route_ticket（让 TRA 自己反问）
        """
        if "ticket_routing" not in self.registry:
            return self._tool_not_available(
                "ticket_routing",
                hint="TRA Tool 未注册。如需立即处理，请联系人工客服。",
            )

        if ctx.get("ticket_id"):
            sub_intent = "query_status"
        elif ctx.get("problem_type"):
            sub_intent = "route_ticket"
        else:
            sub_intent = "route_ticket"

        params = {
            "intent": sub_intent,
            "problem_type": ctx.get("problem_type"),
            "priority": ctx.get("priority", "medium"),
            "tier": ctx.get("tier", "standard"),
            "merchant_id": ctx.get("merchant_id"),
            "diagnosis_id": ctx.get("diagnosis_id"),
            "ticket_id": ctx.get("ticket_id"),
        }
        # 清理 None，让 Tool 自己的 schema 处理缺省
        params = {k: v for k, v in params.items() if v is not None}
        result = self.registry.safe_execute("ticket_routing", params)
        return {
            "intent": "ticket_routing",
            "tool_name": "ticket_routing",
            "tool_result": result,
            "trace": {
                "matched_keywords": matched,
                "sub_intent": sub_intent,
                "params": params,
            },
        }

    def _route_kea(self, query: str, ctx: dict, matched: list[str]) -> dict:
        """路由到 KEATool（Day 6 已实现）。

        自动选 intent：
        - ctx.case_id         → promote_to_faq （商户问"这个案例能进FAQ吗"）
        - ctx.query           → search_faq     （商户直接搜 FAQ）
        - 否则                → list_candidates（让 KEA 列候选给商户看）
        """
        if "knowledge_evolution" not in self.registry:
            return self._tool_not_available(
                "knowledge_evolution",
                hint="KEA Tool 未注册。如需立即处理，请联系人工客服。",
            )

        if ctx.get("case_id"):
            sub_intent = "promote_to_faq"
        elif ctx.get("query"):
            sub_intent = "search_faq"
        else:
            sub_intent = "list_candidates"

        params = {
            "intent": sub_intent,
            "case_id": ctx.get("case_id"),
            "query": ctx.get("query") or query,
            "top_k": ctx.get("top_k", 5),
            "country": ctx.get("country"),
            "min_confidence": ctx.get("min_confidence", 0.85),
            "limit": ctx.get("limit", 20),
        }
        # 去掉 None，让 Tool schema 自行处理缺省
        params = {k: v for k, v in params.items() if v is not None}
        result = self.registry.safe_execute("knowledge_evolution", params)
        return {
            "intent": "knowledge_evolution",
            "tool_name": "knowledge_evolution",
            "tool_result": result,
            "trace": {
                "matched_keywords": matched,
                "sub_intent": sub_intent,
                "params": params,
            },
        }

    def _unknown_response(self, query: str, matched: list[str]) -> dict:
        """意图不明 → 兜底到 MSA collect_profile（让商户说出更多）。"""
        # 同时尝试 MSA 的 collect_profile（友好引导）
        if "merchant_success" in self.registry:
            result = self.registry.safe_execute("merchant_success", {
                "intent": "collect_profile",
                "merchant_context": {},
                "user_query": query,
            })
            return {
                "intent": "unknown_fallback_to_msa",
                "tool_name": "merchant_success",
                "tool_result": result,
                "trace": {
                    "matched_keywords": matched,
                    "fallback_reason": "no_keyword_match",
                },
            }

        # 兜底中的兜底（无 MSA 时）
        return {
            "intent": "unknown",
            "tool_name": None,
            "tool_result": {
                "success": False,
                "error_code": "INTENT_UNKNOWN",
                "error_message": (
                    f"无法识别您的意图：「{query[:30]}」。"
                    "请补充：支付失败（诊断）/ 选支付方式（推荐）/ 工单状态 / 知识查询。"
                ),
            },
            "trace": {"matched_keywords": matched},
        }

    @staticmethod
    def _tool_not_available(tool_name: str, hint: str = "") -> dict:
        return {
            "intent": tool_name,
            "tool_name": tool_name,
            "tool_result": {
                "success": False,
                "error_code": "TOOL_NOT_REGISTERED",
                "error_message": f"Tool '{tool_name}' 未注册。{hint}",
            },
            "trace": {},
        }
"""Orchestrator - 商户成功 AI 中枢（意图分流 + Tool 编排）。

设计（PoC 精简版 · Day 4）：
- 基于关键词 + LLM 兜底的意图分类
- 单 query 单意图（最常见）
- 显式 unknown intent → 友好提示

未来扩展（Day 5+）：
- ReAct 模式（思考 → 行动 → 观察 → 循环）
- 多意图拆分（同一 query 命中多种）
- 上下文管理（多轮对话）
- LLM 动态 Tool 选择（vs 当前关键词白名单）
"""

from __future__ import annotations

from typing import Optional

from app.interfaces.base_tool import ToolRegistry, BaseTool
from app.interfaces.base_llm import BaseLLMGateway
from app.implementations.llm.qwen_gateway import MockLLMGateway


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


class Orchestrator:
    """商户成功 AI 中枢。

    使用：
        orch = Orchestrator()
        orch.register_tool(PDATool())
        orch.register_tool(MSATool())
        result = orch.route(user_query="...")
    """

    def __init__(
        self,
        llm: Optional[BaseLLMGateway] = None,
        registry: Optional[ToolRegistry] = None,
    ):
        self.llm = llm or MockLLMGateway()
        self.registry = registry or ToolRegistry()

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
        """主入口：识别意图 → 调对应 Tool → 返回统一结果。

        Returns:
            {
                "intent": "payment_diagnosis" | ...,
                "tool_name": "...",
                "tool_result": {...},           # safe_execute 返回的 data
                "trace": {
                    "matched_keywords": [...],
                    "llm_used": bool,
                }
            }
        """
        ctx = merchant_context or {}

        # Step 1: 关键词匹配
        intent, matched = self._classify_intent(user_query)

        # Step 2: 按意图构造 params 并调 Tool
        if intent == "payment_diagnosis":
            return self._route_pda(user_query, ctx, matched)
        elif intent == "merchant_success":
            return self._route_msa(user_query, ctx, matched)
        elif intent == "ticket_routing":
            return self._route_tra(user_query, ctx, matched)
        elif intent == "knowledge_evolution":
            return self._route_kea(user_query, ctx, matched)
        else:
            return self._unknown_response(user_query, matched)

    # === 意图分类 ===

    @staticmethod
    def _classify_intent(query: str) -> tuple[str, list[str]]:
        """关键词匹配，返回 (best_intent, all_matched_keywords)。

        评分：每个 intent 命中关键词数。
        Tie-break：intent 顺序（payment_diagnosis > merchant_success > ticket_routing > knowledge_evolution）。
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
        result = self.registry.safe_execute("payment_diagnosis", params)
        return {
            "intent": "payment_diagnosis",
            "tool_name": "payment_diagnosis",
            "tool_result": result,
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
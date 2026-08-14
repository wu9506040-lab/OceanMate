"""Orchestrator - 商户成功 AI 中枢（意图分流 + Tool 编排）。

设计（PoC 精简版 · Day 4 + Day 14 P1-1 + Day 15 P1-6）：
- 关键词匹配（白名单）→ LLM 兜底（Qwen chat_structured）
- 单 query 单意图（最常见）
- 显式 unknown intent → 友好提示
- 4 个 Tool 路由函数拆到 routers.py（Orchestrator 只做调度）
- 自动链式编排（PDA → TRA → KEA）

未来扩展（Day 5+）：
- ReAct 模式（思考 → 行动 → 观察 → 循环）
- 多意图拆分（同一 query 命中多种）
- 上下文管理（多轮对话）
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.interfaces.base_tool import ToolRegistry, BaseTool
from app.interfaces.base_llm import BaseLLMGateway
from app.implementations.llm.qwen_gateway import MockLLMGateway, QwenGateway
from app.agents.orchestrator.chain_config import get_next_chain_rule
from app.agents.orchestrator import routers as _routers


# Day 14 P1-3：链式触发最大深度（防止死循环）
MAX_CHAIN_DEPTH = 5

# Day 15 P0-1：query 长度上限（防止 1000+ 字 query 触发 Qwen token 上限报错）
MAX_QUERY_LENGTH = 500


logger = logging.getLogger(__name__)


# === 通用工具 ===

def _coerce_float(value, *, default: float, field: str) -> Optional[float]:
    """Day 15 P0-3：把任意值安全转为 float，失败降级为 default。

    防 LLM 返回 "0.85" 字符串 / 缺失字段 / None 等导致下游比较 TypeError。
    """
    if value is None:
        return default
    try:
        result = float(value)
        # 截断到 [0.0, 1.0]
        return max(0.0, min(1.0, result))
    except (TypeError, ValueError):
        logger.warning(f"[Orchestrator] {field} 强转 float 失败: value={value!r}, 降级 {default}")
        return default


# === 意图识别（关键词白名单） ===

INTENT_KEYWORDS = {
    "payment_diagnosis": [
        "失败", "错误码", "ERR_", "拒付", "退款异常",
        "Webhook 回调", "3DS 失败", "风控拦截", "无法支付",
        # Day 14 P0-1：场景类问题（无错误码）此前根本进不来诊断意图
        "延迟", "不到账", "到账慢", "结算", "对账", "不稳定",
        "回调失败", "chargeback", "申诉", "扣款",
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

    Day 15 P1-6：4 个 Tool 的路由函数已拆到 routers.py，
    本类只负责：意图分类、并发锁、自动链式调度。

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
        # Day 15 P0-2：并发锁（threading.RLock 保证同一线程可重入；
        # 当前 route() 内部状态实际已全局部化无共享，但加锁防未来回归）
        self._route_lock = threading.RLock()

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
        # Day 15 P0-1：超长输入截断（防止 token 上限报错 + 礼貌提示）
        if user_query and len(user_query) > MAX_QUERY_LENGTH:
            truncated = user_query[:MAX_QUERY_LENGTH]
            logger.warning(
                f"[Orchestrator] query 超长截断: 原长={len(user_query)}, 截断后={MAX_QUERY_LENGTH}"
            )
            return {
                "intent": "unknown",
                "tool_name": None,
                "tool_result": {
                    "success": False,
                    "error_code": "QUERY_TOO_LONG",
                    "error_message": (
                        f"输入过长（{len(user_query)} 字），请精简到 {MAX_QUERY_LENGTH} 字以内重试。"
                        f"已自动截断前 {MAX_QUERY_LENGTH} 字处理：\n\n{truncated}..."
                    ),
                },
                "trace": {
                    "matched_keywords": [],
                    "llm_used": False,
                    "llm_intent": None,
                    "llm_confidence": None,
                    "truncated": True,
                    "original_length": len(user_query),
                },
            }

        # Day 15 P0-2：并发锁（route 入口加锁，instance 级可重入）
        with self._route_lock:
            return self._route_locked(user_query, merchant_context)

    def _route_locked(
        self,
        user_query: str,
        merchant_context: Optional[dict],
    ) -> dict:
        """route() 的加锁实现（Day 15 P0-2：threading.RLock 包裹）。

        拆出来便于：1) 加锁点单一；2) 不污染 docstring。
        4 个 Tool 的路由逻辑已委托到 routers.py（Day 15 P1-6）。
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

        # Step 3: 按意图委托到 routers.py 中的对应路由函数（Day 15 P1-6）
        if intent == "payment_diagnosis":
            result = _routers.route_pda(user_query, ctx, matched, self.registry)
        elif intent == "merchant_success":
            result = _routers.route_msa(user_query, ctx, matched, self.registry)
        elif intent == "ticket_routing":
            result = _routers.route_tra(user_query, ctx, matched, self.registry)
        elif intent == "knowledge_evolution":
            result = _routers.route_kea(user_query, ctx, matched, self.registry)
        else:
            result = _routers.unknown_response(user_query, matched, self.registry)

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
            # Day 15 P0-3：强校验 confidence 必须是 float，否则降级 0.5
            # （防止 Qwen 返回 "0.85" 字符串 → 下游 >= 0.7 比较 TypeError）
            confidence = _coerce_float(confidence, default=0.5, field="llm_confidence")
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
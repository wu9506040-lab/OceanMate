"""AtoA 自动链式编排规则配置（Day 14 P1-3）。

定义「前序 Tool 完成 → 自动触发下一 Tool」的链路规则。
链路决策 = trigger 条件 + params_builder（如何从前序结果构造下一 Tool 的入参）。

设计原则：
1. 触发条件基于前序 Tool 返回结果（不依赖时间/状态机）
2. params_builder 把前序结果"翻译"成下一 Tool 的 schema
3. 默认全部链路开启，Orchestrator 用 chain_mode="single" 关闭

PoC 阶段定义两条链路：
- PDA → TRA（诊断 → 派单）
- TRA → KEA（派单 → 查相关 FAQ；不直接 promote，避免错误沉淀）

未来扩展：
- TRA → KEA promote_to_faq（结案后自动 promote，仅在 status="closed" 时）
- KEA search_faq → MSA recommend（用户问支付方式 → 推荐 + 关联 FAQ）
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# === 链路规则定义 ===

# 链路 1：PDA → TRA
# 触发：PDA 诊断成功 + confidence ≥ 0.7 + problem_type 非空 + next_agent 指向 TRA
# 下一 Tool：ticket_routing（intent=route_ticket）
# 注：trigger/params_builder 都接收 prev_data（即 safe_execute 返回的 data dict）
PDA_TO_TRA_CHAIN = {
    "next_tool": "ticket_routing",
    "trigger": lambda prev_data: (
        prev_data.get("confidence", 0.0) >= 0.7
        and bool(prev_data.get("problem_type"))
        # next_agent 是 LLM 输出，可能是 "Ticket Routing Agent" / "ticket_routing" 等
        # 用关键词宽松匹配
        and "ticket" in prev_data.get("next_agent", "").lower()
    ),
    "params_builder": lambda prev_data, ctx: {
        "intent": "route_ticket",
        "problem_type": prev_data.get("problem_type"),
        "priority": ctx.get("priority") or prev_data.get("priority") or "medium",
        "tier": ctx.get("tier", "standard"),
        "merchant_id": ctx.get("merchant_id"),
        "diagnosis_id": prev_data.get("diagnosis_id"),
        "problem_summary": ctx.get("user_query", "")[:200],
        # 注意：TRA schema 不接受 source 字段（不在 input_schema 中），省略
    },
}

# 链路 2：TRA → KEA（半自动：派单成功后查相关 FAQ，不直接 promote）
# 触发：TRA route_ticket 成功
# 下一 Tool：knowledge_evolution（intent=search_faq）
TRA_TO_KEA_CHAIN = {
    "next_tool": "knowledge_evolution",
    "trigger": lambda prev_data: (
        bool(prev_data.get("ticket_id"))
        and prev_data.get("status") in ("pending", "processing")
    ),
    "params_builder": lambda prev_data, ctx: {
        "intent": "search_faq",
        "query": (prev_data.get("problem_type", "") or "") + " " + (ctx.get("user_query", "") or ""),
        "top_k": 3,
        "country": ctx.get("country"),
    },
}


# Tool 名称 → 链路规则 映射
CHAIN_RULES: dict[str, dict] = {
    "payment_diagnosis": PDA_TO_TRA_CHAIN,
    "ticket_routing": TRA_TO_KEA_CHAIN,
    # knowledge_evolution 不再继续链式（避免无限触发）
}


def get_next_chain_rule(tool_name: str) -> Optional[dict]:
    """获取指定 Tool 完成后的下一跳链路规则（若无则返回 None）。"""
    return CHAIN_RULES.get(tool_name)
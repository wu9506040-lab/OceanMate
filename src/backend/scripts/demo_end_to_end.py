"""End-to-End Demo - 真实端到端验证（Day 8 · 方向 A）。

设计：
- 9 个真实商户咨询场景，覆盖 4 Tool（payment_diagnosis / merchant_success / ticket_routing / knowledge_evolution）
- 真实 KB（error_codes_vec 10 / cases_vec 4 / payment_methods_vec 9）
- 真实 Orchestrator 路由 + 真实 Tool 执行
- 输出：每个 query 的 intent / tool / RAG 召回 chunks / 最终回复
- 末尾：报告统计（覆盖率 / RAG 命中数 / 各 Tool 命中数）

依赖：不需要 dashscope / feishu key（全部走 mock LLM，但数据流真实）
用法：
    cd src/backend
    python scripts/demo_end_to_end.py
    python scripts/demo_end_to_end.py --quiet  # 只打报告
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from app.agents.orchestrator import create_default_orchestrator
from app.implementations.rag.chroma_rag import ChromaRAGEngine


# 9 个真实商户场景（覆盖 4 Tool + 边界 case）
DEMO_QUERIES = [
    # ===== payment_diagnosis（4 个）=====
    {
        "id": "Q1",
        "query": "BR Visa 拒付 ERR_DEMO_RISK_BLOCK_BR_VISA_001 失败怎么解决",
        "expect_intent": "payment_diagnosis",
        "expect_kb": "cases_vec",
        "scenario": "商户提交错误码，期望 PDA 召回 BR 风控案例",
    },
    {
        "id": "Q2",
        "query": "BR 区域 3DS 认证失败 ERR_DEMO_3DS_REQUIRED_001",
        "expect_intent": "payment_diagnosis",
        "expect_kb": "cases_vec",
        "scenario": "BR 3DS 配置问题",
    },
    {
        "id": "Q3",
        "query": "PayPal 退款异常怎么处理",
        "expect_intent": "payment_diagnosis",
        "expect_kb": "cases_vec",
        "scenario": "PayPal 退款被拒",
    },
    {
        "id": "Q4",
        "query": "Webhook 回调失败 商户收不到通知",
        "expect_intent": "payment_diagnosis",
        "expect_kb": "error_codes_vec",
        "scenario": "Webhook 5xx 问题",
    },
    # ===== merchant_success（2 个）=====
    {
        "id": "Q5",
        "query": "BR 国家准备做跨境电商 B2C，推荐什么支付方式",
        "expect_intent": "merchant_success",
        "expect_kb": "payment_methods_vec",
        "scenario": "MSA PWR 子能力：BR 电商推荐",
    },
    {
        "id": "Q6",
        "query": "客单价 $500 B2B 怎么接入 OP",
        "expect_intent": "merchant_success",
        "expect_kb": "payment_methods_vec",
        "scenario": "MSA：US B2B 大额推荐",
    },
    # ===== ticket_routing（1 个）=====
    {
        "id": "Q7",
        "query": "帮我建一个工单，需要 OP 客服支持",
        "expect_intent": "ticket_routing",
        "expect_kb": None,
        "scenario": "TRA 创建工单",
    },
    # ===== knowledge_evolution（2 个）=====
    {
        "id": "Q8",
        "query": "FAQ 知识库怎么操作 怎么升级案例",
        "expect_intent": "knowledge_evolution",
        "expect_kb": None,
        "scenario": "KEA search_faq / list_candidates",
    },
    {
        "id": "Q9",
        "query": "如何接入 Merchant Console 教程",
        "expect_intent": "knowledge_evolution",
        "expect_kb": None,
        "scenario": "KEA 文档检索",
    },
]


def run_demo(quiet: bool = False) -> dict:
    """跑 9 个 query，输出报告。

    Returns:
        {
            "total_queries": int,
            "intent_correct": int,
            "rag_hits": int,           # 实际 RAG 召回数（独立测 ChromaRAGEngine.retrieve）
            "by_tool": dict,           # {tool_name: count}
            "details": list,
        }
    """
    orch = create_default_orchestrator(
        db_path="data/oceanmate.db",
        chroma_path="data/chroma",
        auto_init_db=False,
    )
    # 单独测 RAG 召回（Orchestrator 不持有 RAG，Tool 内部用）
    rag = ChromaRAGEngine()

    print(f"\n{'=' * 70}")
    print(f"OceanMate End-to-End Demo · 9 真实商户场景")
    print(f"{'=' * 70}")

    details = []
    by_tool = {}
    intent_correct = 0
    rag_total_hits = 0
    rag_zero_count = 0

    for item in DEMO_QUERIES:
        qid = item["id"]
        q = item["query"]
        expect_intent = item["expect_intent"]
        expect_kb = item.get("expect_kb")
        scenario = item["scenario"]

        result = orch.route(user_query=q, merchant_context={"user_id": "demo_user"})
        actual_intent = result["intent"]
        tool_name = result["tool_name"]
        tool_result = result.get("tool_result", {})

        is_correct = (actual_intent == expect_intent)
        if is_correct:
            intent_correct += 1
        by_tool[tool_name] = by_tool.get(tool_name, 0) + 1

        # 独立测 RAG 召回（直接调 rag.retrieve，不走 Tool 组装）
        rag_hits = []
        if rag and expect_kb:
            rag_hits = rag.retrieve(q, top_k=5, collection_name=expect_kb)

        if rag_hits:
            rag_total_hits += len(rag_hits)
        else:
            rag_zero_count += 1

        # 看 Tool 是否把 RAG 用上了（从 tool_result.data 推断）
        tool_used_rag = False
        rag_usage_hint = ""
        if isinstance(tool_result, dict):
            data = tool_result.get("data", {})
            # PDA: root_causes 含 config_snapshot 说明用了 RAG
            if "root_causes" in data and data.get("root_causes"):
                tool_used_rag = True
                rag_usage_hint = f"root_causes: {data['root_causes'][:1]}"
            # KEA: candidates / faqs 非空
            elif "candidates" in data and data.get("candidates"):
                tool_used_rag = True
                rag_usage_hint = f"candidates: {len(data['candidates'])} 条"
            elif "faqs" in data and data.get("faqs"):
                tool_used_rag = True
                rag_usage_hint = f"faqs: {len(data['faqs'])} 条"
            # MSA: recommendations 非空
            elif "recommendations" in data and data.get("recommendations"):
                tool_used_rag = True
                rag_usage_hint = f"recommendations: {len(data['recommendations'])} 条"

        if not quiet:
            print(f"\n{qid}: {q}")
            print(f"  场景: {scenario}")
            print(f"  intent: {actual_intent} {'✅' if is_correct else '❌ 期望 ' + expect_intent}")
            print(f"  tool: {tool_name}")
            print(f"  RAG (独立测): {len(rag_hits)} 条 (KB={expect_kb})")
            if rag_hits:
                top_hit = rag_hits[0]
                print(f"    Top-1: [{top_hit.id[:30]}] {top_hit.text[:60]}")
            if tool_used_rag:
                print(f"  Tool 使用 RAG: ✅ ({rag_usage_hint})")
            elif expect_kb:
                print(f"  Tool 使用 RAG: ⚠️ 期望但未看到证据")

        details.append({
            "id": qid,
            "query": q,
            "expect_intent": expect_intent,
            "actual_intent": actual_intent,
            "tool": tool_name,
            "correct": is_correct,
            "kb": expect_kb,
            "rag_hits": len(rag_hits),
            "tool_used_rag": tool_used_rag,
            "top_hit_id": rag_hits[0].id if rag_hits else None,
        })

    # ===== 报告 =====
    total = len(DEMO_QUERIES)
    kb_queries = sum(1 for d in details if d["kb"])
    rag_hit_queries = sum(1 for d in details if d["rag_hits"] > 0)

    print(f"\n{'=' * 70}")
    print(f"📊 端到端报告")
    print(f"{'=' * 70}")
    print(f"  总 query 数:        {total}")
    print(f"  Intent 命中:        {intent_correct}/{total} ({intent_correct*100//total}%)")
    print(f"  RAG 召回覆盖:       {rag_hit_queries}/{kb_queries} (查 KB 的 query 中召回 > 0 的比例)")
    print(f"  RAG 总召回数:       {rag_total_hits} 条 / {kb_queries*5} 期望 top_k")
    print(f"  Tool 实际使用 RAG:  {sum(1 for d in details if d['tool_used_rag'])}/{total}")
    print(f"\n  按 Tool 分布:")
    for tool, cnt in sorted(by_tool.items(), key=lambda x: -x[1]):
        print(f"    {tool}: {cnt}")

    # 失败的 query
    failed = [d for d in details if not d["correct"]]
    if failed:
        print(f"\n  ❌ Intent 失误:")
        for d in failed:
            print(f"    [{d['id']}] 期望 {d['expect_intent']} / 实际 {d['actual_intent']}")

    # RAG 零召回
    rag_zero = [d for d in details if d["kb"] and d["rag_hits"] == 0]
    if rag_zero:
        print(f"\n  ⚠️ RAG 零召回（应排查 Embedding 语义）:")
        for d in rag_zero:
            print(f"    [{d['id']}] {d['query'][:40]}")

    return {
        "total_queries": total,
        "intent_correct": intent_correct,
        "rag_hit_queries": rag_hit_queries,
        "rag_total_hits": rag_total_hits,
        "by_tool": by_tool,
        "details": details,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-End Demo")
    parser.add_argument("--quiet", action="store_true", help="只打报告不打印详情")
    args = parser.parse_args()

    run_demo(quiet=args.quiet)
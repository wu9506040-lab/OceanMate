"""P1-1 验证脚本：LLM intent fallback 真实路径测试。

测试 4 种场景：
1. 关键词直接命中（拒付问题紧急 → payment_diagnosis）
2. 关键词不命中但 LLM 兜底命中（"有什么支付方式可以选" → merchant_success）
3. 关键词不命中 + LLM 也 unknown（"今天天气真好" → unknown_fallback_to_msa）
4. 关闭 LLM fallback 时，关键词不命中 → 走 unknown_response

预期：
- 场景 1: llm_used=False, intent=payment_diagnosis
- 场景 2: llm_used=True, intent=merchant_success, llm_confidence > 0.7
- 场景 3: llm_used=True, intent=unknown_fallback_to_msa (兜底到 MSA collect_profile)
- 场景 4: llm_used=False, intent=unknown (走 unknown_response，未注册 MSA 时)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

# 自动加载 .env（验证脚本直跑场景）
from dotenv import load_dotenv
_project_root = Path(__file__).resolve().parents[2]  # scripts/ → backend/ → src/
for _ in range(4):
    if (_project_root / ".env").exists():
        load_dotenv(_project_root / ".env", override=False)
        break
    _project_root = _project_root.parent

from app.agents.orchestrator import Orchestrator


def test_case(name: str, orch: Orchestrator, query: str, expected_intent: str, expected_llm_used: bool):
    print(f"\n--- 测试: {name} ---")
    print(f"  Query: '{query}'")
    result = orch.route(user_query=query)
    actual_intent = result["intent"]
    actual_llm_used = result["trace"].get("llm_used", False)
    llm_confidence = result["trace"].get("llm_confidence")
    print(f"  → intent: {actual_intent}")
    print(f"  → llm_used: {actual_llm_used}, llm_confidence: {llm_confidence}")
    print(f"  → tool_name: {result.get('tool_name')}")
    ok_intent = actual_intent == expected_intent
    ok_llm = actual_llm_used == expected_llm_used
    if ok_intent and ok_llm:
        print(f"  ✅ PASS")
    else:
        print(f"  ❌ FAIL — expected intent='{expected_intent}', llm_used={expected_llm_used}")


def main():
    print("=" * 70)
    print("P1-1: LLM Intent Fallback 真实路径测试")
    print("=" * 70)

    # 构造 Orchestrator（自动加载 Qwen / Mock）
    orch = Orchestrator(use_llm_fallback=True)

    # 场景 1: 关键词命中（拒付）
    test_case(
        "关键词命中（拒付 → payment_diagnosis）",
        orch,
        "商户反馈拒付问题紧急，需要马上处理",
        expected_intent="payment_diagnosis",
        expected_llm_used=False,
    )

    # 场景 2: 关键词不命中 + LLM 兜底命中 payment_diagnosis
    # "退单"不在关键词白名单，但 LLM 能识别为 diagnosis 类
    test_case(
        "LLM 兜底（退单 → payment_diagnosis）",
        orch,
        "Visa 退单率突然飙升，墨西哥市场受影响",
        expected_intent="payment_diagnosis",
        expected_llm_used=True,
    )

    # 场景 3: 关键词不命中 + LLM 兜底命中 merchant_success
    # "墨西哥市场感兴趣"、"入门"都不在关键词白名单
    test_case(
        "LLM 兜底（市场入门 → merchant_success）",
        orch,
        "我对墨西哥市场感兴趣，应该怎么入门？",
        expected_intent="merchant_success",
        expected_llm_used=True,
    )

    # 场景 4: 关键词不命中 + LLM 兜底命中 ticket_routing
    # "ticket" "状态" 在关键词里 → 改 query
    test_case(
        "LLM 兜底（同义词 → ticket_routing）",
        orch,
        "我的 issue 已经分给谁了？进展如何？",
        expected_intent="ticket_routing",
        expected_llm_used=True,
    )

    # 场景 5: 关键词不命中 + LLM 也 unknown → 兜底 MSA
    test_case(
        "LLM 也 unknown（无关问题 → unknown_fallback_to_msa）",
        orch,
        "今天深圳天气怎么样",
        expected_intent="unknown_fallback_to_msa",
        expected_llm_used=True,
    )

    # 场景 6: 关闭 LLM fallback
    print("\n" + "=" * 70)
    print("场景 6: 关闭 LLM fallback（仅关键词模式）")
    print("=" * 70)
    orch_no_llm = Orchestrator(use_llm_fallback=False)
    test_case(
        "关闭 LLM fallback（无关问题 → unknown）",
        orch_no_llm,
        "今天深圳天气怎么样",
        expected_intent="unknown",
        expected_llm_used=False,
    )


if __name__ == "__main__":
    main()
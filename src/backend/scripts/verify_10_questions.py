"""Day 14 P1-9：10 个真实自然语言问题端到端验证。

走完整链路：Orchestrator.route() → 意图识别 → 参数提取 → Tool → 飞书格式化。
不用固定参数 safe_execute，就是飞书里商户会怎么打字就怎么测。

跑法：cd src/backend && python scripts/verify_10_questions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows 中文/emoji 输出兼容（CLAUDE.md 已知约束）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.kea.tool import KEATool
from app.agents.msa.tool import MSATool
from app.agents.orchestrator.orchestrator import Orchestrator
from app.agents.pda.tool import PDATool
from app.agents.tra.tool import TRATool
from app.implementations.feishu.webhook import FeishuWebhookHandler

QUESTIONS = [
    "美国 Visa 13.1 拒付好多怎么解决",
    "英国 MC 4837 持卡人未授权怎么办",
    "巴西 Pix 周末凌晨延迟",
    "荷兰用什么支付方式比较好",
    "美国 Webhook 回调失败",
    "退款异常，用户说没收到退款",
    "墨西哥市场用什么支付方式",
    "Visa 10.1 EMV 欺诈拒付怎么申诉",
    "工单进度怎么查",
    "知识库怎么检索 BR Pix 相关问题",
]

# 商户可见文本里绝不允许出现的字样
FORBIDDEN = ("example.com", "placeholder", "<demo_", "ERR_UNKNOWN", "**")


def build_orchestrator() -> Orchestrator:
    orch = Orchestrator(chain_mode="single")
    for tool in (PDATool(), MSATool(), TRATool(), KEATool()):
        try:
            orch.register_tool(tool)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 注册 {type(tool).__name__} 失败: {e}")
    return orch


def main() -> int:
    orch = build_orchestrator()
    failures = []

    for i, q in enumerate(QUESTIONS, 1):
        print("=" * 72)
        print(f"[{i}/10] 商户提问：{q}")
        try:
            result = orch.route(q)
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ route 抛异常: {e}")
            failures.append((q, f"exception: {e}"))
            continue

        intent = result.get("intent")
        trace = result.get("trace", {})
        reply = FeishuWebhookHandler.format_reply(result)

        print(f"  意图：{intent}")
        if trace.get("params"):
            p = trace["params"]
            print(
                f"  参数：country={p.get('country')} channel={p.get('channel')} "
                f"error_code={p.get('error_code') or '(空)'}"
            )
        if trace.get("query_type"):
            print(f"  类型：{trace['query_type']}")
        ev = result.get("tool_result", {}).get("data", {})
        if isinstance(ev, dict) and ev.get("evidence_chain"):
            print(f"  证据：{[(e['type'], e['id']) for e in ev['evidence_chain']]}")
        print("  ---- 飞书回复 ----")
        for line in reply.splitlines():
            print(f"  {line}")

        low = reply.lower()
        hits = [b for b in FORBIDDEN if b.lower() in low]
        if hits:
            print(f"  ❌ 含禁止字样: {hits}")
            failures.append((q, f"forbidden: {hits}"))
        elif intent == "unknown":
            print("  ❌ 意图未识别")
            failures.append((q, "intent unknown"))
        else:
            print("  ✅ PASS")

    print("=" * 72)
    if failures:
        print(f"❌ {len(failures)}/10 未通过：")
        for q, why in failures:
            print(f"  - {q} → {why}")
        return 1
    print("✅ 10/10 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

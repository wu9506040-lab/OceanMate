"""终端 Demo - 不需要启动 FastAPI，直接出诊断结果。

用法：
    python run_demo.py
    python run_demo.py --country US --channel Visa --error-code ERR_DEMO_CHARGEBACK_001
"""

import argparse
import json
import sys
from pathlib import Path

# Windows 默认 GBK 终端兼容：emoji/中文不会崩
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Py3.7+
except (AttributeError, OSError):
    pass

# 把 src/backend 加到 path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.agents.payment_diagnosis.schemas import DiagnoseRequest, ProblemRecord
from app.agents.payment_diagnosis.service import PaymentDiagnosisService

# 颜色（Windows Terminal / VS Code 终端支持 ANSI）
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def hr(char="─", width=72):
    return GRAY + char * width + RESET


def print_diagnosis(resp):
    d = resp["diagnosis"]
    t = resp["trace"]

    print()
    print(BOLD + BLUE + "=" * 72 + RESET)
    print(BOLD + BLUE + f"  OceanMate AI · Payment Diagnosis Agent (LLM = {t['llm_provider']})" + RESET)
    print(BOLD + BLUE + "=" * 72 + RESET)
    print()

    print(BOLD + "📋 问题档案" + RESET)
    print(hr())
    p = _problem
    print(f"  商户 ID    : {YELLOW}{p.merchant_id}{RESET}")
    print(f"  国家/渠道  : {YELLOW}{p.country} / {p.channel}{RESET}")
    print(f"  错误码     : {YELLOW}{p.error_code}{RESET}")
    print(f"  订单数     : {YELLOW}{len(p.affected_orders)}{RESET}")
    print()

    print(BOLD + f"🔍 诊断结果 (置信度 {d['confidence']:.0%})" + RESET)
    print(hr())
    print(f"  问题类型   : {RED}{d['problem_type']}{RESET}")
    print()
    print(f"  {BOLD}根因分析{RESET}:")
    for i, rc in enumerate(d["root_causes"], 1):
        print(f"    {i}. {rc}")
    print()

    print(f"  {BOLD}证据链 (共 {len(d['evidence_chain'])} 条 · 可追溯){RESET}:")
    for e in d["evidence_chain"]:
        color = {"risk_rule": RED, "channel_status": YELLOW, "config_snapshot": GREEN}[e["type"]]
        print(f"    {color}●{RESET} {e['type']:18s} {e['id']:42s} ← {e['source']}")
        if e.get("description"):
            print(f"      {GRAY}└─ {e['description'][:80]}{RESET}")
    print()

    print(f"  {BOLD}建议处理{RESET}:")
    for a in d["recommended_actions"]:
        print(f"    {a}")
    print()

    print(f"  → 下一跳   : {BLUE}{d['next_agent']}{RESET} (自动派单)")
    print()
    print(hr("═"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OceanMate AI · Payment Diagnosis 终端 Demo")
    parser.add_argument("--merchant-id", default="<DEMO_MERCHANT_ID>")
    parser.add_argument("--country", default="BR")
    parser.add_argument("--channel", default="Visa")
    parser.add_argument(
        "--error-code", default="ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        help="如 ERR_DEMO_RISK_BLOCK_BR_VISA_001 / ERR_DEMO_3DS_REQUIRED_001 / ERR_DEMO_CHARGEBACK_001 ...",
    )
    parser.add_argument("--orders", nargs="*", default=["<DEMO_ORDER_ID>"])
    args = parser.parse_args()

    _problem = ProblemRecord(
        merchant_id=args.merchant_id,
        country=args.country,
        channel=args.channel,
        error_code=args.error_code,
        affected_orders=args.orders,
    )

    svc = PaymentDiagnosisService()
    resp = svc.diagnose(DiagnoseRequest(problem_record=_problem))
    print_diagnosis(resp.model_dump())

    print()
    print(GRAY + "  💡 提示：所有 *_demo_xxx ID 均为占位符，对接 OP 真实环境时仅替换 ID 值。" + RESET)
    print(GRAY + "     启动 FastAPI 服务: uvicorn app.main:app --port 8000" + RESET)
    print()
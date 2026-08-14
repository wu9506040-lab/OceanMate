#!/usr/bin/env python
"""Day 15 真实端到端验证：10 个真实问题打到 backend，输出真实结果。

执行：cd E:/ai-pioneer/src/backend && PYTHONIOENCODING=utf-8 python docs/reports/day15_verification/_run_all.py
输出：docs/reports/day15_verification/_raw_results.json + 每个 case_XX_*.json
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib import request as urlreq

BACKEND = "http://localhost:8000"
HERE = Path(__file__).resolve().parent

# === 10 个真实测试用例 ===

CASES = [
    # === 1. NL 推荐（Fix A: best_practice 自动补齐）===
    {
        "id": "case_01_nl_recommend",
        "title": "荷兰 NL 支付方式推荐",
        "key_check": "Fix A: country=NL 应自动走 recommend（best_practice_filled=True）",
        "user_query": "我想做 NL 站，时尚 B2C 电商，客单价 80 欧",
        "merchant_context": {"country": "NL"},
        "expect": {
            "intent": "merchant_success",
            "sub_intent": "recommend_payment_methods",
            "best_practice_filled": True,
        },
    },
    # === 2. Visa 13.1 拒付（Fix D + 配图 C）===
    {
        "id": "case_02_visa_13_1",
        "title": "美国 Visa 13.1 拒付诊断",
        "key_check": "Fix D: reason_name=Merchandise/Services Not Received + actions 包含物流/签收",
        "user_query": "我美国站卖软件的，Visa 13.1 拒付好多，怎么办？",
        "merchant_context": {"merchant_id": "M001", "country": "US", "channel": "Visa", "error_code": "CB_13.1"},
        "expect": {
            "intent": "payment_diagnosis",
            "reason_name_contains": "Merchandise",
            "image_path": "data/error_images/cb_demo_13_1.png",
        },
    },
    # === 3. MC 4837 拒付（Fix D 差异化对比）===
    {
        "id": "case_03_mc_4837",
        "title": "美国 Mastercard 4837 拒付诊断",
        "key_check": "Fix D: reason_name=No Cardholder Authorization + actions 包含 3DS/Collaboration",
        "user_query": "美国 MC 4837 拒付越来越多",
        "merchant_context": {"merchant_id": "M002", "country": "US", "channel": "Mastercard", "error_code": "CB_4837"},
        "expect": {
            "intent": "payment_diagnosis",
            "reason_name_contains": "Cardholder Authorization",
            "image_path": "data/error_images/cb_demo_4837.png",
        },
    },
    # === 4. 创建工单（Fix B: TRA 优先）===
    {
        "id": "case_04_create_ticket",
        "title": "「帮我创建一个工单」路由",
        "key_check": "Fix B: 应路由到 ticket_routing，不是 payment_diagnosis",
        "user_query": "帮我创建一个工单",
        "merchant_context": {"user_id": "ou_test"},
        "expect": {
            "intent": "ticket_routing",
            "sub_intent": "route_ticket",
        },
    },
    # === 5. 工单状态查询 ===
    {
        "id": "case_05_query_ticket",
        "title": "工单状态查询",
        "key_check": "TRA query_status 子意图",
        "user_query": "我的工单状态怎么样",
        "merchant_context": {"user_id": "ou_test"},
        "expect": {
            "intent": "ticket_routing",
        },
    },
    # === 6. BR Pix 周末延迟（场景类）===
    {
        "id": "case_06_br_pix_weekend",
        "title": "BR Pix 周末凌晨延迟",
        "key_check": "PDA 场景类诊断",
        "user_query": "BR 站 Pix 周六凌晨怎么总是延迟不到账",
        "merchant_context": {"merchant_id": "M_BR", "country": "BR", "channel": "Pix"},
        "expect": {
            "intent": "payment_diagnosis",
        },
    },
    # === 7. FAQ 知识查询 ===
    {
        "id": "case_07_faq_search",
        "title": "FAQ 知识检索 - 操作类",
        "key_check": "KEA search_faq（用知识库关键词触发）",
        "user_query": "FAQ 里有没有 Pix 的教程？",
        "merchant_context": {"user_id": "ou_test"},
        "expect": {
            "intent": "knowledge_evolution",
            "sub_intent": "search_faq",
        },
    },
    # === 7b. 工单查询 vs FAQ 路由边界 ===
    {
        "id": "case_07b_ticket_or_faq",
        "title": "「怎么查工单进度」- TRA 优先",
        "key_check": "含'工单'词被路由到 TRA（业务可争议：TRA 查状态也合理）",
        "user_query": "怎么查工单进度？",
        "merchant_context": {"user_id": "ou_test"},
        "expect": {
            "intent": "ticket_routing",
            "sub_intent": "query_status",
        },
    },
    # === 8. 未知意图兜底 ===
    {
        "id": "case_08_unknown",
        "title": "完全无关 query 兜底",
        "key_check": "unknown_fallback_to_msa",
        "user_query": "今天天气怎么样",
        "merchant_context": {"user_id": "ou_test"},
        "expect": {
            "intent": "unknown_fallback_to_msa",
        },
    },
    # === 9. 完整 webhook Visa 13.1（验证 send_image 真实路径）===
    {
        "id": "case_09_webhook_visa",
        "title": "webhook Visa 13.1 → send_image",
        "key_check": "完整链路: webhook → orchestrator → send_image 触发",
        "user_query": "我美国站卖软件的，Visa 13.1 拒付好多，怎么办？",
        "via": "webhook",
        "merchant_context": {"user_id": "ou_aa9ece53b9a503cf7007ce2d42021a1c"},
        "expect": {
            "intent": "payment_diagnosis",
            "image_path": "data/error_images/cb_demo_13_1.png",
        },
    },
    # === 10. 完整 webhook MC 4837 ===
    {
        "id": "case_10_webhook_mc",
        "title": "webhook MC 4837 → send_image",
        "key_check": "完整链路: webhook → orchestrator → send_image + Fix D",
        "user_query": "美国 MC 4837 拒付越来越多",
        "via": "webhook",
        "merchant_context": {"user_id": "ou_aa9ece53b9a503cf7007ce2d42021a1c"},
        "expect": {
            "intent": "payment_diagnosis",
            "image_path": "data/error_images/cb_demo_4837.png",
        },
    },
]


def post_chat(query: str, ctx: dict) -> dict:
    """直接调 /api/chat 模拟商户提问。"""
    payload = json.dumps({"query": query, "merchant_context": ctx}, ensure_ascii=False).encode("utf-8")
    req = urlreq.Request(
        f"{BACKEND}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urlreq.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_webhook(query: str, user_id: str) -> int:
    """发完整 webhook 事件（验证 send_image 全链路）。"""
    payload = {
        "schema": "2.0",
        "header": {
            "event_type": "im.message.receive_v1",
            "app_id": "cli_aaf8271657f9dbb5",
            "tenant_key": "x",
            "create_time": str(int(time.time())),
        },
        "event": {
            "sender": {"sender_id": {"open_id": user_id}, "sender_type": "user"},
            "message": {
                "message_id": f"om_verify_{int(time.time() * 1000000)}",
                "chat_id": "oc_6296625bae097b350d108e36150a869f",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": query}),
            },
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlreq.Request(
        f"{BACKEND}/feishu/webhook",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urlreq.urlopen(req) as resp:
        return resp.status


def run_case(case: dict) -> dict:
    """运行一个测试用例并返回结果摘要。"""
    started = time.time()
    if case.get("via") == "webhook":
        status = post_webhook(case["user_query"], case["merchant_context"]["user_id"])
        # webhook 不返回结果细节，但要调一次 /api/chat 拿到真实结果
        # 这样既能验证 webhook 路径，又能拿到结构化数据
        chat_result = post_chat(case["user_query"], {"user_id": case["merchant_context"]["user_id"]})
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "case": case["id"],
            "via": "webhook",
            "http_status": status,
            "elapsed_ms": elapsed_ms,
            "result": chat_result,
            "expect": case["expect"],
        }
    else:
        result = post_chat(case["user_query"], case["merchant_context"])
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "case": case["id"],
            "via": "api",
            "elapsed_ms": elapsed_ms,
            "result": result,
            "expect": case["expect"],
        }


def main():
    all_results = []
    print(f"Running {len(CASES)} cases...\n")
    for case in CASES:
        print(f"[{case['id']}] {case['title']}")
        try:
            r = run_case(case)
        except Exception as e:
            r = {"case": case["id"], "error": str(e)}
        all_results.append(r)
        # 单 case 落盘
        with open(HERE / f"{case['id']}.json", "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        if "error" in r:
            print(f"  ✗ ERROR: {r['error']}\n")
        else:
            print(f"  ✓ {r['elapsed_ms']}ms ({r.get('via', '?')})\n")

    # 总汇总
    summary = {
        "total": len(all_results),
        "ok": sum(1 for r in all_results if "error" not in r),
        "err": sum(1 for r in all_results if "error" in r),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    final = {"summary": summary, "cases": all_results}
    with open(HERE / "_raw_results.json", "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n========")
    print(f"OK:   {summary['ok']}/{summary['total']}")
    print(f"ERR:  {summary['err']}")
    print(f"Saved: {HERE / '_raw_results.json'}")


if __name__ == "__main__":
    main()
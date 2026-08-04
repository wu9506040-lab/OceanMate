"""Seed cases → Chroma cases_vec（demo 占位案例）。

用法：
    cd src/backend
    python scripts/seed_cases.py
    python scripts/seed_cases.py --reset
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from app.implementations.rag.chroma_rag import ChromaRAGEngine, COLLECTION_CASES
from app.implementations.chunking import SmartChunker
from app.implementations.pipelines import IngestionPipeline


# Demo 占位案例（4 条）—— 真实对接时从 cases.json / 飞书多维表格同步
_DEMO_CASES = [
    {
        "id": "case_demo_001",
        "problem_desc": "BR 区域商户 Visa 支付失败 ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        "diagnosis": "BR Visa 渠道风控规则命中，单笔金额超阈值 + 短时间内多次尝试",
        "resolution": "联系风控团队确认规则阈值；必要时加入白名单；建议商户开启 BR 区域 3DS 配置",
        "country": "BR",
        "channel": "Visa",
        "problem_type": "支付失败",
        "error_code": "ERR_DEMO_RISK_BLOCK_BR_VISA_001",
        "confidence": 0.85,
    },
    {
        "id": "case_demo_002",
        "problem_desc": "BR 区域 3DS 认证未通过 ERR_DEMO_3DS_REQUIRED_001",
        "diagnosis": "BR 区域 Visa 必须配套 3DS 配置；当前商户未开启或持卡人 3DS 认证失败",
        "resolution": "检查 Merchant Console 3DS 配置；联系商户开启 BR 区域 3DS",
        "country": "BR",
        "channel": "Visa",
        "problem_type": "支付失败",
        "error_code": "ERR_DEMO_3DS_REQUIRED_001",
        "confidence": 0.90,
    },
    {
        "id": "case_demo_003",
        "problem_desc": "US 区域商户 Visa 拒付 chargeback ERR_DEMO_CHARGEBACK_001",
        "diagnosis": "持卡人在发卡行侧发起 dispute，需走 RDR/CDRN 流程",
        "resolution": "准备 CB 申诉材料（订单/物流/签收凭证）；通过 Verifi/Mastercard RDR 提前拦截",
        "country": "US",
        "channel": "Visa",
        "problem_type": "拒付",
        "error_code": "ERR_DEMO_CHARGEBACK_001",
        "confidence": 0.78,
    },
    {
        "id": "case_demo_004",
        "problem_desc": "PayPal 退款被拒 ERR_DEMO_REFUND_REJECTED_001",
        "diagnosis": "原交易超退款窗口（>180 天）或通道拒绝退款",
        "resolution": "走 OP 财务团队特批流程；商户端沟通替代方案（账户余额 / 重新下单）",
        "country": "GLOBAL",
        "channel": "PayPal",
        "problem_type": "退款异常",
        "error_code": "ERR_DEMO_REFUND_REJECTED_001",
        "confidence": 0.72,
    },
]


def _to_records() -> list[dict]:
    """Demo cases → Pipeline records。"""
    records = []
    for c in _DEMO_CASES:
        # text 拼接 problem + diagnosis + resolution（向量含完整问题-诊断-处理链）
        text = (
            f"{c['problem_desc']}。"
            f"诊断：{c['diagnosis']}。"
            f"处理建议：{c['resolution']}"
        )
        records.append({
            "id": c["id"],
            "text": text,
            "country": c["country"],
            "channel": c["channel"],
            "problem_type": c["problem_type"],
            "error_code": c["error_code"],
            "confidence": c["confidence"],
        })
    return records


def seed(reset: bool = False, collection: str = COLLECTION_CASES) -> dict:
    engine = ChromaRAGEngine()

    if reset:
        existing_ids = engine.recall_by_metadata({}, limit=10000, collection_name=collection)
        if existing_ids:
            for d in existing_ids:
                engine.delete_document(d.id, collection_name=collection)
            print(f"[reset] 清除 {len(existing_ids)} 条旧文档")

    records = _to_records()
    pipeline = IngestionPipeline(rag=engine, chunker=SmartChunker())
    stats = pipeline.ingest(
        records=records,
        source_table="cases_demo",
        collection_name=collection,
    )

    return {
        "source_records": len(records),
        **stats,
        "collection_total": engine.get_collection_stats()[collection],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo cases to Chroma cases_vec")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    result = seed(reset=args.reset)

    print(f"[OK] Cases Seed 完成")
    print(f"   source_records:  {result['source_records']}")
    print(f"   total_chunks:    {result['total_chunks']}")
    print(f"   skipped_records: {result['skipped_records']}")
    print(f"   strategies_used: {result['strategies_used']}")
    print(f"   collection_total: {result['collection_total']}")
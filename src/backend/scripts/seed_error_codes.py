"""Seed error_codes + cases + config_templates → Chroma error_codes_vec。

幂等：重复运行会覆盖更新（用 upsert via update_document）。
统一走 IngestionPipeline（clean → chunk → embed → store）。

用法：
    cd src/backend
    python scripts/seed_error_codes.py                # 默认增量
    python scripts/seed_error_codes.py --reset         # 清空 collection 后重灌
"""

import argparse
import json
import sys
from pathlib import Path

# 让脚本能直接 `from app.xxx import ...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    COLLECTION_ERROR_CODES,
)
from app.implementations.chunking import SmartChunker
from app.implementations.pipelines import IngestionPipeline


_DEFAULT_DATA = Path(__file__).resolve().parents[3] / "docs" / "data" / "payment_error_cases.json"


def _to_records(data: dict) -> list[dict]:
    """把 JSON 内容转成 Pipeline 输入 records。"""
    records = []

    # 1. 错误码规则（cases 字段）
    for r in data.get("cases", []):
        # text 用 rule_description + recommended_action + trigger_condition
        text = (
            f"{r.get('rule_description', '')} "
            f"触发条件：{r.get('trigger_condition', '')} "
            f"建议处理：{r.get('recommended_action', '')}"
        )
        records.append({
            "id": r["id"],
            "text": text.strip(),
            "error_code": r.get("error_code", ""),
            "country": r.get("country", "GLOBAL"),
            "channel": r.get("channel", "ANY"),
            "problem_type": r.get("problem_type", ""),
            "severity": r.get("severity", "medium"),
        })

    # 2. config templates（合并入知识库，便于 PDA 检索）
    for r in data.get("config_templates", []):
        text = (
            f"配置模板：{r.get('config_key', '')} = {r.get('config_value', '')}。"
            f"备注：{r.get('note', '')}"
        )
        records.append({
            "id": r["id"],
            "text": text.strip(),
            "country": r.get("country", "GLOBAL"),
            "config_key": r.get("config_key", ""),
        })

    # 3. channel status templates
    for r in data.get("channel_status_templates", []):
        text = (
            f"通道状态：{r.get('country', '')} {r.get('channel', '')} "
            f"当前状态 {r.get('status', '')}，成功率 {r.get('success_rate', '')}。"
            f"备注：{r.get('note', '')}"
        )
        records.append({
            "id": r["id"],
            "text": text.strip(),
            "country": r.get("country", ""),
            "channel": r.get("channel", ""),
            "status": r.get("status", ""),
        })

    return records


def seed(data_path: Path, reset: bool = False, collection: str = COLLECTION_ERROR_CODES) -> dict:
    """Seed error_codes_vec。"""
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    engine = ChromaRAGEngine()

    # reset：清空 collection
    if reset:
        existing_ids = engine.recall_by_metadata({}, limit=10000, collection_name=collection)
        if existing_ids:
            for d in existing_ids:
                engine.delete_document(d.id, collection_name=collection)
            print(f"[reset] 清除 {len(existing_ids)} 条旧文档")

    records = _to_records(data)
    pipeline = IngestionPipeline(rag=engine, chunker=SmartChunker())
    stats = pipeline.ingest(
        records=records,
        source_table="payment_error_cases",
        collection_name=collection,
    )

    return {
        "source_records": len(records),
        **stats,
        "collection_total": engine.get_collection_stats()[collection],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed error_codes to Chroma")
    parser.add_argument("--data", type=Path, default=_DEFAULT_DATA)
    parser.add_argument("--reset", action="store_true", help="清空 collection 后重灌")
    args = parser.parse_args()

    result = seed(args.data, reset=args.reset)

    print(f"[OK] Seed 完成")
    print(f"   source_records:  {result['source_records']}")
    print(f"   total_chunks:    {result['total_chunks']}")
    print(f"   skipped_records: {result['skipped_records']}")
    print(f"   strategies_used: {result['strategies_used']}")
    print(f"   avg_chunk_size:  {result['avg_chunk_size']:.0f}")
    print(f"   max_chunk_size:  {result['max_chunk_size']}")
    print(f"   collection_total: {result['collection_total']}")
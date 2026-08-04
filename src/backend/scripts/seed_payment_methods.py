"""Seed payment_methods.json → Chroma payment_methods_vec collection。

幂等：重复运行会覆盖更新（用 upsert）。

用法：
    cd src/backend
    python scripts/seed_payment_methods.py
    python scripts/seed_payment_methods.py --reset  # 清空旧 collection
"""

import argparse
import json
import sys
from pathlib import Path

# 让脚本能直接 `from app.xxx import ...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 中文输出兼容
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    COLLECTION_PAYMENT_METHODS,
)
from app.interfaces.base_rag import Document

_DEFAULT_DATA = Path(__file__).resolve().parents[3] / "docs" / "data" / "payment_methods.json"


def seed(data_path: Path, reset: bool = False) -> dict:
    """Seed payment_methods 到 Chroma。

    Args:
        data_path: payment_methods.json 路径
        reset: 是否先清空 collection

    Returns:
        {"collection": str, "count": int, "collection_total": int}
    """
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    engine = ChromaRAGEngine()

    if reset:
        # Chroma 没有 reset 单 collection；通过删除全部 docs 实现
        try:
            existing_ids = engine._collections[COLLECTION_PAYMENT_METHODS].get()["ids"]
            if existing_ids:
                engine._collections[COLLECTION_PAYMENT_METHODS].delete(ids=existing_ids)
                print(f"[reset] 清除 {len(existing_ids)} 条旧文档")
        except Exception as e:
            print(f"[reset] 跳过（collection 暂无数据）: {e}")

    added = 0
    for pm in data["methods"]:
        # text 用 description + rationale + tags，方便 RAG 检索
        text = (
            f"{pm['method']} {pm['country']} 支付方式。"
            f"{pm['description']} "
            f"理由：{pm['rationale']} "
            f"标签：{', '.join(pm.get('evidence_tags', []))}"
        )
        metadata = {
            "method": pm["method"],
            "country": pm["country"],
            "industries": ",".join(pm.get("industries", [])),
            "fee_rate": pm["fee_rate"],
            "settlement": pm["settlement"],
            "currency": pm["currency"],
            "min_amount": pm["min_amount"],
            "max_amount": pm["max_amount"],
        }
        # update_document 内部已支持先 update 后 add
        engine.update_document(
            pm["id"],
            Document(id=pm["id"], text=text, metadata=metadata),
            collection_name=COLLECTION_PAYMENT_METHODS,
        )
        added += 1

    total = engine.get_collection_stats()[COLLECTION_PAYMENT_METHODS]

    return {
        "collection": COLLECTION_PAYMENT_METHODS,
        "added": added,
        "collection_total": total,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed payment_methods to Chroma")
    parser.add_argument("--data", type=Path, default=_DEFAULT_DATA)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    result = seed(args.data, reset=args.reset)
    print(f"✅ Seed 完成")
    print(f"   collection: {result['collection']}")
    print(f"   added: {result['added']}")
    print(f"   total in collection: {result['collection_total']}")
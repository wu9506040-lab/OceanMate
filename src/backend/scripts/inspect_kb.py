"""Inspect KB - 打印 3 个 Chroma collection 的统计 + 各 3 条样本。

用于：
- 验证 seed 效果
- Debug 检索召回（看实际入库内容）
- 评审演示"知识库长什么样"

用法：
    cd src/backend
    python scripts/inspect_kb.py
    python scripts/inspect_kb.py --top 5         # 每 collection 看 5 条样本
    python scripts/inspect_kb.py --collection cases_vec   # 只看一个
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    COLLECTION_ERROR_CODES,
    COLLECTION_CASES,
    COLLECTION_PAYMENT_METHODS,
)


def inspect(collection_name: str = None, top: int = 3) -> dict:
    """打印 collection 统计 + 样本。"""
    engine = ChromaRAGEngine()
    stats = engine.get_collection_stats()

    collections = [collection_name] if collection_name else [
        COLLECTION_ERROR_CODES,
        COLLECTION_CASES,
        COLLECTION_PAYMENT_METHODS,
    ]

    result = {}
    for cname in collections:
        count = stats.get(cname, 0)
        print(f"\n{'=' * 60}")
        print(f"Collection: {cname}  ({count} docs)")
        print(f"{'=' * 60}")

        if count == 0:
            print("  (empty)")
            result[cname] = {"count": 0, "samples": []}
            continue

        # 直接用 chroma get() 拉样本（recall_by_metadata 要求非空 filter）
        samples = []
        try:
            raw = engine._collections[cname].get(limit=top)
            if raw and raw.get("ids"):
                from app.interfaces.base_rag import Document
                samples = [
                    Document(
                        id=raw["ids"][i],
                        text=raw["documents"][i] if raw.get("documents") else "",
                        metadata=raw["metadatas"][i] if raw.get("metadatas") else {},
                    )
                    for i in range(len(raw["ids"]))
                ]
        except Exception as e:
            print(f"  [WARN] 拉样本失败: {e}")

        for i, doc in enumerate(samples, 1):
            text_preview = doc.text[:80] + ("..." if len(doc.text) > 80 else "")
            strategy = doc.metadata.get("strategy", "?")
            print(f"  [{i}] id={doc.id}  strategy={strategy}")
            print(f"      text: {text_preview}")
            if doc.metadata:
                meta_preview = {k: v for k, v in list(doc.metadata.items())[:4]}
                print(f"      meta: {meta_preview}")

        result[cname] = {"count": count, "samples": [d.to_dict() for d in samples]}

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Chroma KB")
    parser.add_argument("--collection", type=str, default=None, help="只看一个 collection")
    parser.add_argument("--top", type=int, default=3, help="每个 collection 显示样本数")
    args = parser.parse_args()

    inspect(collection_name=args.collection, top=args.top)
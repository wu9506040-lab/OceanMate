"""P1-2 验证脚本：混合检索 + Rerank 真实路径测试。

对比维度：
1. 纯向量 vs 混合（向量 + BM25 RRF）vs 混合 + Rerank
2. 测试 query 类型：
   - 语义类（同义词）→ 向量强，hybrid 持平
   - 字面类（具体错误码 "13.1"）→ BM25 强
   - 混合类（拒付 + 国家）
   - 中英混合
3. 重点看 Top-1 是否是真正相关条目
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

# 自动加载 .env
from dotenv import load_dotenv
_project_root = Path(__file__).resolve().parents[2]
for _ in range(4):
    if (_project_root / ".env").exists():
        load_dotenv(_project_root / ".env", override=False)
        break
    _project_root = _project_root.parent

from app.implementations.rag.chroma_rag import ChromaRAGEngine


def evaluate(label: str, docs: list, expected_first_id: str | None = None) -> tuple[bool, str]:
    """评估检索结果。"""
    if not docs:
        return False, "(空结果)"
    top1_id = docs[0].id
    top1_country = docs[0].metadata.get("country", "?")
    top1_ec = docs[0].metadata.get("error_code", "?")
    top3_ids = [d.id for d in docs[:3]]
    hit = (expected_first_id is None) or (top1_id == expected_first_id)
    mark = "✅" if hit else "⚠️"
    summary = f"{mark} Top-1={top1_id} country={top1_country} ec={top1_ec} | Top-3={top3_ids}"
    return hit, summary


def main():
    e = ChromaRAGEngine()
    stats = e.get_collection_stats()
    print(f"=== Chroma 集合状态 ===")
    for k, v in stats.items():
        print(f"  {k}: {v} 条")
    print()

    # 6 个测试 query
    test_queries = [
        # (label, query, expected_first_id, hint)
        ("语义查询-1", "Visa 拒付激增", None, "向量召回即可"),
        ("语义查询-2", "卡组织退款", None, "向量召回即可"),
        ("字面查询-1", "13.1 拒付", None, "BM25 应该有强信号"),
        ("字面查询-2", "CB_FR4", None, "BM25 应该 100% 命中"),
        ("中英混合", "Pix 周六延迟", None, "混合"),
        ("具体规则", "未收到货 chargeback", None, "Rerank 重排序"),
    ]

    print("=" * 70)
    print("P1-2: 混合检索 + Rerank 三路对比")
    print("=" * 70)
    for label, query, expected, hint in test_queries:
        print(f"\n[{label}] '{query}'  ({hint})")

        # 纯向量
        v_docs = e.retrieve(query, top_k=3, collection_name="error_codes_vec", use_hybrid=False, use_rerank=False)
        ok, summary = evaluate("vector", v_docs)
        print(f"  纯向量:   {summary}")

        # 混合（向量+BM25 RRF）
        h_docs = e.retrieve(query, top_k=3, collection_name="error_codes_vec", use_hybrid=True, use_rerank=False)
        ok, summary = evaluate("hybrid", h_docs)
        print(f"  混合:     {summary}")

        # 混合 + Rerank
        r_docs = e.retrieve(query, top_k=3, collection_name="error_codes_vec", use_hybrid=True, use_rerank=True)
        ok, summary = evaluate("rerank", r_docs)
        print(f"  混合+rerank: {summary}")

        # 一致性检查：3 路 Top-3 ids
        v_ids = set(d.id for d in v_docs[:3])
        h_ids = set(d.id for d in h_docs[:3])
        r_ids = set(d.id for d in r_docs[:3])
        print(f"  重叠: vec∩hybrid={len(v_ids & h_ids)}, vec∩rerank={len(v_ids & r_ids)}, hybrid∩rerank={len(h_ids & r_ids)}")

    # 总结：具体错误码字面查询
    print("\n" + "=" * 70)
    print("关键场景：具体错误码 '13.1' / 'CB_FR4' 字面匹配")
    print("=" * 70)
    for q in ["13.1", "CB_FR4", "4837"]:
        v_docs = e.retrieve(q, top_k=3, collection_name="error_codes_vec", use_hybrid=False, use_rerank=False)
        h_docs = e.retrieve(q, top_k=3, collection_name="error_codes_vec", use_hybrid=True, use_rerank=False)
        v_top1 = v_docs[0].metadata.get("error_code", "?") if v_docs else "?"
        h_top1 = h_docs[0].metadata.get("error_code", "?") if h_docs else "?"
        v_in_top3 = any(q in d.id or q in d.metadata.get("error_code", "") for d in v_docs)
        h_in_top3 = any(q in d.id or q in d.metadata.get("error_code", "") for d in h_docs)
        print(f"  query='{q}': 纯向量 Top1={v_top1} hit_top3={v_in_top3} | 混合 Top1={h_top1} hit_top3={h_in_top3}")


if __name__ == "__main__":
    main()
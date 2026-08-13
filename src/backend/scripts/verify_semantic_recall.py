"""P0-1 验证脚本：Qwen Embedding 真实语义召回测试。

核心检验：同义词 / 中英混合 / 语义相近的 query 能否召回相关知识。
对比 Hash Embedder 的"字符相似" vs Qwen Embedding 的"语义相似"。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.implementations.rag.chroma_rag import ChromaRAGEngine


def main():
    e = ChromaRAGEngine()
    print(f"=== Chroma 集合状态 ===")
    stats = e.get_collection_stats()
    for k, v in stats.items():
        print(f"  {k}: {v} 条")
    print()

    # 测试 1：同义词召回（Visa 拒付 vs chargeback vs refund vs 退款）
    print("=== 测试 1: 同义词召回（Visa 拒付 / chargeback / refund）===")
    queries = [
        ("Visa 拒付", "中文拒付"),
        ("Visa chargeback", "英文拒付"),
        ("Visa refund", "英文退款"),
        ("拒付争议", "中文拒付2"),
        ("卡组织退款", "中文退款"),
        ("客户撤销交易", "近义表达"),
    ]
    for q, label in queries:
        docs = e.retrieve(q, top_k=3, collection_name="error_codes_vec")
        ids = [d.id for d in docs]
        # 取出第一条的 country / error_code / 文本前 60 字
        first_text = docs[0].text[:60] if docs else "(空)"
        first_meta = docs[0].metadata if docs else {}
        print(f"  [{label}] '{q}'")
        print(f"    → Top-3 IDs: {ids}")
        print(f"    → #1 meta: country={first_meta.get('country', '?')}, error_code={first_meta.get('error_code', '?')}")
        print(f"    → #1 text: {first_text}...")
        print()

    # 测试 2：中英混合 - 中英是否召回相同内容
    print("=== 测试 2: 中英混合语义召回 ===")
    test_pairs = [
        ("信用卡3D Secure验证失败", "3D Secure authentication failed"),
        ("巴西PIX支付超时", "Brazil PIX payment timeout"),
        ("商户配置错误", "merchant configuration error"),
    ]
    for cn, en in test_pairs:
        docs_cn = e.retrieve(cn, top_k=3, collection_name="error_codes_vec")
        docs_en = e.retrieve(en, top_k=3, collection_name="error_codes_vec")
        ids_cn = set(d.id for d in docs_cn)
        ids_en = set(d.id for d in docs_en)
        overlap = ids_cn & ids_en
        print(f"  CN: '{cn}' → {sorted(ids_cn)[:3]}")
        print(f"  EN: '{en}' → {sorted(ids_en)[:3]}")
        print(f"  重叠: {len(overlap)}/{len(ids_cn | ids_en)} → {overlap}")
        print()

    # 测试 3：语义对比 - 完全不相关
    print("=== 测试 3: 不相关 query 不应误召 ===")
    unrelated = ["今天天气真好", "hello world", "Python 教程"]
    for q in unrelated:
        docs = e.retrieve(q, top_k=2, collection_name="error_codes_vec")
        # 检查 top1 score
        print(f"  '{q}' → {len(docs)} 条（预期 top-k 距离较远，但 Chroma 默认返回 top-k）")

    print()
    print("=== 验收结论 ===")
    print("若测试 1 中 'Visa 拒付' 和 'Visa chargeback' 召回相同/相似的 error_code 条目，")
    print("则说明 Qwen Embedding 真实语义生效（同义词命中核心场景）。")


if __name__ == "__main__":
    main()
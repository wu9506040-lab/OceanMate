"""BM25 关键词检索器（Day 14 P1-2 · 混合检索组件之一）。

为什么需要 BM25：
- Qwen 向量检索擅长语义（同义词、跨语言）
- 但对**精确关键词命中**（如具体错误码 "13.1"、"CB_FR4"、商户 ID）召回率低
- BM25 是经典 TF-IDF 变体，对字面匹配权重高
- 两者融合（RRF）= 兼顾语义 + 字面

设计：
- 启动时从 Chroma collection 拉全部文档 → jieba 分词 → 构建 BM25 索引
- 提供 retrieve(query, top_k) 接口返回 Document 列表
- 与向量检索并行使用，结果由 HybridRetriever 做 RRF 融合

PoC 阶段权衡：
- 不持久化 BM25 索引（每次 retrieve 时实时重建）
- 数据量 ≤200 条，重建耗时 < 100ms，可接受
- 真实环境应改为增量更新 + 持久化（pickle/sqlite）
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import jieba
from rank_bm25 import BM25Okapi

from app.interfaces.base_rag import BaseRAGEngine, Document
from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    COLLECTION_ERROR_CODES,
)


logger = logging.getLogger(__name__)


# 停用词（中英文常见，避免干扰 BM25）
_STOPWORDS = set([
    "的", "了", "和", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as", "into",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
])


def _tokenize(text: str) -> list[str]:
    """中文 jieba 分词 + 英文按空格切 + 去停用词 + 保留数字/字母/中文 token。

    例："Visa 13.1 拒付交易失败" → ["Visa", "13", "1", "拒付", "交易", "失败"]
    """
    if not text:
        return []

    # 1. 中文 jieba 分词（自动处理中英文混合）
    tokens = list(jieba.cut(text))

    # 2. 进一步切分英文/数字 token（jieba 对纯英文/数字合并不友好）
    refined = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t.lower() in _STOPWORDS:
            continue
        # 把 "13.1" 拆成 ["13", "1"]，把 "Visa13" 拆成 ["Visa", "13"]
        sub_tokens = re.findall(r"[A-Za-z]+|\d+", t)
        if sub_tokens:
            refined.extend(sub_tokens)
        else:
            refined.append(t)

    return refined


class BM25Retriever:
    """BM25 检索器（PoC 简化：每次 retrieve 实时重建索引）。"""

    def __init__(self, chroma_engine: ChromaRAGEngine):
        self.chroma = chroma_engine

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str = COLLECTION_ERROR_CODES,
    ) -> list[Document]:
        """BM25 检索：从 Chroma 拉全部文档 → 重建索引 → 检索 top-K。

        Returns:
            Document 列表（按 BM25 score 降序）
        """
        # 1. 从 Chroma 拉全部文档
        all_docs = self._fetch_all(collection_name)
        if not all_docs:
            return []

        # 2. 分词 + 构建 BM25 索引
        corpus = [_tokenize(d.text) for d in all_docs]
        bm25 = BM25Okapi(corpus)

        # 3. 检索
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        scores = bm25.get_scores(query_tokens)

        # 4. 排序 + 截断
        scored = list(zip(all_docs, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [doc for doc, score in scored[:top_k] if score > 0]

    def _fetch_all(self, collection_name: str) -> list[Document]:
        """从 Chroma 拉 collection 全部文档（PoC 数据量小可接受）。"""
        try:
            results = self.chroma._client.get_collection(
                name=collection_name,
                embedding_function=self.chroma._embedding_function,
            ).get()
            documents = []
            if results and results.get("ids"):
                for i, doc_id in enumerate(results["ids"]):
                    text = results["documents"][i] if results.get("documents") else ""
                    metadata = results["metadatas"][i] if results.get("metadatas") else {}
                    documents.append(Document(id=doc_id, text=text, metadata=metadata))
            return documents
        except Exception as e:
            logger.warning(f"[BM25Retriever] fetch_all 失败: {e}")
            return []
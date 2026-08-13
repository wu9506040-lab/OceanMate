"""Qwen Reranker - DashScope text-rerank 实现（Day 14 P1-2）。

为什么需要 Rerank：
- 向量召回 + BM25 融合后仍有噪声（top-K*3 候选里可能有弱相关）
- Rerank 用 Cross-Encoder 模型对 (query, doc) 精排，准确率显著高于双塔召回
- 召回 30 → rerank 取 5，精度提升 10-20%

设计：
- 使用 DashScope text-rerank API（gte-rerank 或 qwen3-rerank）
- 失败降级：返回原顺序（保证 Demo 不中断）
- 单次最多 50 条候选（DashScope 限制）
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.interfaces.base_rag import Document


logger = logging.getLogger(__name__)


# DashScope text-rerank 模型（按需选用）
RERANK_MODEL = "gte-rerank"  # 通用、轻量；可选 qwen3-rerank


class QwenReranker:
    """Qwen Rerank 包装（调用 DashScope text-rerank API）。

    Raises:
        ValueError: 无 DASHSCOPE_API_KEY 时
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = (
            api_key
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("DASHSCOPE_KEY")
        )
        if not self._api_key:
            raise ValueError(
                "QwenReranker 需要 DASHSCOPE_API_KEY。无 key 时调用 rerank() 自动降级保留原顺序。"
            )

    def rerank(
        self,
        query: str,
        documents: list[Document],
        top_k: Optional[int] = None,
    ) -> list[Document]:
        """Rerank 候选文档。

        Args:
            query: 查询文本
            documents: 候选文档（已通过向量+BM25 召回）
            top_k: 返回 Top-K（None 表示保留全部，按 rerank score 排序）

        Returns:
            重排后的 Document 列表（按 rerank score 降序）
        """
        if not documents:
            return []
        if not self._api_key:
            # 无 key 时降级：保留原顺序
            logger.warning("[QwenReranker] 无 DASHSCOPE_API_KEY，降级保留原顺序")
            return documents[:top_k] if top_k else documents

        try:
            import dashscope
            from dashscope import TextReRank
            # DashScope TextReRank.call() 参数（按官方文档）：model + query + documents（list[str]）
            doc_texts = [d.text for d in documents]
            resp = TextReRank.call(
                model=RERANK_MODEL,
                query=query,
                documents=doc_texts,
                top_n=len(documents),  # 让 API 给所有候选打分，前端截断
                return_documents=False,
                api_key=self._api_key,
            )
            if resp.status_code != 200:
                logger.warning(f"[QwenReranker] API 失败 {resp.status_code}，降级保留原顺序: {resp.message}")
                return documents[:top_k] if top_k else documents

            # 解析：resp.output.results = [{"index": 0, "relevance_score": 0.95}, ...]
            ranked = resp.output.get("results", [])
            scored_docs = []
            for item in ranked:
                idx = item.get("index")
                score = item.get("relevance_score", 0.0)
                if idx is not None and 0 <= idx < len(documents):
                    scored_docs.append((score, documents[idx]))
            scored_docs.sort(key=lambda x: x[0], reverse=True)

            if top_k:
                scored_docs = scored_docs[:top_k]
            return [doc for _, doc in scored_docs]
        except Exception as e:
            logger.warning(f"[QwenReranker] rerank 异常，降级保留原顺序: {e}")
            return documents[:top_k] if top_k else documents
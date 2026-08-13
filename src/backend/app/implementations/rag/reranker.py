"""Qwen Reranker - DashScope text-rerank 实现（Day 14 P1-2 + Day 14 Rerank 修复）。

为什么需要 Rerank：
- 向量召回 + BM25 融合后仍有噪声（top-K*3 候选里可能有弱相关）
- Rerank 用 Cross-Encoder 模型对 (query, doc) 精排，准确率显著高于双塔召回
- 召回 30 → rerank 取 5，精度提升 10-20%

设计：
- 使用 DashScope text-rerank API
- 默认 qwen3-rerank（实测可用，分数分布 0.33-0.53 有区分度）
- 备选 gte-rerank-v2（实测可用但分数偏低 0.006-0.16）
- 失败降级：返回原顺序（保证 Demo 不中断）
- 单次最多 50 条候选（DashScope 限制）

Day 14 Rerank 修复记录：
- 旧默认 gte-rerank → 403 Access denied（当前 DashScope 账号无权限）
- 新默认 qwen3-rerank → 200 + 真实分数（验证 reranker_smoke.py）
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.interfaces.base_rag import Document


logger = logging.getLogger(__name__)


# DashScope text-rerank 模型（按需选用，详见类注释）
# 实测可用性（2026-08-13）：
#   qwen3-rerank     → 200 ✅ 推荐（分数 0.33-0.53 有区分度）
#   gte-rerank-v2    → 200 ✅ 备选（分数 0.006-0.16 区分度较弱）
#   gte-rerank       → 403 ❌ 无权限
#   qwen-rerank      → 403 ❌ 无权限
SUPPORTED_MODELS = ("qwen3-rerank", "gte-rerank-v2")
DEFAULT_RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3-rerank")


class QwenReranker:
    """Qwen Rerank 包装（调用 DashScope text-rerank API）。

    默认 model=qwen3-rerank（实测 200 可用）；可通过 env RERANK_MODEL 覆盖。
    实测模型列表见模块顶部 SUPPORTED_MODELS 注释。

    Raises:
        ValueError: 无 DASHSCOPE_API_KEY 时
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = (
            api_key
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("DASHSCOPE_KEY")
        )
        if not self._api_key:
            raise ValueError(
                "QwenReranker 需要 DASHSCOPE_API_KEY。无 key 时调用 rerank() 自动降级保留原顺序。"
            )
        # 模型选择：默认 qwen3-rerank，env RERANK_MODEL 可覆盖
        self._model = model or DEFAULT_RERANK_MODEL
        if self._model not in SUPPORTED_MODELS:
            logger.warning(
                f"[QwenReranker] 模型 {self._model} 不在实测可用列表 {SUPPORTED_MODELS}，"
                f"将继续尝试（如果 API 返回 403 会降级）"
            )

    @property
    def model(self) -> str:
        return self._model

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
            from dashscope import TextReRank
            doc_texts = [d.text for d in documents]
            resp = TextReRank.call(
                model=self._model,
                query=query,
                documents=doc_texts,
                top_n=len(documents),  # 让 API 给所有候选打分，前端截断
                return_documents=False,
                api_key=self._api_key,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"[QwenReranker] API 失败 {resp.status_code} (model={self._model})，"
                    f"降级保留原顺序: {resp.message}"
                )
                return documents[:top_k] if top_k else documents

            # 解析：resp.output.results = [{"index": 0, "relevance_score": 0.95}, ...]
            ranked = resp.output.get("results", [])
            scored_docs = []
            for item in ranked:
                idx = item.get("index")
                score = item.get("relevance_score", 0.0)
                if idx is not None and 0 <= idx < len(documents):
                    # Day 14 Rerank: 把真实分数回写到 Document，方便上层展示
                    documents[idx].score = float(score)
                    scored_docs.append((score, documents[idx]))
            scored_docs.sort(key=lambda x: x[0], reverse=True)

            if top_k:
                scored_docs = scored_docs[:top_k]
            top_score = f"{scored_docs[0][0]:.4f}" if scored_docs else "N/A"
            logger.info(
                f"[QwenReranker] model={self._model}, query='{query[:30]}', "
                f"candidates={len(documents)}, returned={len(scored_docs)}, "
                f"top_score={top_score}"
            )
            return [doc for _, doc in scored_docs]
        except Exception as e:
            logger.warning(f"[QwenReranker] rerank 异常，降级保留原顺序: {e}")
            return documents[:top_k] if top_k else documents
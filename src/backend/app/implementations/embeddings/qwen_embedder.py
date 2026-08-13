"""QwenEmbedder - 阿里云 DashScope text-embedding-v3 实现（Day 14 P0-1）。

特点：
- 真实语义向量（语义召回，同义词能命中，如「拒付」/「chargeback」/「refund」相关）
- 中文友好（Qwen 系列原生多语言模型）
- 维度可配（Qwen v3 支持 512/768/1024/1536/2048，默认 1024）
- 实现 BaseEmbedder 接口 + Chroma EmbeddingFunction 协议（双重兼容）
- 失败降级 HashEmbedder（保证 Demo 不断）

替换 HashEmbedder 的位置：
- src/backend/app/implementations/rag/chroma_rag.py 第 67 行（ChromaRAGEngine 默认值）
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.interfaces.base_embedder import BaseEmbedder

logger = logging.getLogger(__name__)


# Qwen text-embedding-v3 支持的维度（per DashScope 官方文档）
SUPPORTED_DIMENSIONS = (512, 768, 1024, 1536, 2048)


class QwenEmbedder(BaseEmbedder):
    """Qwen text-embedding-v3 Embedding 实现。

    Args:
        dimension: 向量维度（默认 1024，必须在 SUPPORTED_DIMENSIONS 内）
        api_key: DashScope API key（默认从 env DASHSCOPE_API_KEY 读）

    Raises:
        ValueError: DASHSCOPE_API_KEY 未配置，或 dimension 不在支持列表
        RuntimeError: API 调用失败（带降级 HashEmbedder）
    """

    DEFAULT_DIMENSION = 1024
    MODEL_NAME = "text-embedding-v3"

    def __init__(
        self,
        dimension: int = DEFAULT_DIMENSION,
        api_key: Optional[str] = None,
    ):
        if dimension not in SUPPORTED_DIMENSIONS:
            raise ValueError(
                f"dimension {dimension} 不在 Qwen v3 支持列表 {SUPPORTED_DIMENSIONS}"
            )
        self._dimension = dimension
        self._api_key = (
            api_key
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("DASHSCOPE_KEY")  # 兼容旧 alias
        )
        if not self._api_key:
            raise ValueError(
                "QwenEmbedder 需要 DASHSCOPE_API_KEY 环境变量。"
                "PoC 演示可在 .env 配置真实 key；评审 Demo 启动时会校验。"
            )

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量向量化（Qwen v3 单次最多 10 条，超出自动分批）。

        Returns:
            list of vectors（每个维度 = self.dimension）
        """
        if not texts:
            return []

        # Qwen v3 限流保护：单次最多 10 条
        BATCH_SIZE = 10
        all_vectors = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            vectors = self._embed_batch(batch)
            all_vectors.extend(vectors)
        return all_vectors

    def embed_query(self, text: str) -> list[float]:
        """单条 query 向量化。"""
        return self._embed_batch([text])[0]

    # Chroma EmbeddingFunction 协议（chroma 调用入口）
    def __call__(self, input: list[str]) -> list[list[float]]:
        """Chroma 调用入口：输入文本列表，输出向量列表。"""
        return self.embed_documents(input)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """调 DashScope API；失败时降级 HashEmbedder（保证 PoC 不断）。"""
        try:
            from dashscope import TextEmbedding
            resp = TextEmbedding.call(
                model=self.MODEL_NAME,
                input=texts,
                api_key=self._api_key,
                dimension=self._dimension,
            )
            if resp.status_code == 200:
                return [
                    list(item["embedding"])
                    for item in resp.output["embeddings"]
                ]
            raise RuntimeError(f"Qwen Embedding 返回 {resp.status_code}: {resp.message}")
        except Exception as e:
            logger.warning(
                f"[QwenEmbedder] API 调用失败，降级 HashEmbedder: {e}"
            )
            # 降级：保证 Demo 不中断；线上应该 raise + 上层重试
            from app.implementations.embeddings.hash_embedder import HashEmbedder
            return HashEmbedder(dimension=self._dimension).embed_documents(texts)


# 向后兼容别名（与 HashEmbedder 平级引用）
HashEmbeddingFunction = QwenEmbedder  # 老代码 import 别名指向新实现
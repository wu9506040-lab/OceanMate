"""HashEmbedder - 确定性 hash embedding（占位实现）。

从 chroma_rag.py 的 HashEmbeddingFunction 抽出独立模块，
既实现 BaseEmbedder 接口（业务用），又实现 Chroma 的 EmbeddingFunction 接口（ChromaRAGEngine 用）。

特点：
- 无外部依赖、不下载模型
- 确定性（相同输入 → 相同输出）
- 中文按字 + 英文按词
- 维度可配（默认 128）
- 语义能力弱（同义词召回差），仅作 PoC 占位

真实环境替换（详见 docs/sop/SOP-RAG.md §6）：
- ONNXMiniLM_L6_V2（轻量英文为主）
- Qwen TextEmbedding v3（中文友好）
- BGE-large-zh（开源中文 SOTA）
"""

import hashlib
from typing import Optional

from app.interfaces.base_embedder import BaseEmbedder


class HashEmbedder(BaseEmbedder):
    """Hash-based Embedding 实现（BaseEmbedder + Chroma 兼容）。

    实现 2 个接口：
    - BaseEmbedder.embed_documents / embed_query / dimension
    - __call__(input: list[str]) -> list[list[float]]（Chroma EmbeddingFunction 协议）
    """

    DEFAULT_DIMENSION = 128

    def __init__(self, dimension: int = DEFAULT_DIMENSION):
        if dimension <= 0:
            raise ValueError("dimension 必须 > 0")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    # Chroma EmbeddingFunction 协议（向后兼容）
    def __call__(self, input: list[str]) -> list[list[float]]:
        """Chroma 调用入口：输入文本列表，输出向量列表。"""
        return self.embed_documents(input)

    def _embed_one(self, text: str) -> list[float]:
        """单个文本 → 向量。"""
        tokens = self._tokenize(text)

        vector = [0.0] * self._dimension
        for token in tokens:
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vector[h % self._dimension] += 1.0

        # L2 归一化
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词（中文字 + 英文词）。"""
        tokens = []
        current_word = []
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                # 中文：按字
                if current_word:
                    tokens.append("".join(current_word).lower())
                    current_word = []
                tokens.append(char)
            elif char.isalnum():
                current_word.append(char)
            else:
                if current_word:
                    tokens.append("".join(current_word).lower())
                    current_word = []
        if current_word:
            tokens.append("".join(current_word).lower())
        return tokens
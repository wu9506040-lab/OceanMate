"""BaseEmbedder - Embedding 模型抽象接口。

关键可替换点：未来从 HashEmbedder 切到 Qwen v3 / BGE / OpenAI 只需换实现，
业务代码（IngestionPipeline / RAG）零改动。

3 个核心方法：
- embed_documents()    批量向量化（入库用）
- embed_query()        单文本向量化（检索用，部分模型 query/doc 用不同 prefix）
- dimension 属性       向量维度（用于 sanity check + 索引重建）
"""

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    """Embedding 模型基类。"""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding 向量维度。"""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量向量化文本。

        Args:
            texts: 文本列表

        Returns:
            向量列表（每个向量维度 = self.dimension）

        Raises:
            RuntimeError: 调用失败（如 API 限流 / 模型加载失败）
        """

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """向量化单条查询文本。

        Args:
            text: 查询文本

        Returns:
            向量（维度 = self.dimension）

        Note:
            某些模型（如 BGE）对 query 和 document 使用不同前缀，
            实现可在此区分。当前 HashEmbedder 无差。
        """
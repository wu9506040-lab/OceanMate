"""BaseRAGEngine - RAG 引擎抽象接口。

4 个核心方法：
- retrieve()      检索相关文档（最常用）
- add_document()  添加文档到知识库
- delete_document() 删除文档
- update_document() 更新文档

实现层：app/implementations/rag/chroma_rag.py
SOP：SOP-RAG-001（3 个逆向场景：知识库空/相似度低/Embedding 失败）
"""

from abc import ABC, abstractmethod
from typing import Optional


class Document:
    """知识库文档（最小数据单元）。"""

    def __init__(
        self,
        id: str,
        text: str,
        metadata: Optional[dict] = None,
        embedding: Optional[list[float]] = None,
    ):
        self.id = id
        self.text = text
        self.metadata = metadata or {}
        self.embedding = embedding

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "metadata": self.metadata,
        }


class BaseRAGEngine(ABC):
    """RAG 引擎基类。

    评审意义：未来切换向量库（Chroma → Milvus/Pinecone）只需换实现。
    """

    @abstractmethod
    def retrieve(
        self, query: str, top_k: int = 5, filter: Optional[dict] = None
    ) -> list[Document]:
        """检索相关文档。

        Args:
            query: 查询文本
            top_k: 返回 Top-K 文档
            filter: 元数据过滤条件（如 {"country": "BR"}）

        Returns:
            Document 列表，按相似度降序

        Raises:
            RuntimeError: 检索失败（Embedding 失败等）

        Note:
            检索结果可能为空（知识库空 / 相似度全低），返回 []，由调用方决定降级策略。
        """

    @abstractmethod
    def add_document(self, document: Document) -> bool:
        """添加文档到知识库。

        Args:
            document: Document 对象

        Returns:
            True 成功 / False 失败

        Raises:
            RuntimeError: 写入失败
        """

    @abstractmethod
    def delete_document(self, doc_id: str) -> bool:
        """删除文档。

        Args:
            doc_id: 文档 ID

        Returns:
            True 成功 / False 文档不存在
        """

    @abstractmethod
    def update_document(self, doc_id: str, document: Document) -> bool:
        """更新文档。

        Args:
            doc_id: 文档 ID
            document: 新内容

        Returns:
            True 成功 / False 文档不存在
        """
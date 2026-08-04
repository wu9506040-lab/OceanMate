"""BaseRAGEngine - RAG 引擎抽象接口。

7 个核心方法：
- retrieve()           检索相关文档（最常用）
- add_document()       单条添加
- add_documents()      批量添加（Day 8 扩展，用于 seed）
- delete_document()    删除文档
- update_document()    更新文档
- recall_by_metadata() 纯元数据召回（无 query，Day 8 扩展）
- get_by_id()          按 ID 取单文档（Day 8 扩展）

实现层：app/implementations/rag/chroma_rag.py
SOP：SOP-RAG-001 + SOP-RAG-002（Day 8 新增章节）
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
        """添加单条文档到知识库。

        Args:
            document: Document 对象

        Returns:
            True 成功 / False 失败

        Raises:
            RuntimeError: 写入失败
        """

    @abstractmethod
    def add_documents(self, documents: list[Document]) -> bool:
        """批量添加文档（用于 seed 脚本，Day 8 新增）。

        Args:
            documents: Document 列表

        Returns:
            True 全部成功 / False 部分或全部失败

        Note:
            实现可选择事务语义（全成功或全失败）或 best-effort。
            PoC 阶段 ChromaRAGEngine 走 best-effort + 累计成功数。
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

    @abstractmethod
    def recall_by_metadata(
        self, filter: dict, limit: int = 100, collection_name: Optional[str] = None
    ) -> list[Document]:
        """纯元数据召回（无 query，Day 8 新增）。

        适用：
        - 列出某国家所有错误码（filter={"country": "BR"}）
        - 列出某渠道所有支付方式（filter={"country": "BR", "channel": "Visa"}）

        Args:
            filter: 元数据过滤条件（必填，至少 1 个键值对）
            limit: 最大返回数
            collection_name: Collection 名（默认 error_codes_vec）

        Returns:
            Document 列表（无相似度排序，按 ID 升序）

        Raises:
            ValueError: filter 为空
        """

    @abstractmethod
    def get_by_id(self, doc_id: str, collection_name: Optional[str] = None) -> Optional[Document]:
        """按 ID 取单文档（Day 8 新增）。

        Args:
            doc_id: 文档 ID
            collection_name: Collection 名

        Returns:
            Document 或 None（不存在）
        """
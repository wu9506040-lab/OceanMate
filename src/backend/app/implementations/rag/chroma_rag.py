"""Chroma RAG Engine 实现（嵌入式，无需搭服务）。

3 个 Collection：
- error_codes_vec       错误码知识（PDA 检索）
- cases_vec             案例知识（PDA + KEA 沉淀）
- payment_methods_vec   支付方式知识（MSA PWR 子能力检索）

详见 SOP-RAG-001（3 个逆向场景：知识库空/相似度低/Embedding 失败）。

PoC 阶段使用 HashEmbeddingFunction（无外部依赖、不下载模型），
保证 Demo 可演示。真实环境可切换为 chromadb 默认 ONNX MiniLM 或 Qwen Embedding。
"""

import hashlib
import os
from pathlib import Path
from typing import Optional

from app.interfaces.base_rag import BaseRAGEngine, Document
from app.implementations.embeddings import HashEmbedder
from app.implementations.llm.qwen_gateway import get_default_gateway


# 默认数据目录（指向 src/backend/data/chroma/）
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "chroma"

# Collection 名称常量
COLLECTION_ERROR_CODES = "error_codes_vec"
COLLECTION_CASES = "cases_vec"
COLLECTION_PAYMENT_METHODS = "payment_methods_vec"


# 向后兼容别名（Day 8 重构）
# 老代码引用 chroma_rag.HashEmbeddingFunction 不报错（指向新 HashEmbedder）
HashEmbeddingFunction = HashEmbedder


class ChromaRAGEngine(BaseRAGEngine):
    """Chroma 嵌入式 RAG 引擎。

    评审意义：PoC 阶段不搭 Milvus/Pinecone 服务，本地文件即可。
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        llm_gateway=None,
        embedding_function=None,
    ):
        """初始化 Chroma 客户端。

        Args:
            data_dir: Chroma 数据目录（默认 src/backend/data/chroma/）
            llm_gateway: 用于生成文本 embedding（默认 get_default_gateway()）
            embedding_function: Chroma embedding 函数（默认 HashEmbeddingFunction）
        """
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 禁用 Chroma telemetry（加速启动）
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

        import chromadb
        self._client = chromadb.PersistentClient(path=str(self.data_dir))

        self.llm = llm_gateway or get_default_gateway()
        self._embedding_function = embedding_function or HashEmbedder()

        # 预创建 3 个 collection
        self._collections = {
            COLLECTION_ERROR_CODES: self._client.get_or_create_collection(
                name=COLLECTION_ERROR_CODES,
                metadata={"description": "错误码知识库"},
                embedding_function=self._embedding_function,
            ),
            COLLECTION_CASES: self._client.get_or_create_collection(
                name=COLLECTION_CASES,
                metadata={"description": "诊断案例库"},
                embedding_function=self._embedding_function,
            ),
            COLLECTION_PAYMENT_METHODS: self._client.get_or_create_collection(
                name=COLLECTION_PAYMENT_METHODS,
                metadata={"description": "支付方式知识（PWR 用）"},
                embedding_function=self._embedding_function,
            ),
        }

    def retrieve(
        self, query: str, top_k: int = 5, filter: Optional[dict] = None,
        collection_name: str = COLLECTION_ERROR_CODES,
    ) -> list[Document]:
        """检索相关文档。

        Args:
            query: 查询文本
            top_k: 返回 Top-K
            filter: 元数据过滤（如 {"country": "BR"}）
            collection_name: Collection 名（默认错误码库）

        Returns:
            Document 列表（按相似度降序），知识库空时返回 []
        """
        if collection_name not in self._collections:
            raise ValueError(f"Collection '{collection_name}' 不存在")

        collection = self._collections[collection_name]

        # Chroma 的 query 用 embedding 函数（这里用 Chroma 自带的）
        # 注：Chroma 默认用 all-MiniLM-L6-v2 模型，无需我们自己 embed
        # 如果后续要切到 Qwen Embedding，可以改为自定义 embedding function
        try:
            results = collection.query(
                query_texts=[query],
                n_results=top_k,
                where=filter,
            )
        except Exception as e:
            raise RuntimeError(f"Chroma 检索失败: {e}") from e

        # 解析结果
        documents = []
        if results and results.get("documents"):
            for i, text in enumerate(results["documents"][0]):
                doc_id = results["ids"][0][i] if results.get("ids") else f"unknown_{i}"
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                documents.append(
                    Document(id=doc_id, text=text, metadata=metadata)
                )
        return documents

    def add_document(
        self, document: Document, collection_name: str = COLLECTION_ERROR_CODES
    ) -> bool:
        """添加文档到指定 collection。"""
        if collection_name not in self._collections:
            raise ValueError(f"Collection '{collection_name}' 不存在")

        try:
            self._collections[collection_name].add(
                ids=[document.id],
                documents=[document.text],
                metadatas=[document.metadata] if document.metadata else None,
            )
            return True
        except Exception as e:
            raise RuntimeError(f"添加文档失败: {e}") from e

    def add_documents(
        self,
        documents: list[Document],
        collection_name: str = COLLECTION_ERROR_CODES,
    ) -> bool:
        """批量添加文档（Day 8 新增 · 用于 seed 脚本）。

        Chroma 原生支持批量 add；这里走 best-effort，partial success 不抛异常。
        返回值：True = 全部成功；False = 入参空或 collection 不存在。
        """
        if not documents:
            return False
        if collection_name not in self._collections:
            raise ValueError(f"Collection '{collection_name}' 不存在")

        ids = [d.id for d in documents]
        texts = [d.text for d in documents]
        metadatas = [d.metadata if d.metadata else None for d in documents]

        try:
            self._collections[collection_name].add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
            )
            return True
        except Exception as e:
            raise RuntimeError(f"批量添加文档失败: {e}") from e

    def delete_document(
        self, doc_id: str, collection_name: str = COLLECTION_ERROR_CODES
    ) -> bool:
        """删除文档。"""
        if collection_name not in self._collections:
            return False
        try:
            self._collections[collection_name].delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def update_document(
        self,
        doc_id: str,
        document: Document,
        collection_name: str = COLLECTION_ERROR_CODES,
    ) -> bool:
        """更新文档（先 get() 检查存在性，再决定 update 或 add）。

        Chroma 的 update() 对不存在 ID 只 warning 不抛异常，单纯 try/except
        无法触发 fallback。改用 get() 先判断。
        """
        if collection_name not in self._collections:
            return False
        col = self._collections[collection_name]
        try:
            existing = col.get(ids=[doc_id])
            exists = bool(existing and existing.get("ids"))
        except Exception:
            exists = False
        try:
            if exists:
                col.update(
                    ids=[doc_id],
                    documents=[document.text],
                    metadatas=[document.metadata] if document.metadata else None,
                )
            else:
                col.add(
                    ids=[doc_id],
                    documents=[document.text],
                    metadatas=[document.metadata] if document.metadata else None,
                )
            return True
        except Exception:
            return False

    def get_collection_stats(self) -> dict:
        """获取所有 collection 的文档数（运维/测试用）。"""
        stats = {}
        for name, col in self._collections.items():
            stats[name] = col.count()
        return stats

    # ===== Day 8 新增方法 =====

    def recall_by_metadata(
        self,
        filter: dict,
        limit: int = 100,
        collection_name: str = COLLECTION_ERROR_CODES,
    ) -> list[Document]:
        """纯元数据召回（无 query）。

        Chroma 支持 `where` 过滤；多键值组合需用 $and / $or 操作符。
        自动转换：filter={"k1": v1, "k2": v2} → where={"$and": [{"k1": v1}, {"k2": v2}]}
        """
        if not filter:
            raise ValueError("filter 必须至少 1 个键值对")
        if collection_name not in self._collections:
            raise ValueError(f"Collection '{collection_name}' 不存在")

        # 多键值自动包装 $and
        if len(filter) == 1:
            where_clause = filter
        else:
            where_clause = {
                "$and": [{k: v} for k, v in filter.items()]
            }

        try:
            results = self._collections[collection_name].get(
                where=where_clause,
                limit=limit,
            )
        except Exception as e:
            raise RuntimeError(f"recall_by_metadata 失败: {e}") from e

        documents = []
        if results and results.get("ids"):
            for i, doc_id in enumerate(results["ids"]):
                text = results["documents"][i] if results.get("documents") else ""
                metadata = results["metadatas"][i] if results.get("metadatas") else {}
                documents.append(Document(id=doc_id, text=text, metadata=metadata))
        return documents

    def get_by_id(
        self,
        doc_id: str,
        collection_name: str = COLLECTION_ERROR_CODES,
    ) -> Optional[Document]:
        """按 ID 取单文档。"""
        if collection_name not in self._collections:
            return None
        try:
            results = self._collections[collection_name].get(ids=[doc_id])
        except Exception:
            return None

        if not results or not results.get("ids"):
            return None
        # 取第一条
        text = results["documents"][0] if results.get("documents") else ""
        metadata = results["metadatas"][0] if results.get("metadatas") else {}
        return Document(id=results["ids"][0], text=text, metadata=metadata)
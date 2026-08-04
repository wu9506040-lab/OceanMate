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
from app.implementations.llm.qwen_gateway import get_default_gateway


# 默认数据目录（指向 src/backend/data/chroma/）
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "chroma"

# Collection 名称常量
COLLECTION_ERROR_CODES = "error_codes_vec"
COLLECTION_CASES = "cases_vec"
COLLECTION_PAYMENT_METHODS = "payment_methods_vec"


class HashEmbeddingFunction:
    """Hash-based Embedding Function — 无外部依赖，PoC 阶段使用。

    原理：把文本分词 → 每个词 hash → 固定维度向量。
    优点：不下载模型、可重现、检索质量够 PoC。
    缺点：语义检索能力弱（同义词召回差）。

    真实环境替换方案：
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        embedding_function = ONNXMiniLM_L6_V2()
    """

    DIMENSION = 128  # 固定维度

    def __init__(self, dimension: int = DIMENSION):
        self.dimension = dimension

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Chroma 调用接口：输入文本列表，输出向量列表。"""
        return [self._embed_one(text) for text in input]

    def _embed_one(self, text: str) -> list[float]:
        """单个文本 → 向量。"""
        # 简单分词（中文按字，英文按词）
        tokens = self._tokenize(text)

        # 初始化零向量
        vector = [0.0] * self.dimension

        # 每个 token 累加 hash 值
        for token in tokens:
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            vector[idx] += 1.0

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
        self._embedding_function = embedding_function or HashEmbeddingFunction()

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
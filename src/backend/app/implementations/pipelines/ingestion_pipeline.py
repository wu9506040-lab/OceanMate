"""IngestionPipeline - clean → chunk → embed → store 一站式入库编排。

设计原则：
1. 各阶段独立（cleaner / chunker / embedder / rag 都是可插拔）
2. 阶段可跳过（cleaner=None 时不清理；embedder=None 时让 Chroma 内部 embed）
3. 返回 chunk_stats 便于调试 + seed 脚本打印
4. 错误隔离：单条记录失败不阻断整体（记 skipped_records）

适用场景：
- seed 脚本（cases.json / payment_methods.json → Chroma）
- KEA Tool 沉淀新案例时（运行时单条入库）
- 飞书多维表格同步（批量同步）

详见 docs/sop/SOP-RAG.md §6（Day 8 新增 Pipeline 章节）。
"""

from typing import Optional

from app.interfaces.base_rag import BaseRAGEngine, Document
from app.interfaces.base_chunker import BaseChunker
from app.implementations.chunking import SmartChunker


class IngestionPipeline:
    """入库编排器。

    Args:
        rag: 必填，RAG 引擎
        chunker: 默认 SmartChunker（自动选策略）
        cleaner: 可选，None 时不清理（直接 chunk）
        embedder: 可选，None 时让 RAG 自己处理 embedding（Chroma 内置）
    """

    def __init__(
        self,
        rag: BaseRAGEngine,
        chunker: Optional[BaseChunker] = None,
        cleaner=None,
        embedder=None,
    ):
        self.rag = rag
        self.chunker = chunker or SmartChunker()
        self.cleaner = cleaner
        self.embedder = embedder

    def ingest(
        self,
        records: list[dict],
        source_table: str,
        collection_name: str,
        text_field: str = "text",
        id_field: str = "id",
    ) -> dict:
        """批量入库。

        Args:
            records: list of dict（如从 JSON 读出来的 rows）
            source_table: 来源表名（用于日志 / 审计）
            collection_name: 目标 collection
            text_field: 记录中文本字段名
            id_field: 记录中 ID 字段名

        Returns:
            chunk_stats: {
                "source_table": str,
                "collection": str,
                "total_records": int,
                "total_chunks": int,
                "skipped_records": int,
                "strategies_used": dict,    # {"whole_record": 5, "qa_pair": 3}
                "avg_chunk_size": float,
                "max_chunk_size": int,
            }
        """
        stats = {
            "source_table": source_table,
            "collection": collection_name,
            "total_records": len(records),
            "total_chunks": 0,
            "skipped_records": 0,
            "strategies_used": {},
            "avg_chunk_size": 0.0,
            "max_chunk_size": 0,
        }
        chunk_sizes = []

        for record in records:
            doc_id = str(record.get(id_field, ""))
            text = record.get(text_field, "")
            base_metadata = {
                k: v for k, v in record.items()
                if k not in (id_field, text_field) and not isinstance(v, (list, dict))
            }
            base_metadata["source_table"] = source_table

            # 1. clean（可选）
            if self.cleaner is not None:
                cleaned = self.cleaner.clean(text)
                text = cleaned.text

            # 2. chunk
            chunks = self.chunker.chunk(text, doc_id, base_metadata)
            if not chunks:
                stats["skipped_records"] += 1
                continue

            # 3. embed（可选，留 hook；当前 Chroma 自管 embedding）
            # if self.embedder is not None:
            #     embeddings = self.embedder.embed_documents([c.text for c in chunks])
            #     for c, e in zip(chunks, embeddings):
            #         c.embedding = e

            # 4. store：Chunk → Document → rag.add_documents
            documents = [
                Document(id=c.chunk_id, text=c.text, metadata=c.metadata)
                for c in chunks
            ]
            try:
                self.rag.add_documents(documents, collection_name=collection_name)
            except Exception as e:
                # 错误隔离：单条失败不阻断整体
                stats["skipped_records"] += 1
                continue

            # 累计 stats
            stats["total_chunks"] += len(documents)
            for c in chunks:
                size = len(c.text)
                chunk_sizes.append(size)
                strategy = c.metadata.get("strategy", "unknown")
                stats["strategies_used"][strategy] = stats["strategies_used"].get(strategy, 0) + 1

        if chunk_sizes:
            stats["avg_chunk_size"] = sum(chunk_sizes) / len(chunk_sizes)
            stats["max_chunk_size"] = max(chunk_sizes)

        return stats

    def ingest_single(
        self,
        record: dict,
        source_table: str,
        collection_name: str,
        text_field: str = "text",
        id_field: str = "id",
    ) -> dict:
        """单条入库（KEA Tool 沉淀用）。

        返回单条 chunk_stats。
        """
        return self.ingest(
            [record], source_table=source_table,
            collection_name=collection_name,
            text_field=text_field, id_field=id_field,
        )
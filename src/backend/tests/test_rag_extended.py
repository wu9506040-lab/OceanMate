"""RAG 扩展 SOP 测试 — Day 8。

覆盖 6 场景：
- SOP-RAG-002-A add_documents 批量入库
- SOP-RAG-002-B recall_by_metadata 纯元数据召回
- SOP-RAG-002-C get_by_id 单文档读取
- SOP-RAG-002-D IngestionPipeline clean→chunk→store 端到端
- SOP-RAG-002-E IngestionPipeline 空 records 跳过
- SOP-RAG-002-F IngestionPipeline chunk_stats 准确

详见 docs/sop/SOP-RAG.md §6。
"""

import pytest
from pathlib import Path

from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    COLLECTION_ERROR_CODES,
    COLLECTION_CASES,
    COLLECTION_PAYMENT_METHODS,
)
from app.interfaces.base_rag import Document
from app.implementations.chunking import SmartChunker, WholeRecordChunker
from app.implementations.pipelines import IngestionPipeline


@pytest.fixture
def tmp_chroma_dir(tmp_path):
    d = tmp_path / "chroma"
    d.mkdir()
    return d


@pytest.fixture
def rag(tmp_chroma_dir):
    return ChromaRAGEngine(data_dir=tmp_chroma_dir)


# ===== RAG 扩展方法 =====

class TestRAGAddDocuments:
    """SOP-RAG-002-A：批量入库。"""

    def test_add_documents_batch(self, rag):
        docs = [
            Document(id="d1", text="BR Visa 拒付 ERR_X_001 规则 1", metadata={"country": "BR"}),
            Document(id="d2", text="BR Mastercard 通道维护规则 2", metadata={"country": "BR"}),
            Document(id="d3", text="US PayPal 账户被封规则 3", metadata={"country": "US"}),
        ]
        assert rag.add_documents(docs, collection_name=COLLECTION_ERROR_CODES) is True

        stats = rag.get_collection_stats()
        assert stats[COLLECTION_ERROR_CODES] == 3

    def test_add_documents_empty_returns_false(self, rag):
        """空 list → False（不算失败，但不写入）。"""
        assert rag.add_documents([], collection_name=COLLECTION_ERROR_CODES) is False

    def test_add_documents_to_nonexistent_collection_raises(self, rag):
        docs = [Document(id="x", text="y")]
        with pytest.raises(ValueError):
            rag.add_documents(docs, collection_name="nonexistent")


class TestRAGRecallByMetadata:
    """SOP-RAG-002-B：纯元数据召回（无 query）。"""

    def test_recall_all_BR_records(self, rag):
        """filter={"country": "BR"} → 仅返回 BR 记录。"""
        docs = [
            Document(id="br1", text="BR rule 1", metadata={"country": "BR"}),
            Document(id="br2", text="BR rule 2", metadata={"country": "BR"}),
            Document(id="us1", text="US rule", metadata={"country": "US"}),
        ]
        rag.add_documents(docs, collection_name=COLLECTION_ERROR_CODES)

        results = rag.recall_by_metadata({"country": "BR"}, collection_name=COLLECTION_ERROR_CODES)
        ids = {d.id for d in results}
        assert ids == {"br1", "br2"}

    def test_recall_combined_filters(self, rag):
        """多键值过滤。"""
        docs = [
            Document(id="a", text="BR Visa rule", metadata={"country": "BR", "channel": "Visa"}),
            Document(id="b", text="BR MC rule", metadata={"country": "BR", "channel": "Mastercard"}),
            Document(id="c", text="US Visa rule", metadata={"country": "US", "channel": "Visa"}),
        ]
        rag.add_documents(docs, collection_name=COLLECTION_ERROR_CODES)

        results = rag.recall_by_metadata(
            {"country": "BR", "channel": "Visa"},
            collection_name=COLLECTION_ERROR_CODES,
        )
        assert len(results) == 1
        assert results[0].id == "a"

    def test_recall_empty_filter_raises(self, rag):
        """空 filter → ValueError（避免误全表扫描）。"""
        with pytest.raises(ValueError):
            rag.recall_by_metadata({}, collection_name=COLLECTION_ERROR_CODES)

    def test_recall_limit(self, rag):
        """limit 参数生效。"""
        docs = [Document(id=f"d{i}", text=f"doc {i}", metadata={"k": "v"}) for i in range(10)]
        rag.add_documents(docs, collection_name=COLLECTION_ERROR_CODES)

        results = rag.recall_by_metadata(
            {"k": "v"}, limit=3, collection_name=COLLECTION_ERROR_CODES,
        )
        assert len(results) == 3


class TestRAGGetById:
    """SOP-RAG-002-C：单文档读取。"""

    def test_get_existing(self, rag):
        rag.add_document(Document(
            id="doc_x", text="hello world", metadata={"k": "v"},
        ), collection_name=COLLECTION_ERROR_CODES)

        doc = rag.get_by_id("doc_x", collection_name=COLLECTION_ERROR_CODES)
        assert doc is not None
        assert doc.id == "doc_x"
        assert doc.text == "hello world"
        assert doc.metadata == {"k": "v"}

    def test_get_nonexistent_returns_none(self, rag):
        assert rag.get_by_id("nope", collection_name=COLLECTION_ERROR_CODES) is None


# ===== IngestionPipeline =====

class TestIngestionPipeline:
    """SOP-RAG-002-D/E/F：Pipeline 编排。"""

    def test_ingest_end_to_end(self, rag):
        """完整流程：records → chunk → store → stats。"""
        records = [
            {"id": "r1", "text": "BR Visa 拒付 ERR_X_001", "country": "BR"},
            {"id": "r2", "text": "BR Pix 即时支付通道说明", "country": "BR"},
            {"id": "r3", "text": "US PayPal 账户被封处理", "country": "US"},
        ]
        pipeline = IngestionPipeline(rag=rag, chunker=WholeRecordChunker())
        stats = pipeline.ingest(
            records=records,
            source_table="cases",
            collection_name=COLLECTION_CASES,
        )

        assert stats["source_table"] == "cases"
        assert stats["collection"] == COLLECTION_CASES
        assert stats["total_records"] == 3
        assert stats["total_chunks"] == 3
        assert stats["skipped_records"] == 0
        assert stats["strategies_used"]["whole_record"] == 3
        assert stats["max_chunk_size"] > 0
        assert stats["avg_chunk_size"] > 0

        # 验证确实入库
        assert rag.get_collection_stats()[COLLECTION_CASES] == 3

    def test_ingest_empty_records_returns_zero_stats(self, rag):
        """空 records → 全 0 stats。"""
        pipeline = IngestionPipeline(rag=rag, chunker=WholeRecordChunker())
        stats = pipeline.ingest(
            records=[],
            source_table="x",
            collection_name=COLLECTION_CASES,
        )
        assert stats["total_records"] == 0
        assert stats["total_chunks"] == 0
        assert stats["avg_chunk_size"] == 0.0

    def test_ingest_with_smart_chunker_dispatches_correctly(self, rag):
        """SmartChunker 自动调度：短文本走 whole_record，长 Q/A 走 qa_pair。"""
        records = [
            {"id": "short1", "text": "BR Visa 拒付规则"},
            {
                "id": "long_qa",
                "text": """Q: BR Pix 通道何时支持？
A: BR 央行 2020 推出的 Pix 即时支付已成 BR 主流跨境收款必须支持，覆盖 B2C 全行业且费率极低。
Q: Boleto 现金支付比例？
A: BR 无银行账户人群约 30%，Boleto 是 BR 现金支付补充，适合高客单或分期场景。
Q: 通道维护怎么查？
A: 看 OP 通道监控 API 状态，关注上游通道返回的 5xx 或超时率是否超过阈值。
Q: ACH 适用什么场景？
A: US 大额或 B2B 场景，费率远低于信用卡，教育培训的学费分期常使用。
Q: UnionPay 在跨境场景的角色？
A: 银联是中国本土主流，跨境场景如出境游、海外学费必备，覆盖 CN 用户海外消费 95% 以上。
Q: WeChat Pay 跨境电商是否需要支持？
A: 微信支付覆盖 CN 移动支付 80% 以上用户，跨境电商需支持 CN 消费者购买流程。
Q: BR 区域 3DS 是否强制？
A: 按当地合规要求 BR 区域 Visa 必须配套 3DS 配置，否则会被风控拦截。
Q: 拒付后怎么申诉？
A: 准备 CB 申诉材料（订单/物流/签收凭证），通过 Verifi/Mastercard RDR 提前拦截。""",
            },
        ]
        pipeline = IngestionPipeline(rag=rag, chunker=SmartChunker())
        stats = pipeline.ingest(
            records=records,
            source_table="faq",
            collection_name=COLLECTION_CASES,
        )

        # short1 → 1 chunk (whole_record)
        # long_qa → 4 chunks (qa_pair)
        assert stats["total_chunks"] >= 4
        assert "whole_record" in stats["strategies_used"]
        assert "qa_pair" in stats["strategies_used"]
        assert stats["strategies_used"]["qa_pair"] >= 4

    def test_ingest_single(self, rag):
        """单条入库（KEA 沉淀场景）。"""
        pipeline = IngestionPipeline(rag=rag, chunker=WholeRecordChunker())
        stats = pipeline.ingest_single(
            record={"id": "single1", "text": "test content"},
            source_table="cases",
            collection_name=COLLECTION_CASES,
        )
        assert stats["total_records"] == 1
        assert stats["total_chunks"] == 1
        assert rag.get_collection_stats()[COLLECTION_CASES] == 1

    def test_ingest_metadata_inherited(self, rag):
        """base_metadata 正确传递到 chunk.metadata。"""
        records = [{"id": "r1", "text": "test", "country": "BR", "channel": "Visa", "priority": 1}]
        pipeline = IngestionPipeline(rag=rag, chunker=WholeRecordChunker())
        pipeline.ingest(
            records=records,
            source_table="t",
            collection_name=COLLECTION_CASES,
        )
        doc = rag.get_by_id("r1#w0", collection_name=COLLECTION_CASES)
        assert doc is not None
        assert doc.metadata["country"] == "BR"
        assert doc.metadata["channel"] == "Visa"
        assert doc.metadata["source_table"] == "t"
        assert doc.metadata["strategy"] == "whole_record"
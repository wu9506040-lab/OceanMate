"""Day 19 入库幂等测试 — add→upsert 修复的回归防线。

背景：chroma 的 add() 对重复 id 抛异常，导致 seed / IngestionPipeline / KEA 重跑即炸。
修复为 upsert() 后，本测试锁定三条幂等契约：
- IDEM-1 add_document 同 id 重复写 → 不抛异常、只有一份、metadata 被最新值覆盖
- IDEM-2 add_documents 批量重复写 → count 不膨胀
- IDEM-3 IngestionPipeline 同一批 records 跑两遍 → collection 数量与单遍一致（重跑安全）
"""

import pytest

from app.implementations.rag.chroma_rag import (
    ChromaRAGEngine,
    HashEmbeddingFunction,
    COLLECTION_CASES,
)
from app.implementations.pipelines.ingestion_pipeline import IngestionPipeline
from app.interfaces.base_rag import Document


@pytest.fixture
def rag(tmp_path):
    d = tmp_path / "chroma"
    d.mkdir()
    # 显式注入 HashEmbedder：测试不依赖外部 embedding API（确定性）
    return ChromaRAGEngine(data_dir=d, embedding_function=HashEmbeddingFunction())


class TestUpsertIdempotent:

    def test_idem1_single_document_repeat_overwrites_not_raises(self, rag):
        doc = Document(id="case_X#whole0", text="visa 13.1 拒付", metadata={"confidence": 0.6})
        assert rag.add_document(doc, collection_name=COLLECTION_CASES) is True
        # 第二次同 id 写入：修复前抛"添加文档失败"，修复后覆盖
        doc2 = Document(id="case_X#whole0", text="visa 13.1 拒付（修订）", metadata={"confidence": 0.9})
        assert rag.add_document(doc2, collection_name=COLLECTION_CASES) is True

        col = rag._collections[COLLECTION_CASES]
        assert col.count() == 1
        got = col.get(ids=["case_X#whole0"])
        assert got["metadatas"][0]["confidence"] == 0.9  # upsert = 以最新为准

    def test_idem2_batch_repeat_count_stable(self, rag):
        docs = [
            Document(id=f"d{i}#whole0", text=f"case text {i}", metadata={"i": i})
            for i in range(5)
        ]
        assert rag.add_documents(docs, collection_name=COLLECTION_CASES) is True
        assert rag.add_documents(docs, collection_name=COLLECTION_CASES) is True  # 重跑
        assert rag._collections[COLLECTION_CASES].count() == 5

    def test_idem3_pipeline_double_ingest_no_duplication(self, rag):
        records = [
            {"id": "M001", "text": "US 商户 Visa 拒付 13.1，建议补充收单凭证申诉"},
            {"id": "M002", "text": "BR 商户 Pix 到账延迟咨询，已按 SLA 处理"},
        ]
        pipeline = IngestionPipeline(rag=rag)
        stats1 = pipeline.ingest(records, source_table="cases", collection_name=COLLECTION_CASES)
        # 第二遍完全相同的入库（修复前第二遍 store 抛异常 → skipped 全记录）
        stats2 = pipeline.ingest(records, source_table="cases", collection_name=COLLECTION_CASES)

        assert stats1["total_chunks"] == stats2["total_chunks"]
        assert stats2["skipped_records"] == 0
        assert rag._collections[COLLECTION_CASES].count() == stats1["total_chunks"]

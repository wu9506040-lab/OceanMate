"""跨语言检索真实验证（Day 14 P1-7）。

问题背景：docs 里之前只标了「跨语言 embedding 相似度 0.5253」这个离线指标，
但**没有验证真实 query 能不能召回**。这个文件用真实知识库（117 条拒付码，
正文是英文 reason code + 中文说明）做端到端召回验证。

依赖真实 Chroma 数据（src/backend/data/chroma），知识库为空时自动 skip。
"""

from __future__ import annotations

import pytest

from app.implementations.rag.chroma_rag import (
    COLLECTION_ERROR_CODES,
    ChromaRAGEngine,
)


@pytest.fixture(scope="module")
def rag():
    engine = ChromaRAGEngine()
    if engine.get_collection_stats().get(COLLECTION_ERROR_CODES, 0) < 50:
        pytest.skip("知识库未 seed（跑 scripts/seed_error_codes.py 后再测）")
    return engine


def _texts(docs) -> str:
    return " ".join(d.text or "" for d in docs).lower()


class TestChineseQueryRecallsEnglishKnowledge:
    """中文提问 → 英文 reason code 知识，必须能召回。"""

    def test_chargeback_cn_recalls_en(self, rag):
        """中文「拒付」→ top5 至少 1 条英文 chargeback 相关知识。"""
        docs = rag.retrieve("拒付", top_k=5, collection_name=COLLECTION_ERROR_CODES)
        assert docs, "中文「拒付」应召回结果"
        blob = _texts(docs)
        assert any(
            kw in blob for kw in ("chargeback", "dispute", "not received", "authorization")
        ), f"未召回英文 chargeback 相关知识: {[d.id for d in docs]}"

    @pytest.mark.parametrize(
        "query,expect_code",
        [
            ("持卡人未授权", "cb_demo_4837"),      # MC 4837 No Cardholder Authorization
            ("未收到货", "cb_demo_13_1"),          # Visa 13.1 Merchandise Not Received
            ("EMV 欺诈", "cb_demo_10_1"),          # Visa 10.1 EMV Liability Shift Counterfeit Fraud
        ],
    )
    def test_cn_semantic_query_hits_expected_english_code(self, rag, query, expect_code):
        """中文业务语义 → 命中对应英文 reason code（不靠关键词字面匹配）。"""
        docs = rag.retrieve(query, top_k=5, collection_name=COLLECTION_ERROR_CODES)
        ids = [d.id for d in docs]
        assert any(i.startswith(expect_code) for i in ids), (
            f"query='{query}' 未命中 {expect_code}，实际 top5: {ids}"
        )

    def test_english_query_recalls_chinese_annotated_knowledge(self, rag):
        """反向：英文 query 也能召回（知识库正文中英混排）。"""
        docs = rag.retrieve(
            "cardholder did not authorize this transaction",
            top_k=5,
            collection_name=COLLECTION_ERROR_CODES,
        )
        assert docs
        blob = _texts(docs)
        assert "authorization" in blob or "授权" in blob, (
            f"英文 query 召回结果无授权相关知识: {[d.id for d in docs]}"
        )

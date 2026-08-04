"""Embedder SOP 测试 — Day 8 占位实现。

覆盖 5 场景：
- SOP-EMB-001-A 确定性（相同输入 → 相同输出）
- SOP-EMB-001-B 不同输入 → 不同输出
- SOP-EMB-001-C L2 归一化
- SOP-EMB-001-D 中英文 token 区分
- SOP-EMB-001-E Chroma EmbeddingFunction 协议（__call__）

详见 docs/sop/SOP-RAG.md §5。
"""

import pytest

from app.implementations.embeddings import HashEmbedder, BaseEmbedder


class TestHashEmbedderBase:
    """SOP-EMB-001-A/B/C/D：HashEmbedder 性质。"""

    def test_deterministic_same_input_same_output(self):
        """确定性：相同输入 → 相同输出。"""
        ef = HashEmbedder(dimension=64)
        v1 = ef.embed_query("hello world")
        v2 = ef.embed_query("hello world")
        assert v1 == v2

    def test_different_text_different_vector(self):
        """不同输入 → 不同输出（区分度）。"""
        ef = HashEmbedder(dimension=64)
        v1 = ef.embed_query("apple")
        v2 = ef.embed_query("banana")
        # 不完全相等（hash 碰撞概率极低）
        assert v1 != v2

    def test_l2_normalized(self):
        """L2 归一化（模长 ≈ 1）。"""
        ef = HashEmbedder(dimension=32)
        vec = ef.embed_query("test text with some tokens 中文测试")
        norm = sum(x * x for x in vec) ** 0.5
        assert 0.99 <= norm <= 1.01

    def test_chinese_vs_english_distinct(self):
        """中文 vs 英文 → 不同向量。"""
        ef = HashEmbedder(dimension=32)
        v_zh = ef.embed_query("中文测试")
        v_en = ef.embed_query("english test")
        assert v_zh != v_en

    def test_embed_documents_batch(self):
        """embed_documents 批量调用。"""
        ef = HashEmbedder(dimension=64)
        texts = ["hello", "world", "中文测试"]
        vecs = ef.embed_documents(texts)
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == 64

    def test_dimension_property(self):
        """dimension 属性正确。"""
        ef = HashEmbedder(dimension=256)
        assert ef.dimension == 256

    def test_invalid_dimension_raises(self):
        """dimension <= 0 → ValueError。"""
        with pytest.raises(ValueError):
            HashEmbedder(dimension=0)
        with pytest.raises(ValueError):
            HashEmbedder(dimension=-1)


class TestHashEmbedderChromaCompat:
    """SOP-EMB-001-E：Chroma EmbeddingFunction 协议兼容。"""

    def test_call_interface(self):
        """__call__(list[str]) -> list[list[float]]（Chroma 协议）。"""
        ef = HashEmbedder(dimension=32)
        result = ef(["text1", "text2"])
        assert len(result) == 2
        assert all(len(v) == 32 for v in result)


class TestBaseEmbedderInterface:
    """BaseEmbedder 抽象接口验证。"""

    def test_hash_embedder_is_base_embedder(self):
        """HashEmbedder 是 BaseEmbedder 子类。"""
        ef = HashEmbedder()
        assert isinstance(ef, BaseEmbedder)

    def test_cannot_instantiate_base(self):
        """BaseEmbedder 不能直接实例化（abstract）。"""
        with pytest.raises(TypeError):
            BaseEmbedder()  # type: ignore[abstract]


class TestBackwardCompatAlias:
    """向后兼容：chroma_rag.HashEmbeddingFunction 仍可引用。"""

    def test_alias_resolves_to_hash_embedder(self):
        from app.implementations.rag.chroma_rag import HashEmbeddingFunction
        assert HashEmbeddingFunction is HashEmbedder
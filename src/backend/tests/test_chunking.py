"""Chunking SOP 测试 — Day 8 切片策略。

覆盖 4 策略 + 1 调度器（8 用例）：
- SOP-CHUNK-001-A WholeRecord 短文本 → 1 chunk
- SOP-CHUNK-001-B QAPair Q+A 一起切（关键设计）
- SOP-CHUNK-001-C MarkdownSection 按 heading 切
- SOP-CHUNK-001-D MarkdownSection 无 heading → 按段落
- SOP-CHUNK-001-E SlidingWindow 滑动切
- SOP-CHUNK-001-F SmartChunker 短文本 → WholeRecord
- SOP-CHUNK-001-G SmartChunker Q/A 文本 → QAPair
- SOP-CHUNK-001-H SmartChunker 超长无结构 → SlidingWindow

详见 docs/sop/SOP-RAG.md §5（Day 8 新增章节）。
"""

import pytest

from app.implementations.chunking import (
    WholeRecordChunker,
    QAPairChunker,
    MarkdownSectionChunker,
    SlidingWindowChunker,
    SmartChunker,
)
from app.interfaces.base_chunker import Chunk


# === 1. WholeRecordChunker ===

class TestWholeRecordChunker:
    """SOP-CHUNK-001-A：整条记录 = 1 chunk。"""

    def test_short_text_returns_one_chunk(self):
        """短文本 → 恰好 1 个 chunk。"""
        chunker = WholeRecordChunker()
        chunks = chunker.chunk(
            "BR 区域 Visa 渠道风控拦截规则。",
            doc_id="doc_001",
            base_metadata={"country": "BR"},
        )
        assert len(chunks) == 1
        c = chunks[0]
        assert c.chunk_id == "doc_001#w0"
        assert c.doc_id == "doc_001"
        assert c.chunk_index == 0
        assert c.text == "BR 区域 Visa 渠道风控拦截规则。"
        assert c.metadata["strategy"] == "whole_record"
        assert c.metadata["country"] == "BR"  # base_metadata 继承

    def test_empty_text_returns_empty_list(self):
        """空文本 / 纯空白 → []。"""
        chunker = WholeRecordChunker()
        assert chunker.chunk("", doc_id="x") == []
        assert chunker.chunk("   \n  ", doc_id="x") == []
        assert chunker.chunk("\n\n", doc_id="x") == []

    def test_none_raises(self):
        """None → ValueError。"""
        with pytest.raises(ValueError):
            WholeRecordChunker().chunk(None, doc_id="x")


# === 2. QAPairChunker ===

class TestQAPairChunker:
    """SOP-CHUNK-001-B：Q+A 一起切（关键设计）。"""

    def test_qa_pairs_split_with_qa_together(self):
        """多对 Q/A → 每对 1 个 chunk，Q+A 不拆开。"""
        text = """Q: BR Visa 拒付 ERR_X_001 怎么办？
A: 检查 Merchant Console 3DS 配置；联系商户开启 BR 区域 3DS。
Q: 通道维护怎么查？
A: 看 OP 通道监控 API 状态。"""

        chunker = QAPairChunker()
        chunks = chunker.chunk(text, doc_id="faq_001")

        assert len(chunks) == 2

        # 第 1 个 chunk 应含 Q + A 完整文本（不拆开）
        c0 = chunks[0]
        assert "Q:" in c0.text
        assert "BR Visa" in c0.text
        assert "A:" in c0.text
        assert "3DS" in c0.text
        assert c0.metadata["strategy"] == "qa_pair"
        assert c0.metadata["has_q"] is True
        assert c0.metadata["has_a"] is True

        # 第 2 个 chunk
        c1 = chunks[1]
        assert "Q:" in c1.text
        assert "通道维护" in c1.text
        assert "A:" in c1.text

    def test_q_without_a_returns_chunk_with_has_a_false(self):
        """Q 没 A → 仍成 chunk，has_a=False（由调用方决定 fallback 策略）。"""
        text = "Q: 这个商户问的什么？\n不是 Q/A 模式的注释行"
        chunks = QAPairChunker().chunk(text, doc_id="faq_002")
        assert len(chunks) == 1
        assert chunks[0].metadata["has_q"] is True
        assert chunks[0].metadata["has_a"] is False

    def test_chinese_qa_pattern(self):
        """中文 Q/A 模式识别。"""
        text = """问：BR Pix 通道是否支持？
答：BR 央行 2020 推出的 Pix 即时支付，已成 BR 主流。"""

        chunks = QAPairChunker().chunk(text, doc_id="faq_003")
        assert len(chunks) == 1
        assert "问：" in chunks[0].text
        assert "答：" in chunks[0].text
        assert "Pix" in chunks[0].text

    def test_no_qa_pattern_returns_empty(self):
        """没有 Q/A 模式 → []（调度器会 fallback 到其他策略）。"""
        text = "这是一段普通的描述文字，没有任何 Q/A 标记。"
        chunks = QAPairChunker().chunk(text, doc_id="x")
        assert chunks == []


# === 3. MarkdownSectionChunker ===

class TestMarkdownSectionChunker:
    """SOP-CHUNK-001-C/D：按 heading 或段落切。"""

    def test_split_by_heading(self):
        """按 markdown heading 切分。"""
        text = """# 引言

这是引言段落。

## 支付方式推荐

推荐 Visa + Pix 组合。

## 风险提示

BR 区域有 3DS 强制要求。"""

        chunks = MarkdownSectionChunker().chunk(text, doc_id="doc_002")
        titles = [c.metadata["section_title"] for c in chunks]
        assert "引言" in titles
        assert "支付方式推荐" in titles
        assert "风险提示" in titles
        assert len(chunks) == 3
        for c in chunks:
            assert c.metadata["strategy"] == "markdown_section"
            assert "char_range" in c.metadata

    def test_no_heading_split_by_paragraph(self):
        """无 heading 但 ≥2 段落 → 按段落切。"""
        text = """第一段内容比较长，讲述商户背景。

第二段讲述支付方式推荐：Visa + Pix。

第三段提示风险：3DS 强制要求。"""

        chunks = MarkdownSectionChunker().chunk(text, doc_id="doc_003")
        # 应该切成 3 段（每段一个 chunk）
        assert len(chunks) >= 2
        for c in chunks:
            assert c.metadata["strategy"] == "markdown_section"
            assert c.metadata["section_title"].startswith("para_")

    def test_single_paragraph_returns_one_chunk(self):
        """单段落无 heading → 1 个 chunk。"""
        text = "这是一段普通文字，没有 heading 也没有段落分隔。"
        chunks = MarkdownSectionChunker().chunk(text, doc_id="x")
        assert len(chunks) == 1


# === 4. SlidingWindowChunker ===

class TestSlidingWindowChunker:
    """SOP-CHUNK-001-E：滑动窗口切片。"""

    def test_sliding_window_basic(self):
        """chunk_size=100, overlap=10 → 切片数 = ceil((N - 10) / 90)。"""
        text = "a" * 250
        chunker = SlidingWindowChunker(chunk_size=100, overlap=10)
        chunks = chunker.chunk(text, doc_id="long_001")

        # 250 chars, step=90, 切片位置：[0,100), [90,190), [180,250]
        assert len(chunks) == 3
        assert chunks[0].text == "a" * 100
        assert chunks[1].text == "a" * 100  # [90,190)
        assert chunks[2].text == "a" * 70   # [180,250) → 70 chars
        for c in chunks:
            assert c.metadata["strategy"] == "sliding_window"
            assert "char_range" in c.metadata

    def test_invalid_overlap_raises(self):
        """overlap >= chunk_size → ValueError。"""
        with pytest.raises(ValueError):
            SlidingWindowChunker(chunk_size=100, overlap=100)
        with pytest.raises(ValueError):
            SlidingWindowChunker(chunk_size=100, overlap=-1)


# === 5. SmartChunker（调度器）===

class TestSmartChunker:
    """SOP-CHUNK-001-F/G/H：智能调度。"""

    def test_short_text_dispatches_to_whole_record(self):
        """短文本（< 512 chars）→ WholeRecord。"""
        text = "BR 区域 Visa 拒付规则。" * 5  # ~115 chars
        chunks = SmartChunker().chunk(text, doc_id="doc_a")
        assert len(chunks) == 1
        assert chunks[0].metadata["strategy"] == "whole_record"

    def test_qa_text_dispatches_to_qa_pair(self):
        """长文本含 Q/A → QAPair（不拆开）。"""
        text = """Q: BR Visa 拒付 ERR_X_001 怎么办？
A: 检查 Merchant Console 3DS 配置；联系商户开启 BR 区域 3DS。
Q: 通道维护怎么查？
A: 看 OP 通道监控 API 状态。
Q: Pix 通道何时支持？
A: BR 央行 2020 推出的 Pix 即时支付已成 BR 主流跨境收款必须支持。
Q: Boleto 现金支付比例？
A: BR 无银行账户人群约 30%，Boleto 是 BR 现金支付补充。"""

        # 重复 2 次让长度 > 512（约 660 chars）
        text = text + "\n" + text + "\n" + text
        chunks = SmartChunker().chunk(text, doc_id="faq_long")

        # 应该切成多对 Q/A（每对独立 chunk，至少 8 对）
        assert len(chunks) >= 8
        for c in chunks:
            assert c.metadata["strategy"] == "qa_pair"

    def test_paragraph_text_dispatches_to_markdown_section(self):
        """长文本含多段落（无 heading）→ MarkdownSection。"""
        para1 = "BR 区域 Visa 渠道风控拦截规则比较严格。" * 10
        para2 = "推荐商户开启 BR 区域 3DS 配置降低拒付率。" * 10
        para3 = "如仍拒付，准备 CB 申诉材料走 RDR 流程。" * 10
        text = f"{para1}\n\n{para2}\n\n{para3}"

        chunks = SmartChunker().chunk(text, doc_id="doc_b")
        assert len(chunks) == 3
        for c in chunks:
            assert c.metadata["strategy"] == "markdown_section"

    def test_long_single_paragraph_falls_back_to_sliding_window(self):
        """超长单段（无 heading/QA/段落）→ SlidingWindow。"""
        # 1500 chars 连续，无段落分隔
        text = "BR Visa 拒付 ERR_X_001 错误码处理建议：请商户检查 3DS 配置。" * 30
        assert "\n\n" not in text  # 确认无段落

        chunks = SmartChunker().chunk(text, doc_id="doc_long")
        assert len(chunks) >= 2
        for c in chunks:
            assert c.metadata["strategy"] == "sliding_window"
            assert len(c.text) <= 1024  # max_chunk_size 不超

    def test_empty_text_returns_empty(self):
        """空文本 → []。"""
        assert SmartChunker().chunk("", doc_id="x") == []
        assert SmartChunker().chunk("   ", doc_id="x") == []
"""Data Cleaning SOP 测试 — Day 8。

覆盖 6 场景：
- SOP-CLEAN-001-A 控制字符去除
- SOP-CLEAN-001-B Unicode NFKC（全角→半角）
- SOP-CLEAN-001-C 多空格 / 多换行折叠
- SOP-CLEAN-001-D BOM 去除
- SOP-CLEAN-001-E 空 / 空白输入
- SOP-CLEAN-001-F AggressiveCleaner 去 emoji

详见 docs/sop/SOP-RAG.md §7。
"""

import pytest

from app.implementations.data_cleaning import (
    DefaultDataCleaner,
    AggressiveCleaner,
    BaseDataCleaner,
    CleanedText,
)


class TestDefaultCleanerControlChars:
    """SOP-CLEAN-001-A：控制字符去除。"""

    def test_removes_null_and_other_control_chars(self):
        """去除 \\x00、\\x01 等控制字符。"""
        cleaner = DefaultDataCleaner()
        text = "hello\x00world\x01\x02"
        result = cleaner.clean(text)
        assert "\x00" not in result.text
        assert "helloworld" in result.text

    def test_preserves_newline_and_tab(self):
        """保留 \\n 和 \\t（用于段落分隔）。"""
        cleaner = DefaultDataCleaner()
        text = "line1\nline2\twith tab"
        result = cleaner.clean(text)
        assert "\n" in result.text
        assert "\t" in result.text


class TestDefaultCleanerUnicode:
    """SOP-CLEAN-001-B：Unicode NFKC 标准化。"""

    def test_fullwidth_to_halfwidth(self):
        """全角字符 → 半角字符。"""
        cleaner = DefaultDataCleaner()
        # 全角数字 ０１２３ → 半角 0123
        result = cleaner.clean("金额：１００元")
        assert "100" in result.text
        assert "元" in result.text

    def test_unicode_normalization_marked_in_metadata(self):
        """metadata 标记 normalized_unicode。"""
        cleaner = DefaultDataCleaner()
        result = cleaner.clean("ＡＢＣ")  # 全角 ABC
        assert result.metadata.get("normalized_unicode") is True


class TestDefaultCleanerWhitespace:
    """SOP-CLEAN-001-C：空白折叠。"""

    def test_collapses_multiple_spaces(self):
        """多个连续空格 → 单个空格。"""
        cleaner = DefaultDataCleaner()
        result = cleaner.clean("hello     world")
        assert " " in result.text
        assert "    " not in result.text

    def test_collapses_multiple_newlines(self):
        """≥3 个连续换行 → 2 个（即保留段落分隔）。"""
        cleaner = DefaultDataCleaner()
        result = cleaner.clean("para1\n\n\n\n\npara2")
        assert result.text.count("\n") <= 2
        assert "para1" in result.text
        assert "para2" in result.text


class TestDefaultCleanerBOM:
    """SOP-CLEAN-001-D：BOM 去除。"""

    def test_removes_bom(self):
        """开头 BOM \\ufeff 被去除。"""
        cleaner = DefaultDataCleaner()
        text = "\ufeffhello world"
        result = cleaner.clean(text)
        assert not result.text.startswith("\ufeff")
        assert "hello world" in result.text
        assert result.metadata.get("removed_bom") is True


class TestDefaultCleanerEmpty:
    """SOP-CLEAN-001-E：空 / 空白输入。"""

    def test_empty_string(self):
        cleaner = DefaultDataCleaner()
        result = cleaner.clean("")
        assert result.text == ""
        assert result.metadata.get("skipped") is True

    def test_whitespace_only(self):
        cleaner = DefaultDataCleaner()
        result = cleaner.clean("   \n\t  ")
        assert result.text == ""
        assert result.metadata.get("skipped") is True

    def test_none_input(self):
        cleaner = DefaultDataCleaner()
        result = cleaner.clean(None)  # type: ignore[arg-type]
        assert result.text == ""


class TestAggressiveCleaner:
    """SOP-CLEAN-001-F：AggressiveCleaner 去 emoji。"""

    def test_removes_emoji(self):
        """emoji 被移除。"""
        cleaner = AggressiveCleaner()
        text = "重要提示 📌✅ 这是商户必读文档"
        result = cleaner.clean(text)
        assert "📌" not in result.text
        assert "✅" not in result.text
        assert "重要提示" in result.text
        assert "商户必读文档" in result.text
        assert result.metadata.get("removed_emoji") is True

    def test_removes_html_tags(self):
        """HTML 标签被移除。"""
        cleaner = AggressiveCleaner()
        text = "<p>重要内容 <b>加粗</b></p>"
        result = cleaner.clean(text)
        assert "<p>" not in result.text
        assert "<b>" not in result.text
        assert "重要内容" in result.text
        assert "加粗" in result.text

    def test_default_cleaner_keeps_emoji(self):
        """DefaultDataCleaner 不去 emoji（默认保留业务表情）。"""
        cleaner = DefaultDataCleaner()
        text = "📌 提示"
        result = cleaner.clean(text)
        assert "📌" in result.text


class TestCleanerInterface:
    """接口验证。"""

    def test_default_is_base_cleaner(self):
        assert isinstance(DefaultDataCleaner(), BaseDataCleaner)

    def test_aggressive_is_base_cleaner(self):
        assert isinstance(AggressiveCleaner(), BaseDataCleaner)

    def test_cannot_instantiate_base(self):
        with pytest.raises(TypeError):
            BaseDataCleaner()  # type: ignore[abstract]

    def test_returns_cleaned_text_dataclass(self):
        result = DefaultDataCleaner().clean("test")
        assert isinstance(result, CleanedText)
        assert hasattr(result, "text")
        assert hasattr(result, "metadata")
"""DefaultDataCleaner - 通用清洗（去噪 + Unicode NFKC + 多语言保留）。

清洗规则：
1. 去控制字符：\\x00-\\x1f、\\x7f（保留 \\n / \\t 用于段落分隔）
2. Unicode NFKC 标准化（全角 → 半角、繁体 → 简体可选）
3. 折叠连续空白（多个空格 / 换行压缩为单空格）
4. 去除 BOM（\\ufeff）
5. strip 前后空白
6. 保留中 / 英 / 数字 / 常用标点 / 多语言字符

不动 emoji（业务文本中 emoji 可能是有效信息，如"📌"）。

详见 docs/sop/SOP-RAG.md §7。
"""

import re
import unicodedata

from app.interfaces.base_data_cleaner import BaseDataCleaner, CleanedText


# 控制字符（保留 \n=0x0a 和 \t=0x09）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# BOM
_BOM = "\ufeff"

# 连续空白（≥2 个空格或 ≥3 个换行 → 单个）
_MULTI_SPACE = re.compile(r"[^\S\n]{2,}")  # 多个非换行空白
_MULTI_NEWLINE = re.compile(r"\n{3,}")  # 多个换行


class DefaultDataCleaner(BaseDataCleaner):
    """通用清洗实现。"""

    def clean(self, text: str) -> CleanedText:
        if text is None:
            return CleanedText(text="", metadata={"skipped": True, "reason": "None input"})

        if not text or not text.strip():
            return CleanedText(text="", metadata={"skipped": True, "reason": "empty"})

        original_len = len(text)
        meta = {"original_length": original_len}

        # 1. 去 BOM
        if text.startswith(_BOM):
            text = text[1:]
            meta["removed_bom"] = True

        # 2. 去控制字符（保留 \n \t）
        cleaned = _CONTROL_CHARS.sub("", text)
        if len(cleaned) != len(text):
            meta["dropped_control_chars"] = len(text) - len(cleaned)
        text = cleaned

        # 3. Unicode NFKC 标准化（全角→半角、兼容字符）
        normalized = unicodedata.normalize("NFKC", text)
        if normalized != text:
            meta["normalized_unicode"] = True
        text = normalized

        # 4. 折叠连续空白
        text = _MULTI_SPACE.sub(" ", text)
        text = _MULTI_NEWLINE.sub("\n\n", text)

        # 5. strip
        text = text.strip()

        meta["cleaned_length"] = len(text)
        return CleanedText(text=text, metadata=meta)


class AggressiveCleaner(BaseDataCleaner):
    """激进清洗：在 DefaultDataCleaner 基础上再额外去 emoji / HTML / URL。"""

    # emoji unicode range (基础 + 扩展)
    _EMOJI = re.compile(
        r"["
        r"\U0001F600-\U0001F64F"   # 表情
        r"\U0001F300-\U0001F5FF"   # 符号 & 象形文字
        r"\U0001F680-\U0001F6FF"   # 交通 & 地图
        r"\U0001F1E0-\U0001F1FF"   # 国旗
        r"\u2600-\u27BF"           # Misc Symbols + Dingbats（含 ✅ ❌ ⭕）
        r"]",
        flags=re.UNICODE,
    )

    _HTML_TAG = re.compile(r"<[^>]+>")
    _URL = re.compile(r"https?://[^\s]+")

    def __init__(self):
        self._base = DefaultDataCleaner()

    def clean(self, text: str) -> CleanedText:
        result = self._base.clean(text)
        text = result.text
        meta = dict(result.metadata)

        # 去 emoji
        new_text = self._EMOJI.sub("", text)
        if new_text != text:
            meta["removed_emoji"] = True
        text = new_text

        # 去 HTML 标签
        new_text = self._HTML_TAG.sub("", text)
        if new_text != text:
            meta["removed_html"] = True
        text = new_text

        # 去 URL（可选，可能去掉业务相关链接；先保留）
        # new_text = self._URL.sub("[URL]", text)
        # if new_text != text:
        #     meta["removed_urls"] = True
        # text = new_text

        return CleanedText(text=text, metadata=meta)
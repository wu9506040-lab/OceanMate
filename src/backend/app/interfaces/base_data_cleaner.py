"""BaseDataCleaner - 数据清洗抽象接口。

清洗阶段在 chunk 之前执行，目的是把脏文本（如 PDF 复制粘贴的不可见字符、
全角字符、emoji、HTML 标签残留）规整成 embedding 模型友好的纯文本。

3 类清洗（按强度递增）：
- DefaultDataCleaner   通用：去控制字符 + Unicode NFKC + 折叠空白 + 保留多语言
- AggressiveCleaner    激进：再额外去 emoji / 去 HTML / 去 URL
- MinimalCleaner       极简：仅 strip + 折叠空白（保留原貌，便于 debug）

详见 docs/sop/SOP-RAG.md §7（Day 8 新增章节）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CleanedText:
    """清洗结果。

    字段：
    - text      清洗后文本
    - metadata  清洗动作记录（dropped_chars / normalized / removed_emoji / 等）
    """
    text: str
    metadata: dict = field(default_factory=dict)


class BaseDataCleaner(ABC):
    """数据清洗基类。"""

    @abstractmethod
    def clean(self, text: str) -> CleanedText:
        """清洗单条文本。

        Args:
            text: 原始文本

        Returns:
            CleanedText（text + 动作 metadata）

        Note:
            空字符串 / 仅空白 → 返回 CleanedText(text="", metadata={"skipped": True})
        """
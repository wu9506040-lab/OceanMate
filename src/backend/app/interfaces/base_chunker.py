"""BaseChunker - 切片策略抽象接口。

Chunking 是 RAG 入库前的核心步骤，决定向量化的语义单元。
原则：每条记录的切片策略由数据形态决定，不强制用一种切法。

4 种内置策略：
- WholeRecordChunker         整条记录 = 1 chunk（结构化短文本）
- QAPairChunker              Q+A 配对切（FAQ / KEA 沉淀）
- MarkdownSectionChunker     按 heading / 段落切（策论 / 政策 / 妙记）
- SlidingWindowChunker       滑动窗口（超长兜底）

调度器 SmartChunker 自动按数据特征选策略。
详见 docs/sop/SOP-RAG.md（Day 8 新增章节）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    """切片数据单元（in-memory 表达，RAG 入库前存在 Document 内）。

    字段：
    - chunk_id    文档内唯一 ID（{doc_id}#{strategy}{index}）
    - doc_id      来源文档 ID
    - text        切片文本（已 strip，未清洗）
    - chunk_index 文档内切片序号（0-based）
    - metadata    切片元数据（继承 base + strategy / section_title / char_range 等）
    """
    chunk_id: str
    doc_id: str
    text: str
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
        }


class BaseChunker(ABC):
    """切片策略基类。

    评审意义：未来加 SentenceChunker / CodeChunker 等只需新加实现，调度器自动识别。
    """

    @abstractmethod
    def chunk(self, text: str, doc_id: str, base_metadata: Optional[dict] = None) -> list[Chunk]:
        """把单条记录切成 1+ 个 Chunk。

        Args:
            text: 记录文本
            doc_id: 文档 ID（用于生成 chunk_id）
            base_metadata: 继承的元数据（如 country / channel）

        Returns:
            Chunk 列表（至少 1 个；空文本 → []）

        Raises:
            ValueError: text 为 None 或非字符串
        """
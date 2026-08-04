"""SmartChunker - 切片策略调度器（自动按数据特征选策略）。

调度优先级：
1. 空文本 → []
2. text 长度 ≤ short_threshold (默认 512) → WholeRecord
3. 含 Q/A 模式 → QAPair
4. 含 markdown heading 或 ≥2 段落 → MarkdownSection
5. 兜底 → SlidingWindow

任一策略产出后，再过 _enforce_max 检查超长 chunk（> max_chunk_size），
若有则对该 chunk 用 SlidingWindow 重切（保证入库不超过 embedding 模型 token 上限）。
"""

import re
from typing import Optional

from app.interfaces.base_chunker import BaseChunker, Chunk
from app.implementations.chunking.whole_record_chunker import WholeRecordChunker
from app.implementations.chunking.qa_pair_chunker import QAPairChunker
from app.implementations.chunking.markdown_section_chunker import MarkdownSectionChunker
from app.implementations.chunking.sliding_window_chunker import SlidingWindowChunker


class SmartChunker(BaseChunker):
    """智能调度器（默认推荐）。

    Args:
        max_chunk_size: 任一 chunk 超过此长度时强制用 SlidingWindow 重切
        short_threshold: 短文本阈值（≤此长度走 WholeRecord）
        chunk_size / overlap: 透传给 SlidingWindow
    """

    def __init__(
        self,
        max_chunk_size: int = 1024,
        short_threshold: int = 512,
        chunk_size: int = 1024,
        overlap: int = 64,
    ):
        self.max_chunk_size = max_chunk_size
        self.short_threshold = short_threshold

        self.whole_chunker = WholeRecordChunker()
        self.qa_chunker = QAPairChunker()
        self.markdown_chunker = MarkdownSectionChunker()
        self.window_chunker = SlidingWindowChunker(
            chunk_size=chunk_size,
            overlap=overlap,
        )

    def chunk(self, text: str, doc_id: str, base_metadata: Optional[dict] = None) -> list[Chunk]:
        if text is None or not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        text_clean = text.strip()
        if not text_clean:
            return []

        # 1. 短文本 → WholeRecord
        if len(text_clean) <= self.short_threshold:
            return self.whole_chunker.chunk(text_clean, doc_id, base_metadata)

        # 2. Q/A 模式 → QAPair
        if self._has_qa_pattern(text_clean):
            chunks = self.qa_chunker.chunk(text_clean, doc_id, base_metadata)
            if chunks:
                return self._enforce_max(chunks, base_metadata)

        # 3. Markdown / 段落 → MarkdownSection
        if self._has_markdown_or_paragraphs(text_clean):
            chunks = self.markdown_chunker.chunk(text_clean, doc_id, base_metadata)
            if chunks:
                return self._enforce_max(chunks, base_metadata)

        # 4. 兜底 → SlidingWindow
        return self.window_chunker.chunk(text_clean, doc_id, base_metadata)

    def _has_qa_pattern(self, text: str) -> bool:
        """检测 Q: / 问: / Question: 起始行。"""
        return bool(re.search(r"^\s*(Q[:：]|问[:：]|Question[:：]|问题[:：])", text, re.MULTILINE))

    def _has_markdown_or_paragraphs(self, text: str) -> bool:
        """检测 markdown heading 或 ≥2 段落（空行分隔）。"""
        if re.search(r"^#{1,6}\s+\S", text, re.MULTILINE):
            return True
        paragraphs = [p for p in re.split(r"\n\s*\n+", text) if p.strip()]
        return len(paragraphs) >= 2

    def _enforce_max(self, chunks: list[Chunk], base_metadata: Optional[dict]) -> list[Chunk]:
        """超长 chunk → SlidingWindow 重切；保留 chunk_id 命名空间。"""
        result = []
        for c in chunks:
            if len(c.text) > self.max_chunk_size:
                sub = self.window_chunker.chunk(
                    c.text,
                    doc_id=f"{c.doc_id}#sub{c.chunk_index}",
                    base_metadata=c.metadata,
                )
                result.extend(sub)
            else:
                result.append(c)
        return result
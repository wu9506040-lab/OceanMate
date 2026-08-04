"""SlidingWindowChunker - 滑动窗口切片（超长文本兜底）。

仅当其他策略产出超长 chunk 时调用（如无 heading 的连续长文本）。
"""

from typing import Optional

from app.interfaces.base_chunker import BaseChunker, Chunk


class SlidingWindowChunker(BaseChunker):
    """按 chunk_size 切片，相邻 chunk 重叠 overlap 字符。

    默认 chunk_size=1024, overlap=64。
    metadata 含 strategy + char_range。
    """

    def __init__(self, chunk_size: int = 1024, overlap: int = 64):
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须 > 0")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError(f"overlap ({overlap}) 必须 >= 0 且 < chunk_size ({chunk_size})")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, doc_id: str, base_metadata: Optional[dict] = None) -> list[Chunk]:
        if text is None or not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        if not text.strip():
            return []

        text_clean = text.strip()
        step = self.chunk_size - self.overlap

        chunks = []
        i = 0
        start = 0
        while start < len(text_clean):
            end = min(start + self.chunk_size, len(text_clean))
            chunk_text = text_clean[start:end]

            meta = dict(base_metadata or {})
            meta["strategy"] = "sliding_window"
            meta["char_range"] = (start, end)

            chunks.append(Chunk(
                chunk_id=f"{doc_id}#w{i}",
                doc_id=doc_id,
                text=chunk_text,
                chunk_index=i,
                metadata=meta,
            ))

            if end >= len(text_clean):
                break
            start += step
            i += 1

        return chunks
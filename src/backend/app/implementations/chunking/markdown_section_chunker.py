"""MarkdownSectionChunker - 按 markdown heading 或段落切（策论 / 政策 / 妙记转写）。

策略：
1. 优先按 markdown # / ## / ### heading 切
2. 没有 heading 但 ≥2 段落（\\n\\n+ 分隔）→ 按段落切
3. 都没有 → 返回单 chunk（WholeRecord 接管）
"""

import re
from typing import Optional

from app.interfaces.base_chunker import BaseChunker, Chunk


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")


class MarkdownSectionChunker(BaseChunker):
    """按 markdown heading 或段落切。

    返回 chunk 的 metadata 含：
    - strategy         "markdown_section"
    - section_title    章节标题（如 "引言" / "支付方式推荐"）
    - char_range       (start, end) 在原文中的位置
    """

    def chunk(self, text: str, doc_id: str, base_metadata: Optional[dict] = None) -> list[Chunk]:
        if text is None or not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        if not text.strip():
            return []

        text_clean = text.strip()

        # 优先 heading
        sections = self._split_by_heading(text_clean)
        if len(sections) <= 1:
            # 没 heading → 按段落
            sections = self._split_by_paragraph(text_clean)

        if not sections:
            return []

        chunks = []
        cursor = 0
        for i, (title, body) in enumerate(sections):
            # 找 body 在原文的位置（用于 char_range）
            start = text_clean.find(body, cursor) if body else cursor
            end = start + len(body) if body else cursor
            cursor = end

            meta = dict(base_metadata or {})
            meta["strategy"] = "markdown_section"
            meta["section_title"] = title
            meta["char_range"] = (start, end)

            chunks.append(Chunk(
                chunk_id=f"{doc_id}#s{i}",
                doc_id=doc_id,
                text=body,
                chunk_index=i,
                metadata=meta,
            ))
        return chunks

    @staticmethod
    def _split_by_heading(text: str) -> list[tuple[str, str]]:
        """按 markdown heading 切，返回 [(title, body), ...]。

        第一段如果以 heading 开头，title=heading, body=到下一个 heading。
        """
        matches = list(_HEADING_PATTERN.finditer(text))
        if not matches:
            return [("", text)]

        sections = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            title = m.group(2).strip()
            sections.append((title, section_text))
        return sections

    @staticmethod
    def _split_by_paragraph(text: str) -> list[tuple[str, str]]:
        """按段落（连续空行）切。

        单段落也返回 1 个 chunk（保持输入永远产出至少 1 个 chunk）。
        """
        paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
        if not paragraphs:
            return []
        return [(f"para_{i}", p) for i, p in enumerate(paragraphs)]
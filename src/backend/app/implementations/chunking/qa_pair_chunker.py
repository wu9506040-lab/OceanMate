"""QAPairChunker - Q+A 配对切片（FAQ / 商户问答 / KEA 沉淀案例）。

关键设计：Q 和 A 一起切，不拆开。
原因：拆开会破坏语义（Q 向量和 A 向量不同，召回时容易答非所问）。
"""

import re
from typing import Optional

from app.interfaces.base_chunker import BaseChunker, Chunk


# Q/A 起始行（中英文）
_Q_START = re.compile(r"^\s*(Q[:：]|问[:：]|Question[:：]|问题[:：])\s*")
_A_START = re.compile(r"^\s*(A[:：]|答[:：]|Answer[:：]|答案[:：]|解答[:：])\s*")


class QAPairChunker(BaseChunker):
    """把多对 Q/A 切成多个 Chunk，每对 Q+A = 1 个 Chunk。

    支持的中英文模式：
    - Q: / A:（英文）
    - 问：/ 答：（中文）
    - Question: / Answer:
    - 问题：/ 答案：

    无 A 的 Q 单独成 chunk（has_a=False）。
    """

    def chunk(self, text: str, doc_id: str, base_metadata: Optional[dict] = None) -> list[Chunk]:
        if text is None or not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        if not text.strip():
            return []

        pairs = self._split_qa_pairs(text)
        if not pairs:
            return []  # 没识别到 Q/A → 调用方 fallback

        chunks = []
        for i, (q_text, a_text) in enumerate(pairs):
            qa_text = q_text.strip()
            if a_text.strip():
                qa_text = qa_text + "\n" + a_text.strip()
            meta = dict(base_metadata or {})
            meta["strategy"] = "qa_pair"
            meta["has_q"] = bool(q_text.strip())
            meta["has_a"] = bool(a_text.strip())
            chunks.append(Chunk(
                chunk_id=f"{doc_id}#qa{i}",
                doc_id=doc_id,
                text=qa_text,
                chunk_index=i,
                metadata=meta,
            ))
        return chunks

    @staticmethod
    def _split_qa_pairs(text: str) -> list[tuple[str, str]]:
        """解析 Q...A 配对。

        返回 [(q_text, a_text), ...]。
        实现：按行扫描，Q 起始行开始累积，遇到下一个 Q 时 flush。
        """
        lines = text.split("\n")
        pairs = []
        current_q_lines: list[str] = []
        current_a_lines: list[str] = []
        state = "idle"  # idle | in_q | in_a

        for line in lines:
            if _Q_START.match(line):
                # flush previous pair
                if state != "idle":
                    q_text = "\n".join(current_q_lines)
                    a_text = "\n".join(current_a_lines)
                    pairs.append((q_text, a_text))
                current_q_lines = [line]
                current_a_lines = []
                state = "in_q"
            elif _A_START.match(line) and state == "in_q":
                current_a_lines.append(line)
                state = "in_a"
            elif state == "in_a":
                current_a_lines.append(line)
            elif state == "in_q":
                current_q_lines.append(line)
            # idle 状态：跳过非 Q/A 起始行

        # flush last
        if state != "idle":
            q_text = "\n".join(current_q_lines)
            a_text = "\n".join(current_a_lines)
            pairs.append((q_text, a_text))

        return pairs
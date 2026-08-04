"""WholeRecordChunker - 整条记录 = 1 个 Chunk（默认策略）。"""

from app.interfaces.base_chunker import BaseChunker, Chunk


class WholeRecordChunker(BaseChunker):
    """整条记录 = 1 个 Chunk。

    适用：
    - 错误码知识（error_codes）：1 行 = 1 规则
    - 支付方式（payment_methods）：1 行 = 1 支付方式
    - 案例简述（cases short description）：1 案例 = 1 chunk

    触发条件（SmartChunker 调度）：
    - text 长度 < short_threshold（默认 512 chars）
    - 或兜底策略（其他切法都失败时）
    """

    def chunk(self, text: str, doc_id: str, base_metadata=None) -> list[Chunk]:
        if text is None or not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        if not text.strip():
            return []

        text_clean = text.strip()
        meta = dict(base_metadata or {})
        meta["strategy"] = "whole_record"
        return [
            Chunk(
                chunk_id=f"{doc_id}#w0",
                doc_id=doc_id,
                text=text_clean,
                chunk_index=0,
                metadata=meta,
            )
        ]
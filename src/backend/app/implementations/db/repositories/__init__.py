"""6 个 Repository 实现 - 通用 CRUD + 各实体定制方法。

设计：
- 每个 Repository 遵循 BaseRepository Protocol（get_by_id/create/update/list）
- 直接 sqlite3 + 参数化 SQL（防注入）
- 异常包装为 RepositoryError / NotFoundError / DuplicateKeyError / ValidationError
- `from __future__ import annotations` 防止方法名 `list` 覆盖类作用域内的 `list[Type]`
  注解（Python 3.11 已知坑：类体内 def list() 会让后续 list[X] 注解解析成函数对象）

详见 SOP-REPO-001（4 个逆向场景：主键冲突/字段超长/NULL 违反/无结果）。
"""

from __future__ import annotations

from typing import Optional, TypeVar, Generic, get_type_hints
import sqlite3

from app.interfaces.base_database import BaseDatabase
from app.interfaces.base_repository import (
    BaseRepository, RepositoryError, NotFoundError, DuplicateKeyError, ValidationError
)
from app.models import (
    Merchant, ErrorCode, Case, Ticket,
    Conversation, Message, Handoff,
)


T = TypeVar("T")


# === 通用工具函数 ===

def _model_to_dict(model) -> dict:
    """Pydantic Model → dict（用于 SQL 参数）。"""
    return model.model_dump(exclude_none=False)


def _row_to_model(row: dict, model_class) -> object:
    """SQLite row → Pydantic Model。"""
    # 过滤掉 Model 中不存在的字段（如 embedding_meta 表的额外列）
    valid_fields = set(model_class.model_fields.keys())
    filtered = {k: v for k, v in row.items() if k in valid_fields}
    return model_class.model_validate(filtered)


# === 1. MerchantRepository ===

class MerchantRepository:
    """商户仓库。

    实现 BaseRepository[Merchant] Protocol（duck typing，无需继承）。
    """

    def __init__(self, db: BaseDatabase):
        self.db = db

    def get_by_id(self, merchant_id: str) -> Optional[Merchant]:
        rows = self.db.query(
            "SELECT * FROM merchants WHERE id = :id",
            {"id": merchant_id},
        )
        return _row_to_model(rows[0], Merchant) if rows else None

    def create(self, merchant: Merchant) -> bool:
        try:
            return self.db.execute(
                """INSERT INTO merchants
                (id, country, industry, avg_amount, tier, feishu_record_id)
                VALUES (:id, :country, :industry, :avg_amount, :tier, :feishu_record_id)""",
                _model_to_dict(merchant),
            )
        except RuntimeError as e:
            if "UNIQUE constraint failed" in str(e):
                raise DuplicateKeyError(f"商户 ID '{merchant.id}' 已存在") from e
            if "NOT NULL constraint failed" in str(e):
                raise ValidationError(f"商户必填字段缺失: {e}") from e
            raise RepositoryError(str(e)) from e

    def update(self, merchant_id: str, merchant: Merchant) -> bool:
        try:
            return self.db.execute(
                """UPDATE merchants SET
                    country = :country,
                    industry = :industry,
                    avg_amount = :avg_amount,
                    tier = :tier,
                    feishu_record_id = :feishu_record_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id""",
                {**_model_to_dict(merchant), "id": merchant_id},
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def list(self, filters: Optional[dict] = None, limit: int = 100) -> list[Merchant]:
        sql = "SELECT * FROM merchants"
        params = {"limit": limit}
        if filters:
            conditions = []
            for key, value in filters.items():
                if key in ("country", "industry", "tier"):
                    conditions.append(f"{key} = :{key}")
                    params[key] = value
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " LIMIT :limit"
        rows = self.db.query(sql, params)
        return [_row_to_model(r, Merchant) for r in rows]


# === 2. ErrorCodeRepository ===

class ErrorCodeRepository:
    """错误码知识库仓库（飞书同步源）。"""

    def __init__(self, db: BaseDatabase):
        self.db = db

    def get_by_id(self, error_id: str) -> Optional[ErrorCode]:
        rows = self.db.query("SELECT * FROM error_codes WHERE id = :id", {"id": error_id})
        return _row_to_model(rows[0], ErrorCode) if rows else None

    def create(self, error_code: ErrorCode) -> bool:
        try:
            return self.db.execute(
                """INSERT INTO error_codes
                (id, code, country, channel, root_cause, solution, feishu_record_id)
                VALUES (:id, :code, :country, :channel, :root_cause, :solution, :feishu_record_id)""",
                _model_to_dict(error_code),
            )
        except RuntimeError as e:
            if "UNIQUE constraint failed" in str(e):
                raise DuplicateKeyError(
                    f"错误码 ({error_code.code}, {error_code.country}, {error_code.channel}) 已存在"
                ) from e
            raise RepositoryError(str(e)) from e

    def update(self, error_id: str, error_code: ErrorCode) -> bool:
        try:
            return self.db.execute(
                """UPDATE error_codes SET
                    code = :code, country = :country, channel = :channel,
                    root_cause = :root_cause, solution = :solution,
                    feishu_record_id = :feishu_record_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id""",
                {**_model_to_dict(error_code), "id": error_id},
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def list(self, filters: Optional[dict] = None, limit: int = 100) -> list[ErrorCode]:
        sql = "SELECT * FROM error_codes"
        params = {"limit": limit}
        if filters:
            conditions = []
            for key in ("code", "country", "channel"):
                if key in filters:
                    conditions.append(f"{key} = :{key}")
                    params[key] = filters[key]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " LIMIT :limit"
        rows = self.db.query(sql, params)
        return [_row_to_model(r, ErrorCode) for r in rows]

    def lookup_by_code(self, code: str, country: Optional[str] = None) -> Optional[ErrorCode]:
        """按 code 查（支持模糊匹配 country/channel）。"""
        sql = "SELECT * FROM error_codes WHERE code = :code"
        params = {"code": code}
        if country:
            sql += " AND (country = :c OR country IS NULL)"
            params["c"] = country
        sql += " LIMIT 1"
        rows = self.db.query(sql, params)
        return _row_to_model(rows[0], ErrorCode) if rows else None

    def search(self, keyword: str, limit: int = 20) -> list[ErrorCode]:
        """按关键字搜索（code/root_cause/solution）。"""
        sql = """SELECT * FROM error_codes
                 WHERE code LIKE :kw OR root_cause LIKE :kw OR solution LIKE :kw
                 LIMIT :limit"""
        rows = self.db.query(sql, {"kw": f"%{keyword}%", "limit": limit})
        return [_row_to_model(r, ErrorCode) for r in rows]


# === 3. CaseRepository ===

class CaseRepository:
    """案例仓库（飞书同步源）。"""

    def __init__(self, db: BaseDatabase):
        self.db = db

    def get_by_id(self, case_id: str) -> Optional[Case]:
        rows = self.db.query("SELECT * FROM cases WHERE id = :id", {"id": case_id})
        return _row_to_model(rows[0], Case) if rows else None

    def create(self, case: Case) -> bool:
        try:
            return self.db.execute(
                """INSERT INTO cases
                (id, problem_desc, diagnosis, resolution, country, channel,
                 error_code, problem_type, confidence, merchant_id, feishu_record_id)
                VALUES (:id, :problem_desc, :diagnosis, :resolution, :country, :channel,
                        :error_code, :problem_type, :confidence, :merchant_id, :feishu_record_id)""",
                _model_to_dict(case),
            )
        except RuntimeError as e:
            if "UNIQUE constraint failed" in str(e):
                raise DuplicateKeyError(f"案例 ID '{case.id}' 已存在") from e
            raise RepositoryError(str(e)) from e

    def update(self, case_id: str, case: Case) -> bool:
        try:
            return self.db.execute(
                """UPDATE cases SET
                    problem_desc = :problem_desc, diagnosis = :diagnosis,
                    resolution = :resolution, country = :country, channel = :channel,
                    error_code = :error_code, problem_type = :problem_type,
                    confidence = :confidence, merchant_id = :merchant_id,
                    feishu_record_id = :feishu_record_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id""",
                {**_model_to_dict(case), "id": case_id},
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def list(self, filters: Optional[dict] = None, limit: int = 100) -> list[Case]:
        sql = "SELECT * FROM cases"
        params = {"limit": limit}
        if filters:
            conditions = []
            for key in ("country", "channel", "error_code", "problem_type"):
                if key in filters:
                    conditions.append(f"{key} = :{key}")
                    params[key] = filters[key]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " LIMIT :limit"
        rows = self.db.query(sql, params)
        return [_row_to_model(r, Case) for r in rows]


# === 4. TicketRepository ===

class TicketRepository:
    """工单仓库（飞书同步源）。"""

    def __init__(self, db: BaseDatabase):
        self.db = db

    def get_by_id(self, ticket_id: str) -> Optional[Ticket]:
        rows = self.db.query("SELECT * FROM tickets WHERE id = :id", {"id": ticket_id})
        return _row_to_model(rows[0], Ticket) if rows else None

    def create(self, ticket: Ticket) -> bool:
        try:
            return self.db.execute(
                """INSERT INTO tickets
                (id, problem_type, priority, status, merchant_id, assignee,
                 source, diagnosis_id, feishu_record_id)
                VALUES (:id, :problem_type, :priority, :status, :merchant_id, :assignee,
                        :source, :diagnosis_id, :feishu_record_id)""",
                _model_to_dict(ticket),
            )
        except RuntimeError as e:
            if "UNIQUE constraint failed" in str(e):
                raise DuplicateKeyError(f"工单 ID '{ticket.id}' 已存在") from e
            raise RepositoryError(str(e)) from e

    def update(self, ticket_id: str, ticket: Ticket) -> bool:
        try:
            return self.db.execute(
                """UPDATE tickets SET
                    problem_type = :problem_type, priority = :priority,
                    status = :status, merchant_id = :merchant_id,
                    assignee = :assignee, source = :source,
                    diagnosis_id = :diagnosis_id, feishu_record_id = :feishu_record_id,
                    resolved_at = :resolved_at,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id""",
                {**_model_to_dict(ticket), "id": ticket_id},
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def list(self, filters: Optional[dict] = None, limit: int = 100) -> list[Ticket]:
        sql = "SELECT * FROM tickets"
        params = {"limit": limit}
        if filters:
            conditions = []
            for key in ("status", "assignee", "priority", "problem_type", "merchant_id"):
                if key in filters:
                    conditions.append(f"{key} = :{key}")
                    params[key] = filters[key]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " LIMIT :limit"
        rows = self.db.query(sql, params)
        return [_row_to_model(r, Ticket) for r in rows]


# === 5. ConversationRepository ===

class ConversationRepository:
    """对话会话仓库（本地）。"""

    def __init__(self, db: BaseDatabase):
        self.db = db

    def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        rows = self.db.query(
            "SELECT * FROM conversations WHERE id = :id", {"id": conversation_id}
        )
        return _row_to_model(rows[0], Conversation) if rows else None

    def create(self, conversation: Conversation) -> bool:
        try:
            return self.db.execute(
                """INSERT INTO conversations
                (id, user_id, status, merchant_id, tool_name)
                VALUES (:id, :user_id, :status, :merchant_id, :tool_name)""",
                _model_to_dict(conversation),
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def update(self, conversation_id: str, conversation: Conversation) -> bool:
        try:
            return self.db.execute(
                """UPDATE conversations SET
                    user_id = :user_id, status = :status,
                    merchant_id = :merchant_id, tool_name = :tool_name,
                    last_msg_at = CURRENT_TIMESTAMP
                WHERE id = :id""",
                {**_model_to_dict(conversation), "id": conversation_id},
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def list(self, filters: Optional[dict] = None, limit: int = 100) -> list[Conversation]:
        sql = "SELECT * FROM conversations"
        params = {"limit": limit}
        if filters:
            conditions = []
            for key in ("user_id", "status", "merchant_id"):
                if key in filters:
                    conditions.append(f"{key} = :{key}")
                    params[key] = filters[key]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY last_msg_at DESC LIMIT :limit"
        rows = self.db.query(sql, params)
        return [_row_to_model(r, Conversation) for r in rows]

    def add_message(self, conversation_id: str, message: Message) -> bool:
        """添加消息（便捷方法）。"""
        try:
            return self.db.execute(
                """INSERT INTO messages (conversation_id, role, content, tool_calls)
                   VALUES (:cid, :role, :content, :tool_calls)""",
                {
                    "cid": conversation_id,
                    "role": message.role,
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                },
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def get_messages(self, conversation_id: str, limit: int = 50) -> list[Message]:
        """获取会话消息。"""
        rows = self.db.query(
            """SELECT * FROM messages
               WHERE conversation_id = :cid
               ORDER BY created_at ASC LIMIT :limit""",
            {"cid": conversation_id, "limit": limit},
        )
        return [_row_to_model(r, Message) for r in rows]


# === 6. HandoffRepository ===

class HandoffRepository:
    """人工交接记录仓库（本地）。"""

    def __init__(self, db: BaseDatabase):
        self.db = db

    def get_by_id(self, handoff_id: str) -> Optional[Handoff]:
        rows = self.db.query("SELECT * FROM handoffs WHERE id = :id", {"id": handoff_id})
        return _row_to_model(rows[0], Handoff) if rows else None

    def create(self, handoff: Handoff) -> bool:
        try:
            return self.db.execute(
                """INSERT INTO handoffs
                (id, conversation_id, agent_id, reason, briefing)
                VALUES (:id, :conversation_id, :agent_id, :reason, :briefing)""",
                _model_to_dict(handoff),
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def update(self, handoff_id: str, handoff: Handoff) -> bool:
        try:
            return self.db.execute(
                """UPDATE handoffs SET
                    conversation_id = :conversation_id,
                    agent_id = :agent_id,
                    reason = :reason,
                    briefing = :briefing,
                    resolved_at = :resolved_at
                WHERE id = :id""",
                {**_model_to_dict(handoff), "id": handoff_id},
            )
        except RuntimeError as e:
            raise RepositoryError(str(e)) from e

    def list(self, filters: Optional[dict] = None, limit: int = 100) -> list[Handoff]:
        sql = "SELECT * FROM handoffs"
        params = {"limit": limit}
        if filters:
            conditions = []
            if "conversation_id" in filters:
                conditions.append("conversation_id = :cid")
                params["cid"] = filters["conversation_id"]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = self.db.query(sql, params)
        return [_row_to_model(r, Handoff) for r in rows]


# === 统一导出 ===

__all__ = [
    "MerchantRepository", "ErrorCodeRepository", "CaseRepository",
    "TicketRepository", "ConversationRepository", "HandoffRepository",
]
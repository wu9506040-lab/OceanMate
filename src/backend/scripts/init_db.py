"""SQLite 数据库初始化脚本 — 建 8 张表 + 索引。

幂等：重复运行不会报错（用 IF NOT EXISTS）。

用法：
    cd src/backend
    python scripts/init_db.py                # 默认 data/oceanmate.db
    python scripts/init_db.py --reset        # 删表重建（仅开发用）
    python scripts/init_db.py --db path/to.db

详见：
- SOP-SQLITE-001（正逆向 SOP）
- docs/architecture/oceanmate_v2.md §4.1 表设计
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Windows 中文输出兼容
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# 数据库文件默认路径
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "oceanmate.db"


# === 8 张表的 DDL ===

DDL_STATEMENTS = [
    # ===== 1. merchants 商户表 =====
    """
    CREATE TABLE IF NOT EXISTS merchants (
        id              TEXT PRIMARY KEY,
        country         TEXT NOT NULL,
        industry        TEXT,
        avg_amount      REAL,
        tier            TEXT DEFAULT 'standard',
        feishu_record_id TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_merchants_country ON merchants(country)",
    "CREATE INDEX IF NOT EXISTS idx_merchants_tier ON merchants(tier)",

    # ===== 2. error_codes 错误码知识库（飞书同步）=====
    """
    CREATE TABLE IF NOT EXISTS error_codes (
        id              TEXT PRIMARY KEY,
        code            TEXT NOT NULL,
        country         TEXT,
        channel         TEXT,
        root_cause      TEXT,
        solution        TEXT,
        feishu_record_id TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(code, country, channel)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_error_codes_code ON error_codes(code)",
    "CREATE INDEX IF NOT EXISTS idx_error_codes_country ON error_codes(country)",

    # ===== 3. cases 诊断案例（飞书同步）=====
    # 注：error_code 是业务码字符串（用于 RAG 检索/前端展示），非 error_codes.id FK。
    # 若要严格关联，应加 error_code_id 列。PoC 阶段先保留业务码字段不加 FK。
    """
    CREATE TABLE IF NOT EXISTS cases (
        id              TEXT PRIMARY KEY,
        problem_desc    TEXT NOT NULL,
        diagnosis       TEXT,
        resolution      TEXT,
        country         TEXT,
        channel         TEXT,
        error_code      TEXT,
        problem_type    TEXT,
        confidence      REAL,
        merchant_id     TEXT,
        feishu_record_id TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (merchant_id) REFERENCES merchants(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cases_country_channel ON cases(country, channel)",
    "CREATE INDEX IF NOT EXISTS idx_cases_problem_type ON cases(problem_type)",

    # ===== 4. tickets 工单（飞书同步）=====
    """
    CREATE TABLE IF NOT EXISTS tickets (
        id              TEXT PRIMARY KEY,
        problem_type    TEXT NOT NULL,
        priority        TEXT DEFAULT 'medium',
        status          TEXT DEFAULT 'pending',
        merchant_id     TEXT,
        assignee        TEXT,
        source          TEXT,
        diagnosis_id    TEXT,
        feishu_record_id TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved_at     DATETIME,
        FOREIGN KEY (merchant_id) REFERENCES merchants(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)",
    "CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee)",
    "CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)",

    # ===== 5. conversations 对话历史（本地）=====
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id              TEXT PRIMARY KEY,
        user_id         TEXT NOT NULL,
        started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_msg_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
        status          TEXT DEFAULT 'active',
        merchant_id     TEXT,
        tool_name       TEXT,
        FOREIGN KEY (merchant_id) REFERENCES merchants(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status)",

    # ===== 6. messages 对话消息（本地）=====
    """
    CREATE TABLE IF NOT EXISTS messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role            TEXT NOT NULL,
        content         TEXT NOT NULL,
        tool_calls      TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)",

    # ===== 7. handoffs 人工交接记录（本地）=====
    """
    CREATE TABLE IF NOT EXISTS handoffs (
        id              TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        agent_id        TEXT,
        reason          TEXT,
        briefing        TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved_at     DATETIME,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_handoffs_conversation ON handoffs(conversation_id)",

    # ===== 8. embedding_meta 向量元数据（关联 Chroma）=====
    """
    CREATE TABLE IF NOT EXISTS embedding_meta (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source_table    TEXT NOT NULL,
        source_id       TEXT NOT NULL,
        chroma_id       TEXT NOT NULL,
        collection_name TEXT NOT NULL,
        synced_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_table, source_id, collection_name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_embedding_meta_source ON embedding_meta(source_table, source_id)",
]


def init_db(db_path: Path, reset: bool = False) -> dict:
    """初始化数据库。

    Args:
        db_path: 数据库文件路径
        reset: 是否删表重建（仅开发用）

    Returns:
        {"tables_created": int, "db_path": str, "db_size_bytes": int}

    Raises:
        RuntimeError: 初始化失败
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if reset and db_path.exists():
        db_path.unlink()
        print(f"[reset] 删除旧数据库: {db_path}")

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")  # 启用外键约束

        cursor = conn.cursor()
        for ddl in DDL_STATEMENTS:
            cursor.execute(ddl)

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"数据库初始化失败: {e}") from e

    # 验证表创建成功
    tables_created = verify_tables(db_path)

    return {
        "tables_created": tables_created,
        "db_path": str(db_path),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
    }


def verify_tables(db_path: Path) -> int:
    """验证表是否都创建成功。"""
    expected_tables = {
        "merchants", "error_codes", "cases", "tickets",
        "conversations", "messages", "handoffs", "embedding_meta",
    }
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    actual_tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    missing = expected_tables - actual_tables
    if missing:
        raise RuntimeError(f"缺失表: {missing}")

    return len(expected_tables)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OceanMate SQLite 初始化")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="数据库文件路径")
    parser.add_argument("--reset", action="store_true", help="删除旧数据库重建")
    args = parser.parse_args()

    result = init_db(args.db, reset=args.reset)
    print(f"✅ 数据库初始化成功")
    print(f"   表数: {result['tables_created']}")
    print(f"   路径: {result['db_path']}")
    print(f"   大小: {result['db_size_bytes']} bytes")
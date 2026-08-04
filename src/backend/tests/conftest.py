"""pytest 公共 fixture — 隔离测试数据库 + 依赖注入。

设计：
- 每个测试用临时 SQLite 文件（避免污染 data/oceanmate.db）
- 复用 init_db 的 DDL，保持与生产一致
- 注入 6 个 Repository 实例
"""

import sys
from pathlib import Path

# 让 pytest 能直接 `from app.xxx import ...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from scripts.init_db import DDL_STATEMENTS
from app.implementations.db.sqlite_db import SQLiteDatabase
from app.implementations.db.repositories import (
    MerchantRepository,
    ErrorCodeRepository,
    CaseRepository,
    TicketRepository,
    ConversationRepository,
    HandoffRepository,
)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """临时数据库文件路径。"""
    return tmp_path / "test.db"


@pytest.fixture
def db(tmp_db_path: Path) -> SQLiteDatabase:
    """初始化空 DB（执行 DDL）+ 返回连接。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in DDL_STATEMENTS:
        conn.execute(ddl)
    conn.commit()
    conn.close()

    database = SQLiteDatabase(tmp_db_path)
    yield database
    database.close()


@pytest.fixture
def repos(db: SQLiteDatabase) -> dict:
    """注入 6 个 Repository 实例。"""
    return {
        "merchant": MerchantRepository(db),
        "error_code": ErrorCodeRepository(db),
        "case": CaseRepository(db),
        "ticket": TicketRepository(db),
        "conversation": ConversationRepository(db),
        "handoff": HandoffRepository(db),
    }
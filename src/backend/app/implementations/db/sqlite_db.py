"""SQLite Database 实现 - 继承 BaseDatabase。

特性：
- 直接 sqlite3 + Repository 手写（不用 ORM，PoC 简化）
- 事务用 contextmanager（BaseDatabase.transaction 抽象）
- 占位符用 ? 或 :name（防 SQL 注入）
- 自动启用外键约束

详见 SOP-DB-001（事务回滚）。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from app.interfaces.base_database import BaseDatabase


class SQLiteDatabase(BaseDatabase):
    """SQLite 数据库实现。

    使用示例：
        db = SQLiteDatabase(Path('data/oceanmate.db'))
        db.execute("INSERT INTO merchants ...", {"id": "m001", ...})
        rows = db.query("SELECT * FROM merchants WHERE country = :c", {"c": "BR"})
        with db.transaction() as tx:
            tx.execute("UPDATE ...")
            tx.execute("INSERT ...")
        db.close()
    """

    def __init__(self, db_path: Path):
        """初始化 SQLite 连接。

        Args:
            db_path: 数据库文件路径

        Raises:
            RuntimeError: 连接失败
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row  # 查询返回 dict-like
            self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as e:
            raise RuntimeError(f"SQLite 连接失败: {e}") from e

    # === BaseDatabase 接口 ===

    def query(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """查询数据。

        Args:
            sql: SQL 语句（用 ? 或 :name 占位符）
            params: 参数 dict

        Returns:
            结果列表（每行一个 dict）

        Raises:
            RuntimeError: 查询失败（包装 sqlite3 异常）
        """
        try:
            cursor = self._conn.execute(sql, params or {})
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise RuntimeError(f"查询失败: {e}\nSQL: {sql}\nParams: {params}") from e

    def execute(self, sql: str, params: Optional[dict] = None) -> bool:
        """执行 SQL（INSERT/UPDATE/DELETE）。

        Returns:
            True 成功

        Raises:
            RuntimeError: 执行失败（包装 sqlite3 异常，含主键冲突/字段超长等）
        """
        try:
            self._conn.execute(sql, params or {})
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            self._conn.rollback()
            raise RuntimeError(f"执行失败: {e}\nSQL: {sql}\nParams: {params}") from e

    @contextmanager
    def transaction(self):
        """事务上下文管理器。

        用法：
            with db.transaction() as tx:
                tx.execute(sql1, params1)
                tx.execute(sql2, params2)
            # 自动 commit；若异常 → 自动 rollback

        Yields:
            _Transaction 代理对象（execute/query）
        """
        tx = _Transaction(self._conn)
        try:
            yield tx
            tx.commit()
        except Exception:
            tx.rollback()
            raise

    def close(self) -> None:
        """关闭数据库连接。"""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass  # 关闭失败不影响

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class _Transaction:
    """事务代理对象。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._committed = False
        self._rolled_back = False

    def execute(self, sql: str, params: Optional[dict] = None) -> None:
        """事务内执行（不自动 commit）。

        Raises:
            RuntimeError: 包装 sqlite3 异常（保持接口异常一致性）
        """
        try:
            self._conn.execute(sql, params or {})
        except sqlite3.Error as e:
            raise RuntimeError(f"事务执行失败: {e}\nSQL: {sql}") from e

    def query(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """事务内查询。"""
        try:
            cursor = self._conn.execute(sql, params or {})
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise RuntimeError(f"事务查询失败: {e}\nSQL: {sql}") from e

    def commit(self) -> None:
        """提交事务。"""
        if not self._committed and not self._rolled_back:
            self._conn.commit()
            self._committed = True

    def rollback(self) -> None:
        """回滚事务。"""
        if not self._committed and not self._rolled_back:
            self._conn.rollback()
            self._rolled_back = True
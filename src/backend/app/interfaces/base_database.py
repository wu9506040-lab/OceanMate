"""BaseDatabase - 数据库抽象接口。

3 个核心方法 + 事务上下文：
- query()      查询（SELECT）
- execute()    执行（INSERT/UPDATE/DELETE）
- transaction() 事务上下文

实现层：app/implementations/db/sqlite_db.py
SOP：SOP-DB-001（事务回滚）/ SOP-SQLITE-001（初始化）
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Optional


class BaseDatabase(ABC):
    """数据库基类。

    评审意义：未来切换数据库（SQLite → PostgreSQL/MySQL）只需换实现。
    """

    @abstractmethod
    def query(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """查询数据。

        Args:
            sql: SQL 语句（用 ? 或 :name 占位符，禁止字符串拼接）
            params: 参数 dict

        Returns:
            结果列表（每行一个 dict）

        Raises:
            RuntimeError: 查询失败
        """

    @abstractmethod
    def execute(self, sql: str, params: Optional[dict] = None) -> bool:
        """执行 SQL（INSERT/UPDATE/DELETE）。

        Args:
            sql: SQL 语句
            params: 参数 dict

        Returns:
            True 成功 / False 失败

        Raises:
            RuntimeError: 执行失败
        """

    @abstractmethod
    @contextmanager
    def transaction(self):
        """事务上下文管理器。

        用法：
            with db.transaction() as tx:
                tx.execute(sql1)
                tx.execute(sql2)
                # 自动 commit；若异常 → 自动 rollback

        Yields:
            事务对象（支持 execute/query）

        Raises:
            RuntimeError: 事务失败
        """

    @abstractmethod
    def close(self) -> None:
        """关闭数据库连接。"""
"""数据库实现层 - SQLite + Repository 模式。

不使用 ORM（PoC 简化），直接 sqlite3 + Repository 手写。
事务通过 BaseDatabase.transaction() 上下文管理。

详见 SOP-DB-001 / SOP-REPO-001 / SOP-SQLITE-001。
"""
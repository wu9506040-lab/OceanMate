"""迁移：去掉 cases 表的外键约束（FK mismatch 阻塞 KEA 数据飞轮）。

根因：
- cases 表有 FK: (error_code) REFERENCES error_codes(code)
- 但 error_codes 表有 UNIQUE(code, country, channel) 复合约束
- FK 只引用单一列 code，违反 SQLite "FK 必须引用完整 UNIQUE/PRIMARY KEY 列" 规则
- 结果：FK mismatch error，连 PRAGMA foreign_keys=ON 都触发崩溃

方案（最简 · 风险最低）：
- cases 表是本地缓存，真相在飞书多维表
- FK 在本地层不提供价值（没有 JOIN 依赖）
- 直接 DROP FK，重建表

执行：python scripts/migrate_drop_cases_fk.py
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.implementations.db.sqlite_db import SQLiteDatabase

DB_PATH = BACKEND_ROOT / "data" / "oceanmate.db"


def main() -> int:
    print(f"[迁移] 目标 DB: {DB_PATH}")
    db = SQLiteDatabase(DB_PATH)

    # 1) 备份现有 cases
    print("[1/4] 备份 cases 现有数据...")
    rows = db.query("SELECT * FROM cases")
    print(f"  备份 {len(rows)} 条 cases")

    # 2) DROP + RECREATE（不带 FK）
    print("[2/4] DROP + CREATE 新表（去 FK）...")
    db.execute("DROP TABLE cases")
    db.execute("""
        CREATE TABLE cases (
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
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  [OK] 新表已创建（无 FK 约束）")

    # 3) 恢复数据
    print("[3/4] 恢复备份数据...")
    for r in rows:
        cols = list(r.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        col_list = ", ".join(cols)
        try:
            db.execute(
                f"INSERT INTO cases ({col_list}) VALUES ({placeholders})",
                dict(r),
            )
        except Exception as e:
            print(f"  [WARN] 恢复 {r.get('id')} 失败: {e}")
    cur_count = db.query("SELECT count(*) AS n FROM cases")[0]["n"]
    print(f"  [OK] 恢复后 cases 总数 = {cur_count}")

    # 4) 验证 schema
    print("[4/4] 验证新 schema...")
    schema = db.query(
        "SELECT sql FROM sqlite_master WHERE name='cases'"
    )[0]["sql"]
    has_fk = "FOREIGN KEY" in schema.upper()
    if has_fk:
        print(f"  [FAIL] schema 仍含 FOREIGN KEY: {schema}")
        return 1
    print(f"  [OK] schema 已无 FK 约束")

    print()
    print("[OK] 迁移完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
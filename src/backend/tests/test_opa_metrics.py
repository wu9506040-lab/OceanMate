"""OPA 运营指标聚合测试（app/implementations/opa_metrics.py）。

覆盖：
- METRICS-1 空库 / 缺表 → 健壮空结构（不抛）
- METRICS-2 cases 分布 + 置信度健康度聚合正确
- METRICS-3 review_decisions 审核通过率（pending 不入分母）
- METRICS-4 embedding_meta 知识资产台账（faq_indexed 口径）
- TRENDS-1 按 ISO 周分桶 + 周内 top 错误码
"""

import sqlite3

import pytest

from app.implementations.opa_metrics import collect_metrics, collect_trends


DDL = [
    """CREATE TABLE cases (
        id TEXT PRIMARY KEY, problem_desc TEXT, diagnosis TEXT, resolution TEXT,
        country TEXT, channel TEXT, error_code TEXT, problem_type TEXT,
        confidence REAL, merchant_id TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE review_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
        decision TEXT NOT NULL, reviewer TEXT, note TEXT, chroma_id TEXT,
        confidence REAL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE embedding_meta (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_table TEXT NOT NULL,
        source_id TEXT NOT NULL, chroma_id TEXT NOT NULL, collection_name TEXT NOT NULL,
        synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_table, source_id, collection_name)
    )""",
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "oceanmate.db"
    conn = sqlite3.connect(path)
    for ddl in DDL:
        conn.execute(ddl)
    yield path, conn
    conn.close()


def _seed_cases(conn, rows):
    conn.executemany(
        """INSERT INTO cases (id, problem_desc, country, channel, error_code,
                              problem_type, confidence, created_at)
           VALUES (?, 'desc', ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


class TestRobustness:

    def test_metrics_missing_db_returns_empty_structure(self, tmp_path):
        m = collect_metrics(tmp_path / "nope.db")
        assert m == {"db_exists": False, "case_total": 0}

    def test_metrics_empty_tables(self, db):
        path, _conn = db
        m = collect_metrics(path)
        assert m["case_total"] == 0
        assert m["review"]["approval_rate"] is None


class TestMetrics:

    def test_metrics_distributions_and_confidence(self, db):
        path, conn = db
        _seed_cases(conn, [
            ("c1", "US", "visa", "13.1", "chargeback", 0.9, "2026-10-01 10:00:00"),
            ("c2", "US", "visa", "13.1", "chargeback", 0.5, "2026-10-02 10:00:00"),
            ("c3", "BR", "pix", "", "payout_delay", 0.8, "2026-10-05 10:00:00"),
        ])
        m = collect_metrics(path)
        assert m["case_total"] == 3
        assert m["error_code_dist"]["13.1"] == 2
        assert m["error_code_dist"]["unknown"] == 1      # 空串归 unknown
        assert m["channel_dist"] == {"visa": 2, "pix": 1}
        assert m["avg_confidence"] == round((0.9 + 0.5 + 0.8) / 3, 4)
        assert m["low_confidence_ratio"] == round(1 / 3, 4)

    def test_metrics_review_approval_rate(self, db):
        path, conn = db
        conn.executemany(
            "INSERT INTO review_decisions (case_id, decision) VALUES (?, ?)",
            [("c1", "approved"), ("c2", "approved"), ("c3", "rejected"),
             ("c4", "pending_review")],
        )
        conn.commit()
        r = collect_metrics(path)["review"]
        assert (r["approved"], r["rejected"], r["pending"]) == (2, 1, 1)
        assert r["approval_rate"] == round(2 / 3, 4)     # pending 不入分母

    def test_metrics_knowledge_assets(self, db):
        path, conn = db
        conn.executemany(
            """INSERT INTO embedding_meta (source_table, source_id, chroma_id, collection_name)
               VALUES ('cases', ?, ?, ?)""",
            [("c1", "faq_c1_x", "faq_vec"), ("c2", "faq_c2_y", "faq_vec"),
             ("c1", "emb_c1_z", "cases_vec")],
        )
        conn.commit()
        assets = collect_metrics(path)["knowledge_assets"]
        assert assets["faq_indexed"] == 2
        assert {c["collection_name"] for c in assets["collections"]} == {"faq_vec", "cases_vec"}


class TestTrends:

    def test_trends_weekly_buckets(self, db):
        path, conn = db
        _seed_cases(conn, [
            ("t1", "US", "visa", "13.1", "chargeback", 0.9, "2026-09-02 08:00:00"),
            ("t2", "US", "visa", "13.1", "chargeback", 0.8, "2026-09-03 08:00:00"),
            ("t3", "BR", "pix", "4837", "fraud", 0.7, "2026-09-15 08:00:00"),
        ])
        t = collect_trends(path, weeks=8)
        assert len(t["series"]) == 2                      # 两个 ISO 周
        first = t["series"][0]
        assert first["cases"] == 2
        assert first["top_error_codes"]["13.1"] == 2
        weeks = [b["week"] for b in t["series"]]
        assert weeks == sorted(weeks)                     # 时间正序

"""OPA 运营指标聚合 — 数据飞轮的"反哺业务"输出端。

业务作用：
    商户咨询（PDA）与工单（TRA）跑出的真实数据沉淀在 cases / review_decisions /
    embedding_meta 三张表里；本模块把它们聚合为运营指标（错误码分布、置信度健康度、
    审核通过率、周趋势、知识资产台账），供 OPA 看板 / 周报 / 风控复盘消费——
    即"数据飞轮"对外输出的一端。

设计原则：
- 只读聚合，零新依赖（stdlib sqlite3），REST 端点与 scripts/opa_report.py 共用
- 表缺失 / 库未初始化时返回空结构不抛异常（PoC 环境健壮性）
- 所有统计基于真实落库数据，不造数

数据源（schema 见 scripts/init_db.py 与 kea/tool.py review_decisions）：
- cases:            error_code / problem_type / channel / country / confidence / created_at
- review_decisions: KEA 案例升格 FAQ 的审核决策（approved / rejected / pending_review）
- embedding_meta:   知识资产台账（source_table × collection_name × synced_at）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

# 与 scripts/init_db.py DEFAULT_DB_PATH 同址：src/backend/data/oceanmate.db
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "oceanmate.db"

# 低置信度阈值：与 KEA 自动升格链路 <0.7 不触发链路的口径对齐
LOW_CONFIDENCE_THRESHOLD = 0.7


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _group_count(conn: sqlite3.Connection, column: str, top_n: int = 10) -> dict:
    """cases 表单列分布统计（空值归入 'unknown'）。列名来自本模块白名单，非用户输入。"""
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF({column}, ''), 'unknown') AS k,
                   COUNT(*) AS c
            FROM cases
            GROUP BY k
            ORDER BY c DESC
            LIMIT ?""",
        (top_n,),
    ).fetchall()
    return {r["k"]: r["c"] for r in rows}


def collect_metrics(db_path: Optional[Path | str] = None) -> dict:
    """运营指标快照（看板首屏数据源）。

    Returns:
        {
          "case_total": int,
          "error_code_dist": {code: count},       # 拒付错误码分布（风控复盘入口）
          "problem_type_dist": {type: count},
          "channel_dist": {channel: count},        # 渠道健康度视角
          "country_dist": {country: count},
          "avg_confidence": float | None,          # 诊断质量健康度
          "low_confidence_ratio": float | None,    # <0.7 占比（PDA 能力边界信号）
          "review": {approved, rejected, pending, approval_rate, decided},
          "knowledge_assets": {                    # 知识资产台账（embedding_meta）
            "faq_indexed": int,                    # 已升格入 faq_vec 的 FAQ 数
            "collections": [{source_table, collection_name, count, last_synced}],
          },
        }
    """
    path = Path(db_path or DEFAULT_DB_PATH)
    if not path.exists():
        return {"db_exists": False, "case_total": 0}

    conn = _connect(path)
    try:
        metrics: dict = {"db_exists": True}
        if not _table_exists(conn, "cases"):
            metrics["case_total"] = 0
            return metrics

        metrics["case_total"] = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        metrics["error_code_dist"] = _group_count(conn, "error_code")
        metrics["problem_type_dist"] = _group_count(conn, "problem_type")
        metrics["channel_dist"] = _group_count(conn, "channel")
        metrics["country_dist"] = _group_count(conn, "country")

        row = conn.execute(
            """SELECT AVG(confidence) AS avg_c,
                      SUM(CASE WHEN confidence < ? THEN 1 ELSE 0 END) AS low_c
               FROM cases WHERE confidence IS NOT NULL""",
            (LOW_CONFIDENCE_THRESHOLD,),
        ).fetchone()
        total_with_conf = (row["avg_c"] is not None) and row["low_c"] is not None
        metrics["avg_confidence"] = round(row["avg_c"], 4) if row["avg_c"] is not None else None
        metrics["low_confidence_ratio"] = (
            round(row["low_c"] / metrics["case_total"], 4)
            if total_with_conf and metrics["case_total"] else None
        )

        # KEA 审核决策分布（数据资产准入质量）
        review = {"approved": 0, "rejected": 0, "pending": 0, "approval_rate": None, "decided": 0}
        if _table_exists(conn, "review_decisions"):
            for r in conn.execute(
                "SELECT decision, COUNT(*) AS c FROM review_decisions GROUP BY decision"
            ):
                key = "pending" if "pending" in (r["decision"] or "") else (
                    "approved" if r["decision"] == "approved" else "rejected"
                )
                review[key] = r["c"]
            review["decided"] = review["approved"] + review["rejected"]
            if review["decided"]:
                review["approval_rate"] = round(review["approved"] / review["decided"], 4)
        metrics["review"] = review

        # 知识资产台账
        assets: dict = {"faq_indexed": 0, "collections": []}
        if _table_exists(conn, "embedding_meta"):
            assets["faq_indexed"] = conn.execute(
                "SELECT COUNT(*) FROM embedding_meta WHERE collection_name = 'faq_vec'"
            ).fetchone()[0]
            assets["collections"] = [
                dict(r)
                for r in conn.execute(
                    """SELECT source_table, collection_name,
                              COUNT(*) AS count, MAX(synced_at) AS last_synced
                       FROM embedding_meta
                       GROUP BY source_table, collection_name
                       ORDER BY count DESC"""
                )
            ]
        metrics["knowledge_assets"] = assets
        return metrics
    finally:
        conn.close()


def collect_trends(db_path: Optional[Path | str] = None, weeks: int = 8) -> dict:
    """按 ISO 周的案例量与错误码趋势（周报 / 风控策略反哺数据源）。

    Returns:
        {"weeks": int, "series": [{"week", "cases", "top_error_codes": {code: count}}]}
    """
    path = Path(db_path or DEFAULT_DB_PATH)
    empty = {"weeks": weeks, "series": []}
    if not path.exists():
        return empty

    conn = _connect(path)
    try:
        if not _table_exists(conn, "cases"):
            return empty
        buckets = [
            dict(r)
            for r in conn.execute(
                """SELECT strftime('%Y-W%W', created_at) AS week,
                          COUNT(*) AS cases
                   FROM cases
                   WHERE created_at IS NOT NULL
                   GROUP BY week
                   ORDER BY week DESC
                   LIMIT ?""",
                (weeks,),
            )
        ]
        for b in buckets:
            top = conn.execute(
                """SELECT COALESCE(NULLIF(error_code, ''), 'unknown') AS k, COUNT(*) AS c
                   FROM cases
                   WHERE strftime('%Y-W%W', created_at) = ?
                   GROUP BY k ORDER BY c DESC LIMIT 5""",
                (b["week"],),
            ).fetchall()
            b["top_error_codes"] = {r["k"]: r["c"] for r in top}
        buckets.reverse()  # 时间正序更适合画趋势
        return {"weeks": weeks, "series": buckets}
    finally:
        conn.close()

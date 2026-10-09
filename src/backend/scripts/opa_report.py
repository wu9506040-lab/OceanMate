"""opa_report.py — 生成 OPA 运营周报（数据飞轮"反哺业务"的文件产物）。

读取真实落库数据（cases / review_decisions / embedding_meta），聚合为 Markdown 报表
写入 docs/reports/，供产品与风控策略复盘——补全飞轮链路：
    商户咨询 → 案例沉淀 → 知识进化 → **指标聚合 → 报表反哺**

用法（在 src/backend 目录）：
    python scripts/opa_report.py                # 默认库 + 8 周趋势
    python scripts/opa_report.py --weeks 12
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.implementations.opa_metrics import collect_metrics, collect_trends  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def render_markdown(metrics: dict, trends: dict, weeks: int) -> str:
    if not metrics.get("db_exists"):
        return "# OPA 运营报表\n\n> 数据库不存在（先跑 scripts/init_db.py 与 seed 脚本）\n"

    def dist_table(dist: dict) -> str:
        if not dist:
            return "_（无数据）_\n"
        lines = ["| 键 | 数量 |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in dist.items()]
        return "\n".join(lines)

    rev = metrics.get("review", {})
    assets = metrics.get("knowledge_assets", {})
    series = trends.get("series", [])

    md = [
        f"# OPA 运营报表（{datetime.now().strftime('%Y-%m-%d %H:%M')}）",
        "",
        "## 案例总览",
        f"- 案例总量：**{metrics.get('case_total', 0)}**",
        f"- 平均诊断置信度：**{metrics.get('avg_confidence', '—')}**"
        f"　低置信(<0.7)占比：**{metrics.get('low_confidence_ratio', '—')}**",
        "",
        "## 拒付错误码分布（风控复盘入口）",
        dist_table(metrics.get("error_code_dist", {})),
        "",
        "## 问题类型 / 渠道 / 国家",
        dist_table(metrics.get("problem_type_dist", {})),
        "",
        dist_table(metrics.get("channel_dist", {})),
        "",
        dist_table(metrics.get("country_dist", {})),
        "",
        "## KEA 知识进化（数据飞轮）",
        f"- 审核决策：approved {rev.get('approved', 0)} / rejected {rev.get('rejected', 0)}"
        f" / pending {rev.get('pending', 0)}，通过率 **{rev.get('approval_rate', '—')}**",
        f"- 已升格 FAQ 入库：**{assets.get('faq_indexed', 0)}** 条",
        "",
        f"## 近 {weeks} 周趋势",
    ]
    if series:
        md += ["| 周 | 案例数 | Top 错误码 |", "|---|---|---|"]
        for b in series:
            top = ", ".join(f"{k}×{v}" for k, v in b["top_error_codes"].items())
            md.append(f"| {b['week']} | {b['cases']} | {top} |")
    else:
        md.append("_（暂无时间序列数据）_")
    md.append("")
    return "\n".join(md)


def main() -> int:
    parser = argparse.ArgumentParser(description="OPA 运营周报生成")
    parser.add_argument("--db", type=Path, default=None, help="oceanmate.db 路径（默认取模块配置）")
    parser.add_argument("--weeks", type=int, default=8, help="趋势回溯周数")
    args = parser.parse_args()

    metrics = collect_metrics(args.db)
    trends = collect_trends(args.db, weeks=args.weeks)

    out_dir = REPO_ROOT / "docs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    (out_dir / f"opa_report_{stamp}.md").write_text(
        render_markdown(metrics, trends, args.weeks), encoding="utf-8")
    (out_dir / f"opa_metrics_{stamp}.json").write_text(
        json.dumps({"metrics": metrics, "trends": trends}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"[OK] 报表已生成：docs/reports/opa_report_{stamp}.md")
    print(f"[OK] 指标快照：docs/reports/opa_metrics_{stamp}.json")
    if metrics.get("db_exists"):
        print(f"     案例 {metrics.get('case_total')} | FAQ {metrics.get('knowledge_assets', {}).get('faq_indexed')}"
              f" | 趋势周数 {len(trends.get('series', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

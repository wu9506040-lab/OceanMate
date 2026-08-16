"""录屏前 seed 待审核数据 — Day 18 P2-final。

目的：让 dashboard pending_count > 0（录屏可见「⏳ 待审核 X 条」橙色卡）。

流程：
1. 启动 backend（lifespan 注入真实 FeishuFrontend + KEATool）
2. 选 2 个未审的 conf=0.85 case
3. 调 promote_to_faq → KEA 走 pending_review 分支 → 写多维表格 review_decisions
4. 退出（无需重启 backend）

用法：
    cd src/backend
    python scripts/seed_pending_review.py

幂等：已审过的 case 不会重复入审（_has_any_review_decision 过滤）。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import sqlite3

from app.implementations.db.sqlite_db import SQLiteDatabase
from app.implementations.db.repositories import CaseRepository
from app.agents.kea.tool import KEATool
from app.implementations.feishu import get_feishu_frontend


def select_unreviewed_cases(db_path: str, n: int = 2) -> list[str]:
    """从 SQLite 选 N 个未审 + conf=0.85 的 case_id（最近优先）。"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT id FROM cases c
           WHERE confidence = 0.85
             AND NOT EXISTS (SELECT 1 FROM review_decisions r WHERE r.case_id = c.id)
           ORDER BY created_at DESC LIMIT ?""",
        (n,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def backfill_empty_resolutions(db_path: str) -> int:
    """回填 SQLite cases 表里 resolution 为空的记录。

    原因：早期 demo seed_cases / demo_scenarios 生成的案例可能只有 problem_desc 没写 resolution，
    直接调 KEA sync 会把空字符串写到多维表格。运营审核时看不到解决方案 = 不知道审什么。

    Returns:
        回填的记录数。
    """
    # 按 problem_type 准备模板（轮询分配，避免全部 case 用同一个 resolution）
    templates = {
        "拒付": [
            "启用 3DS 2.0 + 接入 Verifi RDR/CDRN 提前拦截高风险交易",
            "联系卡组织提供拒付凭证 + 重新提交申诉材料",
            "补充 3DS 验证 + 卡组织 RDR/CDRN 注册",
            "商户补充发货证明 + 拒付 reason code 处理",
        ],
        "支付失败": [
            "更换支付通道 + 引导用户更换卡组织",
            "启用 3DS 验证 + 接入防欺诈引擎",
        ],
        "咨询": ["提供商户操作文档 + 1v1 引导"],
        "退款异常": ["联系支付通道核对 + 手工发起退款"],
    }
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, problem_type FROM cases WHERE resolution = '' OR resolution IS NULL"
    ).fetchall()
    if not rows:
        conn.close()
        return 0
    print(f"[OK] 回填空 resolution：{len(rows)} 条")
    for i, (case_id, pt) in enumerate(rows):
        pool = templates.get(pt, ["联系运营处理"])
        resolution = pool[i % len(pool)]
        conn.execute("UPDATE cases SET resolution = ? WHERE id = ?", (resolution, case_id))
        print(f"  {case_id[:35]} ({pt}): {resolution[:40]}")
    conn.commit()
    conn.close()
    return len(rows)


def dedup_bitable() -> int:
    """清理飞书多维表格 review_decisions 重复记录（按 case_id 留最新决策时间）。

    防止 seed 重跑产生重复。返回值：删除的记录数。
    """
    import httpx

    env_text = Path(r'E:\ai-pioneer\.env').read_text(encoding='utf-8')
    env = {}
    for line in env_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

    token = httpx.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']},
        timeout=10,
    ).json()['tenant_access_token']
    headers = {'Authorization': 'Bearer ' + token}
    app_token = env['FEISHU_BTABLE_APP_TOKEN']
    review_table_id = env['FEISHU_BTABLE_REVIEW_DECISIONS_TABLE_ID']

    r = httpx.get(
        f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{review_table_id}/records',
        headers=headers, params={'page_size': 500},
        timeout=15,
    )
    items = (r.json().get('data') or {}).get('items') or []
    latest = {}
    for it in items:
        f = it.get('fields', {}) or {}
        case_id = f.get('案例ID', '')
        if not case_id:
            continue
        ts = f.get('决策时间', 0) or 0
        if case_id not in latest or ts > latest[case_id][1]:
            latest[case_id] = (it['record_id'], ts)

    deleted = 0
    for it in items:
        case_id = it.get('fields', {}).get('案例ID', '')
        if case_id and latest.get(case_id, (None, 0))[0] != it['record_id']:
            httpx.delete(
                f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{review_table_id}/records/{it["record_id"]}',
                headers=headers, timeout=15,
            )
            deleted += 1
    print(f"[OK] bitable 去重：删 {deleted} 条，剩 {len(latest)} 条唯一 case")
    return deleted


def fetch_bitable_case_ids() -> set[str]:
    """拉 bitable review_decisions 表所有 case_id 集合（用于去重）。"""
    import httpx

    env_text = Path(r'E:\ai-pioneer\.env').read_text(encoding='utf-8')
    env = {}
    for line in env_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

    token = httpx.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']},
        timeout=10,
    ).json()['tenant_access_token']
    headers = {'Authorization': 'Bearer ' + token}
    app_token = env['FEISHU_BTABLE_APP_TOKEN']
    review_table_id = env['FEISHU_BTABLE_REVIEW_DECISIONS_TABLE_ID']

    r = httpx.get(
        f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{review_table_id}/records',
        headers=headers, params={'page_size': 500},
        timeout=15,
    )
    items = (r.json().get('data') or {}).get('items') or []
    return {it.get('fields', {}).get('案例ID', '') for it in items if it.get('fields', {}).get('案例ID')}


def main():
    db_path = "data/oceanmate.db"

    # 0a) 回填 SQLite cases 表里空的 resolution（避免 bitable 解决方案列空）
    backfill_empty_resolutions(db_path)

    # 0b) 清理飞书多维表格里的重复 case（保留每个 case_id 最新一条）
    try:
        dedup_bitable()
    except Exception as e:
        print(f"[WARN] bitable 去重失败（非阻断）：{e}")

    # 拉 bitable 现有 case_id 集合（避免重复入审）
    existing_in_bitable = fetch_bitable_case_ids()

    # 1) 选候选 case
    candidate_ids = select_unreviewed_cases(db_path, n=10)  # 多选些，过滤后再挑
    if not candidate_ids:
        print("[WARN] 没有未审的 conf=0.85 case 可选。录屏前已全部入审/通过。")
        return

    # 过滤掉 bitable 里已存在的 case_id
    case_ids = [cid for cid in candidate_ids if cid not in existing_in_bitable][:2]
    if not case_ids:
        print("[INFO] 所有候选 case 都已在 bitable 里，无需重复入审。")
        return

    print(f"[OK] 选中 {len(case_ids)} 个未审 case（已过滤 bitable 已有）:")
    for cid in case_ids:
        print(f"  - {cid}")

    # 2) 实例化 KEATool（带真实 FeishuFrontend → 写多维表格）
    db = SQLiteDatabase(db_path)
    case_repo = CaseRepository(db)
    frontend = get_feishu_frontend()  # 真实凭证 → FeishuFrontend，非 Mock
    kea = KEATool(case_repo=case_repo, embedding_meta_repo=db, frontend=frontend)

    print(f"\n[OK] KEATool 实例化完成")
    print(f"  - frontend: {type(frontend).__name__}")

    # 3) 触发 promote_to_faq（conf=0.85 → pending_review 分支）
    print(f"\n=== 触发 promote_to_faq（pending_review 分支）===")
    for cid in case_ids:
        result = kea.execute({"intent": "promote_to_faq", "case_id": cid})
        trace = result.get("trace") or {}
        print(f"  {cid}: decision={trace.get('decision')}, reason={trace.get('reason')}")
        if not result.get("pending_review"):
            print(f"    [WARN] 未进 pending_review 分支：{result}")

    # 4) 关闭
    db.close()

    # 5) 校验 SQLite review_decisions 表是否有 pending_review 记录（KEA 没写 SQLite，只写了多维表格）
    conn = sqlite3.connect(db_path)
    cnt = conn.execute(
        """SELECT COUNT(*) FROM review_decisions WHERE decision = 'pending_review'"""
    ).fetchone()[0]
    conn.close()
    print(f"\n[INFO] SQLite review_decisions 表 pending_review 记录数: {cnt}")
    print(f"[INFO] 多维表格 review_decisions 表 pending_review 记录数: 应为 {len(case_ids)}（需到飞书后台看）")


if __name__ == "__main__":
    main()
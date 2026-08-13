"""清理 routing_rules 工单池数据，让 dashboard 趋势图能看出变化。

清理项：
1. created_at 分散到最近 7 天（2026-08-07 ~ 2026-08-13），趋势图可看出分布
2. 补全 status=空 的 10 条（分配 pending/in_progress/resolved/closed）
3. 清理 problem_type="*" 和 "Webhook 回调失败" 这 2 个无效类别
   - "*" → 改成具体合法类型（按 rule_id 推断或默认 '拒付'）
   - "Webhook 回调失败" → 保留（其实合规；按用户记忆说要"过滤"展示，而不是改数据）

执行：python scripts/cleanup_dashboard_data.py
"""
from __future__ import annotations
import sys, json, time, random, hashlib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from pathlib import Path as P
import httpx

env_text = P(r'E:\ai-pioneer\.env').read_text(encoding='utf-8')
env = {}
for line in env_text.splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()


def main() -> int:
    token = httpx.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']},
        timeout=10,
    ).json()['tenant_access_token']

    app_token = env['FEISHU_BTABLE_APP_TOKEN']
    rt_id = env['FEISHU_BTABLE_ROUTING_RULES_TABLE_ID']

    headers = {'Authorization': 'Bearer ' + token}

    # 1) 拉所有记录
    print('[1/5] 拉取全部 routing_rules ...')
    all_records = []
    page_token = None
    for _ in range(20):
        params = {'page_size': 500}
        if page_token: params['page_token'] = page_token
        r = httpx.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{rt_id}/records',
            headers=headers, params=params, timeout=15,
        )
        d = r.json()
        items = (d.get('data') or {}).get('items') or []
        all_records.extend(items)
        if not (d.get('data') or {}).get('has_more'): break
        page_token = (d.get('data') or {}).get('page_token')
    print(f'  拉取 {len(all_records)} 条')

    # 2) 计算每条记录的 cleanup 计划
    print()
    print('[2/5] 计算 cleanup 计划 ...')
    random.seed(42)  # 确定性输出，方便复现

    # 7 天分散（2026-08-07 ~ 2026-08-13，base 凌晨 02:00 + 当日随机偏移）
    base_day = 7  # 8/7 = day 7
    end_day = 13  # 8/13 = day 13
    days_span = end_day - base_day + 1  # 7 days

    updates = []  # list of (record_id, fields_dict)
    for i, rec in enumerate(all_records):
        rid = rec.get('record_id')
        f = rec.get('fields', {})
        new_fields = {}

        # 2.1) spread created_at 到 7 天
        # 决定分配到哪一天（按 index + random）
        day_offset = (i + random.randint(0, days_span - 1)) % days_span
        # 在当天内的随机小时（让分布更真实）
        hour = random.randint(8, 22)
        minute = random.randint(0, 59)
        ts = int(time.mktime(time.strptime(f'2026-08-{base_day + day_offset:02d} {hour:02d}:{minute:02d}:00', '%Y-%m-%d %H:%M:%S'))) * 1000
        new_fields['created_at'] = ts

        # 2.2) 补全 status 空的
        cur_status = f.get('status')
        if cur_status is None or cur_status == '':
            # 按 priority 决定：high → in_progress / pending，low → resolved
            prio = f.get('priority', 'medium')
            if prio == 'high':
                new_fields['status'] = random.choice(['in_progress', 'pending', 'pending'])
            elif prio == 'low':
                new_fields['status'] = random.choice(['resolved', 'resolved', 'closed'])
            else:
                new_fields['status'] = random.choice(['pending', 'in_progress', 'resolved'])

        # 2.3) 清理 problem_type="*" → 默认 '拒付'
        if f.get('problem_type') == '*':
            new_fields['problem_type'] = '拒付'

        # 注意：'Webhook 回调失败' 是合法类型（per input_schema enum），保留
        # 仅在 dashboard 配置时过滤展示即可

        if new_fields:
            updates.append((rid, new_fields))

    print(f'  共 {len(updates)} 条记录需要更新')

    # 3) 批量更新（飞书支持单条 update，每次最多 1 条）
    print()
    print('[3/5] 应用更新（逐条）...')
    success = 0
    failed = []
    for rid, fields in updates:
        try:
            r = httpx.put(
                f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{rt_id}/records/{rid}',
                headers={**headers, 'Content-Type': 'application/json'},
                json={'fields': fields},
                timeout=15,
            )
            d = r.json()
            if d.get('code') == 0:
                success += 1
            else:
                failed.append((rid, fields, d.get('msg')))
        except Exception as e:
            failed.append((rid, fields, str(e)))
    print(f'  成功 {success}/{len(updates)}')
    if failed:
        print(f'  失败 {len(failed)} 条：')
        for rid, fields, msg in failed[:5]:
            print(f'    {rid}: {msg}')

    # 4) 验证最终分布
    print()
    print('[4/5] 验证最终分布 ...')
    final = []
    page_token = None
    for _ in range(20):
        params = {'page_size': 500}
        if page_token: params['page_token'] = page_token
        r = httpx.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{rt_id}/records',
            headers=headers, params=params, timeout=15,
        )
        d = r.json()
        items = (d.get('data') or {}).get('items') or []
        final.extend(items)
        if not (d.get('data') or {}).get('has_more'): break
        page_token = (d.get('data') or {}).get('page_token')

    type_count = {}
    status_count = {}
    date_count = {}
    for r in final:
        f = r.get('fields', {})
        type_count[f.get('problem_type', '-')] = type_count.get(f.get('problem_type', '-'), 0) + 1
        status_count[f.get('status', '-')] = status_count.get(f.get('status', '-'), 0) + 1
        ca = f.get('created_at')
        if ca:
            if isinstance(ca, (int, float)):
                if ca > 1e12: ca = ca / 1000
                dt = time.strftime('%Y-%m-%d', time.gmtime(ca + 8 * 3600))  # UTC+8
            else:
                dt = str(ca)[:10]
            date_count[dt] = date_count.get(dt, 0) + 1
    print(f'  problem_type: {type_count}')
    print(f'  status: {status_count}')
    print(f'  created_at 分布: {sorted(date_count.items())}')

    print()
    print('[5/5] cleanup 完成')
    return 0


if __name__ == "__main__":
    sys.exit(main())
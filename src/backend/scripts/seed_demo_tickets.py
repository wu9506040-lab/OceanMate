"""Seed 模拟工单到 routing_rules 表，让 dashboard 有真实数据看。

策略：
- 复用 routing_rules 表（10 条基础规则）+ 加 ticket_001 ~ ticket_050 共 50 条模拟工单
- created_at 分布在近 7 天（每天 ~7 条）
- problem_type 4 类：拒付、支付失败、退款异常、咨询
- priority 3 类：high、medium、low（按真实分布）
- status 3 类：pending / in_progress / resolved
"""
import os
import sys
import json
import time
import random
import httpx

sys.path.insert(0, '.')
env_path = '../../.env'
env = {}
with open(env_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
for k, v in env.items():
    os.environ[k] = v

token = httpx.post(
    'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']},
    timeout=10,
).json()['tenant_access_token']
app_token = env['FEISHU_BTABLE_APP_TOKEN']
rr_table = env['FEISHU_BTABLE_ROUTING_RULES_TABLE_ID']

# 基础数据：4 类问题、3 类优先级、3 类状态
PROBLEM_TYPES = ['拒付', '支付失败', '退款异常', '咨询']
PRIORITIES = ['high', 'high', 'high', 'medium', 'medium', 'medium', 'medium', 'low']
STATUSES = ['pending', 'in_progress', 'resolved']
ASSIGNEES = {
    '拒付': '财务团队-争议处理',
    '支付失败': '技术团队-L2（VIP 专线）',
    '退款异常': '财务团队-争议处理',
    '咨询': '商户成功团队',
}
SLA = {'high': 4, 'medium': 8, 'low': 24}
NOTIFY = {
    '拒付': '飞书财务群',
    '支付失败': '飞书技术群',
    '退款异常': '飞书财务群',
    '咨询': '飞书商户成功群',
}

# 生成 50 条工单，覆盖近 7 天
records = []
now_ms = int(time.time() * 1000)
day_ms = 24 * 3600 * 1000
for i in range(1, 51):
    ptype = random.choice(PROBLEM_TYPES)
    prio = random.choice(PRIORITIES)
    status = random.choice(STATUSES) if ptype != '咨询' else random.choice(['resolved', 'resolved', 'in_progress'])
    # 时间：随机分布在过去 7 天
    days_ago = random.randint(0, 6)
    hour_offset = random.randint(0, 23)
    created_ms = now_ms - days_ago * day_ms - hour_offset * 3600 * 1000
    # 解决时长（仅 resolved 有）
    resolution_hours = random.randint(1, 12) if status == 'resolved' else 0

    rec = {
        'rule_id': f'tkt_2026_08_{i:03d}',
        'problem_type': ptype,
        'priority': prio,
        'tier': random.choice(['vip', 'vip', 'standard', 'standard', 'standard']),
        'assignee': ASSIGNEES[ptype],
        'sla_hours': SLA[prio],
        'notification_channel': NOTIFY[ptype],
        'status': status,
        # created_at 字段类型 1001 是 created_time 类型，bitable 会自动填创建时间
        # 这里我们用类型 1 (文本) 模拟，存 ISO 时间
        # 实际上 created_at 是 type=1001，不能从外部写入，用 created_at 文本字段
    }
    records.append(rec)

# 批量写入（每批 1000，飞书限制）
url_api = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{rr_table}/records/batch_create'
print(f'[{len(records)}] 准备批量写入模拟工单到 routing_rules 表')
r = httpx.post(
    url_api,
    headers={'Authorization': f'Bearer {token}'},
    json={'records': [{'fields': rec} for rec in records]},
    timeout=30,
)
d = r.json()
print(f'  code: {d.get("code")}')
print(f'  msg: {d.get("msg")}')
created = d.get('data', {}).get('records', [])
print(f'  ✅ 写入 {len(created)} 条模拟工单')

# 验证总数
r = httpx.get(
    f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{rr_table}/records',
    headers={'Authorization': f'Bearer {token}'},
    params={'page_size': 1},
    timeout=10,
)
total = r.json().get('data', {}).get('total', 0)
print(f'  表内总数: {total} 条（基础 10 + 模拟 50 = 应为 60）')
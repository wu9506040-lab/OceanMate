"""验证 send_private 真实链路（避开 bash 转义问题）。"""
import os
import sys
import json
import httpx

sys.path.insert(0, '.')

# 加载 .env
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

token_resp = httpx.post(
    'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']},
    timeout=10,
).json()
token = token_resp['tenant_access_token']

user_id = env['FEISHU_TEAM_TECH_L2_OPEN_ID']
print(f'收件人 open_id: {user_id}')
print()

briefing_text = (
    '\U0001f4e8 **\u65b0\u5de5\u5355\u4ea4\u63a5\u7b80\u62a5\uff08\u771f\u5b9e\u94fe\u8def\u9a8c\u8bc1\uff09**\n\n'
    '**\u5de5\u5355 ID**\uff1atkt_real_test_001\n'
    '**\u5546\u6237 ID**\uff1aM_US_VIP_001\n'
    '**\u95ee\u9898\u7c7b\u578b**\uff1a\u62d2\u4ed8\n'
    '**\u4f18\u5148\u7ea7**\uff1ahigh\n'
    '**SLA**\uff1a4 \u5c0f\u65f6\n\n'
    '**\u95ee\u9898\u6458\u8981**\uff1a\n'
    'US \u7ad9 Visa 13.1 \u6570\u5b57\u5546\u54c1\u62d2\u4ed8\u9ad8\u53d1\n\n'
    '**\ud83e\udd16 AI \u6839\u56e0\u5206\u6790**\uff1a\n'
    '- \u6570\u5b57\u5546\u54c1\u672a\u63d0\u4f9b\u5b9e\u7269\u7b7e\u6536\u51ed\u8bc1\n'
    '- 3DS \u914d\u7f6e\u8986\u76d6\u7387\u4e0d\u8db3\n\n'
    '**\ud83d\udca1 AI \u5efa\u8bae\u5904\u7406**\uff1a\n'
    '1. \u5347\u7ea7 3DS 2.0 \u5168\u8986\u76d6\n'
    '2. \u542f\u7528 Verifi RDR/CDRN \u63d0\u524d\u62e6\u622a\n'
    '3. \u51c6\u5907\u6570\u5b57\u5546\u54c1\u4ea4\u4ed8\u51ed\u8bc1\u6a21\u677f\n\n'
    '\u2192 \u6765\u81ea .env \u771f\u5b9e\u6536\u4ef6\u4eba\u94fe\u8def\u9a8c\u8bc1'
)

content_json = json.dumps({'text': briefing_text}, ensure_ascii=False)
print('[1] \u53d1\u9001\u79c1\u6709\u6d88\u606f\uff08\u542b\u7b80\u62a5 markdown\uff09')
r = httpx.post(
    'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
    headers={'Authorization': f'Bearer {token}'},
    json={'receive_id': user_id, 'msg_type': 'text', 'content': content_json},
    timeout=15,
)
d = r.json()
print(f'  HTTP code: {d.get("code")}')
print(f'  msg: {d.get("msg")}')
msg_id = d.get('data', {}).get('message_id')
print(f'  message_id: {msg_id}')

if d.get('code') == 0:
    print()
    print('\u2705 \u771f\u5b9e\u94fe\u8def\u9a8c\u8bc1\u901a\u8fc7\uff01')
    print('   \u4f60\u98de\u4e66\u91cc\u5e94\u8be5\u5df2\u7ecf\u6536\u5230\u8fd9\u6761\u79c1\u804a briefing')
else:
    print()
    print(f'\u274c \u5931\u8d25: {d}')
# Runbook: 在飞行社企业里重建 3 张多维表

> **背景**：原表在测试企业，应用身份权限没开+没被加为协作者，91403 Forbidden。
> **目标**：在飞行社企业建表+导 143 条数据+更新 .env+验证读写。

---

## 1. 准备工作（开发需要什么）

| 必备项 | 来源 |
|--------|------|
| `cli_aaf8271657f9dbb5` 应用身份（已有） | 当前 `.env` 里 |
| 飞行社企业管理员权限 | 找 zwyyy7 或管理员开 |
| 当前脚本 `src/backend/scripts/seed_bitables.py` | 已有，**不用改** |
| 数据源 3 个 JSON | `docs/data/payment_error_cases.json` + `payment_methods.json` + `ticket_routing_rules.json` |

---

## 2. 执行步骤（10 分钟）

### Step 1：在飞行社企业创建一个空多维表（2 分钟，手动）

1. 打开飞行社 → 新建多维表格 → 任意名字（如"OceanMate"）
2. URL 形如 `https://feishu.cn/base/<APP_TOKEN>`，**记下 APP_TOKEN**
3. （可选）把应用 `cli_aaf8271657f9dbb5` 加为协作者（设置 → 分享 → 添加应用 → 给予「可管理」权限）

### Step 2：更新 `.env`（30 秒）

**当前（错的）**：
```
FEISHU_BTABLE_APP_TOKEN=BMbLbEuIsaCpoGs9F1XcEgG4nGf
FEISHU_BTABLE_TABLE_ID=<PLACEHOLDER_BTABLE_TABLE_ID>
FEISHU_BTABLE_ERROR_CODES_TABLE_ID=tblZlbWrzlYMEJaV
FEISHU_BTABLE_PAYMENT_METHODS_TABLE_ID=tblkwdkyaWKJrFJI
FEISHU_BTABLE_ROUTING_RULES_TABLE_ID=tblvcNOegLvJjBTi
```

**改为**：
```
FEISHU_BITABLE_APP_TOKEN=<新 APP_TOKEN>     ← 重点：有 I 的版本
FEISHU_BTABLE_APP_TOKEN=<新 APP_TOKEN>       ← 也写一份兼容
FEISHU_BTABLE_TABLE_ID=tbl_auto_filled      ← 脚本会自动填，保留占位即可
FEISHU_BTABLE_ERROR_CODES_TABLE_ID=tbl_auto_filled
FEISHU_BTABLE_PAYMENT_METHODS_TABLE_ID=tbl_auto_filled
FEISHU_BTABLE_ROUTING_RULES_TABLE_ID=tbl_auto_filled
```

> 注：脚本 `seed_bitables.py` 读完字段后会**自动创建 3 张子表 + 打印新 table_id**，开发者把打印的 3 个 table_id 回填到 .env。

### Step 3：跑脚本（5 分钟）

```bash
cd E:\ai-pioneer\src\backend
python scripts/seed_bitables.py
```

脚本会自动：
- 读 3 个 JSON 数据源
- 在新 APP_TOKEN 下建 3 张表（error_codes / payment_methods / routing_rules）
- 批量导入 117+16+10 = 143 条数据
- 打印 3 个新 table_id

### Step 4：把 table_id 写回 `.env`（30 秒）

复制脚本输出的 3 个 `table_id`，覆盖 .env 里 `tbl_auto_filled` 三个占位符。

### Step 5：验证读写（2 分钟）

```bash
cd E:\ai-pioneer\src\backend
python -c "
import os, sys; sys.path.insert(0, '.')
env_path = '../../.env'
env = {}
with open(env_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
for k, v in env.items(): os.environ[k] = v

import httpx
token = httpx.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
               json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']}, timeout=10).json()['tenant_access_token']
app_token = env['FEISHU_BITABLE_APP_TOKEN'] or env['FEISHU_BTABLE_APP_TOKEN']

for name, tid in [('error_codes', env['FEISHU_BTABLE_ERROR_CODES_TABLE_ID']),
                  ('payment_methods', env['FEISHU_BTABLE_PAYMENT_METHODS_TABLE_ID']),
                  ('routing_rules', env['FEISHU_BTABLE_ROUTING_RULES_TABLE_ID'])]:
    r = httpx.get(f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/records',
                  headers={'Authorization': f'Bearer {token}'}, params={'page_size': 1}, timeout=10)
    d = r.json()
    total = d.get('data', {}).get('total', 0)
    print(f'{name:18s}: code={d.get(\"code\")}, total={total}')
"
```

**预期输出**：
```
error_codes        : code=0, total=117
payment_methods    : code=0, total=16
routing_rules      : code=0, total=10
```

---

## 3. 完成后告诉 zwyyy7

回填这 4 个变量：

```
新 APP_TOKEN = ???
新 error_codes_table_id   = tbl???
新 payment_methods_table_id = tbl???
新 routing_rules_table_id  = tbl???
```

---

## 4. 配套后续

zwyyy7 拿到新凭证后会做：
1. 跑完整 run_all 6 个 demo（验证 PDA / MSA / TRA / KEA 都用新表）
2. 跑 `test_real_feishu_e2e.py` 端到端验证
3. 在飞行社后台给 3 张表配运营看板视图
4. 截图嵌入 `docs/reports/submission.md`

---

## 附：脚本核心字段（3 张表）

**error_codes**（117 条）：error_code_id / error_code / country / channel / problem_type / severity / rule_description / trigger_condition / recommended_action / source

**payment_methods**（16 条）：method_id / method / country / min_amount / max_amount / settlement / fee_rate / currency / description / rationale

**routing_rules**（10 条）：rule_id / problem_type / priority / tier / assignee / sla_hours / notification_channel
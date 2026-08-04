# SOP-TRA · Ticket Routing Agent（工单智能路由）标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用组件**：`app/agents/tra/tool.py`
> **对位架构**：4 Tool 之工单路由（详见 `docs/architecture/oceanmate_v2.md` §2）
> **对位官方命题**：方向 ③「智能工单路由」
> **关联文件**：
> - 实现：`src/backend/app/agents/tra/tool.py`
> - 路由规则：`docs/data/ticket_routing_rules.json`（10 条规则，OP 真实生产 = 飞书多维表格）
> - 测试：`src/backend/tests/test_tra_sop.py`（25/25）
> - 集成：`src/backend/app/agents/orchestrator/orchestrator.py` `_route_tra`

---

## 1. SOP 总览（8 子 SOP · 25 测试）

| 编号 | 场景 | 类型 | 测试方法 | 状态 |
|------|------|------|---------|------|
| SOP-TRA-001-A | 4 层规则匹配优先级（exact > wc_p > wc_p_m > default） | 正向 | `TestRuleMatchPriority::*` | ✅ |
| SOP-TRA-001-B | DB + memory 双写持久化，DB 失败自动 fallback | 正向 | `TestPersistence::*` | ✅ |
| SOP-TRA-001-C | query_status 查工单（DB + memory + not_found） | 正向 | `TestQueryStatus::*` | ✅ |
| SOP-TRA-002-A | 缺 problem_type → 友好错误（不抛 raw exception） | 逆向（降级） | `TestFriendlyDegradation::test_missing_problem_type_*` | ✅ |
| SOP-TRA-002-B | 路由规则文件不存在 → 友好兜底 | 逆向（降级） | `TestFriendlyDegradation::test_no_rules_loaded_*` | ✅ |
| SOP-TRA-002-C | 规则 JSON 热更新（rehearsal 飞书同步场景） | 运维 | `TestFriendlyDegradation::test_reload_rules_*` | ✅ |
| SOP-TRA-002-D | DB 写入异常 → in-memory 兜底（保证 Demo 不断） | 逆向（容错） | `TestPersistence::test_db_failure_*` | ✅ |
| SOP-TRA-INT-001 | Orchestrator 关键词分流 → TRA 自动选 route / query | 集成 | `TestTRAEnd2End::*` | ✅ |

**当前 SOP 矩阵总进度**：10/10 主体完成 ✅

---

## 2. 规则匹配优先级（SOP-TRA-001-A · 核心）

### 2.1 4 层降级链

```
┌────────────────────────────────────────────────────────────┐
│  Layer 1 · exact                                           │
│  problem_type == X AND priority == Y AND tier == Z        │
│  → match_level = "exact"                                  │
│  例：(支付失败, high, vip) → rule_demo_payfail_vip_high    │
│      SLA 2h · 通知：飞书 VIP 群 + 电话                      │
└────────────────────────────────────────────────────────────┘
                          │ 不命中
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 2 · priority_wildcard                              │
│  problem_type == X AND priority == Y AND tier == "*"      │
│  → match_level = "priority_wildcard"                      │
│  例：(支付失败, high, standard) → rule_demo_payfail_any    │
│      SLA 4h · 通知：飞书技术群                              │
└────────────────────────────────────────────────────────────┘
                          │ 不命中
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 3 · problem_wildcard（降级到 medium + tier 通配）   │
│  problem_type == X AND priority == "medium" AND tier == "*"│
│  → match_level = "problem_wildcard"                       │
│  例：(支付失败, low, standard) → rule_demo_payfail_...    │
│      SLA 8h · 通知：飞书技术群                              │
└────────────────────────────────────────────────────────────┘
                          │ 不命中
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 4 · default_fallback                               │
│  problem_type == "*" AND priority == "medium" AND tier=="*"│
│  → match_level = "default_fallback"                       │
│  例：任何未知 (problem_type, priority, tier)              │
│      SLA 24h · 通知：飞书通用群                             │
└────────────────────────────────────────────────────────────┘
```

### 2.2 匹配规则示例（10 条真实规则）

| problem_type | priority | tier | assignee | SLA | 通知渠道 |
|--------------|----------|------|----------|-----|----------|
| 支付失败 | high | vip | 技术团队-L2（VIP 专线）| **2h** | 飞书 VIP 群 + 电话 |
| 支付失败 | high | premium | 技术团队-L2 | 4h | 飞书技术群 |
| 支付失败 | medium | standard | 技术团队-L1 | 8h | 飞书技术群 |
| 支付失败 | high | * | 技术团队-L2 | 4h | 飞书技术群 |
| 拒付 | high | * | 财务团队-争议处理 | 4h | 飞书财务群 + 审批流 |
| 拒付 | medium | * | 财务团队-争议处理 | 12h | 飞书财务群 |
| 退款异常 | high | * | 财务团队-退款 | 6h | 飞书财务群 |
| 退款异常 | medium | * | 财务团队-退款 | 24h | 飞书财务群 |
| Webhook 回调失败 | high | * | 技术团队-Webhook | 4h | 飞书技术群 + PagerDuty |
| *（默认兜底）| medium | * | 通用支持团队 | 24h | 飞书通用群 |

> **设计取舍**：
> - VIP 客户的 high SLA 是 2h（普通 high 是 4h）—— 评审可演示"差异化服务"
> - 拒付的 medium SLA 是 12h（默认是 24h）—— 财务类有时效要求

### 2.3 断言清单

| # | 断言 |
|---|------|
| 1 | `match_level` 为 4 选 1 字符串（exact/priority_wildcard/problem_wildcard/default_fallback）|
| 2 | `assignee` 与 SLA 在所有层都正确返回（默认兜底层仍返回 assignee="通用支持团队"）|
| 3 | `trace.rules_loaded` 等于实际加载的规则数 |
| 4 | `rule_id` 与规则表 `id` 一一对应（评审可追溯到 JSON 文件）|

---

## 3. 持久化策略（SOP-TRA-001-B + SOP-TRA-002-D）

### 3.1 双写策略（DB + Memory）

```
route_ticket 触发：
  1. 查规则表 → 拿 rule
  2. 生成 ticket_id (tkt_<uuid12>) + feishu_record_id (fss_<uuid16>)
  3. ticket_repo.create(Ticket(...))    ← DB 写入
  4. _memory_store[ticket_id] = {...}    ← Memory 缓存（规则元数据）
  5. 返回 trace.persisted_via = "both"
```

**为什么双写？**
- DB 是事务持久化（SQLite `tickets` 表 + 11 索引）
- Memory 缓存 Ticket 模型外字段（rule_id / sla_hours / notification_channel）
- query_status 时合并两者：DB 给 Ticket 字段，memory 给 rule 字段

### 3.2 降级路径（DB 失败）

```python
try:
    repo.create(ticket)
    return "both"
except Exception:
    return "memory"  # DB 失败但工单仍存在（PoC 演示保证不断）
```

> **设计取舍**：DB 失败时直接降级到 memory 不抛异常（避免演示"系统错误"），同时仍会记录 `trace.feishu_record_id` 用于事后对账。

### 3.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | DB 模式 + 完整写入 | `persisted_via == "both"`，DB 中可查 `tkt_xxx` |
| 2 | 无 repo 默认实例 | `persisted_via == "memory"`，`_memory_store` 有记录 |
| 3 | DB 抛异常（monkeypatch） | `persisted_via == "memory"`，工单仍创建成功 |

---

## 4. query_status 子能力（SOP-TRA-001-C）

### 4.1 行为

```python
tra.execute({"intent": "query_status", "ticket_id": "tkt_xxx"})
→ {
    "status": "pending" | "not_found",
    "ticket_id": "tkt_xxx",
    "problem_type": "...",
    "rule_id": "rule_demo_webhook_high",
    "sla_hours": 4,
    "match_level": "queried",
    ...
}
```

### 4.2 优先级

1. 先查 DB（`ticket_repo.get_by_id`）
2. 找不到 / DB 异常 → 查 memory
3. 都没有 → `status="not_found"`（不抛异常，trace 含 `error`）

### 4.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 查 DB 已建工单 | status=pending，所有字段回显完整 |
| 2 | 查 memory 工单 | status=pending，match_level="queried" |
| 3 | 查不存在 ID | status=not_found，trace.error 有说明 |
| 4 | 缺 ticket_id | status=not_found，trace.error 含 "ticket_id 必填" |

---

## 5. Orchestrator 集成（SOP-TRA-INT-001）

### 5.1 关键词识别 → 自动选 intent

```python
# Orchestrator._classify_intent
"我的工单状态" → ticket_routing 命中
                 ↓
# Orchestrator._route_tra
if ctx.get("ticket_id"):
    sub_intent = "query_status"
elif ctx.get("problem_type"):
    sub_intent = "route_ticket"
else:
    sub_intent = "route_ticket"  # 默认走 route（让 TRA 引导补全）
```

### 5.2 典型链 PDA → TRA（端到端评审演示）

```
商户提问："我的 Visa 支付失败 ERR_X_001"
  ↓ Orchestrator
  关键词命中 → intent=payment_diagnosis → PDATool
  ↓ PDA
  output: {problem_type: "支付失败", confidence: 0.9, next_agent: "Ticket Routing Agent", ...}
  ↓ Orchestrator（typical）with ctx 含 problem_type/priority/tier
  识别 ticket_routing → TRATool.route_ticket
  ↓ TRA
  匹配 rule_demo_payfail_vip_high → 创建 tkt_xxx → assignee=技术团队-L2（VIP 专线）
  ↓ Orchestrator 输出
  trace.sub_intent = "route_ticket"
```

### 5.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 关键词「工单」+ ctx 含 problem_type | intent=ticket_routing, sub_intent=route_ticket |
| 2 | 关键词「工单状态」+ ctx 含 ticket_id | intent=ticket_routing, sub_intent=query_status |
| 3 | TRA 未注册 | error_code=TOOL_NOT_REGISTERED，hint="TRA 待实现" |

---

## 6. 真实环境差异

| 项 | Demo（PoC）| 真实生产 |
|---|---|---|
| 规则存储 | 本地 JSON 文件 | 飞书多维表格 + 本地缓存 |
| 规则更新 | `reload_rules(new_path)` 手动 | 飞书 SDK webhook 自动同步 |
| 通知 | `notification_channel` 字段值（字符串）| 调飞书机器人群 + PagerDuty API |
| ID 生成 | UUID4 截断 | 飞书 record_id（创建记录返回）|
| SLA 计时 | `now() + sla_hours`（PoC 估算）| 飞书审批流 schema + 定时巡检 |
| 人员 | `assignee` 字符串 | 飞书 user_open_id + 自动派单人 |
| 工单存储 | SQLite `tickets` 表 | 飞书工单系统 + 多维表格双写 |

---

## 7. 已知约束与避坑

| # | 约束 / 坑 | 解决方式 |
|---|----------|---------|
| 1 | `tickets.merchant_id` 有 FK 到 `merchants.id`，非 NULL merchant_id 必须先有 merchant 行 | 测试 fixture 预置 merchant；生产环境商户档案同步先于工单创建 |
| 2 | Windows 中文路径 + GBK 默认编码 → 规则 JSON 写入失败 | 所有 `Path.write_text()` 显式 `encoding="utf-8"` |
| 3 | SQLite 默认无 FK 约束（必须 `PRAGMA foreign_keys = ON`）| `SQLiteDatabase.__init__` 已开启 |
| 4 | Ticket 模型不含 `rule_id` 等路由字段 | 用 `_memory_store` 缓存（DB-Memory 双写策略）|
| 5 | 加载规则失败不报错（静默 `_rules=[]`）| `trace.rules_loaded` 暴露实际加载数，0 时返 not_found 友好提示 |
| 6 | `match_level` 命名需可读 | 4 选 1 enum：exact / priority_wildcard / problem_wildcard / default_fallback |

---

## 附录 A · 评审可演示命令

### A.1 跑测试

```bash
cd src/backend
python -m pytest tests/test_tra_sop.py -v           # 仅 TRA（25 测试）
python -m pytest tests/ -q                           # 全套（125+）
```

### A.2 端到端：商户咨询 → TRA 路由 + 查状态

> **注意**：当前 Orchestrator 是**单意图分流**（一条 query 只调一个 Tool）。
> PDA → TRA 的"一条龙自动派单"在真实生产里通过 conversation + Tool 编排实现；
> 本 SOP 演示 TRA 自身两条独立路径：

```python
from app.agents.orchestrator import Orchestrator
from app.agents.tra import TRATool

orch = Orchestrator()
orch.register_tool(TRATool())

# === 步骤 1：商户说"我要开个工单" → TRATool.route_ticket ===
result = orch.route(
    "我要开个工单",
    merchant_context={
        "merchant_id": "<DEMO_MERCHANT_ID>",
        "problem_type": "支付失败",
        "priority": "high",
        "tier": "vip",
    },
)

print(f"意图: {result['intent']}")
print(f"Tool: {result['tool_name']}")
print(f"子意图: {result['trace']['sub_intent']}")
print(f"工单: {result['tool_result']['data']['ticket_id']}")
print(f"分配: {result['tool_result']['data']['assignee']}")
print(f"SLA: {result['tool_result']['data']['sla_hours']}h")
print(f"通知: {result['tool_result']['data']['notification_channel']}")
print(f"匹配级别: {result['tool_result']['data']['match_level']}")
print(f"持久化: {result['tool_result']['data']['trace']['persisted_via']}")
```

### A.3 端到端：商户查询已建工单的状态

```python
# 接着上面，再问状态
ticket_id = result['tool_result']['data']['ticket_id']
result2 = orch.route(
    "我的工单状态如何",
    merchant_context={"ticket_id": ticket_id},
)

print(f"子意图: {result2['trace']['sub_intent']}")
print(f"工单状态: {result2['tool_result']['data']['status']}")
print(f"问题类型: {result2['tool_result']['data']['problem_type']}")
print(f"处理人: {result2['tool_result']['data']['assignee']}")
```

### A.4 评审可演示点（5 个）

| # | 演示项 | 评审看点 |
|---|------|---------|
| 1 | `mcp_tool_spec` 输出 | 标准 MCP 协议格式，对位 AtoA 挑战 |
| 2 | `match_level` 4 层降级链 | 复杂业务规则工程化 |
| 3 | DB + Memory 双写 | 真实生产级容错（数据库挂了也不挂服务）|
| 4 | `reload_rules` 热更新 | 飞书多维表格同步入口 |
| 5 | Orchestrator 自动选 sub_intent | AtoA Tool 编排能力 |

---

## 附录 B · 与官方命题的对位

| OP 命题方向 | TRA 对位 | 落地 |
|------------|---------|------|
| ③ 工单智能路由 | 4 层规则匹配 + 双写持久化 + 热更新 | `tool.py` 主体 + 路由规则 JSON |
| AtoA 挑战 | MCP tool_spec 导出 | `to_mcp_tool_spec()` |
| 工单 SLA 差异化 | 4 个 match_level × priority × tier 组合 | 10 条规则表 |

---

## SOP 矩阵进度更新

| 编号 | Tool | 类型 | 状态 |
|------|------|------|------|
| SOP-TRA-001 | TRATool | 正向（路由 + 持久化 + 查询）| ✅ **Day 5 完成** |
| SOP-TRA-002 | TRATool | 逆向（友好降级 + 热更新）| ✅ **Day 5 完成** |

**当前 SOP 矩阵进度**：✅ 10/10 主体完成，Day 5 收官。

---

## 附录 C · TRA 重构建议（生产化路径）

> 当 PoC 升级到真实环境时，按以下顺序迁移：

1. **规则 JSON → 飞书多维表格**：
   - 把 `docs/data/ticket_routing_rules.json` 移到飞书多维表格 base
   - TRA 实现一个 `FeishuRuleSource` 替身，实现 `load_rules()`
   - 业务代码零改动（已协议化）

2. **SQLite tickets → 飞书工单系统**：
   - 把 `_persist_ticket` 拆成 `LocalPersist + RemotePersist`
   - 真实环境优先 write to 飞书
   - DB 退化为本地缓存层（离线场景可用）

3. **`_memory_store` → Redis**：
   - 把内存 dict 换成 Redis client
   - 跨进程共享元数据（多 Pod 部署）

4. **idempotent=True**：
   - 加 `idempotency_key` 参数（商户咨询级别的去重）
   - 同一 idempotency_key 多次调用返同一 ticket_id

详见 `docs/architecture/oceanmate_v2.md` §4（替换指南）。

# OceanMate 飞书多维表 · AI 字段配置手册

> **目的**：在飞行社企业下"OceanMate 数据"多维表中**配置 2 个 AI 字段**（工单自动打 priority + intent 标签），体现"用飞书原生 AI 能力"。
> **当前状态**：规划+演示脚本就绪，待管理员实际配置。
> **预计时间**：20-30 分钟（含验证）

---

## 1. 为什么用飞书 AI 字段

| 传统做法 | 飞书 AI 字段 |
|---------|------------|
| 运营手动给每个工单打 priority | AI 自动根据 `problem_summary` 打 priority |
| 运营手动分类 intent | AI 自动打 intent 标签 |
| 每天 10000 工单 × 5 秒 = 14 小时 | 自动完成，0 人时 |
| 标签一致性差（不同运营标准不同）| 100% 一致（同一 LLM）|

---

## 2. 配置 2 个 AI 字段

### 2.1 字段 1：`ai_priority`（自动优先级）

| 配置项 | 值 |
|-------|----|
| 字段名 | `ai_priority` |
| 字段类型 | AI 字段（飞书原生）|
| 输入字段 | `problem_summary`、`affected_orders_count` |
| 处理模型 | Qwen（自定义 Prompt）|
| 输出选项 | `high` / `medium` / `low` |
| Prompt 模板 | 见 §3.1 |

### 2.2 字段 2：`ai_intent`（自动意图分类）

| 配置项 | 值 |
|-------|----|
| 字段名 | `ai_intent` |
| 字段类型 | AI 字段 |
| 输入字段 | `problem_summary` |
| 处理模型 | Qwen |
| 输出选项 | `拒付` / `退款异常` / `支付失败` / `Webhook 回调失败` / `其他` |
| Prompt 模板 | 见 §3.2 |

---

## 3. Prompt 模板（配置到飞书 AI 字段）

### 3.1 `ai_priority` Prompt

```
你是 OP 跨境支付的工单优先级判定助手。
判断以下工单应分配的优先级（high / medium / low）。

判断规则：
- high：拒付 / 大额（>5000 USD） / 商户投诉 / 系统级故障
- medium：支付失败 / 中额（500-5000 USD） / 退款异常
- low：信息咨询 / 小额（<500 USD） / FAQ 类

工单内容：{problem_summary}
受影响订单数：{affected_orders_count}

请只输出一个词：high / medium / low
```

### 3.2 `ai_intent` Prompt

```
你是 OP 跨境支付的工单意图分类助手。
判断以下工单属于哪种问题类型。

类别：
- 拒付（chargeback）相关
- 退款异常
- 支付失败
- Webhook 回调失败
- 其他

工单内容：{problem_summary}

请只输出一个类别名。
```

---

## 4. 验证脚本（无需飞书管理员权限）

```bash
cd src/backend
python scripts/verify_feishu_ai_field.py
```

**预期输出**：

```
=== 飞书 AI 字段效果验证 ===
[1/3] 加载 5 条样本工单
[2/3] 调用本地 Qwen LLM（模拟飞书 AI 字段行为）
  - ticket_001 "商户反馈 VISA 13.1 拒付...受影响的订单有 120 笔"
    → ai_priority: high ✅
    → ai_intent: 拒付 ✅
  - ticket_002 "NL iDEAL 周末无法支付"
    → ai_priority: medium ✅
    → ai_intent: 支付失败 ✅
  - ticket_003 "想了解一下你们的支付方式"
    → ai_priority: low ✅
    → ai_intent: 其他 ✅
[3/3] 一致性验证
  - 5/5 样本与人工标签一致（100%）

✅ 验证通过：飞书 AI 字段 Prompt 模板可用
```

---

## 5. 实际配置步骤（飞书管理员）

> 仅供飞书超级管理员参考，PoC 阶段可不做。

| 步骤 | 操作 | 时间 |
|------|------|------|
| 1 | 打开多维表 `tickets` 表 | 1 分钟 |
| 2 | 添加字段 → 类型选"AI 字段" | 2 分钟 |
| 3 | 字段名 `ai_priority`，复制 §3.1 Prompt | 5 分钟 |
| 4 | 添加字段 `ai_intent`，复制 §3.2 Prompt | 5 分钟 |
| 5 | 对 60 条已有工单触发"重新计算" | 2 分钟 |
| 6 | 截图存到 `docs/runbook/feishu_ai_field_screenshot.png` | 1 分钟 |

---

## 6. 未来扩展（V2.0）

| AI 字段 | 用途 | 优先级 |
|---------|------|-------|
| `ai_sla_hours` | 自动建议 SLA（基于 priority + 客户等级）| P0 |
| `ai_team` | 自动建议处理团队 | P0 |
| `ai_summary` | 工单内容一句话总结 | P1 |
| `ai_sentiment` | 商户情绪判定（生气/中性/满意）| P1 |
| `ai_similar_ticket` | 推荐相似历史工单 | P2 |

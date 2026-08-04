# SOP-ORC · Orchestrator（商户成功 AI 中枢）标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用组件**：`app/agents/orchestrator/orchestrator.py`
> **对位架构**：中枢层（详见 `docs/architecture/oceanmate_v2.md` §1）
> **关联文件**：
> - 实现：`src/backend/app/agents/orchestrator/orchestrator.py`
> - 测试：`src/backend/tests/test_orchestrator_sop.py`

---

## SOP 总览（3 子 SOP）

| 编号 | 场景 | 类型 | 测试方法 |
|------|------|------|---------|
| SOP-ORC-001-A | 关键词意图分类 → 路由到对应 Tool | 正向 | `TestIntentClassification::*` |
| SOP-ORC-001-B | 未知意图兜底到 MSA collect_profile | 逆向（降级） | `TestFallbackMechanism::*` |
| SOP-ORC-001-C | Tool 未注册 → 友好错误（不崩） | 逆向（容错） | `TestToolNotRegistered::*` |

---

## SOP-ORC-001-A · 关键词意图分类

### 1.1 适用场景

商户在飞书智能伙伴提问，Orchestrator 识别意图后调对应 Tool。

### 1.2 意图白名单（关键词）

| Intent | 关键词 |
|--------|--------|
| `payment_diagnosis` | 失败、错误码、ERR_、拒付、退款异常、Webhook 回调、3DS 失败、风控拦截、无法支付 |
| `merchant_success` | 支付方式、选什么、推荐、PWR、国家、客单价、B2B、B2C、接入、想做、准备做、开拓 |
| `ticket_routing` | 工单、派单、SLA、状态、T0、已分配、已派、转人工、客服 |
| `knowledge_evolution` | FAQ、知识库、怎么操作、如何接入、文档、教程、Merchant Console |

### 1.3 分类算法

```python
scores = {intent: count(hits) for intent, kws in INTENT_KEYWORDS}
best_intent = max(scores, key=lambda i: (scores[i], -order(i)))
```

- 评分：每个 intent 命中关键词数
- Tie-break：按 INTENT_KEYWORDS 顺序（PDA > MSA > TRA > KEA）

### 1.4 路由矩阵

| Intent | 调 Tool | 子意图逻辑 |
|--------|---------|-----------|
| `payment_diagnosis` | `payment_diagnosis` | 用 merchant_context 直接传 country/channel/error_code |
| `merchant_success` | `merchant_success` | 根据画像完整度决定 recommend_payment_methods vs collect_profile |
| `ticket_routing` | `ticket_routing` | Day 6 实现 |
| `knowledge_evolution` | `knowledge_evolution` | Day 7 实现 |

### 1.5 MSA 子意图分流

```
完整画像（4 必填都填） → sub_intent = recommend_payment_methods
缺任意字段            → sub_intent = collect_profile
```

### 1.6 断言清单

| # | 断言 |
|---|------|
| 1 | `result["intent"]` 等于识别出的 intent |
| 2 | `result["tool_name"]` 等于调用的 Tool 名 |
| 3 | `result["tool_result"]["success"] is True`（Tool 执行成功）|
| 4 | `result["trace"]["matched_keywords"]` 非空 |
| 5 | `result["trace"]["sub_intent"]` 正确（MSA 时）|
| 6 | 完整 Orchestrator 端到端跑通 |

### 1.7 真实环境差异

| 项 | Demo（关键词白名单）| 真实（LLM 动态分类）|
|---|---|---|
| 分类器 | 关键词匹配（PoC）| LLM Function Call（GPT-4 / Qwen）|
| 维护成本 | 低（改 INTENTS 常量）| 中（需 Prompt Engineering）|
| 多意图 | ❌ 单意图 | ✅（Function Call 可一次返多个 Tool 调用）|
| 上下文 | ❌ 无 | ✅（保留对话历史）|

---

## SOP-ORC-001-B · 未知意图兜底

### 2.1 适用场景

商户提问完全无关（"今天天气怎么样？"）或含糊不清。

### 2.2 兜底逻辑

```
1. 关键词匹配 → 0 个 intent 命中
2. 若 MSA Tool 已注册 → 调 MSA collect_profile（让商户补充画像）
3. 若 MSA 也未注册 → 返 INTENT_UNKNOWN 错误（兜底中的兜底）
```

### 2.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 完全无关 query + MSA 注册 | `intent="unknown_fallback_to_msa"` + MSA collect 调用成功 |
| 2 | 完全无关 query + 无任何 Tool | `intent="unknown"` + `error_code="INTENT_UNKNOWN"` |
| 3 | Tool 已识别但未注册（见 SOP-ORC-001-C）| `intent="payment_diagnosis"` + `error_code="TOOL_NOT_REGISTERED"` |

### 2.4 真实环境差异

真实环境兜底更智能：用 LLM 生成"我可能没理解您的意思，请问您是想..."的友好话术，而非简单"无法识别"。

---

## SOP-ORC-001-C · Tool 未注册容错

### 3.1 适用场景

Orchestrator 识别到 TRA 意图但 TRA Tool 还没注册（Day 4 下午 vs Day 6）。

### 3.2 设计原则

> **意图识别 ≠ Tool 可用** — 即使没注册对应 Tool，也不应该 500 / 抛异常。

### 3.3 行为

```python
def _route_tra(self, query, ctx, matched):
    if "ticket_routing" not in self.registry:
        return self._tool_not_available(
            "ticket_routing",
            hint="TRA Tool 待 Day 6 实现。如需立即处理，请联系人工客服。"
        )
    ...
```

### 3.4 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 问工单 + 无 TRA | `intent="ticket_routing"` + `error_code="TOOL_NOT_REGISTERED"` + error_message 含 "TRA Tool 待 Day 6" |
| 2 | 问知识 + 无 KEA | `intent="knowledge_evolution"` + `error_code="TOOL_NOT_REGISTERED"` |
| 3 | 不抛异常（不 500）| tool_result.success = False |

---

## 附录 A：评审可演示命令

```bash
cd src/backend

# 跑 Orchestrator SOP 测试
python -m pytest tests/test_orchestrator_sop.py -v

# 端到端：商户对话路由 demo
python -c "
from app.agents.orchestrator import Orchestrator
from app.agents.pda import PDATool
from app.agents.msa import MSATool

orch = Orchestrator()
orch.register_tool(PDATool())
orch.register_tool(MSATool())

print('=== 已注册 Tool（MCP tool_spec）===')
for spec in orch.list_tools():
    print(f'- {spec[\"name\"]}: {spec[\"description\"][:50]}')

print()
print('=== 场景 1：商户报支付失败 ===')
r1 = orch.route('我的 Visa 支付失败了', merchant_context={
    'country': 'BR', 'channel': 'Visa',
    'error_code': 'ERR_DEMO_RISK_BLOCK_BR_VISA_001',
})
print(f'  intent: {r1[\"intent\"]}')
print(f'  matched: {r1[\"trace\"][\"matched_keywords\"]}')
print(f'  problem_type: {r1[\"tool_result\"][\"data\"][\"problem_type\"]}')
print(f'  evidence: {len(r1[\"tool_result\"][\"data\"][\"evidence_chain\"])} 条')

print()
print('=== 场景 2：商户问推荐 + 完整画像 ===')
r2 = orch.route('推荐支付方式', merchant_context={
    'country': 'US', 'industry': 'fashion',
    'avg_amount': 85.0, 'target_users': 'B2C',
})
print(f'  intent: {r2[\"intent\"]}, sub_intent: {r2[\"trace\"][\"sub_intent\"]}')
print(f'  推荐: {[r[\"method\"] for r in r2[\"tool_result\"][\"data\"][\"recommendations\"]]}')

print()
print('=== 场景 3：商户问推荐 + 不完整画像 → MSA 反问 ===')
r3 = orch.route('推荐支付方式', merchant_context={'country': 'US'})
print(f'  intent: {r3[\"intent\"]}, sub_intent: {r3[\"trace\"][\"sub_intent\"]}')
print(f'  追问: {len(r3[\"tool_result\"][\"data\"][\"follow_up_questions\"])} 个')

print()
print('=== 场景 4：未知 query → 兜底 MSA ===')
r4 = orch.route('今天天气怎么样？')
print(f'  intent: {r4[\"intent\"]}')
print(f'  fallback_reason: {r4[\"trace\"][\"fallback_reason\"]}')
"
```

## 附录 B：与 AtoA / MCP 的关系

Orchestrator 当前是单进程函数调用 + ToolRegistry，与完整 AtoA 协议不同：

| 维度 | 当前（PoC）| 完整 AtoA |
|---|---|---|
| 通信 | 函数调用 | 跨进程消息（gRPC / HTTP）|
| Tool 发现 | `register_tool()` 注册 | Discovery Server（Anthropic MCP / A2A） |
| 鉴权 | ❌ 无 | ✅（OAuth / JWT）|
| 流式响应 | ❌ | ✅（SSE）|
| 状态管理 | 单次 query 无状态 | 多轮会话上下文 |

**评审意义**：Orchestrator 的接口（`route(query, ctx) → {intent, tool_result, trace}`）已与 AtoA 兼容（每次调用都返回完整状态机信息）。真实环境替换为 AtoA Client 时，业务代码（4 Tool）零改动。

详见 `docs/architecture/agent_architecture.md` §4。

---

## SOP 矩阵进度更新

| 编号 | Tool | 类型 | 状态 |
|------|------|------|------|
| SOP-ORC-001 | Orchestrator | 正逆 3 子场景 | ✅ **Day 4 完成** |

**当前 SOP 矩阵进度**：9/10 主体完成。

| 剩余 | Tool | 预计 |
|---|---|---|
| SOP-TRA-001 | TRATool | Day 6 |
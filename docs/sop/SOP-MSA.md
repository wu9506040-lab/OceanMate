# SOP-MSA · 商户成功助手（含 PWR）标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用 Tool**：`merchant_success`（MSATool）
> **对位业务**：OP 命题方向 ①（支付方式推荐 PWR）+ ④（数据协作采集）
> **关联文件**：
> - 实现：`src/backend/app/agents/msa/tool.py`
> - 测试：`src/backend/tests/test_msa_sop.py`
> - 知识库数据：`docs/data/payment_methods.json`（9 种支付方式 Demo）
> - Seed 脚本：`src/backend/scripts/seed_payment_methods.py`

---

## SOP 总览（2 子 SOP）

| 编号 | 场景 | 类型 | 测试方法 |
|------|------|------|---------|
| SOP-MSA-001 | 画像完整 → RAG 推荐支付方式 | 正向（happy path） | `test_us_b2c_fashion_*` / `test_br_returns_pix_*` |
| SOP-MSA-002 | 画像不完整 → 主动反问（不进入 RAG）| 逆向（友好降级） | `test_missing_all_*` / `test_partial_*` |

---

## SOP-MSA-001 · PWR 支付方式推荐

### 1.1 适用场景

商户在飞书智能伙伴提问："我想做美国站，帮我选支付方式" / "BR 客单价 $150 选什么支付好"。

中枢识别意图 → 调 MSATool（intent=`recommend_payment_methods`）。

### 1.2 前置条件

| 项 | 状态 |
|---|------|
| `docs/data/payment_methods.json`（9 种支付方式）| ✅ |
| Chroma `payment_methods_vec` collection | ✅（已 seed 9 条）|
| Seed 脚本 | `python scripts/seed_payment_methods.py --reset` |
| LLM | MockLLMGateway（无 key 时）/ QwenGateway（降级）|

### 1.3 输入参数

```json
{
  "intent": "recommend_payment_methods",
  "merchant_context": {
    "merchant_id": "m_001",
    "country": "US",
    "industry": "fashion",
    "avg_amount": 85.0,
    "target_users": "B2C"
  },
  "user_query": "我想做美国站"
}
```

### 1.4 画像完整性规则

| 必填字段 | 评分权重 |
|---------|---------|
| `country` | 0.25 |
| `industry` | 0.25 |
| `avg_amount` | 0.25 |
| `target_users` | 0.25 |

`profile_completeness = 已填字段数 / 4`（0-1）

- **完整度 < 1.0** → 走 SOP-MSA-002（主动反问，不进 RAG）
- **完整度 = 1.0** → 走 RAG 推荐

### 1.5 处理流程

```
Merchant → 飞书智能伙伴 → Orchestrator
    ↓ 意图分流
MSATool.execute(intent=recommend_payment_methods)
    ↓
1. _profile_completeness(ctx) → (1.0, ())
    ↓ 完整
2. _ensure_rag() → ChromaRAGEngine
    ↓
3. RAG.retrieve(f"{country} {industry} 支付方式", top_k=5, filter={country})
    ↓
4. 组装 recommendations[] (method, evidence_id, rationale, fee_rate, settlement)
    ↓
5. LLM.chat() → summary（失败降级模板）
    ↓
返回 {intent, response, recommendations, follow_up_questions=[], profile_completeness=1.0, trace}
```

### 1.6 预期输出（US B2C fashion $85）

```json
{
  "intent": "recommend_payment_methods",
  "response": "根据您做美国 B2C 时尚电商（客单价 $85）的画像...",
  "recommendations": [
    {
      "method": "Visa",
      "evidence_id": "pm_demo_visa_us_001",
      "rationale": "Visa 是 US 最主流的信用卡支付方式...",
      "fee_rate": "2.9% + $0.30",
      "settlement": "T+2"
    },
    {"method": "Mastercard", ...},
    {"method": "PayPal", ...},
    {"method": "ACH", ...}
  ],
  "follow_up_questions": [],
  "profile_completeness": 1.0,
  "trace": {"rag_results": 4, "llm_provider": "MockLLMGateway"}
}
```

### 1.7 断言清单

| # | 断言 | 期望 |
|---|------|------|
| 1 | `intent` | `"recommend_payment_methods"` |
| 2 | `profile_completeness` | 1.0 |
| 3 | `follow_up_questions` | 空 |
| 4 | `recommendations` | ≥ 1 条 |
| 5 | 每条推荐有 `method` + `evidence_id` | `evidence_id` 以 `pm_demo_` 开头 |
| 6 | US 推荐方法 ⊇ {Visa, Mastercard, PayPal, ACH} 之一 | 至少 1 个 |
| 7 | BR 推荐方法 ⊇ {Pix, Boleto} 之一 | 至少 1 个 |
| 8 | `response` 非空 | 含 LLM 总结或 Mock 兜底 |

### 1.8 RAG 失败降级

```python
try:
    docs = rag.retrieve(...)
except Exception as e:
    return {
        "intent": "recommend_payment_methods",
        "response": "抱歉，支付方式知识库暂时无法访问...",
        "recommendations": [],
        "follow_up_questions": [],
        "profile_completeness": 1.0,
        "trace": {"rag_error": str(e), "rag_degraded": True},
    }
```

LLM 失败也降级：模板总结（拼接推荐方法名）。

### 1.9 真实环境差异

| 项 | Demo | 真实 |
|---|---|---|
| 知识库规模 | 9 种支付方式 | OP 全部 500+ 产品 |
| Embedding | HashEmbeddingFunction | Qwen Embedding |
| LLM | MockLLMGateway | Qwen / DeepSeek |
| 国家/行业过滤 | 简单 equality | 多维 metadata 过滤 |
| 商户定制 | 无 | 按 tier + 历史数据个性化 |

---

## SOP-MSA-002 · 画像不完整主动反问

### 2.1 适用场景

商户提问模糊："帮我选支付方式"（没说国家 / 行业 / 客单价）。

### 2.2 核心原则

> **不浪费 RAG 资源**：画像不全 → 直接反问，不进 RAG。
> **不让商户等**：4 个必填字段一次问完，多轮对话逐步收敛。

### 2.3 输入（任意不完整 ctx）

```json
{
  "intent": "recommend_payment_methods",
  "merchant_context": {},  // 或部分填写
  "user_query": "帮我选支付方式"
}
```

### 2.4 追问映射

| 缺失字段 | 默认追问（中文）|
|---------|---------------|
| country | 您想进入哪个国家的市场？（如 US / BR / CN） |
| industry | 您的行业是什么？（如 fashion / electronics / digital） |
| avg_amount | 您的客单价大约多少？（如 50 美元） |
| target_users | 您的目标客户是 B2B 还是 B2C？ |

### 2.5 预期输出

```json
{
  "intent": "recommend_payment_methods",
  "response": "为了给您推荐最合适的支付方式，请先告诉我以下信息：您想进入哪个国家的市场？您的行业是什么？您的客单价大约多少？您的目标客户是 B2B 还是 B2C？",
  "recommendations": [],
  "follow_up_questions": [
    {"field": "country", "question": "您想进入哪个国家的市场？"},
    {"field": "industry", "question": "您的行业是什么？"},
    {"field": "avg_amount", "question": "您的客单价大约多少？"},
    {"field": "target_users", "question": "您的目标客户是 B2B 还是 B2C？"}
  ],
  "profile_completeness": 0.0,
  "trace": {"missing_fields": ["country", "industry", "avg_amount", "target_users"], "rag_skipped": true}
}
```

### 2.6 断言清单

| # | 输入 | 期望 |
|---|------|------|
| 1 | 空 ctx | completeness=0.0，4 个追问 |
| 2 | 只填 country | completeness=0.25，3 个追问（country 不再问）|
| 3 | 缺 1 个 | completeness=0.75，1 个追问 |
| 4 | 全填 | completeness=1.0，走 SOP-MSA-001 |
| 5 | `recommendations` | 空（不进 RAG）|
| 6 | `response` | 含引导文案 |

### 2.7 collect_profile 子能力

显式采集流程（intent=`collect_profile`）：与 recommend 的反问逻辑共享 `_profile_completeness`，但 response 文案不同：

- 完整时："您的画像已完整（国家 / 行业 / 客单价 / 目标用户），可以开始诊断 / 推荐。"
- 不完整时："已记录您提供的信息（完整度 X%）。还差：..."

---

## 附录 A：评审可演示命令

```bash
cd src/backend

# 1. Seed 知识库
python scripts/seed_payment_methods.py --reset

# 2. 跑 MSA SOP 测试
python -m pytest tests/test_msa_sop.py -v

# 3. 端到端：商户提问 → 推荐
python -c "
from app.agents.msa import MSATool
from app.interfaces.base_tool import ToolRegistry
registry = ToolRegistry()
registry.register(MSATool())

# US B2C fashion
r1 = registry.safe_execute('merchant_success', {
    'intent': 'recommend_payment_methods',
    'merchant_context': {
        'country': 'US', 'industry': 'fashion',
        'avg_amount': 85.0, 'target_users': 'B2C',
    },
    'user_query': '美国站时尚电商',
})
print('=== US B2C fashion $85 ===')
print(r1['data']['response'][:100])
print(f'推荐 {len(r1[\"data\"][\"recommendations\"])} 种')
for rec in r1['data']['recommendations'][:3]:
    print(f'  - {rec[\"method\"]}: {rec[\"rationale\"][:50]}')

# 模糊提问 → 反问
r2 = registry.safe_execute('merchant_success', {
    'intent': 'recommend_payment_methods',
    'merchant_context': {},
    'user_query': '帮我选支付方式',
})
print(f'\\n=== 模糊提问 ===')
print(f'追问 {len(r2[\"data\"][\"follow_up_questions\"])} 个')
print(f'response: {r2[\"data\"][\"response\"][:80]}')
"
```

## 附录 B：与 PDA 的协作场景

```
商户：'我的 BR 站 Visa 支付失败了'
    ↓ 中枢识别（意图 = 诊断）
PDATool.execute({country: 'BR', channel: 'Visa', ...})
    ↓ 诊断完成 → 返回 evidence_chain
中枢：'是否要推荐 BR 适配的支付方式？'
    ↓ 商户确认
MSATool.execute(intent='recommend_payment_methods', ctx={country: 'BR', ...})
    ↓
RAG 检索 payment_methods_vec → 推荐 Pix（绕开 Visa 风控）
```

跨 Tool 调用由 Orchestrator 编排，MSA / PDA 之间不直接 import（Module Isolation 原则）。

---

## SOP 矩阵进度更新

| 编号 | Tool | 类型 | 状态 |
|------|------|------|------|
| SOP-MSA-001 | MSATool（PWR） | 正向 | ✅ **Day 4 完成** |
| SOP-MSA-002 | MSATool（画像反问） | 逆向 | ✅ **Day 4 完成** |
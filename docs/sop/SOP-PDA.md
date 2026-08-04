# SOP-PDA · 支付诊断 Tool 标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用 Tool**：`payment_diagnosis`（PDATool）
> **对位业务**：OP 命题方向 ② · 跨境支付诊断（支付失败 / 拒付 / 退款异常 / Webhook 回调失败）
> **关联文件**：
> - 接口：`src/backend/app/interfaces/base_tool.py`
> - 实现：`src/backend/app/agents/pda/tool.py`
> - 业务逻辑（复用）：`src/backend/legacy/agents/payment_diagnosis/service.py`
> - 测试：`src/backend/tests/test_pda_sop.py`

---

## SOP 总览（3 个子 SOP）

| 编号 | 场景 | 类型 | 优先级 | 测试方法 |
|------|------|------|-------|---------|
| SOP-PDA-001 | 命中知识库 → 返回带证据链的诊断 | 正向（happy path） | P0 | `test_happy_path_br_visa` |
| SOP-PDA-002 | 错误码不在数据集 → 友好降级 | 逆向（用户友好） | P0 | `test_happy_path_with_missing_evidence` |
| SOP-PDA-003 | LLM 调用失败 → 自动降级 Mock | 逆向（依赖降级） | P0 | `test_sop_pda_003_*` |

---

## SOP-PDA-001 · 命中知识库 → 带证据链诊断

### 1.1 适用场景

商户在飞书智能伙伴提问："订单 Oxxx 在 BR 用 Visa 支付失败，错误码 `ERR_DEMO_RISK_BLOCK_BR_VISA_001`，怎么办？"

中枢识别意图 → 调 PDATool（payment_diagnosis）。

### 1.2 前置条件

| 项 | 状态 |
|---|------|
| 数据源 `docs/data/payment_error_cases.json` | ✅ 已就绪（8 个 Demo cases） |
| 证据库 | EvidenceStore（3 个 lookup 方法）|
| LLM | `MockLLMProvider` 默认（无 DASHSCOPE_API_KEY 时）|

### 1.3 输入参数

```json
{
  "merchant_id": "m_001",
  "country": "BR",
  "channel": "Visa",
  "error_code": "ERR_DEMO_RISK_BLOCK_BR_VISA_001",
  "affected_orders": ["O001", "O002"]
}
```

### 1.4 处理流程

```
Merchant → 飞书智能伙伴 → Orchestrator
    ↓ 意图分流（payment_diagnosis）
PDATool.execute(params)
    ↓
PaymentDiagnosisService.diagnose(req)
    ↓ Step 1
EvidenceStore.collect_evidence(problem)
    ├── risk_rule    ← 命中 BR/Visa/ERR_DEMO_*
    ├── channel_status ← 命中 BR/Visa
    └── config_snapshot ← BR + GLOBAL 配置
    ↓ Step 2
_infer_problem_type() → "支付失败"
    ↓ Step 3
MockLLMProvider.generate_diagnosis() → root_causes + actions + confidence
    ↓ Step 4
Assemble Diagnosis + DiagnoseResponse
```

### 1.5 预期输出

```json
{
  "problem_type": "支付失败",
  "root_causes": [
    "BR Visa 渠道 3DS 认证配置问题...",
    "BR Visa 通道当前处于 degraded/down 状态"
  ],
  "evidence_chain": [
    {"type": "risk_rule", "id": "risk_rule_demo_001", "source": "...", "description": "..."},
    {"type": "channel_status", "id": "...", "source": "...", "description": "..."},
    {"type": "config_snapshot", "id": "...", "source": "...", "description": "..."}
  ],
  "recommended_actions": ["1. ...", "2. ..."],
  "confidence": 0.95,
  "next_agent": "Ticket Routing Agent",
  "trace": {"evidence_count": 4, "llm_provider": "MockLLMProvider", "evidence_types": [...]}
}
```

### 1.6 断言清单（评审可演示）

| # | 断言 | 期望值 |
|---|------|-------|
| 1 | `problem_type` 合法 | 4 选 1：支付失败 / 拒付 / 退款异常 / Webhook 回调失败 |
| 2 | `evidence_chain` 非空 | ≥ 1 条（含 risk_rule 优先） |
| 3 | `evidence_chain[0].type` 必为 risk_rule | 验证优先级 |
| 4 | `confidence ∈ [0, 1]` | 浮点数合法范围 |
| 5 | `next_agent` 固定 | "Ticket Routing Agent"（下一跳契约） |
| 6 | `trace.evidence_count == len(evidence_chain)` | 透传一致 |

### 1.7 真实环境差异

| 项 | Demo（当前） | 真实环境 |
|---|---|---|
| evidence id | `risk_rule_demo_xxx` 占位符 | OP 实际风控规则 ID |
| evidence source | `payment_error_database_demo` | `op_risk_engine` |
| LLM | MockLLMProvider（基于规则） | QwenProvider → DashScope |
| 数据规模 | 8 条 cases | OP 完整规则库（数千条） |

---

## SOP-PDA-002 · 错误码不在数据集 → 友好降级

### 2.1 适用场景

商户提问包含未录入的错误码 / 新国家 / 新渠道。Demo 数据集中无对应规则。

### 2.2 核心约束（CLAUDE.md 强制）

> **禁止"系统错误"裸抛**（见 `feedback_sop_testing.md`）—— 商户看到的应是"AI 给的建议"，不是 Python 堆栈。

### 2.3 输入参数

```json
{
  "merchant_id": "m_002",
  "country": "ZZ",      // 不存在的国家
  "channel": "UnknownChannel",
  "error_code": "ERR_NONEXISTENT"
}
```

### 2.4 预期行为

| 维度 | 期望 |
|---|---|
| HTTP 状态 | 200（业务成功） |
| 返回结构 | 完整 6 字段 + trace |
| `evidence_chain` | 不含 risk_rule / channel_status（这两类无匹配）；可能含 GLOBAL config_snapshot |
| `root_causes` | 非空，且友好（含"未匹配"/"Demo"/证据类型描述；不含 Traceback） |
| `recommended_actions` | 非空（即使不确定也给方向） |
| `confidence` | 偏低（0.55-0.65 区间，无强证据） |

### 2.5 断言清单

| # | 断言 | 检验内容 |
|---|------|---------|
| 1 | 返回结构完整 | 6 字段全在 |
| 2 | `evidence_chain` 不含 risk_rule / channel_status | 证据类型正确（仅 GLOBAL config 可有） |
| 3 | `root_causes` 无堆栈信息 | "Traceback" / "Exception" / "系统错误" 都不在 |
| 4 | `root_causes` 含兜底说明 | 出现 "未匹配"/"Demo"/证据 ID 之一 |
| 5 | `recommended_actions` 非空 | 给出下一步 |

### 2.6 真实环境差异

真实 OP API 即使错误码未录入，也会返 200 + 标准化错误响应（不返 404）。我们的"友好降级"逻辑恰好匹配此模式。

---

## SOP-PDA-003 · LLM 调用失败 → 自动降级 Mock

### 3.1 适用场景

DashScope 超时 / 限流 / 余额耗尽 / 网络异常。商户口中"AI 不能挂"。

### 3.2 设计原则

| 原则 | 落地 |
|---|---|
| **业务可用性优先** | LLM 失败不能让商户看到 500 |
| **透明可追溯** | trace.degraded=True 标记降级 |
| **避免无限递归** | 当前已是 MockLLMProvider 时不再降级 |

### 3.3 降级逻辑（PDATool.execute）

```
try:
    return self._diagnose(params)            # 调真实 service
except Exception as llm_err:
    if isinstance(self.service.llm, MockLLMProvider):
        raise                                # 已 Mock，再降级也救不了，向上抛
    original = self.service.llm
    self.service.llm = MockLLMProvider()     # 临时替换
    try:
        result = self._diagnose(params)
        result["trace"]["degraded"] = True
        result["trace"]["original_llm"] = type(original).__name__
        result["trace"]["degraded_reason"] = str(llm_err)
        return result
    finally:
        self.service.llm = original           # 恢复（避免污染其他调用）
```

### 3.4 输入参数（同 SOP-PDA-001）

注入 `FailingLLM`（generate_diagnosis 抛 RuntimeError）：

```python
service = PaymentDiagnosisService(
    evidence_store=EvidenceStore(),
    llm_provider=FailingLLM(),
)
tool = PDATool(service=service)
result = tool.execute(params)   # 不应抛异常
```

### 3.5 预期输出

| 字段 | 期望 |
|---|---|
| `problem_type` | 4 选 1（MockLLM 兜底给出） |
| `root_causes` | ≥ 1 条 |
| `trace.degraded` | `True` |
| `trace.original_llm` | `"FailingLLM"` |
| `trace.degraded_reason` | 含 `"模拟 LLM 调用失败"` |

### 3.6 边界情况：降级循环检测

当前 LLM 已是 `MockLLMProvider` 但调用仍失败 → 直接抛原异常，避免无限递归：

```python
class StillFailingLLM(MockLLMProvider):
    def generate_diagnosis(self, **kwargs):
        raise RuntimeError("Mock 也失败")

# 执行会抛 RuntimeError（不无限递归）
tool.execute(params)  # → raises RuntimeError("Mock 也失败")
```

### 3.7 真实环境差异

| 项 | Demo | 真实 |
|---|---|---|
| 降级触发 | FailingLLM mock | DashScope HTTP 5xx / 超时 |
| 降级目标 | MockLLMProvider（规则）| 备选 DeepSeek / 本地 Qwen |
| 告警 | 无 | trace.degraded=True → 飞书运维群告警 |

---

## 附录 A：评审可演示命令

```bash
# 跑全部 PDA SOP 测试
cd src/backend
python -m pytest tests/test_pda_sop.py -v

# 端到端 demo（评审可截屏）
python -c "
from app.agents.pda import PDATool
from app.interfaces.base_tool import ToolRegistry
registry = ToolRegistry()
registry.register(PDATool())
spec = registry.list_tools()[0]
print('=== MCP tool_spec（评审展示）===')
print(spec['name'], '-', spec['description'][:50])
print('capabilities:', spec['capabilities'])

result = registry.safe_execute('payment_diagnosis', {
    'merchant_id': 'm_001', 'country': 'BR', 'channel': 'Visa',
    'error_code': 'ERR_DEMO_RISK_BLOCK_BR_VISA_001',
})
print('=== 诊断结果（happy path）===')
print('problem_type:', result['data']['problem_type'])
print('confidence:', result['data']['confidence'])
print('evidence count:', len(result['data']['evidence_chain']))
"
```

## 附录 B：已知约束与避坑

| # | 约束 | 规避 |
|---|------|------|
| 1 | Demo 数据 config_snapshot 含 GLOBAL，会在所有 country 命中 | 测试断言只排除 risk_rule / channel_status，不强求 evidence_chain 为空 |
| 2 | 真实 Qwen 调用偶发超时 | PDATool 内置降级，不让商户口中"AI 卡死" |
| 3 | MockLLMProvider 文案固定 | 真实环境由 Qwen 生成，更自然但需监控降级率 |
| 4 | trace 字段当前透传给前端 | Demo 用于演示；生产应改为仅日志记录，不暴露给商户 |

## 附录 C：SOP 矩阵进度

| 编号 | Tool | 类型 | 状态 |
|------|------|------|------|
| SOP-PDA-001 | PDATool | 正向 | ✅ Day 2 |
| SOP-PDA-002 | PDATool | 逆向（无匹配） | ✅ Day 2 |
| SOP-PDA-003 | PDATool | 逆向（LLM 降级） | ✅ Day 2 |
| SOP-MSA-001 | MSATool（含 PWR） | 正向 | ⏳ Day 4 |
| SOP-MSA-002 | MSATool（含 PWR） | 逆向（反问） | ⏳ Day 4 |
| SOP-TRA-001 | TRATool | 正向 | ⏳ Day 6 |
| SOP-KEA-001 | KEATool | 正向 | ⏳ Day 7 |
| SOP-ORC-001 | Orchestrator | 正向 | ⏳ Day 5 |
| SOP-LLM-001 | LLM Gateway | 逆向（降级） | ⏳ Day 3 |
| SOP-RAG-001 | RAG Engine | 逆向（空结果） | ⏳ Day 3 |
| SOP-REPO-001 | Repository | 逆向（约束） | ✅ Day 1（主键/无结果）；补 NOT NULL/超长：Day 3 |

**当前完成**：4/10 SOP（PDATool 3/3 + REPO 1/3 子场景）。
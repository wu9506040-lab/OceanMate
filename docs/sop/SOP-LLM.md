# SOP-LLM · LLM Gateway 标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用组件**：`app/implementations/llm/qwen_gateway.py`（QwenGateway + MockLLMGateway）
> **关联**：
> - 接口：`app/interfaces/base_llm.py`
> - 测试：`src/backend/tests/test_llm_sop.py`

---

## SOP 总览（4 逆向 + 2 正向 = 6 子 SOP）

| 编号 | 场景 | 类型 | 测试方法 |
|------|------|------|---------|
| SOP-LLM-001-A | DASHSCOPE_API_KEY 缺失 → 自动用 MockLLMGateway | 逆向（依赖缺失） | `test_key_missing_returns_mock` |
| SOP-LLM-001-B | Qwen 调用失败（5xx / 超时）→ 自动降级 Mock | 逆向（依赖降级） | `test_qwen_call_failure_degrades_to_mock` |
| SOP-LLM-001-C | LLM 返回非 JSON → `_parse_json` 兼容 markdown code block | 逆向（输出解析） | `TestParseJson::test_*` |
| SOP-LLM-001-D | 重试 3 次仍失败 → 抛 RuntimeError（不无限降级） | 逆向（重试耗尽） | `test_retry_exhausted_raises` |
| SOP-LLM-001-E | MockLLMGateway.chat() 返回非空文本 | 正向 | `test_chat_returns_text` |
| SOP-LLM-001-F | MockLLMGateway.chat_structured() 返回符合 schema 的 dict | 正向 | `test_chat_structured_returns_valid_dict` |

---

## SOP-LLM-001-A · Key 缺失自动降级

### 适用场景

新部署的开发机没配 `DASHSCOPE_API_KEY`，但工程不能挂。

### 工厂逻辑

```python
def get_default_gateway() -> BaseLLMGateway:
    if os.getenv("DASHSCOPE_API_KEY"):
        try:
            return QwenGateway()
        except (ImportError, Exception) as e:
            return MockLLMGateway()
    return MockLLMGateway()
```

### 断言

| # | 断言 |
|---|------|
| 1 | `get_default_gateway()` 返回 MockLLMGateway 实例 |
| 2 | 返回对象满足 `BaseLLMGateway` Protocol（chat/chat_structured/embed/vision 都可用）|

### 真实环境差异

| 项 | Demo | 真实 |
|---|---|---|
| 降级目标 | MockLLMGateway（规则）| Qwen + DeepSeek 双 fallback |
| 告警 | 无 | 飞书群消息 + 日志 ERROR |

---

## SOP-LLM-001-B · Qwen 调用失败降级

### 适用场景

DashScope 限流（429）/ 服务异常（5xx）/ 网络断。商户口中"AI 不能挂"。

### 降级逻辑（QwenGateway.chat）

```python
def chat(self, messages, **kwargs):
    def _call():
        resp = self._Generation.call(model=..., messages=messages, ...)
        if resp.status_code != 200:
            raise RuntimeError(f"Qwen 调用失败: {resp.message}")
        return resp.output.choices[0].message.content

    try:
        return _retry_with_backoff(_call)  # 3 次重试
    except Exception as e:
        print(f"[QwenGateway] 降级 Mock: {e}")
        return MockLLMGateway().chat(messages, **kwargs)  # 降级
```

### 降级触发矩阵

| 触发条件 | 重试 | 降级 Mock |
|---|:---:|:---:|
| 429 限流 | ✅ | ✅ |
| 5xx 服务异常 | ✅ | ✅ |
| 网络超时 | ✅ | ✅ |
| Key 无效（401）| ❌（立刻 fail）| ✅ |
| dashscope 包未安装 | N/A | ✅（init 时降级） |

### 断言

| # | 断言 |
|---|------|
| 1 | 调用不抛异常 |
| 2 | 返回非空字符串 |
| 3 | 返回内容含 Mock 标识文案 |

### 真实环境差异

真实环境降级目标应是 DeepSeekGateway 或本地 Qwen。Mock 仅 PoC 用。

---

## SOP-LLM-001-C · 非 JSON 输出兼容

### 适用场景

LLM 输出含自然语言描述 + JSON 块（最常见），或纯 markdown code block。

### 解析逻辑（QwenGateway._parse_json）

```python
# 优先级 1：匹配 ```json\n{...}\n```
m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
if m:
    return json.loads(m.group(1))
# 优先级 2：纯 JSON
m = re.search(r"\{[\s\S]*\}", content)
if m:
    return json.loads(m.group(0))
raise ValueError(f"无法从 LLM 输出提取 JSON: {content[:200]}")
```

### 断言（4 个 case）

| # | 输入 | 期望 |
|---|------|------|
| 1 | ` ```json\n{...}\n``` ` | dict |
| 2 | `{...}` | dict |
| 3 | "好的，结果：\n{...}\n请查收" | dict |
| 4 | "这不是 JSON" | ValueError |

---

## SOP-LLM-001-D · 重试耗尽

### 配置

```python
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 1.0
BACKOFF_MULTIPLIER = 2.0
# 实际退避：1s → 2s → 4s（第 3 次失败后不再 sleep）
```

### 行为

- 重试 3 次都失败 → 抛 `RuntimeError(f"LLM 调用失败（重试 3 次）: {last_error}")`
- **不会**自动降级（重试是 LLM 层的责任，降级是 Tool 层的责任，分层清晰）

### 边界

如果 Tool 层（如 PDATool）捕获到这个 RuntimeError，再触发 SOP-PDA-003 的 MockLLMProvider 降级。

### 断言

| # | 断言 |
|---|------|
| 1 | `_retry_with_backoff(always_fail)` 抛 RuntimeError |
| 2 | 错误信息含 "重试 3 次" |

---

## SOP-LLM-001-E / F · MockLLMGateway 正向路径

### E：chat()

```python
result = gw.chat([{"role": "user", "content": "你好"}])
# 返回 "[Mock LLM 响应] 已收到您的消息：你好（PoC 阶段需要配置 DASHSCOPE_API_KEY...）"
```

### F：chat_structured()

```python
schema = {"type": "object", "properties": {"name": {"type": "string"}, ...}}
result = gw.chat_structured([...], schema)
# 返回 {"name": None, "age": None, "tags": []}（递归生成空结构）
```

---

## 附录 A：评审可演示命令

```bash
cd src/backend
python -m pytest tests/test_llm_sop.py -v

# 端到端：手动触发降级
python -c "
import os
os.environ.pop('DASHSCOPE_API_KEY', None)
from app.implementations.llm.qwen_gateway import get_default_gateway
gw = get_default_gateway()
print(f'当前 LLM: {type(gw).__name__}')
print(f'chat() 输出: {gw.chat([{\"role\": \"user\", \"content\": \"BR Visa 诊断\"}])[:80]}')
print(f'chat_structured() 输出: {gw.chat_structured([], {\"type\": \"object\", \"properties\": {\"x\": {\"type\": \"string\"}}})}')
"
```

## 附录 B：已知约束

| # | 约束 | 缓解 |
|---|------|------|
| 1 | MockLLMGateway 文案固定，演示单调 | PoC 够用；真实环境切 Qwen |
| 2 | chat_structured 失败时仍走 Mock，可能 schema 不全 | 业务方必须容忍 None |
| 3 | `_parse_json` 用正则，复杂 LLM 输出可能匹配错位 | 真实环境用 DashScope `response_format={"type": "json_object"}` 强制 |
| 4 | 重试 sleep 阻塞主线程 | 真实环境改 async + 异步重试 |

---

## SOP 矩阵进度更新

| 编号 | Tool/组件 | 类型 | 状态 |
|------|---------|------|------|
| SOP-LLM-001 | LLM Gateway | 正逆混合 6 子场景 | ✅ **Day 3 完成** |
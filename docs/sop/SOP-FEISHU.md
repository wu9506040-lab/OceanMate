# SOP-FEISHU · 飞书智能伙伴 + Webhook 集成标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用组件**：`app/implementations/feishu/`（api / frontend / mock_frontend / webhook）
> **对位架构**：4 Tool 之外的「飞书载体层」（详见 `docs/architecture/oceanmate_v2.md` §1 L1）
> **对位官方命题**：方向 ⑤「协同」+ AtoA 挑战（MCP 协议友好）
> **关联文件**：
> - 实现：`src/backend/app/implementations/feishu/`
> - 测试：`src/backend/tests/test_feishu_sop.py`（20/20）
> - 集成：`src/backend/app/main.py`（FastAPI 入口 + 11 routes）
> - 老入口：`src/backend/app/main_v1_legacy.py`（v1 PoC · 仅保留，禁止 import）

---

## 1. SOP 总览（4 子 SOP · 20 测试）

| 编号 | 场景 | 类型 | 测试方法 | 状态 |
|------|------|------|---------|------|
| SOP-FEISHU-001-A | URL 验证（飞书首次配置 Webhook） | 正向 | `TestURLVerification::*`（2 用例） | ✅ |
| SOP-FEISHU-001-B | 完整消息流（事件 → Orchestrator → 回复 → Mock 日志） | 正向 | `TestMessageFlow::*`（2 用例） | ✅ |
| SOP-FEISHU-002-A | MockFrontend 5 方法 + 写日志（最简） | 逆向（降级） | `TestMockFrontend::*`（5 用例） | ✅ |
| SOP-FEISHU-002-B | 工厂函数无凭证 → 自动 Mock | 逆向（降级） | `TestFactoryFallback::*`（4 用例） | ✅ |
| SOP-FEISHU-002-C | 真实 FeishuFrontend API 失败 → 友好降级（不抛 raw） | 逆向（容错） | `TestFeishuFrontendDegradation::*`（3 用例） | ✅ |
| SOP-FEISHU-002-D | webhook 4 逆向场景（缺 user_id / 缺 text / 非 chat 事件 / Orchestrator 异常）| 逆向（容错） | `TestWebhookFriendlyDegradation::*`（4 用例） | ✅ |

**当前 SOP 矩阵总进度**：✅ 全部完成。Day 6-7 收官。

---

## 2. URL 验证子能力（飞书首次配置 Webhook 必备）

### 2.1 流程

```
飞书管理后台
  ↓ POST 飞书智能伙伴 → Webhook URL
  ↓ payload: {"type": "url_verification", "challenge": "xxx", "token": "..."}
  ↓
FeishuWebhookHandler.handle_event(payload)
  ↓ _handle_url_verification(payload)
  ↓
返回 {"challenge": "xxx"}
  ↓
飞书确认 Webhook 有效，事件开始推送
```

### 2.2 关键点

| # | 细节 |
|---|------|
| 1 | `type == "url_verification"` 或含 `challenge` 字段都触发 URL 验证逻辑 |
| 2 | 验证 token 不匹配 → log 警告，但仍返回 challenge（飞书侧必须 200） |
| 3 | 真实环境启用 `enable_signature_check=True` 验签（V2 签名算法） |

### 2.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 飞书首次配置 | 返回 `{"challenge": "abc123"}` |
| 2 | 仅带 challenge（无 type）| 同样返回 challenge |

---

## 3. 完整消息流子能力（智能伙伴事件 → 4 Tool → 回复）

### 3.1 全链路

```
飞书智能伙伴 / 用户群
  ↓ POST /feishu/webhook
  ↓ payload: {header.event_type = "im.message.receive_v1", event.message.content = "{...}"}
  ↓
FeishuWebhookHandler.handle_event
  ├─ 验签（PoC 跳过）
  ├─ 解析 sender.open_id + event.message.content.text
  ├─ Orchestrator.route(user_query=text, merchant_context={user_id, chat_id})
  │   └─ 4 Tool 自动选（关键词匹配）
  │       ├─ merchant_success → MSATool
  │       ├─ payment_diagnosis → PDATool
  │       ├─ ticket_routing → TRATool
  │       └─ knowledge_evolution → KEATool
  ├─ _format_reply(orch_result) → markdown 文本
  ├─ frontend.send_message(user_id, reply)
  │   ├─ Mock 模式 → 写 .feishu_mock_log.json
  │   └─ 真实模式 → 调飞书 im/v1/messages API
  └─ 返回 {"code": 0, "msg": "success"}
```

### 3.2 4 intent 的回复模板

| intent | sub_intent | 回复示例 |
|--------|-----------|----------|
| `merchant_success` | `recommend_payment_methods` | `📋 **支付方式推荐**：\n- **Visa**：...` |
| `merchant_success` | `collect_profile` | `请告诉我您的商户信息。` |
| `payment_diagnosis` | — | `🔍 **诊断结果**：支付失败\n置信度：70%\n\n**根因**：\n- 主要受 ...` |
| `ticket_routing` | `route_ticket` | `✅ 工单已创建（ID \`oc_xxx\`），分派至 **OP 客服组**，SLA 4h` |
| `ticket_routing` | `query_status` | `📄 工单 oc_xxx 当前状态：**processing**` |
| `knowledge_evolution` | `promote_to_faq` | `✅ 案例 case_demo_001 已升级为 FAQ。` |
| `knowledge_evolution` | `search_faq` | `🔍 找到 2 条 FAQ：\n- BR Visa 拒付...` |
| `knowledge_evolution` | `list_candidates` | `📚 找到 4 个高置信度候选待升级。` |
| `unknown_fallback_to_msa` | — | `🤔 抱歉没理解，请补充：国家 / 行业 / 客单价 / 目标客户。` |

### 3.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 商户提问"BR Visa 拒付 ERR_X_001" | intent=payment_diagnosis，reply 含 "诊断结果" 关键词 |
| 2 | Mock 日志至少 1 条 send_message 事件 | user_id = "ou_demo_user" |
| 3 | 空白文本（"   "） | 仍返回 `{"code": 0}`（不挂） |

---

## 4. 4 逆向场景（友好降级强制）

| # | 场景 | 行为 | trace/error_code |
|---|------|------|-----------------|
| 1 | **API 超时**（httpx timeout） | `FeishuOpenAPI.send_message` 抛 `FeishuAPIError(code=-1, ...)` | `FeishuAPIError` 内部捕获 |
| 2 | **API JSON 错**（mock 401 响应） | `_parse` 抛 `FeishuAPIError(code=401, ...)` | 同样降级 |
| 3 | **事件缺 user_id** | `_extract_sender` 返回 None → `handle_event` 返回 `{"code": 0, "msg": "ok"}` | 不挂飞书 |
| 4 | **Orchestrator 抛异常** | `try/except` 兜底 → 推送"抱歉暂不可用" → 返回 `{"code": 0}` | 不暴露异常细节 |

### 4.1 关键设计：永远返回 200

> **飞书 webhook 重试策略**：5xx 错误会触发重试（最多 3 次），4xx 不会重试但管理后台告警。
>
> **本设计**：永远返回 `{"code": 0, "msg": "ok"}`（即使内部异常），原因：
> - 单次事件推送失败不应引发飞书重试轰炸
> - 用户已在业务侧推送友好降级提示
> - 异常详情写本地日志，便于排查

### 4.2 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | MockFrontend 5 方法 | send_message / send_private / create_group / add_group_member / sync_dashboard_data 都返回 True/fake_id，写本地日志 |
| 2 | 工厂函数无凭证 | 返回 MockFrontend |
| 3 | force_mock=True | 返回 MockFrontend（即使有凭证） |
| 4 | env FEISHU_FORCE_MOCK=1 | 返回 MockFrontend |
| 5 | 完整凭证 | 返回 FeishuFrontend（httpx 真实调用） |
| 6 | FeishuFrontend.send_message 抛 FeishuAPIError | 返回 False（不抛 raw） |
| 7 | FeishuFrontend.create_group 抛 FeishuAPIError | 返回 "" 空串（不抛 raw） |
| 8 | FeishuFrontend.sync_dashboard_data 缺 btable_app_token | 返回 False（log 警告） |
| 9 | webhook 缺 user_id | 返回 `{"code": 0, "msg": "ok"}` |
| 10 | webhook 缺 text | 返回 `{"code": 0, "msg": "ok"}` |
| 11 | 非 chat 事件（reaction / card action） | 返回 `{"code": 0, "msg": "ok"}`（暂不处理） |
| 12 | Orchestrator 抛 RuntimeError | 仍返回 `{"code": 0, "msg": "ok"}` + 推送"抱歉" |

---

## 5. 工厂降级策略（关键 · Demo 友好）

### 5.1 优先级链

```
get_feishu_frontend(app_id, app_secret, ...)
  ├─ 1. force_mock=True? → MockFrontend
  ├─ 2. env FEISHU_FORCE_MOCK=1? → MockFrontend
  ├─ 3. FEISHU_APP_ID + FEISHU_APP_SECRET 缺失? → MockFrontend（log 警告）
  └─ 4. 凭证齐全 → FeishuFrontend（httpx 真实调飞书）
```

### 5.2 真实环境切换

```bash
# Demo 模式（无凭证）
python -m uvicorn app.main:app --port 8000
# → 自动 MockFrontend，消息写 .feishu_mock_log.json

# 真实模式
export FEISHU_APP_ID="cli_xxxx"
export FEISHU_APP_SECRET="xxx"
export FEISHU_BTABLE_APP_TOKEN="bascnxxx"  # 多维表格
export FEISHU_BTABLE_TABLE_ID="tblxxx"       # 表格 ID
python -m uvicorn app.main:app --port 8000
# → FeishuFrontend，消息发到飞书
```

### 5.3 强制 Mock 场景

| 场景 | 用法 |
|------|------|
| 录屏演示 | `FEISHU_FORCE_MOCK=1` 保证 0 网络依赖 |
| 单元测试 | `force_mock=True` 注入 |
| 故障演练 | 临时切 Mock 排查真实 API 故障 |

---

## 6. 真实环境差异

| 项 | Demo（PoC）| 真实生产 |
|---|---|---|
| Frontend | `MockFrontend`（写本地日志） | `FeishuFrontend`（调 im/v1/messages） |
| tenant_access_token | 不需要 | 缓存 2 小时（自动刷新） |
| 多维表格 | sync_dashboard_data 写日志 | 调 bitable/v1/apps/.../records |
| 签名校验 | 跳过（`enable_signature_check=False`）| 启用 V2 签名校验 |
| Webhook URL | `http://localhost:8000/feishu/webhook` | 公网 HTTPS（内网穿透或域名） |
| 商户 ID | `ou_demo_user` | 飞书 open_id（首次 OAuth 授权） |
| 错误重试 | Mock 永不失败 | 飞书侧会 5xx 重试（我们返 200 阻断） |

---

## 7. 已知约束与避坑

| # | 约束 / 坑 | 解决方式 |
|---|----------|---------|
| 1 | `httpx.Client` 是同步版（不阻塞 FastAPI async event loop）| 简单场景可接受；高并发换 `httpx.AsyncClient` |
| 2 | Windows cmd 默认 GBK，print emoji 报 `UnicodeEncodeError` | `app/main.py` 已加 `sys.stdout.reconfigure(encoding="utf-8")` 兜底 |
| 3 | 飞书 Webhook 5xx 触发重试 | 永远返回 `{"code": 0}`（见 §4.1） |
| 4 | chromadb 初始化时 PostHog telemetry 报错 | 不影响功能（warning 级别），PoC 不处理 |
| 5 | `tenant_access_token` 缓存过期导致首调失败 | 错误码 99991663/99991664 → 自动重试 1 次 |
| 6 | 商户消息 content 是 JSON 字符串 | 解析 `content = json.loads(content); content["text"]` |
| 7 | `force_mock=True` 优先级最高（即使有凭证）| 录屏时强制走 Mock 避免真实 API 干扰 |
| 8 | 老 `app/main.py` 已改名 `app/main_v1_legacy.py` | v1 旧代码保留作参考；禁止新代码 import |
| 9 | `/api/chat` 调试接口不触发 send_message | webhook 才走完整链路（评审演示注意区分） |
| 10 | `enable_signature_check=False` 跳过验签 | PoC 简化；真实环境必须开（V2 签名算法） |

---

## 附录 A · 评审可演示命令

### A.1 跑测试

```bash
cd src/backend
python -m pytest tests/test_feishu_sop.py -v    # 仅飞书（20 测试）
python -m pytest tests/ -q                        # 全套（167）
```

### A.2 启动 FastAPI + 演示

```bash
# 启动
cd src/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 演示 1：健康检查
curl http://localhost:8000/api/health

# 演示 2：列出 4 Tool
curl http://localhost:8000/api/tools

# 演示 3：URL 验证（飞书首次配置）
curl -X POST http://localhost:8000/feishu/webhook \
  -H "Content-Type: application/json" \
  -d '{"type": "url_verification", "challenge": "demo_666"}'

# 演示 4：模拟商户提问"BR Visa 拒付"
curl -X POST http://localhost:8000/feishu/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "header": {"event_type": "im.message.receive_v1"},
    "event": {
      "sender": {"sender_id": {"open_id": "ou_demo_user"}},
      "message": {
        "message_type": "text",
        "content": "{\"text\": \"BR Visa 拒付怎么解决\"}"
      }
    }
  }'

# 演示 5：看 Mock 日志（完整事件流）
curl http://localhost:8000/api/feishu_mock_log | python -m json.tool
```

### A.3 端到端：智能伙伴完整路径

```python
# 评审现场 1 行演示：
import sys, json
sys.path.insert(0, r'E:\ai-pioneer\src\backend')
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    # 模拟 3 轮对话
    queries = [
        "你好",  # → unknown → MSA collect_profile
        "BR Visa 拒付 ERR_X_001",  # → payment_diagnosis
        "FAQ 怎么用",  # → knowledge_evolution
    ]
    for q in queries:
        r = client.post("/feishu/webhook", json={
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_demo"}},
                "message": {
                    "message_type": "text",
                    "content": json.dumps({"text": q}),
                },
            },
        })
        result = r.json()
        print(f"Q: {q}")
        # 拿到 Mock 日志最后一条
        log = client.get("/api/feishu_mock_log").json()["events"]
        if log:
            print(f"A: {log[-1]['message'][:200]}")
        print()
```

### A.4 评审可演示点（5 个）

| # | 演示项 | 评审看点 |
|---|------|---------|
| 1 | `/api/health` | 4 Tool 全部注册；Frontend 自动 Mock 降级 |
| 2 | `/api/tools` | MCP tool_spec 标准输出（对位 AtoA 挑战） |
| 3 | URL 验证 echo | 飞书首次配置兼容（生产必备） |
| 4 | webhook 完整链路 | 4 关键词命中 → 4 intent 自动路由 |
| 5 | Mock 日志 | 录屏演示"消息流"的可视化证据（无飞书环境也能演示） |

---

## 附录 B · 与官方命题的对位

| OP 命题方向 | Feishu 集成对位 | 落地 |
|------------|---------------|------|
| ①-⑤ 整体 | 飞书智能伙伴作为统一入口 | `/feishu/webhook` |
| AtoA 挑战 | MCP 协议友好（4 Tool 注册 + tool_spec 导出） | `/api/tools` 端点 |
| 工单协同 | 工单创建事件自动推送（TRA → frontend.send_message）| `_fmt_tra` reply |
| 知识沉淀 | 案例 promote 通知商户 | `_fmt_kea` reply |
| 多维表格 | `sync_dashboard_data` 写飞书 Bitables | `FeishuFrontend.sync_dashboard_data` |
| 妙记 | （未来）`create_group` 拉客服进群 + 妙记链接 | 预留 hook |

---

## 附录 C · 生产化路径（替换指南）

1. **启用真实 Feishu**：
   ```bash
   export FEISHU_APP_ID=cli_xxxx
   export FEISHU_APP_SECRET=xxx
   ```
   无代码改动，工厂自动切换。

2. **启用签名校验**：
   ```python
   # app/main.py
   _webhook_handler = FeishuWebhookHandler(
       ...,
       enable_signature_check=True,  # ← 改这里
   )
   ```
   + 完整实现 `_verify_signature`（V2 算法）。

3. **多维表格双向同步**：
   - 当前：仅 `sync_dashboard_data` 写多维表格
   - 后续：TRA 创建工单时同步 / KEA 沉淀时同步 / 飞书审批流回写 SQLite

4. **多租户隔离**：
   - 当前：单租户（一个 app_id）
   - 后续：多 app_id + tenant_key 路由（每个 OP 客户一个独立凭证）

5. **妙记自动转工单**：
   - 当前：未实现
   - 后续：监听 `meeting.minute_created_v1` 事件 → 调 LLM 提取待办 → 触发 TRA

详见 `docs/architecture/oceanmate_v2.md` §4（替换指南）+ `docs/architecture/agent_architecture.md` §5（飞书生态绑定）。

---

## 附录 D · 端点清单（11 routes）

| Method | Path | 用途 |
|--------|------|------|
| GET | `/` | 根路径（项目元信息）|
| GET | `/api/health` | 健康检查 |
| GET | `/api/tools` | 4 Tool MCP tool_spec 列表 |
| POST | `/api/chat` | 调试接口（curl 模拟商户提问）|
| GET | `/api/feishu_mock_log` | 查看 Mock 事件日志 |
| POST | `/feishu/webhook` | 飞书智能伙伴事件入口 |
| POST | `/feishu/url_verification` | 飞书 URL 验证（独立端点）|
| OPTIONS | `/...` | CORS 预检（middleware 自动）|
| ... | ... | （CORS 4 个预检自动添加）|

实际 11 routes = 7 业务 endpoint + 4 CORS preflight。

---

## 附录 E · 集成验证清单

提交 / 录屏前自检 6 项：

- [ ] 167/167 测试通过（含 20 飞书）
- [ ] FastAPI 启动 0 错误（5 endpoint 全 200）
- [ ] Mock 日志至少 1 条 send_message（webhook 触发后）
- [ ] 老 `main_v1_legacy.py` 保留（不删除）
- [ ] 工厂函数无凭证 → Mock（自动降级）
- [ ] 4 Tool 全注册（merchant_success / payment_diagnosis / ticket_routing / knowledge_evolution）

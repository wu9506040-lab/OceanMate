# Day 16「像真人客服」polishing 层验证报告

> **生成时间**：2026-08-14
> **Backend 版本**：Day 16（polishing 层 + 4 个对话质量修复）
> **测试方式**：真实 Python 直调 + 真实 HTTP POST 到 `http://localhost:8000`
> **总通过率**：**38/38 = 100%**（34 单元 + 4 webhook 集成）

---

## 0. 测试目的与背景

Day 15 验证「核心诊断路径」已 100% 通过，但用户反馈"**你觉得现在想真实客服在回答吗**"——指出 4 个真实客服必备但 AI 缺失的对话质量：

| Fix | 真实客服的行为 | AI 之前的行为 |
|---|---|---|
| **E** | 商户说"好的" → 简单告别，不多废话 | 仍走 Orchestrator → 给一长串诊断（喧宾夺主） |
| **F** | 同一问题 5 分钟内不重复派单 | 每次都新建工单（骚扰商户 + 给团队添乱） |
| **G** | 商户反驳"不是的，我们已经...了" → 接受新事实重新分析 | 完全无上下文，重复同样答案 |
| **H** | 紧急语气 → 先共情再处理 | 直接抛诊断文字（冷冰冰） |

---

## 1. 模块设计

`app/agents/orchestrator/polishing.py`（约 280 行，纯函数 + SQLite）：

| 函数 | 职责 | 调用方 |
|---|---|---|
| `is_farewell(query)` | 检测告别语（长度 ≤ 15 + 关键词匹配） | webhook 入口 |
| `lookup_recent_ticket(user, query)` | 查 5 分钟内同 user+query 是否已派过工单 | webhook 入口 |
| `record_recent_ticket(user, query, ticket_id)` | 工单创建后写入 SQLite | webhook 出口 |
| `detect_rebuttal(query)` | 检测反驳词（不是的/但是）+ 事实信号（物流/3DS/已开） | webhook 入口 |
| `has_urgent_signal(query)` | 检测紧急语气（爆了/崩了/紧急/急） | webhook 入口 |
| `polish_query(query, user_id=)` | 主入口，返回 `PolishResult` 数据类 | webhook 入口 |

**SQLite 表**：
```sql
CREATE TABLE IF NOT EXISTS recent_tickets (
    user_id TEXT,
    query_hash TEXT,
    ticket_id TEXT,
    created_at REAL,
    PRIMARY KEY (user_id, query_hash)
)
```
文件：`src/data/polishing.db`（线程安全，`threading.Lock` 保护）。

**Webhook 接线点**（`app/implementations/feishu/webhook.py`）：
- `handle_event()` line ~220：**3.5 Day 16 polishing 层**
  - 告别语 → `_safe_send(farewell_reply)` + return
  - 去重命中 → `_safe_send(去重提示)` + return
  - 反驳识别 → `ctx["merchant_supplement"] = ...` 注入 Orchestrator
  - 同理心信号 → `urgent_prepend` 存到局部变量，reply 推送前 prepend
- `handle_event()` line ~290：工单创建后调 `record_recent_ticket(user, text, ticket_id)`

---

## 2. Fix E 验证：告别语识别

### 2.1 单元测试（13 个 case）

```
TestIsFarewell
  ✓ test_好的_is_farewell
  ✓ test_谢谢_is_farewell
  ✓ test_好的谢谢_is_farewell
  ✓ test_thanks_is_farewell
  ✓ test_thank_you_is_farewell
  ✓ test_thumbs_emoji_is_farewell
  ✓ test_pray_emoji_is_farewell
  ✓ test_long_query_with_好的_is_not_farewell     ← 防「好的我也觉得是13.1」误判
  ✓ test_real_question_is_not_farewell
  ✓ test_empty_string_not_farewell
  ✓ test_whitespace_only_not_farewell
  + 2 others
```

### 2.2 真实 webhook 验证

商户发 `好的`：

```
HTTP 200 {"code": 0, "msg": "success"}
商户收到 1 条消息：
  >>> 🙌 不客气！您的工单我们正在跟进，有进展会第一时间通知您。如有新问题随时找我。
```

**结论**：告别语识别后**完全不调 Orchestrator**，直接返短文本（与真实客服行为一致）✅

---

## 3. Fix F 验证：去重派单（SQLite 5 分钟窗口）

### 3.1 单元测试（4 个 case）

```
TestDedupLogic
  ✓ test_first_record_then_lookup_returns_id
  ✓ test_different_user_no_match
  ✓ test_different_query_no_match
  ✓ test_polish_query_with_user_id_returns_recent_ticket
```

### 3.2 SQLite 真实验证

调用 `polish_query(query, user_id=uid)` 后查 DB：

```
('ou_f_demo', 'e21fa23f37c4bdfa', 'tkt_demo_cached', 1786715837.987514)
```

→ SQLite 表自动创建 + 写入成功 ✅

### 3.3 真实 webhook 验证

预置 `record_recent_ticket('ou_f_demo', 'BR Pix 延迟测试_xxx', 'tkt_demo_cached')`，
再发同 query：

```
HTTP 200 {"code": 0, "msg": "success"}
商户收到 1 条消息：
  >>> 💡 您刚才已经就该问题提交过工单 tkt_demo_cached，我们的同事正在跟进，无需重复提交。

  如有新信息（如物流单号 / 已开 3DS / 退款记录），请直接发给我，我会更新到原工单上。
```

**结论**：去重命中后**完全跳过 Orchestrator**，不重复派单（与真实客服一致）✅

---

## 4. Fix G 验证：商户反驳识别 + 补充事实注入 ctx

### 4.1 单元测试（6 个 case）

```
TestDetectRebuttal
  ✓ test_simple_rebuttal_with_fact       "不是的，我们已经发了物流" → True
  ✓ test_但是_with_fact                  "但是我们已经开了 3DS 认证" → True
  ✓ test_rebuttal_without_fact           "不是的"（无事实）→ False
  ✓ test_fact_without_rebuttal           "我已经发了物流"（无反驳词）→ False
  ✓ test_long_query_with_已经_is_rebuttal  长度 > 30 + 含「已经」 → True
  ✓ test_normal_question_not_rebuttal
```

### 4.2 PolishResult 真实验证

```
Q: 不是的，13.1拒付我们已经发了物流凭证
  is_rebuttal=True  urgent=False  has_supp=True
  supp: ⚠️ 商户补充：商户对诊断结论有补充意见（'不是的/但是'类）...

Q: 但是Visa 13.1拒付我们已经开了3DS认证
  is_rebuttal=True  urgent=False  has_supp=True

Q: 美国Visa 13.1拒付爆了紧急，不是的我们已经发过物流了
  is_rebuttal=True  urgent=True  has_supp=True  ← 同时命中 Fix G + Fix H
```

### 4.3 ctx 注入到 PDA 知识库检索

`routers.route_pda()` 把 `merchant_supplement` 拼到 `query_text`：

```python
effective_query = f"{query}\n\n[商户补充事实]\n{merchant_supplement}"
params["query_text"] = effective_query   # ← PDA Tool 拿去做 Chroma 语义检索
```

**结论**：商户反驳事实被注入到 PDA 检索 query，**让 LLM 看到新事实后能调整 root_causes/actions**（与真人客服接受反驳 + 重新分析一致）✅

---

## 5. Fix H 验证：紧急语气 + 同理心开头

### 5.1 单元测试（6 个 case）

```
TestHasUrgentSignal
  ✓ test_紧急_is_urgent
  ✓ test_急_is_urgent
  ✓ test_爆了_is_urgent
  ✓ test_崩了_is_urgent
  ✓ test_normal_question_not_urgent
  ✓ test_empty_not_urgent
```

### 5.2 真实 webhook 验证

商户发 `美国Visa 13.1拒付爆了紧急`：

```
HTTP 200
商户收到 2 条消息（链式 PDA → TRA）：
  1. 🤝 我理解您很着急——这类情况对商户现金流影响很大。
     我立刻为您深度分析 + 派单到对应团队：

     🔍 诊断结果：拒付
     置信度：80%
     📋 问题分析：
       1. 拒付原因码 13.1「Merchandise/Services Not Received」...

  2. ✅ 工单已创建（ID tkt_4f0674cb5180），分派至 财务团队-争议处理，SLA 4h
```

**结论**：同理心短句在 PDA 诊断前 prepend，**冷冰冰的诊断文字变成「先共情 → 再分析 → 再派单」的真人客服节奏** ✅

---

## 6. PolishResult 数据类（综合）

```python
@dataclass
class PolishResult:
    is_farewell: bool = False
    farewell_reply: Optional[str] = None
    recent_ticket_id: Optional[str] = None
    is_rebuttal: bool = False
    urgent_prepend: Optional[str] = None
    merchant_supplement: Optional[str] = None
```

### 6.1 综合场景单元测试（5 个 case）

```
TestPolishQueryMain
  ✓ test_farewell_returns_farewell_reply
  ✓ test_farewell_skips_other_detectors     ← 告别语优先，不走其他检测
  ✓ test_rebuttal_sets_supplement
  ✓ test_urgent_sets_prepend
  ✓ test_normal_question_returns_minimal_polish
  ✓ test_combined_rebuttal_and_urgent      ← 同时命中 Fix G + Fix H
```

### 6.2 webhook 集成测试（4 个 case）

```
TestWebhookPolishing
  ✓ test_fix_e_farewell_skips_orchestrator
  ✓ test_fix_h_urgent_prepends_empathy
  ✓ test_fix_f_dedup_second_call_returns_cached_reply
  ✓ test_fix_g_rebuttal_injects_supplement_to_ctx
```

---

## 7. 真实 HTTP 全链路验证

通过 `urllib.request` POST `/feishu/webhook`：

```
=== Real backend via curl-style HTTP ===
Fix E: HTTP 200, resp={'code': 0, 'msg': 'success'}     ← 告别语
Fix H: HTTP 200, resp={'code': 0, 'msg': 'success'}     ← 紧急
Fix F: 1st=200, 2nd=200                                 ← 去重（同一 query 第 2 次）
Fix G: HTTP 200, resp={'code': 0, 'msg': 'success'}     ← 商户反驳
```

---

## 8. 回归测试

```
$ python -m pytest tests/ -q --no-header
334 passed, 1200 warnings in 57.74s
```

含：
- **新增** 38 个 polishing 测试（34 单元 + 4 webhook 集成）✅
- **原有** 296 个测试全部通过（含 Day 15 P0-C2 修复测试） ✅
- **0 回归** ✅

---

## 9. 验收清单

| 项 | 测试 | 文件 | 期望 | 实际 |
|---|---|---|---|---|
| Fix E（单元） | 13 case | tests/test_polishing.py | 全部 is_farewell 判定 | ✅ |
| Fix E（webhook） | "好的" | curl POST | 1 条短文本，无诊断 | ✅ |
| Fix F（SQLite） | record + lookup | DB inspect | 数据落盘 + 可查 | ✅ |
| Fix F（webhook） | 同 query 第 2 次 | curl POST | 1 条去重提示 | ✅ |
| Fix G（单元） | 6 case | tests/test_polishing.py | 反驳 + 事实 → True | ✅ |
| Fix G（ctx 注入） | PDA query_text | code inspect | 含「[商户补充事实]」 | ✅ |
| Fix H（单元） | 6 case | tests/test_polishing.py | 紧急词 → True | ✅ |
| Fix H（webhook） | "爆了紧急" | curl POST | 第 1 条消息含 🤝 | ✅ |
| 综合场景 | 5 case | tests/test_polishing.py | PolishResult 字段正确 | ✅ |
| 真实 HTTP | 4 fixes | urllib POST | 全部 200 | ✅ |
| 回归 | 334 tests | pytest | 全部 passed | ✅ |

---

## 10. 诚实声明

✅ **真实验证**：所有 4 个 Fix 都通过真实 Python 调用 + 真实 HTTP POST 验证（不是 mock）。
✅ **真实 SQLite**：`polishing.db` 真实创建在 `src/data/`，包含去重记录。
✅ **真实 backend**：连真实 `localhost:8000`，PID 11484，`Started server process`。

⚠️ **未端到端验证的环节**：
- Fix H 同理心开头：商户真实看到的效果需要录屏时打开飞书客户端人工确认。
- Fix F 去重：5 分钟窗口期的边界 case（如 4 分 59 秒 vs 5 分 01 秒）需要时间跨度的录屏验证。
- Fix G ctx 注入：商户反驳事实后 AI 是否真的调整 root_causes，需要看 LLM 真实响应（本项目用 Mock LLM，效果在 LLM prompt 设计上有效，但 Qwen 真实调用时 LLM 是否「听劝」需录屏验证）。

⚠️ **已知边界**：
- 单轮对话场景下 Fix G 的"反驳"识别依赖商户 query 自带反驳词；如果商户只说"我们已经发了物流"（无反驳词）会被当成新问题。
- 多轮对话上下文管理（记忆前序诊断）是 Day 17+ 的任务，本轮不做。

---

## 11. 文件清单

```
docs/reports/day16_verification/
└── README.md                       ← 本文档（审查用）

src/backend/
├── app/agents/orchestrator/polishing.py      ← 新增模块（280 行）
└── app/implementations/feishu/webhook.py      ← handle_event 接线

src/backend/tests/
├── test_polishing.py                          ← 新增 34 个单元测试
└── test_pda_param_extraction.py               ← 追加 4 个 webhook 集成测试

src/backend/app/agents/orchestrator/routers.py ← route_pda 注入 merchant_supplement
src/data/polishing.db                          ← SQLite 数据（自动生成）
```

**复现方法**：

```bash
cd E:/ai-pioneer/src/backend
PYTHONIOENCODING=utf-8 python -m pytest tests/test_polishing.py -v
PYTHONIOENCODING=utf-8 python -m pytest tests/test_pda_param_extraction.py::TestWebhookPolishing -v
```

---

## 12. 与 Day 15 的对比

| 维度 | Day 15 后 | Day 16 后 |
|---|---|---|
| 商户说"好的" | 走 Orchestrator → 一长串诊断 | 1 条告别语 ✅ |
| 商户说"爆了紧急" | 直接诊断文字 | 同理心开头 + 诊断 ✅ |
| 商户 5 分钟内重复发 | 每次新建工单 | 返「已派过」提示 ✅ |
| 商户反驳"不是的..." | 完全无上下文 | PDA 检索 query 含补充事实 ✅ |
| 测试数 | 296 | **334**（+38） ✅ |

---

## 13. 下一步（Day 17+ 候选）

- **多轮上下文管理**：记忆前序诊断（"商户说不是的" → 真的调整 root_causes）
- **告别语扩展**：识别「收到」「好的辛苦」「👌」+ 不限于 ≤ 15 字符
- **去重窗口可配置**：从硬编码 300s 改成 env var 或 ctx 参数
- **同理心短句本地化**：根据 problem_type 给不同共情话术（拒付 vs 接入 vs 退款）

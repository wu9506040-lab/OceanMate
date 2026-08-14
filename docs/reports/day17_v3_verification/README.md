# Day 17 v3 知识沉淀人工审核验证报告（半自动闭环完整）

> **生成时间**：2026-08-15
> **Backend 版本**：Day 17 v3（数字员工闭环第 5 段补齐）
> **测试方式**：真实 Python pytest + 单元 + 集成
> **总通过率**：**24/24 = 100%**（审核流程测试）+ 434/434 全量回归

---

## 0. 补齐动机

Day 17 v3 提交前夜用户反馈：
> "知识沉淀人工审核在哪，我没看到啊"

原 Day 17 v3 实现只完成了「自动审核」（confidence ≥ 0.9 → 自动写 KB），
缺人工审核（0.7-0.9 → 运营审核）。中高置信度案例最需要人工把关，
否则自动入库会污染 KB 检索结果。

本补完整半自动知识沉淀闭环：

```
[商户提问] → [AI 诊断] → [派单] → [人工解决] → [关单]
                                                    ↓
                                            [生成 case_001]
                                          confidence = 0.78
                                                    ↓
                                            ┌───────┴───────┐
                                            ↓               ↓
                                       ≥ 0.9 → auto    0.7-0.9 → pending
                                            ↓               ↓
                                       写 faq_vec    运营收到提醒
                                                        ↓
                                                「✅ case_001」
                                                        ↓
                                                   写 faq_vec
                                                       ↓
                                            「✅ case_001 已加入知识库
                                              当前 faq_vec 共 N 条」
```

---

## 1. 5 类测试覆盖

| 测试类 | 测试数 | 覆盖点 |
|--------|--------|--------|
| TestApproveCase | 5 | 写 Chroma / 幂等 / 缺 case_id / case 不存在 / 无 DB |
| TestRejectCase | 3 | 不写 Chroma / 不存在 case 也记录 / 缺 case_id |
| TestDetectReviewCommand | 9 | 中文 approve/reject / ✅/❌ / 英文 / 无 case_id / 误判保护 |
| TestRouteKeaReviewPriority | 2 | 审核命令 > search_faq / 普通 query 仍 search |
| TestFmtKeaApproveReject | 4 | approve 成功/失败 / reject 成功/失败反馈 |
| **合计** | **24** | **100% 通过** |

---

## 2. 关键代码改动

| 文件 | 行数 | 改动 |
|------|------|------|
| `app/agents/kea/tool.py` | +150 | `_approve_case` / `_reject_case` / `_record_review_decision` + `_error_result` 增 approved/rejected flag |
| `app/agents/orchestrator/routers.py` | +90 | `_KEA_REVIEW_KEYWORDS` / `_KEA_CASE_ID_RE` / `_KEA_APPROVE_VERBS` / `_KEA_REJECT_VERBS` / `_detect_review_command` + `route_kea` 优先级提升 |
| `app/implementations/feishu/webhook.py` | +50 | `_fmt_kea_approve` / `_fmt_kea_reject` + `_fmt_kea` 分支 |
| `tests/test_kea_review.py` | +400 | 24 个新测试 |

---

## 3. 命令格式支持（运营能秒懂）

| 命令 | 效果 |
|------|------|
| `审核 case_001 通过` | approve_case |
| `审核 case_001 拒绝` | reject_case |
| `审一下 case_001 通过` | approve_case |
| `审批 case_001 不通过` | reject_case |
| `✅ case_001` | approve_case |
| `❌ case_001` | reject_case |
| `approve case_001` | approve_case |
| `reject case_001` | reject_case |

---

## 4. 反馈格式（用户原文要求）

**审核通过**：
```
✅ case_001 已通过审核，已加入知识库，当前 faq_vec 共 3 条（审核人：ou_op_001）。

下次商户问同样问题，AI 就能直接复用这条知识。
```

**审核拒绝**：
```
❌ case_001 已拒绝
理由：证据不足（记录人：ou_op_001）。
该案例不会进入知识库，避免污染检索结果。
```

**审核失败（缺 case_id）**：
```
⚠️ 审核未通过：case_id 必填
```

---

## 5. 路由优先级（防误判）

```python
# route_kea 子意图选择优先级
0. 命中审核关键词 + case_id        → approve_case / reject_case   ← Day 17 v3 新增
1. ctx.case_id                     → promote_to_faq
2. ctx.query 显式传入              → search_faq
3. query 命中 search 关键词         → search_faq
4. 默认                            → list_candidates
```

**设计原则**：人工审核命令是「写操作」，必须比「读操作」（search/list）优先级高，
避免「审核 case_001」被误识别为「搜索 case_001 的知识」。

---

## 6. 三段审核逻辑保留

| confidence | 动作 | 实现 |
|------------|------|------|
| ≥ 0.9 | **自动通过** → 写 Chroma faq_vec | `promote_to_faq` auto_promote |
| 0.7-0.9 | **pending_review** → 运营审核 | `approve_case` / `reject_case` |
| < 0.7 | **自动拒绝** → 不入库 | 不写 Chroma |

**关键设计**：0.7-0.9 区间是「机器不确定 + 值得保留」的灰色地带，必须人工判断。
强制自动通过会污染 KB，强制拒绝会丢失有价值的案例。

---

## 7. 幂等保护（防重复审）

```python
# KEA._approve_case 实现
existing_meta = self._get_embedding_meta(source_table="cases", source_id=case_id)
if existing_meta is not None:
    return {"approved": False, "already_approved": True, ...}
```

重复 approve 同一 case_id → 返 `already_approved`，不重复写 Chroma，不重复写 embedding_meta。

---

## 8. 录屏演示脚本（明日 Day 18 用）

```
T0  商户:  「BR Visa 拒付，错误码 13.1，怎么办？」
T1  AI:     「第一步：让商户提供订单号 / 第二步：核实 3DS / 第三步：发卡行反馈」
            + 自动派单（高优先级），简报私发给 lead
T2  运营:   在 lead 私聊里看到简报，联系商户
T3  商户:   「订单号 XXX，3DS 没触发，发卡行说风控拦截」
T4  运营:   在对话里说「已解决」 → TRA 关单 → KEA 生成 case_001（confidence 0.78）
T5  AI:     （私发运营）「新案例 case_001 待审核，置信度 0.78，回复 ✅ 通过 或 ❌ 拒绝」
T6  运营:   在对话里回复「✅ case_001」
T7  AI:     「✅ case_001 已通过审核，已加入知识库，当前 faq_vec 共 3 条」
T8  商户:   （30 分钟后）「BR Visa 13.1 又拒付了」
T9  AI:     （直接复用 case_001 的诊断）→ 5 秒出方案，不用再问运营
```

**闭环完成**：诊断 → 派单 → 解决 → 关单 → 沉淀 → 复用，整个链路在飞书对话里完成。

---

## 9. 测试结果

```bash
$ python -m pytest tests/test_kea_review.py -v
============================= 24 passed in 3.71s ==============================

$ python -m pytest tests/ -q
============================= 434 passed in 57.49s ==============================
```

| 项目 | 数量 |
|------|------|
| 新增测试 | 24 |
| 已有测试 | 410 |
| **总计** | **434 passed** |

---

## 10. 提交记录

- `4842640` feat(day17-v3): 知识沉淀人工审核（数字员工闭环第 5 段 - 半自动闭环完整）
- 推送：github 成功（gitee 历史分歧跳过）

---

## 11. 已知边界（数据诚实）

✅ **真实验证**：24 个单测 + 410 个回归测试 100% 通过。
✅ **真实链路**：webhook → orchestrator → KEA approve_case → Chroma 写入 + feedback 全部走通。
✅ **真实命令识别**：5 种命令格式（中/英/emoji）都通过单元测试。

⚠️ **未端到端验证**：在真实飞书客户端从「商户提问 → 关单 → 审核 → 复用」的完整流程需要在明日（Day 18）录屏时人工确认。
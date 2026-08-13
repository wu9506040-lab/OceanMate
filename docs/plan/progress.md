# 进度跟踪（progress.md · Day 12）

> 实时记录 13 天冲刺的进度。每完成一项打 ✅，遇到阻塞用 🔴 标记。
> 更新频率：每完成一个 WBS 任务更新一次；遇到阻塞立即更新。

---

## 总体进度

| 阶段 | 状态 | 完成度 |
|------|------|--------|
| Phase 1 仓库骨架（7-17） | ✅ 完成 | 14/14 (100%) |
| Phase 2 方案 + 架构（7-18） | ✅ 完成 | 7/7 (100%) |
| Phase 3 代码 + Demo（Day 1-10） | ✅ 完成 | 7/7 (100%) |
| **Phase 4 真实接入 + 录屏 + 提交（Day 8-13）** | 🔄 **进行中** | 9/12 (75%) |

**总进度**：**37/40（90%）** | **当前时间**：2026-08-10 21:00 · Day 12 末
**距离截止**：**6 天**（2026-08-16）

---

## Phase 4 详情（Day 8-13 · 当前）

| ID | 任务 | 状态 | 完成时间 | 备注 |
|----|------|------|---------|------|
| 4.1 | Chunking + Cleaner + Embedder 接口 + Pipeline | ✅ | Day 8 | 226 测试通过 + 17 新文件 |
| 4.2 | 真实 Embedding（DashScope） | ✅ | Day 9 | Chroma 3 collection 满载 |
| 4.3 | 107 张拒付码配图 | ✅ | Day 9 | SVG + PNG 4 类配色 |
| 4.4 | PDA fallback 修复 | ✅ | Day 9 | country.maxLength=2→6 + pattern GLOBAL |
| 4.5 | 真实 LLM 接入 Qwen | ✅ | Day 10 | MSA 走真 LLM + PDA Mock 降级 |
| 4.6 | 智能交接简报（亮点） | ✅ | Day 10 | PDA→TRA + send_private briefing |
| 4.7 | 飞书真实凭证切换 | ✅ | Day 11 | cli_aaf8271... + 新 Secret + bitable token |
| 4.8 | 3 张多维表格 Seed | ✅ | Day 11 | error_codes 117 + payment_methods 16 + routing_rules 10 = 143 条 |
| 4.9 | upload_image / records import 修 bug | ✅ | Day 11 | image_type 字段 + batch_create 端点 |
| 4.10 | WS 真实事件接收 | ✅ | Day 11 | events_received=1 + 你好消息 + bot 主动回复 |
| 4.11 | **submission.md 终稿** | 🔄 进行中 | Day 12 | 6 Agent 6 件套 + 4 Tool 详解 |
| 4.12 | **3 段录屏**（主 demo + AtoA + 飞书原生） | ⏳ 待办 | Day 13-14 | 录屏脚本 + 视频 |
| 4.13 | **GitHub README 包装** + 提交材料索引 | ⏳ 待办 | Day 15 | cross-check + 自检报告 |

---

## Day 12 关键里程碑（追加）

| 里程碑 | 时间 | 通过判据 | 状态 |
|--------|------|---------|------|
| **M7-a 多维表迁飞行社** | **Day 12 20:30** | **新 APP_TOKEN 建表 + 143 条 + 50 模拟工单** | ✅ |
| **M7-b 真实 lead open_id** | **Day 12 20:50** | **占位→ou_aa9ece53... + 加协作者 edit** | ✅ |
| **M7-c Dashboard 配完** | **Day 12 21:00** | **5 模块配出（标题/配色/趋势图/柱状图 4 错误待修）** | 🔄 |
| **M7-d submission.md 终稿** | Day 12 23:00 | 6 Agent 6 件套完整 | ⏳ |

---

## 阻塞清单（🔴）

| 阻塞项 | 触发时间 | 影响范围 | 解阻塞动作 | 状态 |
|--------|---------|---------|-----------|------|
| ~~飞书企业账号未到~~ | ~~7-17 22:00~~ | ~~Phase 3 全部~~ | ~~改 mock + 本地 LLM~~ | ✅ **已解除（Day 11 凭证到位）** |
| ~~跨租户问题~~ | ~~Day 11 00:30~~ | ~~WS 收不到事件~~ | ~~用户切到「飞行社企业」~~ | ✅ **已解除** |
| ~~im:chat:readonly 权限缺失~~ | ~~Day 11 00:40~~ | ~~list_chats 99991672~~ | ~~后台开通应用身份权限~~ | ✅ **已解除** |
| 真实 lead open_id 缺失 | Day 11 末 | 智能交接简报收件人是 demo 占位 | 后续从「飞行社企业」成员管理查 | 🟡 非阻塞（demo 占位可用） |

---

## 风险监控（🟡 黄色预警 / 🔴 红色阻塞）

| # | 风险 | 等级 | 触发条件 | 当前状态 | 应对 |
|---|------|------|---------|---------|------|
| 1 | ~~飞书 AI 权限未到~~ | ~~🔴~~ | ~~7-18 12:00 未申请到~~ | ~~改 mock + 文档截图~~ | ✅ **已解除** |
| 2 | 录屏失败 | 🟡 | 8-14 未完成 | 待监控 | 拆 3 段独立短片（每段 1 分钟） |
| 3 | submission.md 写不完 | 🟡 | 8-12 未完成 | 待监控 | 6 Agent 6 件套直接复 Day 8-10 文档 |
| 4 | 飞书 WS 突然掉链 | 🟡 | 录屏时断 | Poller 兜底（FEISHU_POLL_CHAT_ID 已写入 .env） | 紧急时启 Poller |
| 5 | 评委质疑真实度 | ✅ | — | 193 条数据（117+16+60）+ 真实 WS + 真实 send_private briefing | — |

---

## 决策日志（2026-08-10 · Day 11 追加）

| 时间 | 决策内容 | 决策理由 | 决策人 |
|------|---------|---------|--------|
| 2026-08-10 00:30 | 飞书跨租户问题 → 用户切到「飞行社企业」 | list_chats 0 个 chat + WS 0 events，跨租户安全策略不可绕过 | zwyyy7 |
| 2026-08-10 00:40 | im:chat:readonly 应用身份权限开通 | list_chats 99991672，需应用身份权限（非用户身份） | zwyyy7 |
| 2026-08-10 00:50 | Poller fallback 写入 .env（chat_id=oc_6296625...） | WS 不稳定时快速切兜底，不需重新配置 | zwyyy7 |
| 2026-08-10 01:00 | 完成度评估 90% | 飞书真实接入全通，剩文档 + 录屏 4 天足够 | zwyyy7 |
| 2026-08-10 20:30 | 多维表迁飞行社企业 | 测试企业 91403 Forbidden 阻塞 → 重建在飞行社 APP_TOKEN `REDACTED_BITABLE_TOKEN` | zwyyy7 |
| 2026-08-10 20:45 | 加 50 模拟工单 | 6 模块 dashboard 有真实数据看 | zwyyy7 |
| 2026-08-10 20:50 | 真实 lead open_id 替换 | `ou_demo_lead_tech_l2` → `REDACTED_LEAD_OPEN_ID` | zwyyy7 |
| 2026-08-10 21:00 | Dashboard 5 模块配出 | 4 个错误待修（标题/配色/趋势图/柱状图） | zwyyy7 |

---

## 变更日志（2026-08-10 · Day 11 追加）

| 时间 | 变更内容 | 变更人 |
|------|---------|--------|
| 2026-08-10 00:00 | .env 写入新飞书凭证（cli_aaf8271... + 新 Secret + bitable token） | zwyyy7 |
| 2026-08-10 00:10 | seed_bitables.py 落地（建 3 表 + 143 条） | zwyyy7 |
| 2026-08-10 00:15 | test_real_feishu_e2e.py 落地（4 项通道测试） | zwyyy7 |
| 2026-08-10 00:20 | diag_feishu.py 落地（list_chats + list_messages 诊断） | zwyyy7 |
| 2026-08-10 00:30 | 修 upload_image 缺 image_type 字段 | zwyyy7 |
| 2026-08-10 00:35 | 修 batch_create 端点（不是 /records）| zwyyy7 |
| 2026-08-10 00:40 | 补 im:chat:readonly 权限 | zwyyy7 |
| 2026-08-10 00:50 | 用户切到「飞行社企业」后 WS 收事件成功 | zwyyy7 |
| 2026-08-10 00:55 | bot 主动 send_message 成功（message_id=om_x100b68bf...）| zwyyy7 |
| 2026-08-10 01:00 | FEISHU_POLL_CHAT_ID 写入 .env（Poller 兜底） | zwyyy7 |

---

## 备注（Day 11 末 · 截至 2026-08-10 01:00）

- **今夜完成**：飞书真实接入全链路 ✅（凭证 / 3 表 / WS / 双向消息 / chat_id / open_id）
- **完成度**：90%（↑15% 来自今天）
- **剩余工期**：6 天（8-11 ~ 8-16）
- **明天 8-11 必做**：submission.md 终稿（6 Agent 6 件套 + Part 1/2 更新）
- **Day 13-14 必做**：3 段录屏（主 demo 3 分钟 + AtoA 1 分钟 + 飞书原生 1 分钟）
- **Day 15 必做**：GitHub README 包装 + 提交材料索引 + cross-check
- **Day 16 截止**：22:00 前提交

**比赛评分自检（8 项 · 当前水平）**：
- 命题匹配 9.5 / 业务理解 9.0 / AI 方案合理性 9.0 ↑ / 技术可实现性 9.0 ↑
- 创新性 9.0 / 学生可信度 9.0 → **整体 90 分水平** ↑（昨天 85-90）
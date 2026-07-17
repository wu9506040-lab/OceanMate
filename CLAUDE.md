# OceanMate 跨境商户成功助手 — CLAUDE.md（比赛精简版）

> 项目级约束，源自原 E:\智能客服\CLAUDE.md V2.1。
> **本版本适配 2 天冲刺 + 飞书 AI 生态，保留治理骨架，砍掉企业级细节。**

---

## 1. 项目身份

| 维度       | 值                                                                |
|------------|-------------------------------------------------------------------|
| 业务       | 跨境支付商户成功运营助手（OP/Oceanpayment 命题）                   |
| 赛事       | 2026 飞书 AI 先锋未来人才大赛 · 华南 · 报名截止 2026-07-19         |
| 技术栈     | FastAPI + Vue3 + Qwen (DashScope) + 飞书 AI 全家桶                |
| 架构基线   | 6 Agent + AtoA 协议 + 飞书生态（见 `docs/architecture/oceanmate.md`） |
| 工程纪律   | 本文件 + `docs/governance/race_sop.md`                              |

**比赛核心命题**：「AI 驱动的跨境商户成功运营助手」—— 商户选型 / 接入 / 诊断 / 工单 / 知识 / 协同。

---

## 2. 三大原则（保留 · 不可违反）

| # | 原则 | 含义 | 落地 |
|---|------|------|------|
| 1 | **Interface First** | 先定义 Protocol 再写实现 | 6 Agent 各自有独立 Protocol，放 `src/backend/app/agents/<name>/protocols.py` |
| 2 | **Module Isolation** | 6 Agent 强隔离，禁止跨 Agent 侵入 | Agent 之间仅通过 AtoA 协议交互，不直接调用内部函数 |
| 3 | **Dependency Inversion** | 依赖方向单向，上层依赖抽象 | FastAPI Depends / 工厂函数；禁止 `new` 具体类 |

---

## 3. 禁止行为（比赛版 · 5 条）

| # | 禁止                                                  | 原因                          |
|---|-------------------------------------------------------|-------------------------------|
| 1 | 引入 Kafka / Milvus / Elasticsearch / 新的数据库       | 单体架构基线（比赛 PoC 不需要）|
| 2 | 跨 Agent 写代码（如诊断 Agent 直接调路由 Agent 内部函数）| 违反 Module Isolation        |
| 3 | 一次性设计"未来系统"（空实现 / 占位代码 / TODO-only）   | YAGNI（2 天冲刺不养闲代码）   |
| 4 | API Key / 凭证硬编码到代码或提交到 Git                  | §7 安全 + 比赛评分合规         |
| 5 | 改完未跑验证（curl / pytest / browser / 录屏 四选一缺失）| 比赛提交 = 必须可演示          |

---

## 4. 比赛 4 步任务法（精简自原版 6 步）

| Step | 名称     | 内容                                          |
|------|----------|-----------------------------------------------|
| 1    | 任务分析 | 读相关文件 + 列涉及模块 / 风险点                |
| 2    | 方案设计 | 输出完整方案（接口 / 数据 / 飞书集成 / 录屏）  |
| 3    | 动手开发 | 实施 + 自检（§5 Stop-Loss 6 问通过）           |
| 4    | 提交归档 | commit + Part 1/2 终稿 + 录屏 + 报名表          |

**AI 接到任务必须走完这 4 步；任何一步未完成不得进入下一步。**

### 4.1 Step 2 自检：反例清单 5 条

| #  | 反例                                                | 正确做法                              |
|----|-----------------------------------------------------|---------------------------------------|
| 1  | Agent 直接 `import dashscope; Generation.call(...)` | Agent → `LLMProvider` Protocol       |
| 2  | Prompt 写在 `chat_service.py:42` 的 f-string        | 放 `config/prompts/{name}.yaml`        |
| 3  | 业务规则 `if emotion_score > 80:` 硬编码            | 读 `config.yaml.emotion_threshold`    |
| 4  | 看到 PR 涉及 6 Agent 中 3+ 个                       | 拆 PR / 拆 commit                    |
| 5  | 改完未跑相关测试/录屏就提交                          | §5 自检 + §6 验证                    |

### 4.2 Step 3 Stop-Loss：自检 6 问

| #   | 自检问题                                            | 不通过怎么办              |
|-----|-----------------------------------------------------|---------------------------|
| 1   | 涉及哪些 Agent？每个 Agent 改动 < 100 行？           | 拆 commit                 |
| 2   | 接口签名变化是否同步更新所有调用方？                 | grep 引用                 |
| 3   | 是否引入新依赖？是否在 requirements？               | 加依赖后跑一次 build      |
| 4   | Prompt / 配置改动是否已文档化？                     | 更新 §8 / config          |
| 5   | 是否破坏现有测试？是否新增对应测试？                | pytest + 录屏验证         |
| 6   | 是否触发了 §6 验证分级？每项过？                   | 不满足回 §4               |

---

## 5. Scope Lock（单次任务 · 模块边界）

### 5.1 默认：单 Agent

| 单 Agent 示例                  | 说明                  |
|-------------------------------|-----------------------|
| 仅改诊断 Agent                 | 不动路由 / 协同        |
| 仅改飞书 Webhook 集成          | 不动 6 Agent 逻辑      |
| 仅改前端一个组件               | 不动后端 / 协议        |
| 仅改文档 / Mermaid 图          | 不动代码              |

### 5.2 跨 Agent 改动例外路径

**遇到跨 Agent 改动，先看能否拆成多个 commit；若必须一起改，按 4 要素：**

| # | 必填项        | 示例                                                         |
|---|---------------|--------------------------------------------------------------|
| 1 | 业务原因      | "诊断 Agent 必须联动知识 Agent，否则给商户错误答案"          |
| 2 | 接口变化      | "DiagnosisAgent 增加 `on_query` 事件"                        |
| 3 | 影响范围      | "Diagnosis + Knowledge 两个 Agent；前端只展示，不动"          |
| 4 | 隔离策略      | "Diagnosis 改完 commit 后再改 Knowledge；先用 mock 隔离验证"  |

不满足四要素不批准执行。

---

## 6. 验证标准（比赛版 · 3 级）

| 变更类型           | 验证手段                       | 通过判据                              |
|--------------------|--------------------------------|---------------------------------------|
| 文档 / 注释 / Mermaid 图 | 肉眼通读                   | 无错字；图渲染正常                    |
| Prompt / 配置        | 单测 + 黄金用例（≥ 3 条）       | 全部命中预期                          |
| API 路由 / 6 Agent    | curl + pytest + 飞书 webhook    | 200/正确字段；异常路径返 4xx          |
| 飞书生态集成          | 录屏（智能伙伴对话 + 多维表格）  | 3 分钟内可演示完整业务流              |
| 前端 UI               | build + 浏览器肉眼检查          | 视觉/交互符合预期，无控制台报错       |

**禁止只改代码不验证；禁止"跑过就行"的心态。**

---

## 7. 安全（精简 4 条）

| # | 规则                                                |
|---|-----------------------------------------------------|
| 1 | API Key / Secret 全部走环境变量，`.env` 加入 `.gitignore` |
| 2 | JWT / OAuth Token 不进 URL 参数，不进前端 localStorage |
| 3 | 用户输入（商户咨询内容）做长度限制 + 内容过滤        |
| 4 | 飞书 Webhook 校验签名，防伪造                       |

---

## 8. 文档与提交（比赛 8 件套）

每完成一个关键 Agent，必须在 `docs/reports/submission.md` 追加：
1. What（做了什么）
2. Why（为什么）
3. Flow（输入 → 输出）
4. Architecture Role（在 6 Agent 中的位置）

**新 Agent 交付 6 件套（强制）**：

| # | 交付物          | 形式                                          |
|---|-----------------|-----------------------------------------------|
| 1 | Agent 职责说明  | `docs/reports/submission.md` 中追加章节       |
| 2 | Protocol        | `src/backend/app/agents/<name>/protocols.py` |
| 3 | Schema          | Pydantic Input / Output                       |
| 4 | 依赖关系图      | learning_log 文字或 Mermaid                   |
| 5 | 调用流程        | Mermaid sequence diagram                      |
| 6 | 录屏            | `demo/recordings/`（git ignore）              |

---

## 9. 与原项目的关系

| 维度     | 原 E:\智能客服（V3.1）         | 本 E:\ai-pioneer（OceanMate）   |
|----------|------------------------------|--------------------------------|
| 业务     | 电商智能客服                   | 跨境支付商户成功                |
| 治理     | V2.1 · 18 条 + 13 反例        | 本文件 · 5 禁 + 5 反例          |
| 架构     | V3.1 业务架构                  | 6 Agent + AtoA                  |
| AI       | Qwen + RAG + Emotion          | Qwen + RAG + 飞书 AI 全家桶     |
| 数据     | MySQL + Qdrant + Redis        | 多维表格 + 飞书妙记（不引入新 DB）|
| 复用     | —                              | Provider 抽象 + Prompt 配置化思想 |

**禁止污染原项目**。本项目所有 commit 仅限 `E:\ai-pioneer\` 范围内。

---

## 附录 A：相关文档索引

| 场景                       | 文档                                          |
|----------------------------|-----------------------------------------------|
| 比赛 SOP（提交/录屏/组队） | `docs/governance/race_sop.md`                  |
| 6 Agent 架构              | `docs/architecture/oceanmate.md`               |
| AtoA 时序图                | `docs/architecture/atoa_sequence.md`           |
| 任务计划                   | `docs/plan/task_plan.md`                        |
| 进度跟踪                   | `docs/plan/progress.md`                         |
| 行业调研                   | `docs/plan/findings.md`                         |
| 报名提交材料汇总           | `docs/reports/submission.md`                    |
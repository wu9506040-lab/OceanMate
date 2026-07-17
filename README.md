# OceanMate AI — 跨境商户成功运营助手

> **让 AI 成为跨境商户的"AI 合伙人"和 OP 内部的"数字员工体系"**
>
> 2026 飞书 AI 先锋未来人才大赛 · 华南赛区 · 钱海网络（Oceanpayment）命题参赛项目

[![GitHub](https://img.shields.io/badge/GitHub-wu9506040--lab%2FOceanMate-181717?logo=github)](https://github.com/wu9506040-lab/OceanMate)
[![Gitee](https://img.shields.io/badge/Gitee-zwyyy7%2Focean--mate-C71D23?logo=gitee)](https://gitee.com/zwyyy7/ocean-mate)
[![License](https://img.shields.io/badge/License-MIT-blue)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green?logo=python)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Qwen](https://img.shields.io/badge/LLM-Qwen%20(DashScope)-ff6a00)](https://help.aliyun.com/zh/dashscope)

---

## 🌊 一句话定位

**OceanMate AI 不是"AI 客服"，而是 OP 商户成功团队的"数字员工体系"** —— 由"商户成功 AI 中枢"统领 4 类业务 Agent，让 AI 参与商户选型、支付接入、异常诊断、工单协同、知识沉淀的全生命周期运营。

| 视角 | 助手角色 | 核心动作 |
|------|---------|---------|
| 🛒 商户侧 | 24h AI 合伙人 | 选型咨询 → 接入指引 → 故障诊断 → 增长建议 |
| 🤝 OP 侧 | 跨团队 AI 调度员 | 智能分诊 → 工单路由 → 知识沉淀 → 协同加速 |

---

## 🎯 我们看到的痛点 → OceanMate 的方案

| 真实痛点（公开调研） | 传统 AI 客服 | OceanMate |
|----------------------|------------|----------|
| 跨境电商「退款问题」居投诉 TOP 1（占比 20.00%），「任意仅退款」（仅退款不退货）占 13.60%<sup>[1]</sup> | 只能回答"什么是退款" | **支付诊断 Agent**：错误码归因 + 证据链 + 自动申诉路径 |
| 选型错代价高：OP 500+ 支付产品 / 200+ 国家地区 / 5+ 行业（跨境外贸/旅游航空/软件游戏/数字版权/教育培训）<sup>[2]</sup> | 答非所问 | **商户顾问 Agent**：画像匹配 + RAG 检索 + 推荐组合 |
| 工单协同低效：OP 内部"拉群+截图"模式 | 完全没有能力 | **工单路由 Agent**：飞书多维表格 + 审批流自动派单 |
| 知识沉淀散落：OP 经验散落各团队 | 答完即失 | **知识进化 Agent**：案例→FAQ→知识库→下次自动命中 |

> 关键立场：**AI 不是替代人工，而是让商户成功从"被动响应"升级为主动运营**。

---

## 🏗 4 业务 Agent + 商户成功 AI 中枢

```
┌──────────────────────────────────────────────────────────────────┐
│  📲 入口层 · 飞书 AI 全家桶                                        │
│     智能伙伴(对话)  ·  多维表格(工单池/知识库)  ·  妙记(会议沉淀)   │
│     审批流(SLA)   ·  AI 字段(智能标签)                            │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  🧠 中枢层 · 商户成功 AI 中枢 (Orchestrator)                       │
│     · 意图分流  ·  上下文传递  ·  4 Agent 调度                      │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  🤖 数字员工层 · 4 业务 Agent                                       │
│   ① Merchant Success         ② Payment Diagnosis    ⭐          │
│      选型 + 协作采集              错误码归因 + 证据链                  │
│                                                                  │
│   ③ Ticket Routing           ④ Knowledge Evolution              │
│      飞书多维表格派单              案例→FAQ→RAG 自进化              │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  🔌 Provider 抽象层（PoC ↔ 真实环境切换关键）                      │
│   LLMProvider (Qwen)  ·  VectorStore  ·  Feishu  ·  PaymentSource │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  📦 数据源 · Demo 占位 + OP 真实接口 Provider 抽象预留               │
│   风控规则库 · 通道状态库 · 对账快照 · 飞书多维表格知识库              │
└──────────────────────────────────────────────────────────────────┘
```

📐 详细架构图 + 协作矩阵：[`docs/architecture/agent_architecture.md`](./docs/architecture/agent_architecture.md)
📐 端到端业务流（4 Agent 协同）：[`docs/architecture/business_flow.md`](./docs/architecture/business_flow.md)

---

## ✨ 4 项核心创新点（对应赛制 §四条 评审 4 维度）

| # | 创新 | 类型 | 对应评审维度 | 一句话 |
|---|------|------|----------|-------|
| 1 | **数字员工定位** | 模式 | AI 创新性 | AI = 商户成功团队"数字员工"，而非"高级客服" |
| 2 | **证据链归因** | 技术+流程 | 方案专业度 | 每条诊断附 `risk_rule` / `channel_status` / `config_snapshot` 三类证据 |
| 3 | **飞书生态低代码闭环** | 架构 | 业务价值 | 多维表格 + 审批流 + 妙记，运营热更新规则（不写代码）|
| 4 | **知识自进化闭环** | 模式 | 可推广性 | 案例→FAQ→知识库→下次同类问题自动命中 |

**工程取舍说明（非创新 · 但需声明）**：
- **AtoA Provider 抽象 + MCP 扩展预留** — 这是工程结构设计，非"创新"；PoC 阶段不引入完整 AtoA 框架，对接 OP 真实 API 时仅替换 Provider 实现（CLAUDE.md §4 比赛 4 步任务法 §3 单 Agent Scope Lock 一致）

详细论述：[`docs/architecture/solution_overview.md`](./docs/architecture/solution_overview.md)

---

## 📦 仓库里有什么（评审 30 秒可读）

```
OceanMate/
├── 📄 README.md                         ← 本文件（评审入口）
├── 📜 CLAUDE.md                         ← 项目治理文件（精简版）
│
├── 📂 docs/                             ← 完整方案文档
│   ├── business/
│   │   └── merchant_success.md          ← OP 5 方向 ↔ 4 Agent 对照表
│   ├── agents/                          ← 4 个 Agent 详细职责
│   │   ├── merchant_success_agent.md
│   │   ├── payment_diagnosis_agent.md   ⭐ Demo 核心亮点
│   │   ├── ticket_routing_agent.md
│   │   └── knowledge_evolution_agent.md
│   ├── architecture/                    ← 3 张架构图 + 方案说明
│   │   ├── business_flow.md             ← 端到端业务流 Mermaid
│   │   ├── agent_architecture.md        ← 5 层架构 Mermaid
│   │   └── solution_overview.md         ← 深度方案说明（5 节）
│   ├── plan/                            ← 任务计划 + 进度 + 行业调研
│   │   ├── task_plan.md
│   │   ├── findings.md
│   │   └── progress.md
│   └── governance/
│       └── race_sop.md                  ← 比赛 SOP（提交 / 录屏 / 组队）
│
├── 📂 submission/                       ← 报名附件包（4 件 + 源文件）
│   ├── 开题报告.md                       ← Part 1（286字）+ Part 2（586字）合订
│   ├── 深度方案说明.md                    ← 评审深读版（7 节 / 12 KB）
│   ├── 打印PDF用HTML/                   ← 浏览器 Ctrl+P 直接出 PDF
│   │   ├── 开题报告.html
│   │   └── 深度方案说明.html
│   └── architecture_diagrams/           ← 2 张架构图（Mermaid 源 + 导出说明）
│       ├── source/
│       │   ├── business_flow.mmd
│       │   └── agent_architecture.mmd
│       └── export_guide.md
│
├── 📂 src/                              ← 工程代码（治理骨架 + Agent stub）
├── 📂 demo/                             ← 录屏目录（git ignored）
└── 📄 LICENSE
```

> 💡 评审视角建议阅读顺序：`README`（你正在看）→ `submission/深度方案说明.md` → `docs/architecture/agent_architecture.md` → `docs/agents/payment_diagnosis_agent.md`（Demo 核心）→ `submission/开题报告.md`

---

## 🛠 技术栈

| 维度 | 选型 | 选择理由 |
|------|------|---------|
| 后端 | FastAPI + Python 3.11 | Agent 编排轻量、异步友好、Provider 抽象清晰 |
| LLM | Qwen (DashScope OpenAI 兼容) | 中文场景稳定 + 成本可控；Provider 抽象下 DeepSeek/Claude 可热切换 |
| RAG | 飞书多维表格 + 本地向量库 | 飞书原生（不引入新数据库）；PoC 阶段本地向量库兜底 |
| Agent 协议 | AtoA Provider 抽象 + MCP 扩展预留 | PoC 不引入完整 AtoA；对接真实环境仅替换 Provider 实现 |
| 协同底座 | 飞书 AI 全家桶（智能伙伴/多维表格/妙记/审批流/AI 字段）| 命题核心要求；运营无需开发可热更新规则 |
| 数据 | 飞书多维表格（结构化）+ 妙记（非结构化）| **不引入新数据库**（治理约束第 1 禁） |

---

## 🎯 落地预期价值（对标 OP 真实业务 · 仅承诺能力 · 不承诺量化结果）

> **量化口径**：以下为方案能力描述；具体百分比 / 业务指标需在 OP 真实接入后口径测算（赛制 §五学术诚信条款：不伪造效果数据 / 不夸大技术能力）。

| 价值点 | 对标真实痛点 | 本方案提供 | 量化测算条件 |
|-------|------------|----------|-------------|
| 跨境电商退款申诉 | 「退款问题」投诉 TOP 1，占比 20.00%<sup>[1]</sup> | 支付诊断 Agent 证据链 + 标准化申诉路径模板 | OP 真实接入后测算（需 OP 提供拒付/退款率基线） |
| 友好欺诈拦截 | 「任意仅退款」占比 13.60%<sup>[1]</sup> | 商户顾问选型阶段友好欺诈识别 + 支付诊断 | 需 OP 历史欺诈样本用于训练 |
| 工单自动化 | OP "拉群+截图" | 工单路由 飞书多维表格按问题类型自动派单 | 需 OP 工单分类规则表 + SLA 标准 |
| 知识沉淀 | OP 经验散落团队 | 知识进化 Agent 沉淀历史工单为结构化知识库 | 知识库命中率随时间提升的量化需 OP 真实数据 |

---

## 📊 市场背景锚点（公开行业数据 · 一手来源）

| 项 | 数据 | 来源 |
|---|------|------|
| 中国跨境数字支付 2024 | 7.5 万亿元 | [中商产业研究院][3] |
| 中国跨境数字支付 2025E | 突破 9.4 万亿元（+25% YoY）| [中商产业研究院][3] |
| CIPS 2024 业务量 | 175.49 万亿元（+42.60% YoY）| [中国金融新闻网][4] |
| 连连数字 2024 总收入 | 13.15 亿元（+27.9% YoY）| [连连数字 2024 年报][5] |
| 连连数字 全球支付 TPV | 2815 亿元（+63.1% YoY）| [连连数字 2024 年报][5] |
| 跨境消费意愿 | 54% 消费者预计增加跨境购物、77% 因缺偏好支付方式放弃 | [Airwallex][6] |

---

## 🧪 评审视角 · 30 秒 / 5 分钟 / 30 分钟 三档路径

| 时间 | 看什么 | 链接 |
|------|-------|------|
| **30 秒** | 一句话定位 + 架构图（本文档前半部分）| 你在这里 ✅ |
| **5 分钟** | 痛点 → 方案 → 价值闭环 + 4 Agent 职责 | [`docs/business/merchant_success.md`](./docs/business/merchant_success.md) |
| **30 分钟** | 完整深度方案 + Demo 核心 | [`submission/深度方案说明.md`](./submission/深度方案说明.md) + [`docs/agents/payment_diagnosis_agent.md`](./docs/agents/payment_diagnosis_agent.md) |

---

## 🏆 比赛信息

| 字段 | 内容 |
|------|------|
| 赛事 | 2026 飞书 AI 先锋未来人才大赛 |
| 赛区 | 华南 |
| 命题企业 | 钱海网络（Oceanpayment） |
| 命题 | AI 驱动的跨境商户成功运营助手 |
| 报名截止 | 2026-07-19 24:00（北京时间）|
| 队伍名 | OceanMate AI |

---

## 📜 治理与开源

- 本项目治理文件：[`CLAUDE.md`](./CLAUDE.md)（精简版比赛规则）
- 比赛 SOP（提交/录屏/组队规范）：[`docs/governance/race_sop.md`](./docs/governance/race_sop.md)
- 开源协议：[MIT](./LICENSE)
- 关联项目：本项目与 `E:\智能客服` 物理隔离（不污染原项目）

---

## 🤝 反馈与联系

仓库 Issue / PR 欢迎提交。如对接 OP 真实接口 / 飞书 API 替换 Provider，请参考 [`docs/architecture/agent_architecture.md`](./docs/architecture/agent_architecture.md) §3 Provider 抽象层。

---

## 📚 数据来源（脚注）

| 编号 | 来源（全部一手或权威机构发布） | 用于 |
|------|------|------|
| [1] | [网经社《2024 年度中国出口跨境电商消费投诉数据与典型案例报告》](https://www.100ec.cn/zt/24ckkj/) | 跨境电商「退款问题」投诉占比 20.00%（TOP 1）；「任意仅退款」占 13.60% |
| [2] | [oceanpayment.com 官网](https://oceanpayment.com) | OP 业务覆盖（500+ 支付产品 / 200+ 国家地区 / 5+ 行业：跨境外贸/旅游航空/软件游戏/数字版权/教育培训） |
| [3] | [中商产业研究院《2024-2029 全球及中国支付即服务行业发展现状调研及投资前景分析报告》](https://www.askci.com) | 中国跨境数字支付规模：2024 年 7.5 万亿元 → 2025E 突破 9.4 万亿元（+25% YoY） |
| [4] | [中国金融新闻网《人民币跨境支付系统 CIPS》](https://www.financialnews.com.cn) | 2024 年 CIPS 业务金额 175.49 万亿元（+42.60% YoY），业务笔数 821.69 万笔（+24.25%） |
| [5] | [连连数字 2024 年报](https://global.lianlianpay.com) | 行业头部增速：总收入 13.15 亿元（+27.9% YoY）、全球支付 TPV 2815 亿元（+63.1% YoY） |
| [6] | [Airwallex 跨境电商研究](https://www.airwallex.com) | 54% 消费者预计增加跨境购物 / 77% 因缺偏好支付方式放弃 |
| [7] | [Stripe Radar 公开资料](https://stripe.com/radar) | 头部企业 AI 仍聚焦交易风控，对商户接入/诊断/协同等服务流程仍依赖人工 |

> **数据真实性原则**：本项目所有数字 / 案例 / 比例均可追溯至公开来源；未做具体百分比承诺，量化口径需 OP 真实接入后测算。详见 [`docs/architecture/solution_overview.md`](./docs/architecture/solution_overview.md) §0「数据真实性声明」。

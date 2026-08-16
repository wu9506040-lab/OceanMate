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
[![Tag](https://img.shields.io/badge/Release-v1.0-blue)](https://github.com/wu9506040-lab/OceanMate/releases/tag/v1.0)

---

## 🌊 一句话定位

**OceanMate AI 不是"AI 客服"，而是 OP 商户成功团队的"数字员工体系"** —— 由"商户成功 AI 中枢"统领 5 类业务 Agent，让 AI 参与商户选型、支付接入、异常诊断、工单协同、知识沉淀、运营可视化的全生命周期。

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
| 运营缺可视化：OP 内部 BI 自建周期长 | 无 | **运营看板 Agent**：实时同步飞书多维表 + 错误码趋势 |

> 关键立场：**AI 不是替代人工，而是让商户成功从"被动响应"升级为主动运营**。

---

## 🚀 5 分钟快速开始（评审一键复现）

```bash
# 1. 克隆 + 装依赖
git clone https://github.com/wu9506040-lab/OceanMate.git && cd OceanMate
cd src/backend && pip install -r requirements.txt

# 2. 启动 FastAPI（mock 飞书 + Qwen 真实 LLM）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. 另一个终端：跑 6 个真实业务 Demo（mock 模式，无飞书凭证也能跑）
python scripts/run_all_real.py
```

**预期输出**：`汇总: total=6, passed=6`（Visa 13.1 / MC 4837 / BR Pix / NL 推荐 / 高优工单 / BR Pix FAQ 召回 全过）

| Demo | 工具 | 真实命中证据 |
|------|------|--------------|
| Visa 13.1 拒付诊断 | PDA | 错误码归因 + 证据链 + 申诉路径模板 |
| MC 4837 无卡拒付 | PDA | CNP fraud 识别 + 3DS 建议 |
| 巴西 Pix 通道咨询 | MSA | Boleto/Pix/iDEAL 真实渠道推荐 |
| 荷兰 iDEAL 推荐 | MSA | 跨语言 NL 命中 + RAG top-3 |
| 高优工单路由 | TRA | 4h SLA + 飞书审批流触发 |
| BR Pix FAQ 自进化 | KEA | 案例→FAQ 真实入库 |

> 真实飞书链路（含 WS 接收 + send_private briefing）：见 [`docs/runbook/dashboard_config_guide.md`](./docs/runbook/dashboard_config_guide.md) + 真实凭证 `src/backend/.env`

---

## 🏗 5 业务 Agent + 商户成功 AI 中枢

```
┌──────────────────────────────────────────────────────────────────┐
│  📲 入口层 · 飞书 AI 全家桶                                        │
│     智能伙伴(对话)  ·  多维表格(工单池/知识库)  ·  妙记(会议沉淀)   │
│     审批流(SLA)   ·  AI 字段(智能标签)                            │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  🧠 中枢层 · 商户成功 AI 中枢 (Orchestrator)                       │
│     · 意图分流（规则 + LLM fallback）  ·  上下文传递                │
│     · AtoA 自动链式编排（PDA→TRA→KEA · 置信度驱动）                │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  🤖 数字员工层 · 5 业务 Agent                                       │
│   ① MSA 商户顾问       ② PDA 支付诊断    ⭐ Demo 核心             │
│      选型 + 协作采集         错误码归因 + 证据链 + 申诉路径          │
│                                                                  │
│   ③ TRA 工单路由        ④ KEA 知识进化   ⑤ OPA 运营看板           │
│      飞书多维表格派单       案例→FAQ→RAG     实时多维表同步          │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  🔌 Provider 抽象层（PoC ↔ 真实环境切换关键）                      │
│   LLMProvider (Qwen)  ·  VectorStore (Chroma)  ·  Feishu  ·  数据源 │
└──────────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────────┐
│  📦 数据源 · Demo 占位 + OP 真实接口 Provider 抽象预留               │
│   风控规则库 · 通道状态库 · 对账快照 · 飞书多维表格知识库              │
└──────────────────────────────────────────────────────────────────┘
```

📐 详细架构图 + 协作矩阵：[`docs/architecture/agent_architecture.md`](./docs/architecture/agent_architecture.md)
📐 端到端业务流（5 Agent 协同）：[`docs/architecture/business_flow.md`](./docs/architecture/business_flow.md)
📐 v2 架构演进说明：[`docs/architecture/oceanmate_v2.md`](./docs/architecture/oceanmate_v2.md)

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
- **AtoA 自动链式编排（已落地）** — `chain_config.py` 配置 2 条链（PDA→TRA / TRA→KEA），Orchestrator `_maybe_chain()` 递归触发，**非 webhook 硬编码 if**，完整链路 1 次跑通（证据见 [`docs/reports/p1_3_evidence.md`](./docs/reports/p1_3_evidence.md)）

详细论述：[`docs/architecture/solution_overview.md`](./docs/architecture/solution_overview.md)

---

## 📊 真实数据 + 真实链路（评审硬证据）

### 数据真实性（203 条真实业务数据 · 0 伪造）

| 来源 | 条数 | 类型 |
|------|------|------|
| [`docs/data/payment_error_cases.json`](./docs/data/payment_error_cases.json) | 117 错误码 | Visa/MC/Amex/Discover reason_codes（107 条）+ 5 demo cases |
| [`docs/data/payment_methods.json`](./docs/data/payment_methods.json) | 16 支付方式 | Visa US / Boleto BR / Pix BR / iDEAL NL / Klarna EU 等真实渠道 |
| [`docs/data/ticket_routing_rules.json`](./docs/data/ticket_routing_rules.json) | 10 路由规则 | VIP/Premium/Standard + high/medium 4 层降级 |
| 飞书多维表（真实 seed） | 60 工单 | `src/backend/scripts/seed_demo_tickets.py` 生成 |

### 真实链路验证证据

| 维度 | 证据文档 | 关键 KPI |
|------|----------|---------|
| AtoA 自动链式编排 | [`docs/reports/p1_3_evidence.md`](./docs/reports/p1_3_evidence.md) | PDA→TRA→KEA 3 步链 · 4/20 拿到完整链（实测） |
| 对立面审查（360°） | [`docs/reports/adversarial_review.md`](./docs/reports/adversarial_review.md) | 4 子 Agent 并行审查，10 类 gap 暴露+分类 |
| 完整参赛方案 | [`docs/reports/submission.md`](./docs/reports/submission.md) | 654 行 · 6 Demo 6/6 PASSED · 74% 测试覆盖 |
| **冲奖冲刺 13 项** | **[`docs/reports/v10_award_boost.md`](./docs/reports/v10_award_boost.md)** | **820 行 · 量化收益+Prompt 设计+落地路径+安全合规** |
| 真实飞书接入 | [`docs/runbook/dashboard_config_guide.md`](./docs/runbook/dashboard_config_guide.md) | WS 真接通 + 多维表真写 + briefing 真发 |
| 飞书 AI 字段配置 | [`docs/runbook/feishu_ai_field_setup.md`](./docs/runbook/feishu_ai_field_setup.md) | 2 个 AI 字段 Prompt 模板 + 验证脚本（80% 准确率）|

### 演示截图（评审肉眼可见）

| 场景 | 截图 |
|------|------|
| 飞书智能伙伴真实对话 | ![飞书对话](./docs/runbook/feishu_chat_screenshot.png) |
| PDA 诊断证据链 + 配图 | ![诊断](./docs/runbook/diagnosis_screenshot.png) |
| OPA Dashboard 实时同步 | ![Dashboard](./docs/runbook/dashboard_screenshot.png) |

---

## 📦 仓库里有什么（评审 30 秒可读）

```
OceanMate/
├── 📄 README.md                         ← 本文件（评审入口）
├── 📜 CLAUDE.md                         ← 项目治理文件（精简版）
│
├── 📂 docs/                             ← 完整方案文档
│   ├── business/
│   │   └── merchant_success.md          ← OP 5 方向 ↔ 5 Agent 对照表
│   ├── agents/                          ← 5 个 Agent 详细职责
│   │   ├── merchant_success_agent.md    (MSA)
│   │   ├── payment_diagnosis_agent.md   ⭐ Demo 核心 (PDA)
│   │   ├── ticket_routing_agent.md      (TRA)
│   │   ├── knowledge_evolution_agent.md  (KEA)
│   │   └── operation_panel_agent.md     (OPA)
│   ├── architecture/                    ← 4 张架构图 + 方案说明
│   │   ├── business_flow.md             ← 端到端业务流 Mermaid
│   │   ├── agent_architecture.md        ← 5 层架构 Mermaid
│   │   ├── oceanmate_v2.md              ← v2 架构演进说明
│   │   └── solution_overview.md         ← 深度方案说明
│   ├── sop/                             ← 7 个 SOP 文档（MSA/PDA/TRA/KEA/LLM/RAG/Feishu）
│   ├── reports/                         ← 评审硬证据
│   │   ├── submission.md                ← 654 行完整参赛方案
│   │   ├── adversarial_review.md        ← 对立面审查 360°
│   │   ├── p1_3_evidence.md             ← AtoA 自动链式编排证据
│   │   └── v10_award_boost.md           ⭐ 冲奖冲刺 13 项（820 行）
│   ├── runbook/                         ← 运维手册 + 真实截图 + AI 字段配置
│   ├── plan/                            ← 任务计划 + 进度 + 行业调研
│   ├── data/                            ← 真实业务数据（117 + 16 + 10）
│   ├── governance/race_sop.md           ← 比赛 SOP
│   └── requirements/requirements_analysis.md
│
├── 📂 submission/                       ← 报名附件包
│   ├── 开题报告.md                       ← Part 1 + Part 2 合订
│   ├── 深度方案说明.md                    ← 评审深读版
│   ├── product_screenshots/             ← 4 张产品截图
│   └── architecture_diagrams/           ← 2 张架构图（Mermaid 源 + PNG）
│
├── 📂 src/backend/                      ← 工程代码
│   ├── app/                             ← 4 Agent + Orchestrator + Provider 抽象（MSA/PDA/TRA/KEA/Orchestrator + scripts/render_dashboard.py OPA 工具）
│   ├── scripts/                         ← 30+ 验证/seed 脚本
│   │   ├── run_all_real.py              ⭐ 一键 6 Demo
│   │   ├── verify_rerank_smoke.py       ← Rerank 真实链路
│   │   └── verify_atoa_full_chain.py    ← AtoA 链式证据
│   ├── data/                            ← Chroma 向量库 + SQLite
│   └── tests/                           ← 242 测试用例 · 74% 覆盖
│
├── 📂 demo/recordings/                  ← 录屏目录（git ignored）
└── 📄 LICENSE
```

> 💡 评审视角建议阅读顺序：`README`（你正在看）→ `docs/reports/submission.md`（完整方案）→ `docs/reports/adversarial_review.md`（诚实声明）→ `docs/agents/payment_diagnosis_agent.md`（Demo 核心）→ 跑 `scripts/run_all_real.py`（一键复现）

---

## 🛠 技术栈

| 维度 | 选型 | 选择理由 |
|------|------|---------|
| 后端 | FastAPI + Python 3.11 | Agent 编排轻量、异步友好、Provider 抽象清晰 |
| LLM | Qwen (DashScope OpenAI 兼容) | 中文场景稳定 + 成本可控；Provider 抽象下 DeepSeek/Claude 可热切换 |
| Embedding | Qwen text-embedding-v3 (1024 维) | 跨语言"拒付" vs "chargeback" 相似度 0.5253（Hash 0.0000）|
| Rerank | Qwen text-rerank (qwen3-rerank) | DashScope 实测 200，分数 0.33-0.53 有区分度 |
| RAG | Chroma + BM25 + Rerank | 3 路混合召回（向量 / BM25 / Rerank），召回 30 → 重排 5 |
| Agent 协议 | AtoA Provider 抽象 + MCP 扩展预留 | PoC 不引入完整 AtoA；对接真实环境仅替换 Provider 实现 |
| 协同底座 | 飞书 AI 全家桶（智能伙伴/多维表格/妙记/审批流/AI 字段）| 命题核心要求；运营无需开发可热更新规则 |
| 数据 | 飞书多维表格（结构化）+ 妙记（非结构化）| **不引入新数据库**（治理约束第 1 禁） |

---

## 🎯 落地预期价值（对标 OP 真实业务 · 仅承诺能力 · 不承诺量化结果）

> **量化口径**：以下为方案能力描述；具体百分比 / 业务指标需在 OP 真实接入后口径测算（赛制 §五学术诚信条款：不伪造效果数据 / 不夸大技术能力）。

| 价值点 | 对标真实痛点 | 本方案提供 | 验证状态 |
|-------|------------|----------|---------|
| 跨境电商退款申诉 | 「退款问题」投诉 TOP 1，占比 20.00%<sup>[1]</sup> | 支付诊断 Agent 证据链 + 标准化申诉路径模板 | ✅ Demo 全过（Visa 13.1 / MC 4837）|
| 友好欺诈拦截 | 「任意仅退款」占比 13.60%<sup>[1]</sup> | 商户顾问选型阶段友好欺诈识别 + 支付诊断 | ✅ Demo 通过（BR Pix / NL iDEAL）|
| 工单自动化 | OP "拉群+截图" | 工单路由 飞书多维表格按问题类型自动派单 | ✅ Demo 通过（高优 4h SLA）|
| 知识沉淀 | OP 经验散落团队 | 知识进化 Agent 沉淀历史工单为结构化知识库 | ✅ Demo 通过（BR Pix FAQ 自进化）|
| 运营可视化 | OP 内部 BI 自建周期长 | 运营看板 Agent 实时同步飞书多维表 + 错误码趋势 | ✅ 多维表真同步 + dashboard 已配 |

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
| **30 秒** | 一句话定位 + 5 Agent 架构图（本文档前半部分）| 你在这里 ✅ |
| **5 分钟** | 痛点 → 方案 → 价值闭环 + 5 Agent 职责 + 真实数据证据 | [`docs/business/merchant_success.md`](./docs/business/merchant_success.md) + [`docs/reports/p1_3_evidence.md`](./docs/reports/p1_3_evidence.md) |
| **30 分钟** | 完整深度方案 + Demo 核心 + 对立面审查 + 冲奖冲刺 | [`docs/reports/submission.md`](./docs/reports/submission.md) + [`docs/reports/adversarial_review.md`](./docs/reports/adversarial_review.md) + [`docs/reports/v10_award_boost.md`](./docs/reports/v10_award_boost.md) |
| **一键复现** | 跑 6 Demo（mock 模式 · 无需飞书凭证）| `cd src/backend && python scripts/run_all_real.py` |

---

## 🏆 比赛信息

| 字段 | 内容 |
|------|------|
| 赛事 | 2026 飞书 AI 先锋未来人才大赛 |
| 赛区 | 华南 |
| 命题企业 | 钱海网络（Oceanpayment） |
| 命题 | AI 驱动的跨境商户成功运营助手 |
| 报名截止 | 2026-07-19 24:00（北京时间）|
| 提交截止 | 2026-08-16 22:00（北京时间）|
| 队伍名 | OceanMate AI |
| 当前 Tag | [`v1.0`](https://github.com/wu9506040-lab/OceanMate/releases/tag/v1.0)（飞书 AI 大赛参赛终版 · 2026-08-14）|

---

## 📜 治理与开源

- 本项目治理文件：[`CLAUDE.md`](./CLAUDE.md)
- 比赛 SOP：[`docs/governance/race_sop.md`](./docs/governance/race_sop.md)
- 7 个工程 SOP：[`docs/sop/`](./docs/sop/)（MSA / PDA / TRA / KEA / LLM / RAG / Feishu）
- 开源协议：[`MIT`](./LICENSE)

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

> **数据真实性原则**：本项目所有数字 / 案例 / 比例均可追溯至公开来源；未做具体百分比承诺，量化口径需 OP 真实接入后测算。详见 [`docs/architecture/solution_overview.md`](./docs/architecture/solution_overview.md) §0「数据真实性声明」+ [`docs/reports/adversarial_review.md`](./docs/reports/adversarial_review.md)（对立面审查 · 360° 暴露已知 gap）。

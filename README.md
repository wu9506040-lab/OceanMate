# OceanMate — 跨境商户成功运营助手

> 2026 飞书 AI 先锋未来人才大赛 · 华南赛区 · 钱海网络（Oceanpayment）命题参赛项目
>
> **6 Agent 协同 + AtoA 协议 + 飞书生态原生闭环**——重构跨境支付商户成功协作模式。

---

## 一句话定位

**OceanMate = 商户的"AI 合伙人" + OP 内部的"AI 协同中台"**

| 视角 | 助手角色 | 核心动作 |
|------|---------|---------|
| 商户侧 | 24h AI 合伙人 | 选型咨询 → 接入指引 → 故障诊断 → 增长建议 |
| OP 侧 | 跨团队 AI 调度员 | 智能分诊 → 工单路由 → 知识沉淀 → 协同加速 |

---

## 6 Agent 架构

```
商户咨询（飞书智能伙伴入口）
   ↓
┌──────────────────────────────────────────────────┐
│ AtoA 协议层（Agent-to-Agent / MCP 调用）          │
├──────────────────────────────────────────────────┤
│ ① 选型 Agent      →  RAG + 业务规则引擎           │
│ ② 接入 Agent      →  Code Interpreter + 日志检索   │
│ ③ 诊断 Agent      →  多源数据融合 + 因果推理       │
│ ④ 工单路由 Agent  →  分类模型 + 飞书审批流         │
│ ⑤ 知识沉淀 Agent  →  增量学习 + 知识图谱           │
│ ⑥ 协同 Agent      →  飞书多维表格 + 妙记 + 群机器人 │
└──────────────────────────────────────────────────┘
   ↓
飞书生态（多维表格 / 妙记 / 智能伙伴 / 会议 AI）
```

详细架构图见 `docs/architecture/oceanmate.md`（待补），AtoA 时序图见 `docs/architecture/atoa_sequence.md`（待补）。

---

## 技术栈

| 维度 | 选型 | 理由 |
|------|------|------|
| 后端 | FastAPI + Python 3.11 | Agent 编排轻量、异步友好 |
| 前端 | Vue3 + TypeScript | 飞书生态对接方便 |
| LLM | Qwen (DashScope OpenAI 兼容) | 中文场景表现稳定 + 成本可控 |
| 协议 | AtoA (Agent-to-Agent) + MCP | 命题亮点 #2 直接回应 |
| 协同底座 | 飞书 AI 全家桶（智能伙伴/多维表格/妙记/会议 AI）| 命题亮点 #3 直接回应 |
| 数据 | 飞书多维表格（结构化）+ 妙记（非结构化）| **不引入新数据库**（CLAUDE.md §2 禁止） |

---

## 治理（精简版 CLAUDE.md）

本项目继承原 `E:\智能客服\CLAUDE.md V2.1` 的治理骨架，**保留三大原则 + 精简反例 + 适配比赛**：

| 维度 | 保留内容 |
|------|---------|
| **三原则** | Interface First / Module Isolation / Dependency Inversion |
| **5 禁** | 引入新数据库 / 跨 Agent 侵入 / YAGNI 空实现 / 硬编码密钥 / 无验证提交 |
| **5 反例** | Agent 直调 SDK / Prompt 硬编码 / 业务规则硬编码 / 跨 Agent 一把梭 / 无验证就提交 |
| **4 步法** | 任务分析 → 方案设计 → 动手开发 → 提交归档 |
| **3 级验证** | 文档/Prompt → 单测；代码 → curl + pytest + webhook；UI → build + browser + 录屏 |
| **比赛 6 件套** | 职责/Protocol/Schema/依赖图/时序图/录屏 |

详细见 [`CLAUDE.md`](./CLAUDE.md)。

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://gitee.com/zwyyy7/ocean-mate.git
cd ocean-mate

# 2. 后端环境（待补 requirements.txt）
cd src/backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 QWEN_API_KEY / FEISHU_APP_ID / FEISHU_APP_SECRET

# 4. 启动 FastAPI（待补 main.py）
uvicorn app.main:app --reload --port 8000
```

> ⚠️ 当前阶段（7-17 晚）仓库骨架仅含治理文件 + 调研骨架，**业务代码在 7-18 下午落地**。

---

## 项目结构

```
ocean-mate/
├── CLAUDE.md                  ← 精简版治理文件
├── README.md                  ← 本文件
├── docs/
│   ├── governance/
│   │   └── race_sop.md        ← 比赛 SOP（方案/录屏/提交规范）
│   ├── architecture/          ← 架构图（待补）
│   ├── plan/
│   │   ├── task_plan.md       ← 2 天冲刺 WBS
│   │   ├── findings.md        ← 行业调研
│   │   └── progress.md        ← 进度跟踪
│   └── reports/
│       └── submission.md      ← 提交材料汇总（待补）
├── src/
│   ├── backend/               ← FastAPI + 6 Agent（待补）
│   └── frontend/              ← Vue3（待补）
├── demo/                      ← 录屏（git ignore）
└── submission/                ← 报名附件
    ├── part1_前置分析.md      ← 待补
    ├── part2_整体方案.md      ← 待补
    └── architecture_diagrams/ ← 待补
```

---

## 比赛信息

| 字段 | 内容 |
|------|------|
| 赛事 | 2026 飞书 AI 先锋未来人才大赛 |
| 赛区 | 华南 |
| 命题企业 | 钱海网络（Oceanpayment） |
| 命题 | AI 驱动的跨境商户成功运营助手 |
| 报名截止 | 2026-07-19 24:00 |
| 团队 | 2 人（业务架构 + 工程） |
| 仓库 | Gitee [zwyyy7/ocean-mate](https://gitee.com/zwyyy7/ocean-mate) · GitHub 镜像同步 |

---

## 进度

| 阶段 | 状态 | 完成度 |
|------|------|--------|
| Phase 1 仓库骨架 | ✅ | 9/9 |
| Phase 2 方案 + 架构 | 🔄 | 0/7 |
| Phase 3 代码 + Demo | ⏳ | 0/7 |
| Phase 4 录屏 + 提交 | ⏳ | 0/7 |

详细进度见 [`docs/plan/progress.md`](./docs/plan/progress.md)。

---

## 治理声明

本项目所有 commit 仅限 `E:\ai-pioneer\` 范围内，**不影响原 E:\智能客服\ 项目**。
详见 `CLAUDE.md §9 与原项目的关系`。
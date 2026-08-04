# OceanMate v2 技术总览（代码层单一入口）

> **本文件定位**：给开发者 / AI Agent 用的"代码视角单一入口"。
>
> 与其他架构文档**不重复**：
> - 评审/路演视角 → `solution_overview.md`（业务价值 / 创新点）
> - 评审/路演视角 → `agent_architecture.md`（5 层架构 / Agent 协作矩阵）
> - 评审/路演视角 → `business_flow.md`（业务流图 / 场景走查）
>
> **本文件唯一覆盖**：接口实现映射、配置入口、替换指南、SOP 矩阵、当前实现状态。

---

## 1. 代码分层（自顶向下）

```
┌────────────────────────────────────────────────────────────┐
│  L1 · 入口层                                                  │
│      FastAPI router（src/backend/app/routers/）               │
│      飞书 webhook handler（src/backend/app/feishu/）          │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  L2 · 业务编排层（Orchestrator + 4 Tool）                     │
│      app/agents/orchestrator/    意图分流 / 上下文传递         │
│      app/agents/<name>/          4 Tool：MSA / PDA / TRA / KEA│
│      入口契约：BaseTool（@interface）                          │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  L3 · 数据访问层（6 Repository + 8 SQLite 表）                 │
│      app/implementations/db/repositories/__init__.py          │
│      入口契约：BaseRepository（Protocol）                     │
│      存储：scripts/init_db.py 8 张表                          │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  L4 · 基础能力层（5 接口 + 5 实现）                            │
│      app/interfaces/        BaseTool / BaseLLMGateway /     │
│                              BaseRAGEngine / BaseDatabase /  │
│                              BaseFrontend / BaseRepository   │
│      app/implementations/  LLM / RAG / DB / Feishu 实现     │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  L5 · 模型 / 配置 / 数据源                                     │
│      app/models/__init__.py       7 Pydantic v2 模型         │
│      config/                     Prompt / 业务阈值 YAML      │
│      data/oceanmate.db           SQLite                     │
│      data/chroma/                Chroma 嵌入式               │
│      .env（git ignored）          API Key / 飞书凭证         │
└────────────────────────────────────────────────────────────┘
```

**关键原则**（来自 `CLAUDE.md` §2）：

| 原则 | 含义 | 落地 |
|------|------|------|
| Interface First | 先 Protocol 后实现 | 5 接口 → 5 实现 + 6 Repository |
| Module Isolation | 4 Tool 强隔离 | Tool 间仅通过 Orchestrator + AtoA 协议交互 |
| Dependency Inversion | 依赖方向单向 | FastAPI Depends() + 工厂函数；禁止直接 `new` 具体类 |

---

## 2. 4 Tool + Orchestrator 进度矩阵

> Tool 命名沿用 MSA / PDA / TRA / KEA（与评审文档对齐）；Agent 这一层在 PoC 简化为 Tool。

| Tool | 文件 | 接口实现 | 业务方法 | 状态 | 备注 |
|------|------|---------|---------|------|------|
| **MSA**（商户成功）| `app/agents/msa/` | ✅ | ✅ | ✅ **Day 4 完成** | 含 **PWR**（支付方式推荐）子能力，对位 OP ① + ④ · 17/17 测试通过 |
| **PDA**（支付诊断）| `app/agents/pda/` | ✅ | ✅ | ✅ **Day 2 完成** | 对位 OP ② · Demo 核心 · 13/13 测试通过 |
| **TRA**（工单路由）| `app/agents/tra/` | ✅ | ✅ | ✅ **Day 5 完成** | 对位 OP ③ · 4 层规则匹配优先级 + DB/Memory 双写 · 25/25 测试通过 |
| **KEA**（知识进化）| `app/agents/kea/` | ✅ | ✅ | ✅ **Day 6 完成** | 对位 OP ⑤ · promote + search + list · cases→Chroma→embedding_meta 三层一致 · 22/22 测试通过 |
| **Orchestrator** | `app/agents/orchestrator/` | ✅ | ✅ | ✅ **Day 4 完成** | 关键词意图分流 + Tool 编排 · 22/22 测试通过 |

> **进度图例**：✅ 完成 / 🔄 进行中 / ⏳ 待办

---

## 3. 接口与实现映射表（5 接口 + 6 Repository）

### 3.1 基础能力接口（L4）

| 接口（Protocol/ABC） | 文件 | 实现类 | 文件 | 状态 |
|---------------------|------|-------|------|------|
| `BaseTool` | `app/interfaces/base_tool.py` | —（抽象） | — | ✅ 8 项验证通过 |
| `BaseLLMGateway` | `app/interfaces/base_llm.py` | `QwenGateway` / `MockLLMGateway` | `app/implementations/llm/qwen_gateway.py` | ✅ |
| `BaseRAGEngine` | `app/interfaces/base_rag.py` | `ChromaRAGEngine` + `HashEmbeddingFunction` | `app/implementations/rag/chroma_rag.py` | ✅ |
| `BaseDatabase` | `app/interfaces/base_database.py` | `SQLiteDatabase` | `app/implementations/db/sqlite_db.py` | ✅ |
| `BaseFrontend` | `app/interfaces/base_frontend.py` | — | `app/implementations/feishu/`（Day 7）| ⏳ |
| `BaseRepository` | `app/interfaces/base_repository.py` | 6 Repository | `app/implementations/db/repositories/__init__.py` | ✅ 14/14 测试 |

### 3.2 数据访问 Repository（L3）

| Repository | 实体 | 定制方法 | 状态 |
|-----------|------|---------|------|
| `MerchantRepository` | Merchant | — | ✅ |
| `ErrorCodeRepository` | ErrorCode | `lookup_by_code` / `search` | ✅ |
| `CaseRepository` | Case | — | ✅ |
| `TicketRepository` | Ticket | — | ✅ |
| `ConversationRepository` | Conversation | `add_message` / `get_messages` | ✅ |
| `HandoffRepository` | Handoff | — | ✅ |

### 3.3 异常体系（统一封装）

| 异常类 | 触发场景 | HTTP 状态（规划） |
|-------|---------|-----------------|
| `RepositoryError` | 通用 DB 异常 | 500 |
| `NotFoundError` | 资源不存在 | 404 |
| `DuplicateKeyError` | 主键 / UNIQUE 冲突 | 409 |
| `ValidationError` | 必填字段缺失 / 长度越界 | 400 |

---

## 4. 替换指南（生产化路径 · 关键模块可替换性证明）

### 4.1 换 LLM（Qwen → DeepSeek / GPT / Claude）

```
替换点：app/implementations/llm/qwen_gateway.py
新增文件：app/implementations/llm/deepseek_gateway.py

class DeepSeekGateway(BaseLLMGateway):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        ...
    async def chat(self, messages, **kwargs): ...
```

业务代码（4 Tool / Orchestrator）零改动，只改工厂函数 `get_default_gateway()` 的返回。

### 4.2 换关系型数据库（SQLite → MySQL / PostgreSQL）

```
替换点：app/implementations/db/sqlite_db.py
新增文件：app/implementations/db/mysql_db.py
迁移脚本：scripts/init_db.py 的 DDL → MySQL 方言（auto_increment / charset utf8mb4）
```

Repository 层（6 个）零改动，因为它们只依赖 `BaseDatabase` 接口的 `query` / `execute` / `transaction`。

> **注**：MySQL 规则（来自 `~/.claude/rules/database/mysql.md`）：
> - URL 加 `?useUnicode=true&characterEncoding=utf8mb4&serverTimezone=Asia/Shanghai`
> - Windows 环境显式 `charset=utf8mb4` 防 GBK 乱码
> - 外键用逻辑关联（存 id），不用数据库级 FK（当前 8 张表的 FK 是迁移后第一个要拆的）

### 4.3 换向量库（Chroma → Milvus / FAISS / 飞书索引）

```
替换点：app/implementations/rag/chroma_rag.py
新增文件：app/implementations/rag/milvus_rag.py
```

业务代码零改动，因为 ChromaRAGEngine 已实现 `BaseRAGEngine` 的全部方法（`retrieve` / `add_document` / `delete_document` / `update_document`）。

> **HashEmbeddingFunction 兼容性**：若换真实环境，可改用 Chroma 内置 `ONNXMiniLM_L6_V2` 或 Qwen Embedding（替换 `__init__` 里的 `embedding_function` 参数即可）。

### 4.4 换前端载体（飞书 → 微信 / Slack / Web）

```
替换点：app/interfaces/base_frontend.py + app/implementations/feishu/
新增文件：app/implementations/wechat/wechat_frontend.py
```

4 Tool 只调用 `BaseFrontend` 的 `send_message` / `send_private` / `create_group` / `sync_dashboard_data` 等方法，载体切换零业务改动。

---

## 5. SQLite 8 张表（DDL 在 `scripts/init_db.py`）

| # | 表名 | 主键 | 飞书同步源 | 本地写入 | 用途 |
|---|------|------|-----------|---------|------|
| 1 | `merchants` | `id` | ✅（多维表格）| — | 商户画像 |
| 2 | `error_codes` | `id` + UNIQUE(code,country,channel) | ✅ | — | 错误码知识库（PDA 用） |
| 3 | `cases` | `id` | ✅ | — | 诊断案例库（PDA + KEA 用） |
| 4 | `tickets` | `id` | ✅ | — | 工单（TRA 用） |
| 5 | `conversations` | `id` | — | ✅ | 对话会话 |
| 6 | `messages` | `id`（自增）| — | ✅ | 对话消息 |
| 7 | `handoffs` | `id` | — | ✅ | 人工交接记录 |
| 8 | `embedding_meta` | `id`（自增）+ UNIQUE(source_table,source_id,collection_name) | — | ✅ | Chroma 向量元数据映射 |

**索引**：11 个（按 country / status / problem_type 等高频过滤字段）。

**初始化命令**：

```bash
cd src/backend
python scripts/init_db.py                # 默认 data/oceanmate.db（幂等）
python scripts/init_db.py --reset        # 删表重建（仅开发用）
python scripts/init_db.py --db path/to.db  # 自定义路径
```

---

## 6. 配置入口（环境变量 + 代码层）

### 6.1 环境变量（`.env` 模板，git ignored）

| 变量名 | 必填 | 用途 | 当前实现 |
|-------|------|------|---------|
| `DASHSCOPE_API_KEY` | 可选 | Qwen 调用 | 缺失时自动降级 MockLLMGateway |
| `FEISHU_APP_ID` | 可选 | 飞书应用 ID | Day 7 集成时启用 |
| `FEISHU_APP_SECRET` | 可选 | 飞书应用 Secret | 同上 |
| `FEISHU_VERIFICATION_TOKEN` | 可选 | Webhook 签名校验 | 同上 |
| `DEEPSEEK_API_KEY` | 可选 | DeepSeek 备选 LLM | 占位，未启用 |
| `LOG_LEVEL` | 可选 | DEBUG / INFO / WARNING | 默认 INFO |

> **降级策略**：API Key 缺失时，业务调用不报错，自动用 Mock 返回（避免 Demo 卡壳）。

### 6.2 代码层配置（YAML / Pydantic Settings）

| 配置 | 文件 | 用途 | 状态 |
|------|------|------|------|
| `config/prompts/*.yaml` | 待建（Day 4-5）| Prompt 模板 | ⏳ |
| `config/settings.py` | 待建（Day 7）| Pydantic Settings 统一读 `.env` | ⏳ |
| `config/business_rules.yaml` | 待建（Day 6）| SLA / 阈值 / 业务规则 | ⏳ |

**铁律**（来自 `CLAUDE.md` §3 禁止行为 #4）：
- ❌ API Key / Secret 不得硬编码到代码或提交到 Git
- ❌ Prompt 不得写在 f-string 中

---

## 7. FastAPI 启动 + 依赖注入（规划 · Day 7）

### 7.1 启动入口（计划）

```python
# app/main.py（待建 · Day 7）
from fastapi import FastAPI, Depends
from app.implementations.db.sqlite_db import SQLiteDatabase
from app.implementations.db.repositories import MerchantRepository, ...
from app.implementations.rag.chroma_rag import ChromaRAGEngine
from app.implementations.llm.qwen_gateway import get_default_gateway
from app.routers import merchants, tickets, conversations

app = FastAPI(title="OceanMate AI", version="2.2")

def get_db():
    db = SQLiteDatabase(Path("data/oceanmate.db"))
    try:
        yield db
    finally:
        db.close()

def get_merchant_repo(db = Depends(get_db)) -> MerchantRepository:
    return MerchantRepository(db)

# 注册 router
app.include_router(merchants.router, prefix="/api/merchants", tags=["merchants"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
```

### 7.2 依赖注入原则

| 原则 | 落地 |
|------|------|
| 业务代码（4 Tool / Repository）不接受 `FastAPI Request` | 用 `Depends()` 注入具体对象 |
| 工厂函数返回接口实例 | `get_default_gateway()` / `get_db()` |
| 接口对象在 `yield` 内创建 | 用 `try/finally` 关闭 DB 连接 |

---

## 8. SOP 验证矩阵（10 个 P0/P1 场景）

> **强制**（来自 `feedback_sop_testing.md`）：每个 Tool 必须有正逆向 SOP 测试 + 用户友好降级（不允许"系统错误"裸抛）。

| 优先级 | SOP ID | 场景 | 对应 Tool | 测试文件 | 状态 |
|-------|--------|------|----------|---------|------|
| P0 | SOP-TOOL-001 | PDA 诊断命中知识库 → 返回证据链 | PDA | `tests/test_pda_sop.py` | ✅ Day 2（happy path 通过）|
| P0 | SOP-TOOL-002 | PDA 知识库无匹配 → 友好降级提示 | PDA | 同上 | ✅ Day 2（test_happy_path_with_missing_evidence 通过）|
| P0 | SOP-MSA-001 | MSA 推荐：画像匹配 + RAG 证据 | MSA | `tests/test_msa_sop.py` | ✅ Day 4（含 US/BR 正向）|
| P0 | SOP-MSA-002 | MSA PWR：缺关键参数 → 主动反问 | MSA | 同上 | ✅ Day 4（3 子场景：全缺/部分缺/缺 1 个）|
| P0 | SOP-TRA-001 | TRA 自动派单：4 层规则匹配优先级 | TRA | `tests/test_tra_sop.py` | ✅ **Day 5**（4 层优先级 + DB+Memory 双写 + query_status 共 25 测试；real coverage: exact / priority_wildcard / problem_wildcard / default_fallback / db+memory / query / 4 degradation paths）|
| P0 | SOP-REPO-001 | Repository 主键冲突 / UNIQUE / FK 违反 | Repository | `tests/test_repositories_sop.py` | ✅ Day 1 |
| P1 | SOP-KEA-001 | KEA：promote + search + list_candidates | KEA | `tests/test_kea_sop.py` | ✅ **Day 6**（3 intent + 22 测试） |
| P1 | SOP-KEA-002 | KEA 4 子场景友好降级 | KEA | 同上 | ✅ **Day 6** |
| P1 | SOP-ORC-001 | Orchestrator 意图分流正确 | Orchestrator | `tests/test_orchestrator_sop.py` | ✅ Day 4（3 子场景：分类/兜底/未注册）|
| P1 | SOP-LLM-001 | LLM 调用失败 → 自动降级 Mock | LLM Gateway | `tests/test_llm_sop.py` | ✅ Day 3（6 子场景）|
| P1 | SOP-RAG-001 | RAG 检索空结果 / Embedding 失败降级 | RAG Engine | `tests/test_rag_sop.py` | ✅ Day 3（5 子场景）|

> **完成进度**：10/10 主体完成 ✅（Day 5 TRA 收官，剩 KEA Day 6-7）

---

## 9. 当前实现状态（截至 2026-08-04 · Day 5 收官）

| 阶段 | 任务 | 状态 |
|------|------|------|
| Day 1 | 仓库骨架（接口 + Repository + RAG + LLM）| ✅ 完成 |
| Day 1 | 14/14 Repository 骨架测试 | ✅ 通过 |
| Day 1 | 修复 2 bug（注解遮蔽 / FK 误用）| ✅ |
| Day 2 上午 | PDA 老代码迁移到 BaseTool | ✅ 完成（11/11 测试 + 端到端验证）|
| Day 2 下午 | SOP-PDA-002/003 补完 + SOP-PDA 文档 | ✅ 完成（13/13 测试 + `docs/sop/SOP-PDA.md`）|
| Day 3 | SOP-LLM-001 + SOP-RAG-001 + SOP-REPO 剩余 + 验收 | ✅ 完成（61/61 测试 + 3 个 SOP 文档）|
| Day 4 上午 | MSA（含 PWR）+ payment_methods 知识库 seed | ✅ 完成（17/17 测试 + 9 条支付方式入库 + `docs/sop/SOP-MSA.md`）|
| Day 4 下午 | Orchestrator（关键词意图分流 + Tool 编排）| ✅ 完成（22/22 测试 + `docs/sop/SOP-ORC.md`）|
| **Day 5** | **TRA（工单路由）+ 路由规则 JSON + 双写持久化 + 热更新** | ✅ **完成（25/25 测试 + `docs/sop/SOP-TRA.md`）** |
| **Day 6** | **KEA（知识进化）+ 案例→FAQ 三层一致 + promote/search/list** | ✅ **完成（22/22 测试 + `docs/sop/SOP-KEA.md`）** |
| Day 6-7 | 飞书 webhook 集成（智能伙伴载体）| ⏳ |
| Day 8-9 | Demo 视频录制 + 录屏脚本 | ⏳ |
| Day 10-12 | 方案文档终稿 + 评审材料 | ⏳ |
| Day 13 | 最终提交（2026-08-16 截止）| ⏳ |

**测试累计**：125/125 通过（Day 5 收官）。SOP 主体 10/10 完成。

---

## 10. 关键文档索引（按使用场景）

| 场景 | 文档 |
|------|------|
| **写新 Tool / Repository** | 本文件 §3 接口映射 + `app/interfaces/` 下的 Protocol |
| **替换 LLM / DB / 向量库** | 本文件 §4 替换指南 |
| **改 Schema** | 本文件 §5 + `scripts/init_db.py` DDL |
| **环境变量 / 配置** | 本文件 §6 |
| **写新测试** | 本文件 §8 SOP 矩阵 + `tests/conftest.py` fixture |
| **看进度 / 排期** | 本文件 §9 + `docs/plan/progress.md` |
| **评审答辩** | `solution_overview.md` + `agent_architecture.md` + `business_flow.md` |
| **比赛 SOP（提交 / 录屏）** | `docs/governance/race_sop.md` |
| **CLAUDE.md 总规则** | `E:\ai-pioneer\CLAUDE.md` |

---

## 附录 A：常用命令清单

```bash
# 初始化数据库
cd src/backend
python scripts/init_db.py --reset

# 跑测试
python -m pytest tests/ -v
python -m pytest tests/test_repositories_sop.py -v          # 仅 Repository

# 启动 FastAPI（Day 7 后启用）
uvicorn app.main:app --reload --port 8000

# 看数据库内容
sqlite3 data/oceanmate.db ".tables"
sqlite3 data/oceanmate.db "SELECT * FROM merchants LIMIT 5;"
```

## 附录 B：已知约束与避坑（截至 Day 1）

| # | 约束 / 坑 | 解决方式 |
|---|----------|---------|
| 1 | 类内 `def list(...)` 会遮蔽 builtin，破坏后续 `list[X]` 注解 | 模块顶部加 `from __future__ import annotations` |
| 2 | SQLite 外键引用必须指向 UNIQUE 列；`error_codes(code)` 无 UNIQUE，不能被 FK | 业务码字段不加 FK，仅 `error_codes.id` 可做 FK |
| 3 | Chroma 默认 ONNX MiniLM 模型需联网下载 | 用本地 `HashEmbeddingFunction`（PoC 够用） |
| 4 | Windows 中文路径导致 .env 读取乱码 | 启动前 `chcp 65001`；.env 文件 UTF-8 无 BOM |
| 5 | 飞书 API Key 缺失不要卡死业务 | 所有 Provider 实现都自带 Mock 降级路径 |
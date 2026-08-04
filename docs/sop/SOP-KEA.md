# SOP-KEA · Knowledge Evolution Agent（知识进化）标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用组件**：`app/agents/kea/tool.py`
> **对位架构**：4 Tool 之知识进化（详见 `docs/architecture/oceanmate_v2.md` §2）
> **对位官方命题**：方向 ⑤「知识沉淀」—— 案例→FAQ 自进化闭环
> **关联文件**：
> - 实现：`src/backend/app/agents/kea/tool.py`
> - 测试：`src/backend/tests/test_kea_sop.py`（22/22）
> - 集成：`src/backend/app/agents/orchestrator/orchestrator.py` `_route_kea`

---

## 1. SOP 总览（7 子 SOP · 22 测试）

| 编号 | 场景 | 类型 | 测试方法 | 状态 |
|------|------|------|---------|------|
| SOP-KEA-001-A | promote 完整链路：cases 表 → Chroma → embedding_meta | 正向 | `TestPromoteHappyPath::*` | ✅ |
| SOP-KEA-001-B | promote 去重（重复 promote 不再写入第二条） | 正向 | 同上 | ✅ |
| SOP-KEA-001-C | search_faq 命中 + join cases 表富信息 | 正向 | `TestSearchFAQ::*` | ✅ |
| SOP-KEA-001-D | list_candidates 列高置信未沉淀候选 | 正向 | `TestListCandidates::*` | ✅ |
| SOP-KEA-002-A | 缺 case_id / case 不存在 → 友好降级 | 逆向（降级） | `TestFriendlyDegradation::*` | ✅ |
| SOP-KEA-002-B | Chroma 写入失败 / 无 CaseRepository → 友好降级 | 逆向（容错） | 同上 | ✅ |
| SOP-KEA-INT-001 | Orchestrator 关键词分流 → KEA 自动选 intent | 集成 | `TestKEAEnd2End::*` | ✅ |

**当前 SOP 矩阵总进度**：✅ 全部完成。Day 6 收官。

---

## 2. promote_to_faq 子能力（核心：自进化闭环）

### 2.1 3 层写入链路

```
┌────────────────────────────────────────────────────────────┐
│  Layer 1 · SQLite cases 表                                  │
│  case_id='case_demo_001' 的诊断结果已存在                   │
│  （由 PDA 写入 / 飞书同步 / 人工录入）                       │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 2 · Chroma cases_vec collection                     │
│  写入 rag_text = 问题/诊断/解决方案/国家/渠道/错误码       │
│  chroma_id = "faq_<case_id>_<uuid8>"                       │
│  metadata = {country, channel, error_code, problem_type, confidence} │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 3 · SQLite embedding_meta 表（同步追踪）            │
│  (source_table='cases', source_id=case_id,                 │
│   chroma_id, collection_name='cases_vec')                  │
│  → 用于"已 promote"去重 + 反向追溯                          │
└────────────────────────────────────────────────────────────┘
```

### 2.2 去重逻辑（防重复写入）

```python
existing_meta = self._get_embedding_meta(source_table="cases", source_id=case_id)
if existing_meta is not None:
    return self._error_result(
        "promote_to_faq", error="案例已升级为 FAQ",
        hint=f"原 chroma_id={existing_meta}",
        promoted=False, already=True, case_id=case_id,
        existing_chroma_id=existing_meta,
    )
```

### 2.3 降级路径（部分写入失败）

| 失败步骤 | 行为 | trace 标记 |
|---------|------|-----------|
| cases 表无此 ID | 友好 not_found | `error="案例 ... 不存在"` |
| embedding_meta 已有 | 友好 already_promoted | `already=True` |
| Chroma add 失败 | 友好降级，**不写 meta** | `rag_error=...` |
| embedding_meta insert 失败 | 部分降级（Chroma 已写）| `chroma_id=..., rag_written=True, embedding_meta_error=...` |

### 2.4 断言清单

| # | 断言 |
|---|------|
| 1 | `promoted=True` 仅在 3 层都成功时返回 |
| 2 | `chroma_id` 格式：`faq_<case_id>_<uuid8 hex>` |
| 3 | `embedding_meta` 表真的有 `(source_table='cases', source_id)` 唯一行 |
| 4 | Chroma `cases_vec` 真的能 retrieve 到该 chroma_id |
| 5 | 重复 promote 不会创建第二条 embedding_meta |

---

## 3. search_faq 子能力（召回链路）

### 3.1 检索流程

```
KEA.search_faq(query, top_k, country)
  ↓
ChromaRAGEngine.retrieve(query, top_k, filter={"country":...})
  ↓
对每个 Document:
  parse chroma_id → "faq_<case_id>_<uuid>"
  → CaseRepository.get_by_id(case_id)
  → return chroma_id + case_info 富信息
```

### 3.2 级联失败（无 case_repo 也能查 FAQ）

- 有 DB：返回完整 case_info（problem_desc / resolution / 等）
- 无 DB：case_info=None，仅返回 chroma_id + text_excerpt + metadata

### 3.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | promote 后 search | 命中，case_id 正确解析 |
| 2 | country 过滤 | 所有返回的 faqs.country 都匹配 |
| 3 | 知识库空 | `count=0, faqs=[]`，`empty_reason=no_match` |

---

## 4. list_candidates 子能力（运营筛选用）

### 4.1 算法

```
List all cases (limit * 3)
  ↓
Filter: confidence ≥ min_confidence (默认 0.85)
  ↓
Filter: NOT IN (embedding_meta WHERE source_id = cases.id)
  ↓
Truncate to limit
```

### 4.2 默认阈值 0.85 的设计理由

来自 OP 真实运维经验：
- 0.85 以下：可能是边缘 case / 偶发问题，不宜广泛推给所有商户
- 0.85+：诊断置信度高，可作为 FAQ 候选
- 真实环境阈值可调（`ctx.min_confidence` 覆盖）

### 4.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | 默认阈值 | 仅返回 confidence ≥ 0.85 |
| 2 | 已 promote 的过滤掉 | count 减少 |
| 3 | `min_confidence=0.5` | 返回条数更多（含中等置信）|

---

## 5. Orchestrator 集成（SOP-KEA-INT-001）

### 5.1 自动选 intent

```python
# Orchestrator._route_kea
if ctx.get("case_id"):
    sub_intent = "promote_to_faq"
elif ctx.get("query"):
    sub_intent = "search_faq"
else:
    sub_intent = "list_candidates"
```

### 5.2 评审演示 3 路径

| 商户话术 | 关键词命中 | sub_intent | 评审看点 |
|---------|-----------|-----------|---------|
| "FAQ 怎么用" | knowledge_evolution 命中 | list_candidates | 列高置信候选 |
| "BR Visa 拒付怎么办" | knowledge_evolution 命中 | search_faq | search + join cases |
| "把这个案例沉淀到 FAQ" | knowledge_evolution 命中 + ctx.case_id | promote_to_faq | 自进化闭环 |

### 5.3 断言清单

| # | 场景 | 期望 |
|---|------|------|
| 1 | Orchestrator 默认 KEA（无 DB）+ case_id | data.promoted=False，trace.error 含 "CaseRepository" 或 "不存在" |
| 2 | Orchestrator + 完整 KEA + DB + sample_case | sub_intent=promote_to_faq，data.promoted=True |
| 3 | KEA 执行失败的 trace 字段 | `trace.error` / `trace.hint` 非空 |

---

## 6. 真实环境差异

| 项 | Demo（PoC）| 真实生产 |
|---|---|---|
| cases 表来源 | PDA 诊断自动写入 / 测试 fixture | 飞书多维表格同步 + PDA 写入 |
| Chroma collection | cases_vec（PoC 与 PDA 共享）| cases_vec_public（商户可查） + cases_vec_internal（仅运营）|
| embedding_meta | 自动同步追踪 | 同样 + 反向追踪（Chroma → SQLite 也能查）|
| FAQ 发布审核 | 列表候选 → 自动 promote | 列表候选 → 运营审阅 → 手动 promote |
| 检索召回 | HashEmbedding（语义召回弱）| Qwen Embedding / ONNX MiniLM（语义强召回）|
| Promote 触发 | 显式调 KEA.promote_to_faq | 工单结案事件 → 自动触发（PDA → TRA → KEA 链）|

---

## 7. 已知约束与避坑

| # | 约束 / 坑 | 解决方式 |
|---|----------|---------|
| 1 | `cases.merchant_id` 有 FK → `merchants.id`，非 NULL merchant_id 必须先有 merchant 行 | 测试 fixture `merchant_setup` 预置；生产环境商户档案先于 cases 同步 |
| 2 | Chroma 默认 ONNX MiniLM 模型需联网下载 | KEA 用 ChromaRAGEngine 默认（HashEmbedding）—— PoC 够用 |
| 3 | Windows 中文路径 + GBK 默认编码 → Chroma 写入可能失败 | 测试 fixture `tmp_chroma_dir` + ChromaRAGEngine data_dir 参数 |
| 4 | promote 重复检测需查 embedding_meta 表 | KEA 不强制；调用方负责；KEA 仅当 `_db` 注入时才检查 |
| 5 | `case_id` 含下划线时，chroma_id 解析需 `"_".join(parts[1:-1])` 而非 `parts[1]` | tool.py 内已实现，详见 §3.1 |
| 6 | list_candidates 全表扫（PoC limit*3）| 真实环境加 `is_promoted` 字段 + 索引（cases 表 update_at + problem_type 已有索引）|
| 7 | KEA Tool 默认无 DB（演示友好降级）| 真实生产 KEA 必须注入 case_repo（与 TRA 一致）|

---

## 附录 A · 评审可演示命令

### A.1 跑测试

```bash
cd src/backend
python -m pytest tests/test_kea_sop.py -v           # 仅 KEA（22 测试）
python -m pytest tests/ -q                           # 全套（147）
```

### A.2 端到端：PDA → KEA 自进化闭环演示

```python
import sys
import sqlite3
import tempfile
sys.path.insert(0, r'E:\ai-pioneer\src\backend')

from pathlib import Path
from scripts.init_db import DDL_STATEMENTS
from app.agents.orchestrator import Orchestrator
from app.agents.kea import KEATool
from app.implementations.db.sqlite_db import SQLiteDatabase
from app.implementations.db.repositories import (
    CaseRepository, MerchantRepository,
)
from app.models import Case, Merchant

# 1. 建临时 DB（避免污染 data/oceanmate.db + FK 风险）
with tempfile.TemporaryDirectory() as td:
    db_path = Path(td) / "oceanmate_demo.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in DDL_STATEMENTS:
        conn.execute(ddl)
    conn.commit(); conn.close()
    db = SQLiteDatabase(db_path)
    merchant_repo = MerchantRepository(db)
    case_repo = CaseRepository(db)

    # 2. merchant 必须先建（cases.merchant_id FK）
    merchant_repo.create(Merchant(
        id="m_demo", country="BR", tier="vip",
    ))

    # 3. PDA 诊断结果写进 cases 表（手工模拟）
    case_repo.create(Case(
        id="case_demo_001",
        problem_desc="BR Visa 拒付",
        diagnosis="风控 R001",
        resolution="建议加 3DS",
        country="BR", channel="Visa",
        error_code="ERR_X_001", problem_type="拒付",
        confidence=0.92,
        merchant_id="m_demo",
    ))

    # 4. 注册 KEA（带 DB + 独立 Chroma 目录）
    chroma_dir = Path(td) / "chroma"
    chroma_dir.mkdir()
    kea = KEATool(
        case_repo=case_repo,
        chroma_path=chroma_dir,
        embedding_meta_repo=db,
    )

    # 5. 注册到 Orchestrator
    orch = Orchestrator()
    orch.register_tool(kea)

    # 6. 商户说"把这个案例沉淀到 FAQ"
    result = orch.route(
        "FAQ 怎么用",  # 命中 knowledge_evolution 关键词
        merchant_context={"case_id": "case_demo_001"},
    )

    print(f"intent: {result['intent']}")
    print(f"sub_intent: {result['trace']['sub_intent']}")
    print(f"promoted: {result['tool_result']['data']['promoted']}")
    print(f"chroma_id: {result['tool_result']['data']['chroma_id']}")
    print(f"case_id: {result['tool_result']['data']['case_id']}")
```

### A.3 端到端：search_faq 召回演示

```python
# 接上面，promote 完成后，下次商户提问 → search_faq 命中
result2 = orch.route(
    "FAQ 怎么用",
    merchant_context={
        "query": "BR Visa 拒付怎么办",
        "country": "BR",
    },
)
print(f"sub_intent: {result2['trace']['sub_intent']}")  # search_faq
print(f"count: {result2['tool_result']['data']['count']}")
print(f"top faq: {result2['tool_result']['data']['faqs'][0]}")
```

### A.4 评审可演示点（5 个）

| # | 演示项 | 评审看点 |
|---|------|---------|
| 1 | `mcp_tool_spec` 输出 | 3 intent 完整 schema，对位 AtoA 挑战 |
| 2 | promote 3 层写入（cases → Chroma → embedding_meta）| 数据一致性 + 事务原子性的工程化 |
| 3 | promote 去重 | 幂等性设计（防重复写入） |
| 4 | 友好降级链（无 DB / case 不存在 / Chroma 失败）| "AI 不会挂"的鲁棒性 |
| 5 | list_candidates 阈值过滤 | 知识运营闭环（候选筛选 → 升级） |

---

## 附录 B · 与官方命题的对位

| OP 命题方向 | KEA 对位 | 落地 |
|------------|---------|------|
| ⑤ 案例→FAQ 自进化闭环 | promote_to_faq + search_faq + list_candidates | `tool.py` 主体 |
| AtoA 挑战 | MCP tool_spec 导出 | `to_mcp_tool_spec()` |
| 工单结案触发 | （未来）TRA status=resolved 事件 → KEA.auto_promote | 当前 Orchestrator 手工调用，预留接口 |

---

## SOP 矩阵进度更新

| 编号 | Tool | 类型 | 状态 |
|------|------|------|------|
| SOP-KEA-001 | KEATool | 正向（promote + search + list）| ✅ **Day 6 完成** |
| SOP-KEA-002 | KEATool | 逆向（4 子场景友好降级）| ✅ **Day 6 完成** |

**当前 SOP 矩阵总进度**：✅ 全部完成。Day 6 收官。

---

## 附录 C · KEA 重构建议（生产化路径）

> 当 PoC 升级到真实环境时，按以下顺序迁移：

1. **HashEmbedding → Qwen Embedding**：
   - 替换 `ChromaRAGEngine.__init__` 里的 `embedding_function` 参数
   - 业务代码零改动

2. **embedding_meta 表新增 `promoted_by` / `promoted_at` 字段**：
   - 让 promote 流程可追溯到具体运营/事件

3. **TRA status=resolved 事件 → KEA.auto_promote**：
   - 飞书工单系统 webhook → 检测 status=resolved → 自动触发 KEA.promote_to_faq
   - 当前 Orchestrator 手工调用，预留 hook

4. **多 collection 分离**：
   - `cases_vec_internal`（运营 / PDA）vs `cases_vec_public`（商户 / search）
   - 安全审核门槛

详见 `docs/architecture/oceanmate_v2.md` §4（替换指南）。

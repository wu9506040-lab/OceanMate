# SOP-RAG · RAG Engine 标准操作程序

> **版本**：v1.0 · 2026-08-04
> **适用组件**：`app/implementations/rag/chroma_rag.py`（ChromaRAGEngine + HashEmbeddingFunction）
> **关联**：
> - 接口：`app/interfaces/base_rag.py`
> - 测试：`src/backend/tests/test_rag_sop.py`

---

## SOP 总览（4 逆向 + 1 正向 = 5 子 SOP）

| 编号 | 场景 | 类型 | 测试方法 |
|------|------|------|---------|
| SOP-RAG-001-A | 知识库空 → retrieve 返回 []（调用方降级）| 逆向（空库） | `test_empty_library_returns_empty_list` |
| SOP-RAG-001-B | 检索相似度过低 → 返回 [] | 逆向（弱语义）| `test_retrieve_no_match_keywords` |
| SOP-RAG-001-C | add_document 后 retrieve 命中（正向）| 正向 | `test_add_and_retrieve_same_text` |
| SOP-RAG-001-D | 不存在的 collection 名 → ValueError | 逆向（输入校验）| `test_retrieve_nonexistent_collection_raises` |
| SOP-RAG-001-E | HashEmbeddingFunction L2 归一化正确 | 正向（数学）| `test_l2_normalized` |

> **注**：当前 PoC 实现不强制相似度阈值，"相似度过低"表现为 top_k 内结果极少或不含目标文档。
> 由调用方（如 PDA Tool）判断"空结果/弱结果 → 走兜底逻辑"。

---

## SOP-RAG-001-A · 知识库空 → 友好返回 []

### 适用场景

KEA 刚启动 / 多维表格同步失败 / 知识库首次部署。商户提问前知识库为空。

### 设计原则

> 检索结果可能为空（知识库空 / 相似度全低），返回 `[]`，由调用方决定降级策略。
> —— `BaseRAGEngine.retrieve()` docstring

### 行为

```python
def retrieve(self, query: str, top_k: int = 5, filter=None, collection_name=...) -> list[Document]:
    if collection_name not in self._collections:
        raise ValueError(...)
    try:
        results = collection.query(query_texts=[query], n_results=top_k, where=filter)
    except Exception as e:
        raise RuntimeError(...) from e
    documents = []
    if results and results.get("documents"):
        for i, text in enumerate(results["documents"][0]):
            ...
            documents.append(Document(...))
    return documents  # 空库时返回 []
```

### 断言

| # | 断言 |
|---|------|
| 1 | retrieve() 返回 `[]`（不抛异常）|
| 2 | 带 metadata filter 的空库查询也返回 `[]` |
| 3 | 调用方按 SOP-PDA-002 处理兜底（root_causes 含"未匹配"）|

---

## SOP-RAG-001-B · 相似度过低 → 返回 []

### 适用场景

商户提问与知识库内容完全不相关。

### 行为

Chroma 默认返回 top_k 个最相似的，即使相似度都很低。**当前实现不强制阈值**：

- 如果 top_k 内有 1+ 文档 → 返回（即使相似度低）
- 如果数据库只有 0 文档 → 返回 []

### Hash Embedding 特性

| 项 | HashEmbeddingFunction（PoC）| 真实 MiniLM / Qwen Embedding |
|---|---|---|
| 语义能力 | 弱（同义词召回差）| 强 |
| 可重现 | ✅ 完全确定 | ❌ 模型版本敏感 |
| 模型下载 | ❌ 不需要 | ✅ 首次需联网 |
| Demo 可演示 | ✅ | ⚠️ 离线受限 |

### 断言

| # | 断言 |
|---|------|
| 1 | 添加"苹果"内容后，查询"Visa 风控"返回的文档列表可能为空或非"苹果" |
| 2 | 不抛异常（弱语义场景不应报错）|

### 真实环境差异

真实环境建议加相似度阈值过滤：
```python
docs = [d for d in docs if d.score >= 0.65]
```

---

## SOP-RAG-001-C · add_document 后 retrieve 命中

### 行为

```python
rag.add_document(Document(
    id="doc_br_visa",
    text="BR 区域 Visa 渠道风控拦截规则",
    metadata={"country": "BR"},
))
results = rag.retrieve("BR Visa 风控", top_k=3)
# 至少返回 1 条；Hash embedding 因 hash 碰撞不保证 doc_br_visa 一定在 top-3
```

### 断言

| # | 断言 |
|---|------|
| 1 | 返回 list 类型 |
| 2 | 元素都是 Document 实例 |
| 3 | 至少 1 条结果（强相关场景）|

---

## SOP-RAG-001-D · 不存在的 collection → ValueError

### 行为

ChromaRAGEngine 预创建 3 个 collection（`error_codes_vec` / `cases_vec` / `payment_methods_vec`）。其他名字视为输入错误。

```python
if collection_name not in self._collections:
    raise ValueError(f"Collection '{collection_name}' 不存在")
```

### 断言

| # | 断言 |
|---|------|
| 1 | retrieve("xxx", collection_name="unknown") 抛 ValueError |
| 2 | add_document(doc, collection_name="unknown") 抛 ValueError |
| 3 | 错误信息含"不存在" |

---

## SOP-RAG-001-E · HashEmbeddingFunction 数学性质

### 5 个保证

| # | 性质 | 测试 |
|---|------|------|
| 1 | 同输入 → 同输出（确定性）| `test_deterministic` |
| 2 | 不同输入 → 不同输出（区分度）| `test_different_text_different_vector` |
| 3 | L2 归一化（模长 = 1）| `test_l2_normalized` |
| 4 | 中英文分别 tokenize | `test_chinese_tokenization` |
| 5 | 维度固定（默认 128）| DIMENSION 常量 |

### 算法

```python
def _embed_one(self, text: str) -> list[float]:
    tokens = self._tokenize(text)  # 中文按字 + 英文按词
    vector = [0.0] * self.dimension
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vector[h % self.dimension] += 1.0
    # L2 归一化
    norm = sum(v * v for v in vector) ** 0.5
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector
```

### 已知缺陷

| 缺陷 | 影响 | 真实环境缓解 |
|---|---|---|
| 无语义（"BR 风控" vs "Brazil risk" 不相似）| 召回率低 | 换 ONNXMiniLM_L6_V2 |
| 无词频权重（"the" 和 "风控" 同权）| 短文本质量差 | 真实模型有 IDF |
| Hash 碰撞（极端小概率）| 极少量错召回 | 真实模型无此问题 |

---

## 附录 A：评审可演示命令

```bash
cd src/backend
python -m pytest tests/test_rag_sop.py -v

# 端到端：写入 + 检索演示
python -c "
import tempfile
from pathlib import Path
from app.implementations.rag.chroma_rag import ChromaRAGEngine
from app.interfaces.base_rag import Document

d = Path(tempfile.mkdtemp()) / 'chroma'
rag = ChromaRAGEngine(data_dir=d)
rag.add_document(Document(id='r1', text='BR Visa 风控拦截', metadata={'country': 'BR'}))
rag.add_document(Document(id='r2', text='US PayPal 账户被封', metadata={'country': 'US'}))
print('=== 检索：BR Visa ===')
for doc in rag.retrieve('BR Visa 信用卡风控', top_k=2):
    print(f'- [{doc.id}] {doc.text[:40]}')
print()
print('=== 检索：US PayPal ===')
for doc in rag.retrieve('US PayPal 账户问题', top_k=2):
    print(f'- [{doc.id}] {doc.text[:40]}')
print()
print('=== 3 个 Collection 状态 ===')
print(rag.get_collection_stats())
"
```

## 附录 B：替换指南（详见 `oceanmate_v2.md` §4.3）

```python
# 切到真实模型（联网环境）
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
embedding_function = ONNXMiniLM_L6_V2()
engine = ChromaRAGEngine(data_dir=Path("data/chroma"), embedding_function=embedding_function)
```

业务代码零改动（因为 ChromaRAGEngine 始终实现 BaseRAGEngine 接口）。

---

## SOP 矩阵进度更新

| 编号 | Tool/组件 | 类型 | 状态 |
|------|---------|------|------|
| SOP-RAG-001 | RAG Engine | 正逆混合 5 子场景 | ✅ **Day 3 完成** |
| SOP-CHUNK-001 | Chunking 切片策略 | 4 策略 + 1 调度器 17 用例 | ✅ **Day 8 完成** |
| SOP-RAG-002 | RAG 扩展方法 + Pipeline | 14 用例 | ✅ **Day 8 完成** |

---

# Day 8 新增：SOP-CHUNK-001 · Chunking 切片策略

> **版本**：v1.1 · 2026-08-04
> **适用组件**：`app/implementations/chunking/`（4 策略 + 1 调度器）
> **关联**：
> - 接口：`app/interfaces/base_chunker.py`（BaseChunker + Chunk）
> - 测试：`src/backend/tests/test_chunking.py`（17 用例）

## 1. 设计原则

**Chunking 是 RAG 入库前的核心步骤，决定向量化的语义单元。**

| 原则 | 含义 |
|------|------|
| **语义切分优先** | 不只用滑动窗口；按数据形态选策略（FAQ / 策论 / 短文本）|
| **Q+A 不能拆** | 一起切，向量含完整语义，召回最准 |
| **Metadata 传递** | 每个 chunk 继承 base + 加 strategy / section_title / char_range |
| **不重叠** | 语义切片天然有边界；不强制 overlap |
| **可调度** | SmartChunker 自动按数据特征选策略 |

## 2. 4 策略 + 1 调度器

| 策略 | 适用 | 触发条件 |
|------|------|---------|
| `WholeRecordChunker` | 错误码 / 支付方式 / 案例简述 | text 长度 < 512 chars（默认 short_threshold）|
| `QAPairChunker` | FAQ / 商户问答 / KEA 沉淀 | 检测到 `Q:` / `问：` / `Question:` 起始行 |
| `MarkdownSectionChunker` | 策论 / 政策 / 妙记 | 检测到 markdown heading 或 ≥2 段落 |
| `SlidingWindowChunker` | 超长兜底 | 任何无结构的超长文本（chunk_size=1024, overlap=64）|

**调度器 `SmartChunker`** 优先级：短文本 → Q/A → Markdown/段落 → 滑动窗口。

任一策略产出后再过 `_enforce_max`（默认 1024 chars），超长 chunk 用 SlidingWindow 重切。

## 3. 数据形态 → 策略映射

| 数据源 | 推荐策略 | 原因 |
|--------|---------|------|
| `error_codes_vec` | WholeRecord（默认）| 1 错误码 = 1 规则 |
| `payment_methods_vec` | WholeRecord | 1 支付方式 = 1 条 |
| `cases_vec`（短描述）| WholeRecord | 1 案例 = 1 chunk |
| `cases_vec`（长描述 + Q&A）| QAPair | Q+A 一起 |
| `faq_vec`（未来）| QAPair | 关键设计：Q+A 不拆 |
| 妙记转写（未来）| MarkdownSection | 按段落/章节 |
| 长策略文章 | MarkdownSection | 按 heading |
| 无结构超长 | SlidingWindow | 兜底 |

## 4. Chunk 数据结构

```python
@dataclass
class Chunk:
    chunk_id: str       # "{doc_id}#{strategy_prefix}{index}"
    doc_id: str
    text: str           # 已 strip，未清洗
    chunk_index: int    # 0-based
    metadata: dict      # base + strategy + section_title + char_range + has_q/has_a
```

`strategy` 取值：`whole_record` / `qa_pair` / `markdown_section` / `sliding_window`

## 5. 5 子 SOP 矩阵

| 编号 | 场景 | 测试 |
|------|------|------|
| SOP-CHUNK-001-A | WholeRecord 短文本 → 1 chunk | `TestWholeRecordChunker::*`（3）|
| SOP-CHUNK-001-B | QAPair Q+A 一起切（关键）| `TestQAPairChunker::*`（4）|
| SOP-CHUNK-001-C/D | MarkdownSection heading / 段落 | `TestMarkdownSectionChunker::*`（3）|
| SOP-CHUNK-001-E | SlidingWindow 滑动切 | `TestSlidingWindowChunker::*`（2）|
| SOP-CHUNK-001-F/G/H | SmartChunker 自动调度 | `TestSmartChunker::*`（5）|

**当前进度**：✅ 17/17 测试通过。

---

# Day 8 新增：SOP-RAG-002 · RAG 扩展方法 + IngestionPipeline

## 1. 3 个新方法

| 方法 | 用途 | SOP 测试 |
|------|------|---------|
| `add_documents(docs)` | 批量入库（seed 脚本用）| `TestRAGAddDocuments::*`（3）|
| `recall_by_metadata(filter)` | 纯元数据召回（无 query）| `TestRAGRecallByMetadata::*`（4）|
| `get_by_id(doc_id)` | 单文档取（工单详情页用）| `TestRAGGetById::*`（2）|

### 1.1 多键值过滤自动包装

`recall_by_metadata({"country": "BR", "channel": "Visa"})` 内部自动转 Chroma 语法：
```python
{"$and": [{"country": "BR"}, {"channel": "Visa"}]}
```

调用方无需关心 Chroma `$and` / `$or` 语法。

## 2. IngestionPipeline（编排层）

```python
pipeline = IngestionPipeline(
    rag=rag,
    chunker=SmartChunker(),  # 默认
    # cleaner=None,           # 可选（Day 8+ 接 Cleaner 时启用）
    # embedder=None,          # 可选（Chroma 自管）
)
stats = pipeline.ingest(
    records=[{"id": "r1", "text": "BR Visa 拒付 ERR_X_001", "country": "BR"}, ...],
    source_table="cases",
    collection_name="cases_vec",
)
```

### 2.1 chunk_stats 返回结构

| 字段 | 含义 |
|------|------|
| `source_table` | 来源表名（如 "cases"）|
| `collection` | 目标 collection（如 "cases_vec"）|
| `total_records` | 入参记录数 |
| `total_chunks` | 实际入库 chunk 数 |
| `skipped_records` | 跳过（空文本 / 入库失败）|
| `strategies_used` | 各策略使用次数（如 `{"qa_pair": 4, "whole_record": 1}`）|
| `avg_chunk_size` | 平均 chunk 字符数 |
| `max_chunk_size` | 最大 chunk 字符数 |

### 2.2 错误隔离

单条记录入库失败 → `skipped_records += 1`，不阻断整体流程。

## 3. SOP 测试矩阵（14 用例）

| 编号 | 场景 | 测试 |
|------|------|------|
| SOP-RAG-002-A | add_documents 批量入库 | `TestRAGAddDocuments::*`（3）|
| SOP-RAG-002-B | recall_by_metadata 多键过滤 | `TestRAGRecallByMetadata::*`（4）|
| SOP-RAG-002-C | get_by_id 单文档 | `TestRAGGetById::*`（2）|
| SOP-RAG-002-D/E/F | Pipeline 编排 | `TestIngestionPipeline::*`（5）|

**当前进度**：✅ 14/14 测试通过。

---

## 附录 C · 端到端：records → Chroma 一行跑通（Day 8 新）

```python
import json
from pathlib import Path
from app.implementations.rag.chroma_rag import ChromaRAGEngine, COLLECTION_CASES
from app.implementations.pipelines import IngestionPipeline
from app.implementations.chunking import SmartChunker

records = json.loads(Path("docs/data/payment_error_cases.json").read_text(encoding="utf-8"))["cases"]
records = [{"id": r["id"], "text": r["rule_description"], **r} for r in records]

rag = ChromaRAGEngine()
pipeline = IngestionPipeline(rag=rag, chunker=SmartChunker())
stats = pipeline.ingest(records, source_table="error_codes", collection_name=COLLECTION_CASES)

print(f"入库 {stats['total_chunks']} chunks / 跳过 {stats['skipped_records']} 条")
print(f"策略分布: {stats['strategies_used']}")
```
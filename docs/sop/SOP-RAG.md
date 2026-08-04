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
"""OceanMate AI - 实现层

实现层依赖接口层（interfaces/），不反向依赖。

子模块：
- llm/        LLM 网关实现（Qwen + Mock）
- rag/        RAG 引擎实现（Chroma）
- db/         数据库实现（SQLite + Repository）
- feishu/     飞书 API 实现（Day 6）
"""
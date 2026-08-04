"""RAG 引擎实现层 - Chroma 嵌入式。

3 个 Collection：
- error_codes_vec  错误码知识
- cases_vec        案例知识
- payment_methods_vec  支付方式（PWR 用）

详见 SOP-RAG-001（3 个逆向场景：知识库空/相似度低/Embedding 失败）。
"""
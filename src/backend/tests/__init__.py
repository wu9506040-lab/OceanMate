"""pytest 测试目录。

结构：
- conftest.py                       故障注入 fixtures（5 个）
- test_db_structure_sop.py          表结构 + SOP-SQLITE-001
- test_repositories_sop.py          Repository + SOP-REPO-001
- test_transactions_sop.py          事务 + SOP-DB-001
- test_tool_spec_sop.py             MCP 导出 + SOP-MCP-001 / SOP-TOOL-001
- test_pda_tool_sop.py              PDA execute + SOP-PDA-001
- test_rag_sop.py                   RAG 检索 + SOP-RAG-001
- test_llm_gateway_sop.py           LLM + SOP-LLM-001
- test_feishu_sync_sop.py           飞书同步 + SOP-FEISHU-001
- test_validation_sop.py            参数校验 + SOP-VALIDATE-001
"""
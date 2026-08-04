"""OceanMate AI - 接口层（2 层架构：Tool + Data）

v2.2 架构约束：
- 所有 Tool 继承 BaseTool（MCP tool_spec 兼容）
- 所有 Repository 遵循 BaseRepository Protocol
- 所有外部依赖（LLM/RAG/DB/Frontend）走抽象接口

详见：
- docs/architecture/oceanmate_v2.md（待 Day 2-3 补）
- SOP-MCP-001（tool_spec 导出）
"""

__version__ = "2.2.0"
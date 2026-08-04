"""KEA Tool 模块 - 知识进化助手（OP 命题方向 ⑤ · 案例→FAQ 自进化闭环）。

对位官方命题：
- ⑤ 知识沉淀（闭环：诊断→结案→FAQ→下次诊断召回）
- 飞书多维表格 / RAG 同步（cases_vec + embedding_meta）

详见 tool.py 与 docs/sop/SOP-KEA.md。
"""

from app.agents.kea.tool import KEATool

__all__ = ["KEATool"]

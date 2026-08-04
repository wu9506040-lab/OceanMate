"""TRA Tool 模块 - 工单智能路由（OP 命题方向 ③）。

对位官方命题：
- ③ 智能工单路由（按 problem_type + priority + tier → assignee + SLA）
- 飞书多维表格规则可热更新（路由规则 JSON 加载）

详见 tool.py 与 docs/sop/SOP-TRA.md。
"""

from app.agents.tra.tool import TRATool

__all__ = ["TRATool"]

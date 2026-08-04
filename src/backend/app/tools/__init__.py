"""4 个 Tool 实现 - 继承 BaseTool。

- PDATool   支付诊断（⭐ Demo 核心，Day 2）
- MSATool   对话状态机（含 PWR 子能力，Day 3-4）
- TRATool   工单路由 + 智能交接（Day 4）
- KEATool   知识沉淀（Day 4-5）

所有 Tool 通过 ToolRegistry 注册，由 Orchestrator 调度。
"""
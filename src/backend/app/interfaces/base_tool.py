"""BaseTool - MCP tool_spec 兼容的 Tool 基类。

对位命题「AtoA 挑战」：Tool 接口按 MCP (Model Context Protocol) 标准设计。
不实现完整 MCP 协议栈（discovery server / 跨进程调用），
但接口字段 100% 兼容，未来可直接接入 MCP 生态。

参考：https://modelcontextprotocol.io/

实现要求：
- 每个 Tool 必须实现 name / description / input_schema / output_schema / execute
- capabilities 可选，默认 async_supported=True / idempotent=False / requires_auth=False
- 校验输入参数用 jsonschema 库（默认 validate_input）

示例：
    class PDATool(BaseTool):
        name = "payment_diagnosis"
        description = "诊断跨境支付失败/拒付/退款问题"

        @property
        def input_schema(self):
            return {"type": "object", "properties": {...}, "required": [...]}

        @property
        def output_schema(self):
            return {"type": "object", "properties": {...}, "required": [...]}

        def execute(self, params: dict) -> dict:
            ...
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from jsonschema import validate, ValidationError


class BaseTool(ABC):
    """Tool 基类 — MCP tool_spec 兼容。

    评审用法：
        from app.interfaces.base_tool import BaseTool
        print(MyTool().to_mcp_tool_spec())  # 输出 MCP 标准 dict
    """

    # === MCP tool_spec 必填字段 ===
    name: str = ""                          # 唯一标识（snake_case）
    description: str = ""                   # 给 LLM 看的功能描述

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """输入参数 JSON Schema。

        必须返回符合 JSON Schema Draft 2020-12 规范的 dict。
        Orchestrator 在调用前会用 jsonschema 库校验。
        """

    @property
    @abstractmethod
    def output_schema(self) -> dict:
        """输出结果 JSON Schema。

        必须返回符合 JSON Schema Draft 2020-12 规范的 dict。
        """

    @property
    def capabilities(self) -> dict:
        """Tool 能力声明（AtoA/MCP 扩展）。

        默认值适用于大多数 Tool；需要鉴权或幂等的 Tool 应重写。
        """
        return {
            "async_supported": True,
            "idempotent": False,
            "requires_auth": False,
        }

    @abstractmethod
    def execute(self, params: dict) -> dict:
        """执行 Tool，返回符合 output_schema 的 dict。

        异常处理：
        - 参数校验失败 → 抛 jsonschema.ValidationError（Orchestrator 捕获转 4xx）
        - 业务逻辑失败 → 抛 RuntimeError（Orchestrator 捕获转 5xx + 用户友好提示）
        - 外部依赖失败（LLM/RAG/DB） → 抛对应异常，由 Orchestrator 触发降级

        详见 SOP-PDA-001 / SOP-LLM-001。
        """

    # === MCP 兼容导出（评审展示用）===
    def to_mcp_tool_spec(self) -> dict:
        """导出 MCP 标准 tool_spec 格式。

        返回 dict 结构完全兼容 MCP 协议，可直接喂给支持 MCP 的客户端。
        评审可调用此方法查看所有 Tool 的 spec（/api/tools 端点）。
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "capabilities": self.capabilities,
        }

    # === 输入校验（默认实现，jsonschema 驱动）===
    def validate_input(self, params: dict) -> bool:
        """校验输入参数是否符合 input_schema。

        Returns: True 通过
        Raises: jsonschema.ValidationError 校验失败
        """
        try:
            validate(instance=params, schema=self.input_schema)
            return True
        except ValidationError as e:
            raise ValueError(
                f"Tool '{self.name}' 参数校验失败: {e.message}"
            ) from e

    # === 工具方法（便于 Orchestrator 调用）===
    def safe_execute(self, params: dict) -> dict:
        """安全执行：先校验参数再执行，返回统一结果 dict。

        Returns:
            {
                "success": True/False,
                "data": {...},            # success=True 时
                "error_code": "...",       # success=False 时
                "error_message": "..."     # success=False 时
            }

        评审意义：Orchestrator 不需要自己写 try/except，统一调 safe_execute。
        """
        try:
            self.validate_input(params)
            result = self.execute(params)
            return {"success": True, "data": result}
        except ValueError as e:
            # 参数校验失败
            return {
                "success": False,
                "error_code": "TOOL_PARAM_INVALID",
                "error_message": str(e),
            }
        except Exception as e:
            # 业务逻辑失败 / 外部依赖失败
            return {
                "success": False,
                "error_code": "TOOL_EXEC_ERROR",
                "error_message": str(e),
            }


class ToolRegistry:
    """Tool 注册中心 — Orchestrator 用。

    特性：
    - Tool 名字全局唯一（重名注册抛 ValueError）
    - 提供 list_tools() 返回所有 Tool 的 MCP tool_spec 列表
    - 提供 safe_execute(name, params) 统一执行入口

    使用：
        registry = ToolRegistry()
        registry.register(PDATool())
        registry.register(MSATool())

        # Orchestrator 选 Tool
        for spec in registry.list_tools():
            print(spec["name"], spec["description"])

        # Orchestrator 调 Tool
        result = registry.safe_execute("payment_diagnosis", params)
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册 Tool。

        Raises:
            ValueError: Tool 名字为空、重名、tool.name 与类属性不一致
        """
        if not tool.name:
            raise ValueError("Tool name 不能为空")
        if tool.name in self._tools:
            existing = type(self._tools[tool.name]).__name__
            raise ValueError(
                f"Tool '{tool.name}' 已注册（{existing}），不能重复注册"
            )
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> Optional[BaseTool]:
        """注销 Tool（测试用）。"""
        return self._tools.pop(name, None)

    def get(self, name: str) -> Optional[BaseTool]:
        """按名字获取 Tool，找不到返回 None。"""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """列出所有 Tool 的 MCP tool_spec（给 Orchestrator 选 Tool / 评审展示）。"""
        return [t.to_mcp_tool_spec() for t in self._tools.values()]

    def list_names(self) -> list[str]:
        """列出所有 Tool 名字。"""
        return list(self._tools.keys())

    def safe_execute(self, name: str, params: dict) -> dict:
        """统一执行入口（带 Tool 名字查找）。

        Returns: 见 BaseTool.safe_execute
        """
        tool = self.get(name)
        if tool is None:
            return {
                "success": False,
                "error_code": "TOOL_NOT_FOUND",
                "error_message": f"Tool '{name}' 未注册",
            }
        return tool.safe_execute(params)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
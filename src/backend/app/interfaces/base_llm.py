"""BaseLLMGateway - LLM 网关抽象接口。

4 个核心方法：
- chat()            普通对话
- chat_structured() 结构化输出（保证返回 JSON）
- embed()           Embedding 向量
- vision()          多模态理解（看图，截图 OCR 用）

实现层：app/implementations/llm/qwen_gateway.py（Qwen + Mock 降级）
SOP：SOP-LLM-001（4 个逆向场景：Key 缺失/限流/超时/非 JSON）
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMGateway(ABC):
    """LLM 网关基类。

    评审意义：未来切换 LLM（Qwen → GPT/Claude）只需换实现，业务代码不动。
    """

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        """对话补全。

        Args:
            messages: [{"role": "user", "content": "..."}, ...]
            **kwargs: temperature/max_tokens 等模型参数

        Returns:
            模型回复文本

        Raises:
            RuntimeError: 调用失败（含超时、限流、Key 无效等）
        """

    @abstractmethod
    def chat_structured(
        self, messages: list[dict], output_schema: dict, **kwargs
    ) -> dict:
        """结构化输出（保证返回符合 schema 的 dict）。

        Args:
            messages: 对话历史
            output_schema: JSON Schema 约束
            **kwargs: 模型参数

        Returns:
            符合 output_schema 的 dict

        Raises:
            RuntimeError: 调用失败
            ValueError: 返回内容无法解析为 schema 约束的 dict
        """

    @abstractmethod
    def embed(self, text: str, **kwargs) -> list[float]:
        """生成 Embedding 向量。

        Args:
            text: 输入文本（≤ 模型 token 上限）
            **kwargs: 模型参数

        Returns:
            浮点数向量（维度依模型而定）

        Raises:
            RuntimeError: 调用失败
        """

    @abstractmethod
    def vision(self, image_url: str, prompt: str, **kwargs) -> str:
        """多模态理解（看图）。

        Args:
            image_url: 图片 URL 或本地路径
            prompt: 提示词（如"识别图中的错误码"）

        Returns:
            模型对图片的理解结果

        Raises:
            RuntimeError: 调用失败

        Note:
            PoC 阶段可降级到 Mock（返回固定提示"图片理解功能需要多模态模型"）。
        """
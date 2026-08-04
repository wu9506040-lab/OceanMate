"""Qwen (DashScope) LLM Gateway 实现 + Mock 降级。

设计：
- 有 DASHSCOPE_API_KEY → 用真实 Qwen
- 无 Key 或调用失败 → 自动降级 MockLLMGateway（保证 Demo 始终能跑）
- 加指数退避重试（限流场景）
- 加 chat_structured（保证 JSON 输出）
- 加 embed（向量化）
- vision 用 Mock 降级（PoC 阶段不依赖 Qwen-VL）

详见 SOP-LLM-001（4 个逆向场景：Key 缺失/限流/超时/非 JSON）。
"""

import json
import os
import re
import time
from typing import Optional

from app.interfaces.base_llm import BaseLLMGateway


# === 重试配置 ===

MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 1.0
BACKOFF_MULTIPLIER = 2.0


def _retry_with_backoff(func, *args, **kwargs):
    """指数退避重试包装器。"""
    backoff = INITIAL_BACKOFF_SEC
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
    raise RuntimeError(f"LLM 调用失败（重试 {MAX_RETRIES} 次）: {last_error}")


# === Mock 实现 ===

class MockLLMGateway(BaseLLMGateway):
    """无 Key 时的降级实现。

    规则化输出，保证 Demo 可演示。
    评审意义：PoC 阶段无需 API Key 也能跑通流程。
    """

    def chat(self, messages: list[dict], **kwargs) -> str:
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            ""
        )
        return f"[Mock LLM 响应] 已收到您的消息：{last_user_msg[:80]}（PoC 阶段需要配置 DASHSCOPE_API_KEY 启用真实 Qwen）"

    def chat_structured(
        self, messages: list[dict], output_schema: dict, **kwargs
    ) -> dict:
        """根据 schema 生成空结构。"""
        # 简单实现：递归生成符合 schema 的默认值
        return _empty_from_schema(output_schema)

    def embed(self, text: str, **kwargs) -> list[float]:
        """Mock embedding：固定维度 8 的零向量。"""
        return [0.0] * 8

    def vision(self, image_url: str, prompt: str, **kwargs) -> str:
        """Mock vision：返回固定提示。"""
        return "[Mock Vision] 图片理解功能需要多模态模型（PoC 阶段 Mock 降级）"


def _empty_from_schema(schema: dict) -> dict:
    """从 JSON Schema 生成空 dict（Mock 用）。"""
    if schema.get("type") != "object":
        return None
    result = {}
    for key, prop in schema.get("properties", {}).items():
        if prop.get("type") == "object":
            result[key] = _empty_from_schema(prop)
        elif prop.get("type") == "array":
            result[key] = []
        else:
            result[key] = None
    return result


# === Qwen 真实实现 ===

class QwenGateway(BaseLLMGateway):
    """Qwen (DashScope) 实现 — 需要 DASHSCOPE_API_KEY 环境变量。

    特性：
    - 失败自动重试 3 次（指数退避）
    - chat_structured 通过 prompt 工程 + JSON 解析保证结构化输出
    - 任何异常 → 自动降级 MockLLMGateway
    """

    def __init__(self):
        try:
            import dashscope
            self._dashscope = dashscope
            from dashscope import Generation
            self._Generation = Generation
        except ImportError as e:
            raise ImportError(
                "dashscope 未安装。请运行: pip install dashscope"
            ) from e

    def chat(self, messages: list[dict], **kwargs) -> str:
        def _call():
            resp = self._Generation.call(
                model=kwargs.get("model", "qwen-turbo"),
                messages=messages,
                result_format="message",
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Qwen 调用失败: {resp.message}")
            return resp.output.choices[0].message.content

        try:
            return _retry_with_backoff(_call)
        except Exception as e:
            # 降级 Mock
            print(f"[QwenGateway] 降级 Mock: {e}")
            return MockLLMGateway().chat(messages, **kwargs)

    def chat_structured(
        self, messages: list[dict], output_schema: dict, **kwargs
    ) -> dict:
        # 在 system prompt 中注入 schema 要求
        schema_str = json.dumps(output_schema, ensure_ascii=False, indent=2)
        schema_instruction = (
            f"\n\n【重要】请严格按照以下 JSON Schema 输出结果，"
            f"不要包含任何额外文字或 Markdown 代码块标记：\n```json\n{schema_str}\n```"
        )

        # 复制 messages 并追加 schema 指令到最后一条 user 消息
        augmented = list(messages)
        if augmented and augmented[-1]["role"] == "user":
            augmented[-1] = {
                **augmented[-1],
                "content": augmented[-1]["content"] + schema_instruction,
            }
        else:
            augmented.append({"role": "user", "content": schema_instruction})

        def _call():
            resp = self._Generation.call(
                model=kwargs.get("model", "qwen-turbo"),
                messages=augmented,
                result_format="message",
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Qwen 调用失败: {resp.message}")
            return resp.output.choices[0].message.content

        try:
            content = _retry_with_backoff(_call)
            return self._parse_json(content)
        except Exception as e:
            # 降级 Mock
            print(f"[QwenGateway] chat_structured 降级 Mock: {e}")
            return MockLLMGateway().chat_structured(messages, output_schema, **kwargs)

    def embed(self, text: str, **kwargs) -> list[float]:
        try:
            from dashscope import TextEmbedding
            resp = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v2,
                input=text,
            )
            if resp.status_code == 200:
                return list(resp.output["embeddings"][0]["embedding"])
            raise RuntimeError(f"Qwen Embedding 失败: {resp.message}")
        except Exception as e:
            print(f"[QwenGateway] embed 降级 Mock: {e}")
            return MockLLMGateway().embed(text, **kwargs)

    def vision(self, image_url: str, prompt: str, **kwargs) -> str:
        """多模态调用（需要 Qwen-VL，PoC 阶段默认 Mock 降级）。"""
        try:
            # 留接口给 Day 3-4 MSA Tool 用
            return MockLLMGateway().vision(image_url, prompt, **kwargs)
        except Exception as e:
            print(f"[QwenGateway] vision 降级 Mock: {e}")
            return MockLLMGateway().vision(image_url, prompt, **kwargs)

    @staticmethod
    def _parse_json(content: str) -> dict:
        """从 LLM 输出中提取 JSON（兼容 markdown code block）。"""
        # 尝试匹配 ```json ... ``` 或 ``` ... ```
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
        if m:
            return json.loads(m.group(1))
        # 直接匹配 JSON
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            return json.loads(m.group(0))
        raise ValueError(f"无法从 LLM 输出提取 JSON: {content[:200]}")


# === 工厂函数 ===

def get_default_gateway() -> BaseLLMGateway:
    """工厂：优先 Qwen，无 Key 或调用失败自动 Mock。

    Returns:
        BaseLLMGateway 实例（QwenGateway 或 MockLLMGateway）
    """
    if os.getenv("DASHSCOPE_API_KEY"):
        try:
            return QwenGateway()
        except (ImportError, Exception) as e:
            print(f"[get_default_gateway] Qwen 初始化失败，降级 Mock: {e}")
            return MockLLMGateway()
    return MockLLMGateway()
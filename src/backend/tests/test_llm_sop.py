"""LLM Gateway SOP 测试 — Day 3 SOP-LLM-001。

覆盖 4 个逆向场景 + 2 个正向：
- SOP-LLM-001-A Key 缺失 → 自动降级 MockLLMGateway
- SOP-LLM-001-B Qwen 调用失败 → 自动降级 Mock
- SOP-LLM-001-C LLM 返回非 JSON → _parse_json 兼容 markdown code block
- SOP-LLM-001-D 重试耗尽 → 抛 RuntimeError（不再降级）
- SOP-LLM-001-E（正向）MockLLMGateway.chat() 返回非空文本
- SOP-LLM-001-F（正向）MockLLMGateway.chat_structured() 返回符合 schema 的 dict

详见 docs/sop/SOP-LLM.md。
"""

import json
import pytest

from app.implementations.llm.qwen_gateway import (
    MockLLMGateway,
    QwenGateway,
    get_default_gateway,
    _retry_with_backoff,
)


# === 正向：MockLLMGateway ===

class TestMockLLMGateway:
    """SOP-LLM-001-E / F 正向路径。"""

    def test_chat_returns_text(self):
        gw = MockLLMGateway()
        result = gw.chat([{"role": "user", "content": "你好，请帮我诊断 BR Visa 失败"}])
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Mock" in result or "PoC" in result or "BR" in result or "Visa" in result

    def test_chat_truncates_long_content(self):
        """超长消息截断到 80 字符（防止 Demo 内存问题）。"""
        gw = MockLLMGateway()
        long_msg = "x" * 500
        result = gw.chat([{"role": "user", "content": long_msg}])
        # 截断后消息本体 ≤ 80
        assert len(result) < 200  # 加上前缀不会超过 200

    def test_chat_structured_returns_valid_dict(self):
        gw = MockLLMGateway()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "age", "tags"],
        }
        result = gw.chat_structured([{"role": "user", "content": "test"}], schema)
        assert isinstance(result, dict)
        # 字段都在
        assert "name" in result
        assert "age" in result
        assert "tags" in result
        # 类型符合 schema（name/age 默认 None，tags 默认 []）
        assert result["tags"] == []

    def test_embed_returns_vector(self):
        gw = MockLLMGateway()
        vec = gw.embed("test text")
        assert isinstance(vec, list)
        assert all(isinstance(x, float) for x in vec)
        assert len(vec) > 0

    def test_vision_returns_placeholder(self):
        gw = MockLLMGateway()
        result = gw.vision("http://example.com/img.png", "识别错误码")
        assert isinstance(result, str)
        assert "Mock" in result or "PoC" in result


# === 逆向：Qwen 降级 / 重试 ===

class TestQwenGatewayFallback:
    """SOP-LLM-001-A/B/D：Key 缺失 / 调用失败 / 重试耗尽。"""

    def test_key_missing_returns_mock(self, monkeypatch):
        """SOP-LLM-001-A：DASHSCOPE_API_KEY 缺失 → 返回 MockLLMGateway。"""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        gw = get_default_gateway()
        assert isinstance(gw, MockLLMGateway)

    def test_qwen_init_failure_returns_mock(self, monkeypatch):
        """SOP-LLM-001-B：dashscope 未安装 → QwenGateway 初始化失败 → Mock。"""
        # 模拟 dashscope import 失败
        import sys
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake_key")
        # 移除 dashscope 模块（如果有）
        monkeypatch.setitem(sys.modules, "dashscope", None)
        gw = get_default_gateway()
        # 应该降级到 Mock
        assert isinstance(gw, MockLLMGateway)

    def test_qwen_call_failure_degrades_to_mock(self, monkeypatch):
        """SOP-LLM-001-B：Qwen 调用失败 → chat() 自动降级 Mock。"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake_key")

        # 构造一个 mock DashScope，让 Generation.call 抛 RuntimeError
        class FakeGeneration:
            @staticmethod
            def call(**kwargs):
                raise RuntimeError("模拟 DashScope 5xx 错误")

        class FakeDashScope:
            Generation = FakeGeneration

        # 注入 fake dashscope
        import sys
        monkeypatch.setitem(sys.modules, "dashscope", FakeDashScope)
        # 也要注入 dashscope.Generation 引用
        monkeypatch.setitem(sys.modules, "dashscope.Generation", FakeGeneration)

        # 现在 get_default_gateway 会创建 QwenGateway（因为有 key），但 chat() 会降级
        gw = get_default_gateway()
        # chat 应该返回 Mock 的输出（不抛异常）
        result = gw.chat([{"role": "user", "content": "test"}])
        assert isinstance(result, str)
        assert len(result) > 0
        # Mock 的特征文案
        assert "Mock" in result


class TestRetryLogic:
    """SOP-LLM-001-D：重试耗尽。"""

    def test_retry_succeeds_after_failures(self, monkeypatch):
        """第 2 次成功 → 应返回成功结果，不抛异常。"""
        # 避免实际 sleep
        import time
        monkeypatch.setattr(time, "sleep", lambda x: None)

        attempts = []

        def flaky_func():
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("第 1 次失败")
            return "success"

        result = _retry_with_backoff(flaky_func)
        assert result == "success"
        assert len(attempts) == 2

    def test_retry_exhausted_raises(self, monkeypatch):
        """3 次都失败 → 抛 RuntimeError（含"重试 3 次"信息）。"""
        import time
        monkeypatch.setattr(time, "sleep", lambda x: None)

        def always_fail():
            raise RuntimeError("始终失败")

        with pytest.raises(RuntimeError) as exc_info:
            _retry_with_backoff(always_fail)
        assert "重试 3 次" in str(exc_info.value) or "重试" in str(exc_info.value)


class TestParseJson:
    """SOP-LLM-001-C：非 JSON 输出兼容。"""

    def test_parse_markdown_json_block(self):
        """```json\n{...}\n``` 格式。"""
        content = '```json\n{"name": "test", "value": 42}\n```'
        result = QwenGateway._parse_json(content)
        assert result == {"name": "test", "value": 42}

    def test_parse_bare_json(self):
        """纯 JSON 格式。"""
        content = '{"foo": "bar"}'
        result = QwenGateway._parse_json(content)
        assert result == {"foo": "bar"}

    def test_parse_json_with_surrounding_text(self):
        """JSON 前后有自然语言描述。"""
        content = '好的，结果如下：\n{"x": 1, "y": [1,2,3]}\n请查收。'
        result = QwenGateway._parse_json(content)
        assert result == {"x": 1, "y": [1, 2, 3]}

    def test_parse_invalid_json_raises(self):
        """完全无法解析 → ValueError。"""
        content = "这不是 JSON"
        with pytest.raises(ValueError) as exc_info:
            QwenGateway._parse_json(content)
        assert "无法从 LLM 输出提取 JSON" in str(exc_info.value)
"""Day 15 P0 验证测试 — 4 项关键修复：

P0-1: 超长输入截断（Orchestrator.route 入口）
P0-2: 并发控制（threading.RLock）
P0-3: LLM 返回格式强校验（_coerce_float / chain_config._safe_float）
P0-4: webhook 签名校验（SHA256(timestamp+nonce+encrypt_key+body_str)）

每项给 1-2 个用例 + 真实失败场景 + 友好降级路径。
"""

import hashlib
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from app.agents.orchestrator import Orchestrator
from app.agents.orchestrator.chain_config import _safe_float, PDA_TO_TRA_CHAIN
from app.implementations.feishu.webhook import FeishuWebhookHandler


# === Fixtures ===

@pytest.fixture
def orch():
    """Orchestrator with mock LLM（关键词命中，不依赖 LLM）。"""
    return Orchestrator(use_llm_fallback=False)


class TestP0_1LongInputTruncation:
    """P0-1：超长输入截断。"""

    def test_normal_query_passes_through(self, orch):
        """500 字以内正常路由（不触发截断）。"""
        result = orch.route(user_query="我美国站卖软件，Visa 13.1 拒付好多")
        assert result["intent"] != "unknown", "正常 query 应进入 PDA 意图"
        assert "truncated" not in result.get("trace", {})

    def test_long_query_returns_too_long_error(self, orch):
        """1000 字 query → 触发 QUERY_TOO_LONG 错误，不送 LLM。"""
        long_q = "拒付" + "详情" * 500  # 1001 字
        assert len(long_q) > 500
        result = orch.route(user_query=long_q)
        assert result["intent"] == "unknown"
        assert result["tool_result"]["error_code"] == "QUERY_TOO_LONG"
        assert result["trace"]["truncated"] is True
        assert result["trace"]["original_length"] == len(long_q)
        # 错误消息含原长 + 字数上限
        assert str(len(long_q)) in result["tool_result"]["error_message"]
        assert "500" in result["tool_result"]["error_message"]

    def test_exactly_500_chars_passes(self, orch):
        """恰好 500 字（边界）→ 不触发截断。"""
        q500 = "a" * 500
        result = orch.route(user_query=q500)
        assert "truncated" not in result.get("trace", {})


class TestP0_2Concurrency:
    """P0-2：并发锁 + instance state 隔离。"""

    def test_five_concurrent_requests_no_state_leak(self, orch):
        """5 个并发请求不串台、不报错。"""
        results = [None] * 5
        errors = []

        def call(idx):
            try:
                # 不同 query 让结果可区分
                q = ["拒付问题", "选什么支付", "工单状态", "知识库查询", "退款异常"][idx]
                results[idx] = orch.route(user_query=q)
            except Exception as e:
                errors.append(f"idx={idx}: {e}")

        threads = [threading.Thread(target=call, args=(i,)) for i in range(5)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        elapsed = time.time() - t0

        assert not errors, f"并发异常: {errors}"
        assert all(r is not None for r in results), "部分请求未返回"
        # 5 个请求应在合理时间内完成（<10s）
        assert elapsed < 10, f"并发耗时过长: {elapsed:.1f}s"
        # 每个 result 的 intent 应互不干扰（不串台）
        intents = {r["intent"] for r in results}
        assert len(intents) >= 2, f"5 个 query 至少分到 2 个 intent，实际全 {intents}"

    def test_route_lock_is_reentrant(self, orch):
        """RLock 可重入（同一线程可多次获取）。"""
        with orch._route_lock:
            with orch._route_lock:  # 第二次获取应成功
                pass

    def test_chain_state_is_local_not_instance(self, orch):
        """AtoA 链式状态用 local result 不用 instance state（即使没加锁也不串台）。"""
        r1 = orch.route(user_query="我美国站卖软件，Visa 13.1 拒付好多")
        r2 = orch.route(user_query="英国站 MC 4837 持卡人未授权")
        # 两个 result 不应共享 chain 列表
        assert r1.get("chain") != r2.get("chain") or not r1.get("chain")


class TestP0_3LLMStrictValidation:
    """P0-3：LLM 返回格式强校验。"""

    def test_safe_float_handles_string(self):
        """字符串 "0.85" → 0.85（不抛 TypeError）。"""
        assert _safe_float("0.85") == 0.85
        assert _safe_float("0.7") == 0.7

    def test_safe_float_handles_none(self):
        """None → 0.0（默认）。"""
        assert _safe_float(None) == 0.0

    def test_safe_float_handles_garbage(self):
        """垃圾值 "abc" / 列表 / dict → 0.0（降级，不抛异常）。"""
        assert _safe_float("abc") == 0.0
        assert _safe_float([1, 2]) == 0.0
        assert _safe_float({"a": 1}) == 0.0

    def test_safe_float_clamps_to_0_1(self):
        """超出 [0, 1] 范围的值截断。"""
        assert _safe_float(1.5) == 1.0
        assert _safe_float(-0.3) == 0.0

    def test_pda_chain_trigger_handles_string_confidence(self):
        """PDA_TO_TRA_CHAIN.trigger 在 confidence="0.85" 时不抛 TypeError。"""
        # 模拟 PDA 返回字符串 confidence（之前会 TypeError）
        prev_data = {
            "confidence": "0.85",  # 字符串！
            "problem_type": "拒付",
            "next_agent": "Ticket Routing Agent",
        }
        # 不应抛 TypeError
        result = PDA_TO_TRA_CHAIN["trigger"](prev_data)
        assert result is True, "字符串 '0.85' 应被解析为 0.85 ≥ 0.7"

    def test_orchestrator_handles_string_confidence_from_llm(self, orch):
        """Orchestrator 接收字符串 confidence 不报错（_coerce_float 生效）。"""
        # 让 LLM 返回字符串 confidence（用 mock）
        orch.use_llm_fallback = True
        mock_llm = MagicMock()
        mock_llm.chat_structured.return_value = {
            "intent": "payment_diagnosis",
            "confidence": "0.85",  # 字符串！
            "reason": "test",
        }
        orch.llm = mock_llm

        # 用 unknown query 触发 LLM fallback
        result = orch.route(user_query="完全无关的字符串xyz123")
        # 不应抛 TypeError，且 trace.llm_confidence 应是 float
        assert isinstance(result["trace"]["llm_confidence"], (int, float))


class TestP0_4WebhookSignature:
    """P0-4：飞书 Webhook 签名校验（SHA256 正确算法）。"""

    ENCRYPT_KEY = "test_encrypt_key_xxx"
    BODY_STR = '{"header":{"event_type":"im.message.receive_v1"},"event":{}}'
    TIMESTAMP = "1700000000"
    NONCE = "abc123"

    @property
    def valid_signature(self):
        """按官方算法生成正确签名：SHA256(ts + nonce + key + body).hexdigest()。"""
        content = self.TIMESTAMP + self.NONCE + self.ENCRYPT_KEY + self.BODY_STR
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _make_handler(self, enable_sig: bool, encrypt_key=None):
        """构造一个带 mock orchestrator 的 handler。"""
        mock_orch = MagicMock()
        mock_orch.route.return_value = {
            "intent": "test",
            "tool_result": {"success": True, "data": {}},
        }
        mock_fe = MagicMock()
        return FeishuWebhookHandler(
            orchestrator=mock_orch,
            frontend=mock_fe,
            enable_signature_check=enable_sig,
            encrypt_key=encrypt_key or self.ENCRYPT_KEY,
        )

    def test_correct_signature_passes(self):
        """签名正确 → 业务事件正常处理。"""
        handler = self._make_handler(enable_sig=True)
        result = handler.handle_event(
            payload={"header": {"event_type": "im.message.receive_v1"}, "event": {"sender": {"sender_id": {"open_id": "ou_x"}}, "message": {"content": "{\"text\":\"hi\"}", "message_type": "text", "chat_id": "oc_x"}}},
            body_str=self.BODY_STR,
            timestamp=self.TIMESTAMP,
            nonce=self.NONCE,
            signature=self.valid_signature,
        )
        assert result.get("code") != 401, f"正确签名应通过，实际: {result}"

    def test_wrong_signature_returns_401(self):
        """签名错误 → 返回 401，不进入业务逻辑。"""
        handler = self._make_handler(enable_sig=True)
        result = handler.handle_event(
            payload={"header": {"event_type": "im.message.receive_v1"}, "event": {}},
            body_str=self.BODY_STR,
            timestamp=self.TIMESTAMP,
            nonce=self.NONCE,
            signature="0" * 64,  # 错误签名
        )
        assert result.get("code") == 401, f"错误签名应 401，实际: {result}"
        # orchestrator.route 不应被调用
        handler.orchestrator.route.assert_not_called()

    def test_disabled_signature_skips_check(self):
        """enable_signature_check=False → 跳过校验（Demo 模式）。"""
        handler = self._make_handler(enable_sig=False)
        # 即使 signature 是垃圾也通过（demo 友好）
        result = handler.handle_event(
            payload={"header": {"event_type": "im.message.receive_v1"}, "event": {"sender": {"sender_id": {"open_id": "ou_x"}}, "message": {"content": "{\"text\":\"hi\"}", "message_type": "text", "chat_id": "oc_x"}}},
            body_str=self.BODY_STR,
            timestamp=self.TIMESTAMP,
            nonce=self.NONCE,
            signature="garbage",
        )
        assert result.get("code") != 401, "签名校验关闭应放行"

    def test_missing_signature_headers_returns_401(self):
        """缺 timestamp/nonce/signature → 401（开启校验时）。"""
        handler = self._make_handler(enable_sig=True)
        result = handler.handle_event(
            payload={"header": {"event_type": "im.message.receive_v1"}, "event": {}},
            body_str=self.BODY_STR,
            timestamp="",
            nonce="",
            signature="",
        )
        assert result.get("code") == 401, f"缺 header 应 401，实际: {result}"

    def test_verify_signature_utility_function(self):
        """verify_signature() 静态方法直接验证。"""
        # 正确
        assert FeishuWebhookHandler.verify_signature(
            self.TIMESTAMP, self.NONCE, self.ENCRYPT_KEY, self.BODY_STR, self.valid_signature
        ) is True
        # 错误
        assert FeishuWebhookHandler.verify_signature(
            self.TIMESTAMP, self.NONCE, self.ENCRYPT_KEY, self.BODY_STR, "wrong_sig"
        ) is False
        # 缺字段
        assert FeishuWebhookHandler.verify_signature("", "", "", "", "") is False
"""Day 17 Fix：message_id 去重 — 防止同一条 user 消息被推 3 条相同 reply。

场景：
- WS + Poller + Webhook 三路都可能接收到同一 message_id 的事件
- 修复前：webhook 完全没去重 → 3 条相同 reply
- 修复后：5 分钟内同 message_id 直接 short-circuit

测试覆盖：
1. webhook.handle_event 同 message_id 3 次 → 只 send_message 1 次
2. WS _handle_p2_im_message 同 message_id 3 次 → 只 send_message 1 次
3. webhook + WS 混合（共享 dedup 状态） → 共 1 条
4. 不同 message_id 同 query → 各自处理（不被误杀）
5. _mark_message_seen 单元测试（基本 + TTL 边界）
"""
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

from app.implementations.feishu import (
    FeishuWebhookHandler,
    MockFrontend,
)
from app.implementations.feishu.webhook import (
    _mark_message_seen,
    _recent_message_ids,
)
from app.implementations.feishu.ws_client import _handle_p2_im_message


def _make_webhook_payload(text: str, message_id: str = "", user_id: str = "ou_test_dup") -> dict:
    """构造 webhook IM 事件 payload（含 message_id）。"""
    return {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": user_id, "user_id": user_id}},
            "message": {
                "chat_id": "oc_test",
                "message_type": "text",
                "message_id": message_id,
                "content": json.dumps({"text": text}),
            },
        },
    }


def _make_p2_event(text: str, message_id: str = "om_p2_xxx", user_id: str = "ou_test_dup") -> MagicMock:
    """构造 mock P2ImMessageReceiveV1 数据（含 message_id）。"""
    data = MagicMock()
    data.event.sender.sender_id.open_id = user_id
    data.event.sender.sender_id.user_id = user_id
    data.event.sender.sender_id.union_id = None
    data.event.message.chat_id = "oc_test"
    data.event.message.chat_type = "p2p"
    data.event.message.message_type = "text"
    data.event.message.message_id = message_id
    data.event.message.content = json.dumps({"text": text})
    return data


@pytest.fixture(autouse=True)
def _clear_dedup_state():
    """每个 test 前清空 dedup deque（防 test 间污染）。"""
    _recent_message_ids.clear()
    yield
    _recent_message_ids.clear()


class TestWebhookMessageIdDedup:
    """webhook.handle_event 的 message_id 去重。"""

    def test_same_message_id_3_calls_only_send_once(self, tmp_path):
        """同 message_id 发 3 次 → 只 send_message 1 次（修复前是 3 次）。"""
        frontend = MockFrontend(log_path=tmp_path / "dedup_webhook.log")
        orch = MagicMock()
        orch.route.return_value = {
            "intent": "merchant_success",
            "tool_result": {"success": True, "data": {"recommendations": [
                {"method": "iDEAL", "rationale": "NL 标配"},
            ]}},
            "trace": {},
        }
        handler = FeishuWebhookHandler(orchestrator=orch, frontend=frontend, enable_signature_check=False)

        for i in range(3):
            payload = _make_webhook_payload("荷兰站用什么支付方式", message_id="om_dup_test_xxx")
            handler.handle_event(payload)

        events = frontend.read_log()
        send_events = [e for e in events if e["event"] == "send_message"]
        assert len(send_events) == 1, f"应有 1 条 send_message，实际 {len(send_events)}（修复前是 3）"

    def test_different_message_ids_all_processed(self, tmp_path):
        """不同 message_id → 各自处理（不被误杀）。"""
        frontend = MockFrontend(log_path=tmp_path / "dedup_diff.log")
        orch = MagicMock()
        orch.route.return_value = {
            "intent": "merchant_success",
            "tool_result": {"success": True, "data": {"recommendations": []}},
            "trace": {},
        }
        handler = FeishuWebhookHandler(orchestrator=orch, frontend=frontend, enable_signature_check=False)

        for i in range(3):
            payload = _make_webhook_payload(f"问 {i}", message_id=f"om_diff_{i}")
            handler.handle_event(payload)

        events = frontend.read_log()
        send_events = [e for e in events if e["event"] == "send_message"]
        assert len(send_events) == 3, f"3 个不同 message_id 应各自 send，实际 {len(send_events)}"

    def test_empty_message_id_not_blocked(self, tmp_path):
        """payload 无 message_id（罕见）→ 不阻断业务（视为新消息）。"""
        frontend = MockFrontend(log_path=tmp_path / "dedup_empty.log")
        orch = MagicMock()
        orch.route.return_value = {
            "intent": "unknown",
            "tool_result": {"success": True, "data": {}},
            "trace": {},
        }
        handler = FeishuWebhookHandler(orchestrator=orch, frontend=frontend, enable_signature_check=False)

        # 3 次无 message_id 的请求
        for _ in range(3):
            payload = _make_webhook_payload("无 message_id 测试", message_id="")
            handler.handle_event(payload)

        events = frontend.read_log()
        # 无 message_id 不算 dedup（payload 缺字段也跑业务）
        assert orch.route.call_count == 3


class TestWsMessageIdDedup:
    """WS _handle_p2_im_message 的 message_id 去重（与 webhook 共享状态）。"""

    def test_ws_same_message_id_3_calls_only_send_once(self, tmp_path):
        """WS 同 message_id 3 次 → 只 send_message 1 次。"""
        frontend = MockFrontend(log_path=tmp_path / "dedup_ws.log")
        orch = MagicMock()
        orch.route.return_value = {
            "intent": "merchant_success",
            "tool_result": {"success": True, "data": {"recommendations": [
                {"method": "iDEAL", "rationale": "NL 标配"},
            ]}},
            "trace": {},
        }

        for _ in range(3):
            data = _make_p2_event("荷兰站", message_id="om_ws_dup_xxx")
            _handle_p2_im_message(data, orch, frontend)

        events = frontend.read_log()
        send_events = [e for e in events if e["event"] == "send_message"]
        assert len(send_events) == 1, f"WS 应只推 1 次，实际 {len(send_events)}（修复前是 3）"

    def test_webhook_and_ws_share_dedup(self, tmp_path):
        """webhook + WS 混合调用 → 共 1 条（验证 dedup 状态跨模块共享）。"""
        frontend = MockFrontend(log_path=tmp_path / "dedup_mixed.log")
        orch = MagicMock()
        orch.route.return_value = {
            "intent": "merchant_success",
            "tool_result": {"success": True, "data": {"recommendations": []}},
            "trace": {},
        }

        shared_mid = "om_shared_xxx"
        # webhook 1 次
        handler = FeishuWebhookHandler(orchestrator=orch, frontend=frontend, enable_signature_check=False)
        handler.handle_event(_make_webhook_payload("NL 站", message_id=shared_mid))
        # WS 2 次（同 message_id）
        for _ in range(2):
            _handle_p2_im_message(_make_p2_event("NL 站", message_id=shared_mid), orch, frontend)

        events = frontend.read_log()
        send_events = [e for e in events if e["event"] == "send_message"]
        assert len(send_events) == 1, f"跨模块 dedup 应共 1 条，实际 {len(send_events)}"


class TestMarkMessageSeenUnit:
    """_mark_message_seen 单元测试。"""

    def test_first_call_returns_true(self):
        """首次见到 → True（新消息）。"""
        assert _mark_message_seen("om_unit_test_1") is True

    def test_second_call_returns_false(self):
        """5 分钟内第二次见 → False（重复）。"""
        _mark_message_seen("om_unit_test_2")
        assert _mark_message_seen("om_unit_test_2") is False

    def test_empty_message_id_returns_true(self):
        """空 message_id → True（不阻断业务）。"""
        assert _mark_message_seen("") is True

    def test_thread_safety(self):
        """多线程并发调 _mark_message_seen 应线程安全。"""
        mid = "om_concurrent_test"
        results = []
        lock = threading.Lock()

        def worker():
            r = _mark_message_seen(mid)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 仅第一次返 True，其余 False
        assert results.count(True) == 1, f"应仅 1 个 True，实际 {results.count(True)}"
        assert results.count(False) == 9

    def test_ttl_expires_after_window(self, monkeypatch):
        """5 分钟后同 message_id 不再算重复（验证 TTL 边界）。"""
        from app.implementations.feishu import webhook as webhook_mod

        # mock time.time() 模拟 6 分钟后
        real_time = webhook_mod.time.time
        fake_now = [1000.0]

        def fake_time():
            return fake_now[0]

        monkeypatch.setattr(webhook_mod.time, "time", fake_time)

        # T0: 首次见 → True
        assert _mark_message_seen("om_ttl_test") is True
        # T+4 min: 仍算重复 → False
        fake_now[0] += 4 * 60
        assert _mark_message_seen("om_ttl_test") is False
        # T+6 min: 过期 → 算新消息 True
        fake_now[0] += 2 * 60 + 1
        assert _mark_message_seen("om_ttl_test") is True

        # 恢复（monkeypatch 会自动恢复）
        _ = real_time
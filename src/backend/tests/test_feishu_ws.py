"""Feishu 长连接（WebSocket）事件分发测试（SOP-FEISHU-003 · Day 9）。

覆盖：
- _handle_p2_im_message：解析 event → 提取 user_id/text → 路由 → 推送
- 异常兜底（不抛 raw exception）
- start_feishu_ws_in_background：lark-oapi 缺失时优雅降级
- should_start_ws_client：凭证判断逻辑
- format_reply 公开方法：webhook + ws 共用

详见 docs/sop/SOP-FEISHU.md §5（Day 9 长连接主路径）
"""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.implementations.feishu import (
    FeishuWebhookHandler,
    MockFrontend,
    start_feishu_ws_in_background,
    should_start_ws_client,
)
from app.implementations.feishu.ws_client import _handle_p2_im_message


# === Fixtures ===

@pytest.fixture
def mock_frontend(tmp_path):
    """MockFrontend + 隔离日志路径（避免测试间污染）。"""
    return MockFrontend(log_path=tmp_path / "feishu_ws_test.log")


@pytest.fixture
def mock_orchestrator():
    """Mock Orchestrator（避免外部依赖）。"""
    orch = MagicMock()
    orch.route.return_value = {
        "intent": "payment_diagnosis",
        "tool_result": {
            "success": True,
            "data": {
                "problem_type": "BR Visa 拒付",
                "root_causes": ["3DS 未触发"],
                "recommended_actions": ["联系发卡行"],
                "confidence": 0.85,
            },
        },
        "trace": {},
    }
    return orch


def _make_p2_event(text: str, user_id: str = "ou_test_user", chat_id: str = "oc_test") -> MagicMock:
    """构造 mock P2ImMessageReceiveV1 数据。"""
    data = MagicMock()
    data.event.sender.sender_id.open_id = user_id
    data.event.sender.sender_id.user_id = user_id
    data.event.sender.sender_id.union_id = None
    data.event.message.chat_id = chat_id
    data.event.message.chat_type = "p2p"
    data.event.message.message_type = "text"
    data.event.message.content = json.dumps({"text": text})
    return data


# === _handle_p2_im_message 测试 ===

class TestHandleP2ImMessage:
    """WS 事件处理器单元测试。"""

    def test_basic_text_message_routed_and_replied(self, mock_orchestrator, mock_frontend):
        """基本文本消息 → 路由 → 推送 reply。"""
        data = _make_p2_event("BR Visa 拒付 ERR_X_001")

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        # Orchestrator 被调用（user_query + context）
        mock_orchestrator.route.assert_called_once()
        call_args = mock_orchestrator.route.call_args
        assert call_args.kwargs["user_query"] == "BR Visa 拒付 ERR_X_001"
        assert call_args.kwargs["merchant_context"]["user_id"] == "ou_test_user"
        assert call_args.kwargs["merchant_context"]["chat_id"] == "oc_test"

        # Frontend.send_message 被调用（reply 推送）
        events = mock_frontend.read_log()
        send_events = [e for e in events if e["event"] == "send_message"]
        assert len(send_events) == 1
        assert send_events[0]["user_id"] == "ou_test_user"
        assert "第一步" in send_events[0]["message"]  # Day 17 v2 解决方案式输出

    def test_fallback_to_user_id_when_no_open_id(self, mock_orchestrator, mock_frontend):
        """无 open_id 时用 user_id（兼容）。"""
        data = _make_p2_event("test")
        data.event.sender.sender_id.open_id = None
        data.event.sender.sender_id.user_id = "u_fallback"

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        call_args = mock_orchestrator.route.call_args
        assert call_args.kwargs["merchant_context"]["user_id"] == "u_fallback"

    def test_non_text_message_skipped(self, mock_orchestrator, mock_frontend):
        """非 text 消息类型跳过（PoC 暂不处理 image/file 等）。"""
        data = _make_p2_event("{}")
        data.event.message.message_type = "image"

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_not_called()
        # Frontend 也不应该收到 send_message
        events = mock_frontend.read_log()
        assert not any(e["event"] == "send_message" for e in events)

    def test_missing_user_id_skipped(self, mock_orchestrator, mock_frontend):
        """缺 user_id → 跳过（飞书重推不友好）。"""
        data = _make_p2_event("test")
        data.event.sender.sender_id.open_id = None
        data.event.sender.sender_id.user_id = None

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_not_called()

    def test_empty_text_skipped(self, mock_orchestrator, mock_frontend):
        """空文本 → 跳过。"""
        data = _make_p2_event("   ")
        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)
        mock_orchestrator.route.assert_not_called()

    def test_malformed_json_content_handled(self, mock_orchestrator, mock_frontend):
        """content 不是 JSON 时 → 兜底用原始字符串。"""
        data = _make_p2_event("plain text")
        data.event.message.content = "not_json_xxx"  # 不是 JSON

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        # 应该用原始字符串作为 query
        call_args = mock_orchestrator.route.call_args
        assert call_args.kwargs["user_query"] == "not_json_xxx"

    def test_orchestrator_exception_swallowed(self, mock_frontend):
        """Orchestrator 抛异常 → 内部兜底（不抛 raw exception 触发飞书重推）。"""
        mock_orch = MagicMock()
        mock_orch.route.side_effect = RuntimeError("mock orch crash")
        data = _make_p2_event("test")

        # 不应抛异常
        _handle_p2_im_message(data, mock_orch, mock_frontend)

        # Frontend 也不应收到 send_message（避免误导用户）
        events = mock_frontend.read_log()
        assert not any(e["event"] == "send_message" for e in events)

    def test_frontend_send_exception_swallowed(self, mock_orchestrator):
        """Frontend.send_message 抛异常 → 内部兜底。"""
        mock_front = MagicMock()
        mock_front.send_message.side_effect = RuntimeError("mock frontend crash")
        data = _make_p2_event("test")

        # 不应抛异常
        _handle_p2_im_message(data, mock_orchestrator, mock_front)


# === Day 17 v3: 群聊 @ 机器人过滤测试 ===

def _make_group_event(text: str, mentions: list = None, chat_id: str = "oc_group_test") -> MagicMock:
    """构造 mock 群聊事件（含 mentions）。"""
    data = _make_p2_event(text)
    data.event.message.chat_type = "group"
    data.event.message.chat_id = chat_id
    if mentions is not None:
        data.event.message.mentions = mentions
    else:
        data.event.message.mentions = []
    return data


def _bot_mention(bot_open_id: str = "ou_bot_xxx") -> MagicMock:
    """构造一个 mention 对象（机器人 @）。"""
    m = MagicMock()
    m.id.open_id = bot_open_id
    m.id.user_id = None
    m.id.union_id = None
    return m


def _user_mention(user_open_id: str = "ou_other_user") -> MagicMock:
    """构造一个 mention 对象（普通用户 @）。"""
    m = MagicMock()
    m.id.open_id = user_open_id
    return m


class TestGroupChatAtMentionFilter:
    """群聊消息必须 @ 机器人才响应（飞书规则，避免机器人刷屏）。"""

    def test_p2p_skips_mention_check(self, mock_orchestrator, mock_frontend, monkeypatch):
        """p2p 单聊直接处理，不管 mentions。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_p2_event("订单问题")  # chat_type=p2p by default

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_called_once()
        call_args = mock_orchestrator.route.call_args
        assert call_args.kwargs["user_query"] == "订单问题"

    def test_group_with_bot_mention_processed(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """群聊 + @ 机器人 → 处理。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_group_event(
            "@_user_1 帮我看看拒付",
            mentions=[_bot_mention("ou_bot_xxx")],
        )

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_called_once()

    def test_group_without_mention_skipped(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """群聊 + 没 @ 机器人 → 跳过（不调 orchestrator）。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_group_event(
            "拒付好多啊",
            mentions=[_user_mention("ou_other_user")],  # @ 别人不 @ 机器人
        )

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_not_called()
        events = mock_frontend.read_log()
        assert not any(e["event"] == "send_message" for e in events)

    def test_group_no_mentions_skipped(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """群聊 + mentions 为空（没 @ 任何人）→ 跳过。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_group_event("随便聊聊", mentions=[])

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_not_called()

    def test_group_bot_open_id_not_configured_skipped(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """未配 FEISHU_BOT_OPEN_ID → 群聊一律不响应（fail-safe）。"""
        monkeypatch.delenv("FEISHU_BOT_OPEN_ID", raising=False)
        data = _make_group_event(
            "@_user_1 帮我看",
            mentions=[_bot_mention("ou_bot_xxx")],
        )

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        # bot_open_id 未配 → 保守不响应（避免错误响应刷屏）
        mock_orchestrator.route.assert_not_called()

    def test_mention_tokens_stripped_from_text(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """群聊文本里的 @_user_NNN 标记被剥离，不污染业务 query。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_group_event(
            "@_user_1 @_user_2 帮我看拒付订单",
            mentions=[_bot_mention("ou_bot_xxx")],
        )

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        if mock_orchestrator.route.called:
            call_args = mock_orchestrator.route.call_args
            assert call_args.kwargs["user_query"] == "帮我看拒付订单"
            assert "@_user_1" not in call_args.kwargs["user_query"]
            assert "@_user_2" not in call_args.kwargs["user_query"]

    def test_mention_only_no_text_skipped(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """群聊只发 '@_user_1'（没实际内容）→ 剥离后空 → 跳过。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_group_event(
            "@_user_1 ",
            mentions=[_bot_mention("ou_bot_xxx")],
        )

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_not_called()

    def test_mention_dict_format_supported(
        self, mock_orchestrator, mock_frontend, monkeypatch
    ):
        """mentions 是 dict 列表（Poller/Polling 路径兼容）→ 也支持。"""
        monkeypatch.setenv("FEISHU_BOT_OPEN_ID", "ou_bot_xxx")
        data = _make_group_event(
            "汇率问题",
            mentions=[{"id": {"open_id": "ou_bot_xxx"}, "key": "@_user_1"}],
        )

        _handle_p2_im_message(data, mock_orchestrator, mock_frontend)

        mock_orchestrator.route.assert_called_once()


class TestBotMentionHelpers:
    """_is_bot_mentioned / _strip_mention_tokens 单元测试。"""

    def test_is_bot_mentioned_sdk_objects(self):
        """SDK 对象 mentions → 匹配 bot open_id。"""
        from app.implementations.feishu.ws_client import _is_bot_mentioned

        m1 = MagicMock()
        m1.id.open_id = "ou_other"
        m2 = MagicMock()
        m2.id.open_id = "ou_bot"
        assert _is_bot_mentioned([m1, m2], "ou_bot") is True

    def test_is_bot_mentioned_dict_nested(self):
        """dict mentions（id.open_id 嵌套）→ 匹配。"""
        from app.implementations.feishu.ws_client import _is_bot_mentioned

        mentions = [{"id": {"open_id": "ou_bot_xxx"}}]
        assert _is_bot_mentioned(mentions, "ou_bot_xxx") is True

    def test_is_bot_mentioned_empty_returns_false(self):
        """mentions 空 / bot_open_id 空 → False。"""
        from app.implementations.feishu.ws_client import _is_bot_mentioned

        assert _is_bot_mentioned([], "ou_bot") is False
        assert _is_bot_mentioned(None, "") is False
        assert _is_bot_mentioned(None, "ou_bot") is False

    def test_strip_mention_tokens(self):
        """_strip_mention_tokens 去掉 @_user_NNN。"""
        from app.implementations.feishu.ws_client import _strip_mention_tokens

        assert _strip_mention_tokens("@_user_1 帮我看") == "帮我看"
        assert _strip_mention_tokens("@_user_1 @_user_2 双 @") == "双 @"
        assert _strip_mention_tokens("普通文本") == "普通文本"
        assert _strip_mention_tokens("") == ""


# === start_feishu_ws_in_background 测试 ===

class TestStartFeishuWsInBackground:
    """后台线程启动测试。"""

    def test_returns_thread_when_lark_oapi_available(self):
        """lark-oapi 装好 → 返回 Thread 实例（worker 内部懒加载）。"""
        thread = start_feishu_ws_in_background(
            app_id="cli_test",
            app_secret="secret_test",
            orchestrator=MagicMock(),
            frontend=MockFrontend(),
        )
        # 线程已启动（daemon=True）
        assert isinstance(thread, threading.Thread)
        assert thread.daemon is True
        assert thread.name == "feishu-ws-client"

    def test_thread_does_not_block_caller(self):
        """start_feishu_ws_in_background 不阻塞调用方（同步返回）。"""
        import time
        start = time.time()
        thread = start_feishu_ws_in_background(
            app_id="cli_test",
            app_secret="secret_test",
            orchestrator=MagicMock(),
            frontend=MockFrontend(),
        )
        elapsed = time.time() - start
        # 函数本身应 < 0.5s 返回（worker 线程启动时间）
        assert elapsed < 0.5
        assert thread is not None


# === should_start_ws_client 测试 ===

class TestShouldStartWsClient:
    """凭证判断逻辑。"""

    def test_no_credentials_returns_false(self, monkeypatch):
        """无凭证 → 不启 WS。"""
        monkeypatch.delenv("FEISHU_APP_ID", raising=False)
        monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
        monkeypatch.delenv("FEISHU_FORCE_MOCK", raising=False)
        assert should_start_ws_client() is False

    def test_with_credentials_returns_true(self, monkeypatch):
        """凭证齐全 → 启 WS。"""
        monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
        monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
        monkeypatch.delenv("FEISHU_FORCE_MOCK", raising=False)
        assert should_start_ws_client() is True

    def test_force_mock_disables_ws(self, monkeypatch):
        """FEISHU_FORCE_MOCK=1 → 即使有凭证也不启。"""
        monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
        monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
        monkeypatch.setenv("FEISHU_FORCE_MOCK", "1")
        assert should_start_ws_client() is False

    def test_only_app_id_returns_false(self, monkeypatch):
        """仅 App ID 缺 Secret → 不启。"""
        monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
        monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
        assert should_start_ws_client() is False


# === format_reply 公开方法测试（Day 9 重构后） ===

class TestFormatReplyPublic:
    """format_reply 已从 _format_reply 提为 @staticmethod，webhook + ws 共用。"""

    def test_format_reply_is_static_method(self):
        """format_reply 是 staticmethod（不依赖 self）。"""
        # 验证不需要实例化就能调用
        result = {"intent": "unknown"}
        reply = FeishuWebhookHandler.format_reply(result)
        assert isinstance(reply, str)

    def test_format_reply_handles_all_intents(self):
        """覆盖 4 intent 路径。"""
        for intent in ["merchant_success", "payment_diagnosis", "ticket_routing", "knowledge_evolution", "unknown_fallback_to_msa", "unknown"]:
            result = {
                "intent": intent,
                "tool_result": {"success": True, "data": {}},
                "trace": {},
            }
            reply = FeishuWebhookHandler.format_reply(result)
            assert isinstance(reply, str)
            assert len(reply) > 0

    def test_format_reply_error_path(self):
        """tool_result.success=False → 友好错误提示。"""
        result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": False, "error_message": "服务暂时不可用"},
            "trace": {},
        }
        reply = FeishuWebhookHandler.format_reply(result)
        assert "失败" in reply or "不可用" in reply
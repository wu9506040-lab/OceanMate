"""Feishu SOP 测试 - Day 6-7 SOP-FEISHU-001/002。

覆盖：
- SOP-FEISHU-001-A: URL 验证通过
- SOP-FEISHU-001-B: 完整消息流（mock 智能伙伴发"BR Visa 拒付" → Orchestrator → 回复）
- SOP-FEISHU-002-A: MockFrontend 5 方法 + 日志写入
- SOP-FEISHU-002-B: 工厂函数无凭证 → 自动 Mock
- SOP-FEISHU-002-C: 真实 FeishuFrontend API 失败 → 友好降级（返回 False 不抛）
- SOP-FEISHU-002-D: webhook 事件缺少 user_id → 友好降级

详见 docs/sop/SOP-FEISHU.md。
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.implementations.feishu import (
    MockFrontend,
    FeishuFrontend,
    get_feishu_frontend,
    FeishuWebhookHandler,
)
from app.implementations.feishu.api import FeishuOpenAPI, FeishuAPIError
from app.agents.orchestrator import Orchestrator, create_default_orchestrator


# === Fixtures ===

@pytest.fixture
def tmp_log_path(tmp_path):
    """临时 Mock 日志路径（隔离测试）。"""
    return tmp_path / "feishu_mock_test.log"


@pytest.fixture
def mock_frontend(tmp_log_path):
    """MockFrontend 实例（带临时日志）。"""
    return MockFrontend(log_path=tmp_log_path)


@pytest.fixture
def mock_orchestrator():
    """无 DB 的 Orchestrator（仅 mock 工厂）。"""
    orch = Orchestrator()
    # 注册 Mock 工具（避免外部依赖）
    return orch


@pytest.fixture
def full_orchestrator(tmp_db_path, tmp_path):
    """完整 Orchestrator（4 Tool + temp DB + temp Chroma）。"""
    chroma_path = tmp_path / "chroma"
    chroma_path.mkdir()
    return create_default_orchestrator(
        db_path=str(tmp_db_path),
        chroma_path=str(chroma_path),
        auto_init_db=True,
    )


@pytest.fixture
def webhook_handler(mock_orchestrator, mock_frontend):
    """FeishuWebhookHandler 实例。"""
    return FeishuWebhookHandler(
        orchestrator=mock_orchestrator,
        frontend=mock_frontend,
    )


@pytest.fixture
def full_webhook_handler(full_orchestrator, mock_frontend):
    """完整 WEBHOOK handler（4 Tool + Mock Frontend）。"""
    return FeishuWebhookHandler(
        orchestrator=full_orchestrator,
        frontend=mock_frontend,
    )


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清空 env 中的 FEISHU_* 变量（避免测试间污染）。"""
    for key in ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_FORCE_MOCK"]:
        monkeypatch.delenv(key, raising=False)


# === SOP-FEISHU-001-A: URL 验证 ===

class TestURLVerification:
    """SOP-FEISHU-001-A：飞书智能伙伴 URL 验证。"""

    def test_url_verification_returns_challenge(self, webhook_handler):
        payload = {
            "type": "url_verification",
            "challenge": "abc123FeishuChallenge",
            "token": "some_token",
        }
        result = webhook_handler.handle_event(payload)
        assert result == {"challenge": "abc123FeishuChallenge"}

    def test_url_verification_without_token_field(self, webhook_handler):
        """URL 验证也可以只带 challenge（无 type）。"""
        payload = {"challenge": "xxx"}
        result = webhook_handler.handle_event(payload)
        assert result["challenge"] == "xxx"


# === SOP-FEISHU-001-B: 完整消息流 ===

class TestMessageFlow:
    """SOP-FEISHU-001-B：商户提问 → Webhook → Orchestrator → 回复。"""

    def _make_message_event(self, text: str, user_id: str = "ou_demo_user") -> dict:
        """构造飞书 im.message.receive_v1 事件 payload。"""
        return {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1",
                "app_id": "cli_demo",
                "tenant_key": "demo_tenant",
                "create_time": "1234567890",
            },
            "event": {
                "sender": {
                    "sender_id": {"open_id": user_id, "user_id": "u_xxx"},
                    "sender_type": "user",
                },
                "message": {
                    "message_id": "om_xxx",
                    "chat_id": "oc_xxx",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": json.dumps({"text": text}),
                },
            },
        }

    def test_merchant_query_to_reply(self, full_webhook_handler, mock_frontend):
        """商户提问"BR Visa 拒付" → 4 Tool 路由 → 回复推送。"""
        payload = self._make_message_event("BR Visa 拒付 ERR_X_001")

        result = full_webhook_handler.handle_event(payload)

        # 1. Webhook 返回飞书期望的 success
        assert result == {"code": 0, "msg": "success"}

        # 2. MockFrontend 写入了 send_message（reply 推送）
        events = mock_frontend.read_log()
        send_events = [e for e in events if e["event"] == "send_message"]
        assert len(send_events) >= 1
        # 至少 1 条消息回复给 user_id
        assert any(e["user_id"] == "ou_demo_user" for e in send_events)
        # 消息内容包含关键词（不同 intent 关键词不同）
        all_text = " ".join(e.get("message", "") for e in send_events)
        assert any(
            kw in all_text
            for kw in ["BR", "Visa", "拒付", "诊断", "Diagnose", "支付", "推荐", "FAQ", "工单", "📋", "🔍", "✅"]
        ), f"回复内容应包含业务关键词: {all_text[:200]}"

    def test_empty_query_friendly_degradation(self, full_webhook_handler, mock_frontend):
        """空白文本 → 友好降级（不挂）。"""
        payload = self._make_message_event("   ")
        result = full_webhook_handler.handle_event(payload)
        # 空白 → 不路由，但仍 ok
        assert result["code"] == 0


# === SOP-FEISHU-002: 4 逆向场景 ===

class TestMockFrontend:
    """SOP-FEISHU-002-A：MockFrontend 5 方法 + 日志（最简版本）。"""

    def test_send_message_writes_log(self, mock_frontend, tmp_log_path):
        ok = mock_frontend.send_message("user_1", "BR Visa 拒付诊断完成")
        assert ok is True
        log = mock_frontend.read_log()
        assert len(log) == 1
        assert log[0]["event"] == "send_message"
        assert log[0]["user_id"] == "user_1"
        assert log[0]["message"] == "BR Visa 拒付诊断完成"
        assert log[0]["frontend"] == "mock"

    def test_send_private_writes_log(self, mock_frontend):
        assert mock_frontend.send_private("cs_1", "内部交接简报") is True
        log = mock_frontend.read_log()
        assert log[0]["event"] == "send_private"

    def test_create_group_returns_fake_id(self, mock_frontend):
        gid = mock_frontend.create_group(["user_1", "user_2"], name="BR Visa 工单")
        assert gid.startswith("mock_group_")
        log = mock_frontend.read_log()
        assert log[0]["event"] == "create_group"
        assert log[0]["group_id"] == gid
        assert log[0]["members"] == ["user_1", "user_2"]

    def test_add_group_member_writes_log(self, mock_frontend):
        ok = mock_frontend.add_group_member("mock_group_abc", "user_3")
        assert ok is True
        log = mock_frontend.read_log()
        assert log[0]["event"] == "add_group_member"

    def test_sync_dashboard_data_writes_log(self, mock_frontend):
        data = {"metric": "ticket_count", "value": 42, "timestamp": "2026-08-04"}
        ok = mock_frontend.sync_dashboard_data(data)
        assert ok is True
        log = mock_frontend.read_log()
        assert log[0]["event"] == "sync_dashboard_data"
        assert log[0]["data"] == data


class TestFactoryFallback:
    """SOP-FEISHU-002-B：工厂函数无凭证 → 自动 Mock。"""

    def test_no_credentials_returns_mock(self):
        """无 FEISHU_APP_ID / FEISHU_APP_SECRET → MockFrontend。"""
        frontend = get_feishu_frontend()
        assert isinstance(frontend, MockFrontend)

    def test_force_mock_returns_mock(self):
        """force_mock=True → MockFrontend（即使有凭证）。"""
        frontend = get_feishu_frontend(
            app_id="cli_xxx",
            app_secret="secret_xxx",
            force_mock=True,
        )
        assert isinstance(frontend, MockFrontend)

    def test_force_mock_env_var(self, monkeypatch):
        """env FEISHU_FORCE_MOCK=1 → MockFrontend。"""
        monkeypatch.setenv("FEISHU_FORCE_MOCK", "1")
        frontend = get_feishu_frontend()
        assert isinstance(frontend, MockFrontend)

    def test_with_credentials_returns_real(self):
        """有完整凭证 → FeishuFrontend（不 mock）。"""
        frontend = get_feishu_frontend(
            app_id="cli_xxx",
            app_secret="secret_xxx",
        )
        assert isinstance(frontend, FeishuFrontend)


class TestFeishuFrontendDegradation:
    """SOP-FEISHU-002-C：真实 FeishuFrontend API 失败 → 友好降级（不抛）。"""

    def test_send_message_api_failure_returns_false(self):
        """Mock API 抛错 → FeishuFrontend 返回 False（不抛 raw exception）。"""
        frontend = FeishuFrontend(app_id="cli_xxx", app_secret="secret")
        # 用 mock 替换 api.send_message 抛 FeishuAPIError
        with patch.object(
            frontend.api, "send_message",
            side_effect=FeishuAPIError(code=99991, msg="mock 服务挂了", endpoint="im.send_message"),
        ):
            ok = frontend.send_message("ou_xxx", "test")
            assert ok is False

    def test_create_group_api_failure_returns_empty(self):
        """Mock API 抛错 → create_group 返回空串。"""
        frontend = FeishuFrontend(app_id="cli_xxx", app_secret="secret")
        with patch.object(
            frontend.api, "create_group",
            side_effect=FeishuAPIError(code=99991, msg="mock 服务挂了", endpoint="im.create_group"),
        ):
            gid = frontend.create_group(["ou_xxx"], "BR 工单")
            assert gid == ""

    def test_sync_dashboard_data_no_table_returns_false(self):
        """多维表格未配置 → 友好降级。"""
        frontend = FeishuFrontend(app_id="cli_xxx", app_secret="secret")
        # btable_app_token / btable_table_id 默认空
        ok = frontend.sync_dashboard_data({"metric": "ticket_count", "value": 1})
        assert ok is False


class TestWebhookFriendlyDegradation:
    """SOP-FEISHU-002-D：webhook 4 逆向场景（事件层友好降级）。"""

    def test_missing_user_id_returns_ok(self, webhook_handler):
        """事件缺少 user_id → 返回 ok（不挂飞书）。"""
        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {}},  # 缺 open_id
                "message": {
                    "message_type": "text",
                    "content": json.dumps({"text": "BR Visa 拒付"}),
                },
            },
        }
        result = webhook_handler.handle_event(payload)
        # 永远返回 ok（不让飞书重试）
        assert result["code"] == 0

    def test_missing_text_returns_ok(self, webhook_handler):
        """事件缺 text → 返回 ok。"""
        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_xxx"}},
                "message": {
                    "message_type": "text",
                    "content": json.dumps({"text": ""}),  # 空文本
                },
            },
        }
        result = webhook_handler.handle_event(payload)
        assert result["code"] == 0

    def test_invalid_event_type_returns_ok(self, webhook_handler):
        """非 chat 事件 → 返回 ok（其它事件类型暂不处理）。"""
        payload = {
            "header": {"event_type": "im.message.reaction.created_v1"},
            "event": {},
        }
        result = webhook_handler.handle_event(payload)
        assert result["code"] == 0

    def test_orchestrator_exception_returns_ok(self, mock_frontend):
        """Orchestrator 抛异常 → 仍返回 ok（不曝光异常）。"""
        orch = MagicMock()
        orch.route.side_effect = RuntimeError("mock 异常")
        handler = FeishuWebhookHandler(orchestrator=orch, frontend=mock_frontend)

        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_xxx"}},
                "message": {
                    "message_type": "text",
                    "content": json.dumps({"text": "BR Visa 拒付"}),
                },
            },
        }
        result = handler.handle_event(payload)
        assert result["code"] == 0
        # 友好降级提示已写入 MockFrontend
        events = mock_frontend.read_log()
        assert any("抱歉" in e.get("message", "") for e in events)

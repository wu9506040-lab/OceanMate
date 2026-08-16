"""飞书多维表格 → 后端 反向同步测试 — Day 18 P2-final。

覆盖：
- FeishuFrontend.fetch_review_decisions：拉决策列表（mock api.list_records）
- FeishuFrontend.get_record_by_id：按 record_id 查单条
- FeishuFrontend 凭证缺失 → 返回 [] / {} 不报错
- /admin/sync-bit endpoint：手动同步逻辑
- /feishu/bitable/webhook：单条增量同步逻辑
- MockFrontend.fetch_review_decisions / get_record_by_id 也支持
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.implementations.feishu.frontend import FeishuFrontend
from app.implementations.feishu.mock_frontend import MockFrontend


# === FeishuFrontend 反向读取 ===

class TestFeishuFrontendFetchReviewDecisions:
    """FeishuFrontend.fetch_review_decisions 必须正确调底层 API。"""

    def test_fetch_without_filter_calls_list_records(self):
        """无 decision_filter → list_records(filter=None)。"""
        fe = FeishuFrontend(
            app_id="cli_test", app_secret="secret_test",
            btable_app_token="bascnxxx",
            btable_review_decisions_table_id="tblEcAoxxx",
        )
        fe.api = MagicMock()
        fe.api.list_records.return_value = [
            {"record_id": "rec1", "fields": {"案例ID": "case_a", "决策": "待审核"}},
            {"record_id": "rec2", "fields": {"案例ID": "case_b", "决策": "已通过"}},
        ]

        items = fe.fetch_review_decisions()
        assert len(items) == 2
        # 必须传 None（不是空字符串过滤）
        call_args = fe.api.list_records.call_args
        assert call_args.kwargs.get("filter_expr") is None or call_args.kwargs.get("filter") is None

    def test_fetch_with_decision_filter(self):
        """decision_filter='已通过' → filter_expr 正确转义。"""
        fe = FeishuFrontend(
            app_id="cli_test", app_secret="secret_test",
            btable_app_token="bascnxxx",
            btable_review_decisions_table_id="tblEcAoxxx",
        )
        fe.api = MagicMock()
        fe.api.list_records.return_value = []

        fe.fetch_review_decisions(decision_filter="已通过")
        call_args = fe.api.list_records.call_args
        assert 'CurrentValue.[决策]="已通过"' in str(call_args)

    def test_fetch_returns_empty_when_no_credentials(self):
        """凭证缺失 → 返回 []，不调 API。"""
        fe = FeishuFrontend(
            app_id="", app_secret="",
        )  # 不传 token
        fe.api = MagicMock()
        items = fe.fetch_review_decisions()
        assert items == []
        # 不调底层 API
        fe.api.list_records.assert_not_called()

    def test_fetch_handles_api_error(self):
        """FeishuAPIError → 返回 []，不抛异常。"""
        from app.implementations.feishu.api import FeishuAPIError
        fe = FeishuFrontend(
            app_id="cli_test", app_secret="secret_test",
            btable_app_token="bascnxxx",
            btable_review_decisions_table_id="tblEcAoxxx",
        )
        fe.api = MagicMock()
        fe.api.list_records.side_effect = FeishuAPIError(code=999, msg="rate limit", endpoint="bitable.list_records")
        items = fe.fetch_review_decisions()
        assert items == []


class TestFeishuFrontendGetRecordById:
    """FeishuFrontend.get_record_by_id 单条查询。"""

    def test_get_record_calls_api(self):
        """按 record_id 查 → 调 api.get_record。"""
        fe = FeishuFrontend(
            app_id="cli_test", app_secret="secret_test",
            btable_app_token="bascnxxx",
            btable_review_decisions_table_id="tblEcAoxxx",
        )
        fe.api = MagicMock()
        fe.api.get_record.return_value = {
            "record": {
                "record_id": "rec1",
                "fields": {"案例ID": "case_a", "决策": "已通过"},
            }
        }

        record = fe.get_record_by_id("rec1")
        assert record["record"]["record_id"] == "rec1"
        call_args = fe.api.get_record.call_args
        assert call_args.kwargs.get("record_id") == "rec1" or call_args.args[3] == "rec1"

    def test_get_record_returns_empty_on_no_credentials(self):
        """凭证缺失 → 返回 {}。"""
        fe = FeishuFrontend(
            app_id="", app_secret="",
        )
        fe.api = MagicMock()
        record = fe.get_record_by_id("rec1")
        assert record == {}


# === MockFrontend 兜底 ===

class TestMockFrontendReverseSync:
    """MockFrontend 也要支持 fetch / get_record（录屏 mock 模式）。"""

    def test_fetch_returns_empty_list(self):
        """Mock fetch → 返 []（不调真实 API）。"""
        mock = MockFrontend()
        items = mock.fetch_review_decisions()
        assert items == []

    def test_get_record_returns_empty_dict(self):
        """Mock get_record → 返 {}。"""
        mock = MockFrontend()
        record = mock.get_record_by_id("rec1")
        assert record == {}


# === /admin/sync-bit endpoint 集成测试 ===

class TestAdminSyncBitEndpoint:
    """/admin/sync-bit 必须正确调 KEA approve/reject。"""

    @pytest.fixture
    def client_with_mock(self):
        """构造最小 main app（mock frontend + orchestrator）。"""
        from app.main import app
        # 替换 _frontend / _orchestrator 为 mock
        import app.main as main_mod
        from unittest.mock import MagicMock

        mock_fe = MagicMock()
        mock_fe.fetch_review_decisions = MagicMock(return_value=[
            {"record_id": "rec1", "fields": {"案例ID": "case_x", "决策": "已通过", "审核人": "lead"}},
            {"record_id": "rec2", "fields": {"案例ID": "case_y", "决策": "已拒绝", "审核人": "lead", "备注": "证据不足"}},
            {"record_id": "rec3", "fields": {"案例ID": "case_z", "决策": "待审核"}},  # 应跳过
        ])
        mock_orch = MagicMock()
        mock_orch.registry.safe_execute = MagicMock(return_value={"success": True, "data": {"approved": True}})
        main_mod._frontend = mock_fe
        main_mod._orchestrator = mock_orch

        return TestClient(app)

    def test_sync_processes_approved_and_rejected(self, client_with_mock):
        """/admin/sync-bit → approved/rejected 都调 KEA，pending 跳过。"""
        resp = client_with_mock.post("/admin/sync-bit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["summary"]["synced_count"] == 2
        assert data["summary"]["skipped_count"] == 1

        # 调了 2 次 KEA
        import app.main as main_mod
        assert main_mod._orchestrator.registry.safe_execute.call_count == 2

    def test_sync_handles_no_frontend(self):
        """_frontend=None → 返回 success=False, error 友好。"""
        from app.main import app
        import app.main as main_mod
        main_mod._frontend = None

        client = TestClient(app)
        resp = client.post("/admin/sync-bit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "frontend" in data.get("error", "").lower() or "未配置" in data.get("error", "")


# === /feishu/bitable/webhook endpoint 集成测试 ===

class TestFeishuBitableWebhookEndpoint:
    """/feishu/bitable/webhook 接收飞书事件 → 调 KEA。"""

    def test_webhook_routes_to_approve(self):
        """payload 含 record_id + 决策=已通过 → 调 approve_case。"""
        from app.main import app
        import app.main as main_mod
        from unittest.mock import MagicMock

        mock_fe = MagicMock()
        mock_fe.get_record_by_id = MagicMock(return_value={
            "record": {
                "record_id": "rec1",
                "fields": {"案例ID": "case_webhook_001", "决策": "已通过", "审核人": "lead"},
            }
        })
        mock_orch = MagicMock()
        mock_orch.registry.safe_execute = MagicMock(return_value={"success": True})
        main_mod._frontend = mock_fe
        main_mod._orchestrator = mock_orch

        client = TestClient(app)
        payload = {"event": {"record_id": "rec1"}, "schema": "bitable.record.changed_v1"}
        resp = client.post("/feishu/bitable/webhook", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["case_id"] == "case_webhook_001"

        # 调了 KEA approve_case
        call_args = main_mod._orchestrator.registry.safe_execute.call_args
        assert call_args.args[1]["intent"] == "approve_case"

    def test_webhook_routes_to_reject(self):
        """payload 含 record_id + 决策=已拒绝 → 调 reject_case。"""
        from app.main import app
        import app.main as main_mod
        from unittest.mock import MagicMock

        mock_fe = MagicMock()
        mock_fe.get_record_by_id = MagicMock(return_value={
            "record": {
                "record_id": "rec2",
                "fields": {"案例ID": "case_webhook_002", "决策": "已拒绝", "审核人": "lead", "备注": "证据不足"},
            }
        })
        mock_orch = MagicMock()
        mock_orch.registry.safe_execute = MagicMock(return_value={"success": True})
        main_mod._frontend = mock_fe
        main_mod._orchestrator = mock_orch

        client = TestClient(app)
        payload = {"event": {"record_id": "rec2"}}
        resp = client.post("/feishu/bitable/webhook", json=payload)
        assert resp.status_code == 200
        call_args = main_mod._orchestrator.registry.safe_execute.call_args
        assert call_args.args[1]["intent"] == "reject_case"
        assert call_args.args[1]["reason"] == "证据不足"

    def test_webhook_missing_record_id_returns_400(self):
        """无 record_id → 400。"""
        from app.main import app
        import app.main as main_mod
        main_mod._frontend = MagicMock()
        client = TestClient(app)
        resp = client.post("/feishu/bitable/webhook", json={"event": {}})
        assert resp.status_code == 200  # 飞书期望 200
        assert resp.json()["code"] == 400
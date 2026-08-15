"""Day 17 v3 工单关闭自动沉淀 KB 测试。

覆盖：
1. resolve_ticket 基础：DB 更新状态为 closed
2. auto_promote + 高置信度 case → KEA.promote_to_faq 被调
3. auto_promote + 低置信度 → 不 promote，trace.skip_promote_reason 说明
4. resolve_ticket 工单不存在 → not_found
5. resolve_ticket 重复关闭 → closed_was_already=True
6. auto_promote=False 显式关闭 → 不调 KEA
7. KEA 未注入 → skip_promote_reason 说明（不报错）
8. KEA 调用异常 → 工单更新仍成功，trace.promote_error 不影响主流程
9. diagnosis_id → case_id 反查（_lookup_case_id）
"""
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest

from app.agents.tra.tool import TRATool
from app.models import Ticket, Case


@pytest.fixture
def mock_kea():
    """Mock KEA 工具。"""
    kea = MagicMock()
    # 默认：promote 成功
    kea.execute.return_value = {
        "intent": "promote_to_faq",
        "count": 1,
        "promoted": True,
        "case_id": "case_test_001",
        "chroma_id": "faq_case_test_001_abc",
        "trace": {"decision": "auto_promoted"},
    }
    return kea


@pytest.fixture
def mock_case_repo():
    """Mock CaseRepository。"""
    repo = MagicMock()
    case = Case(
        id="case_test_001",
        problem_desc="Visa 13.1 拒付",
        diagnosis="商品未收到",
        resolution="RDR 自动拦截",
        country="NL",
        channel="Visa",
        error_code="13.1",
        problem_type="拒付",
        confidence=0.95,  # ≥ 0.9 → 应自动 promote
    )
    repo.get_by_id.return_value = case
    repo.list.return_value = [case]
    return repo


@pytest.fixture
def tra_with_kea(mock_kea, mock_case_repo):
    """构造带 KEA + CaseRepo 的 TRA（in-memory ticket store）。"""
    tra = TRATool(
        ticket_repo=None,
        case_repo=mock_case_repo,
        kea=mock_kea,
        rules_path=MagicMock(),  # 不需要加载真实规则
    )
    # 注入一个内存工单
    tra._memory_store["tkt_test_001"] = {
        "problem_type": "拒付",
        "priority": "high",
        "status": "pending",
        "assignee": "技术团队-L2",
        "source": "merchant_diagnosis",
        "diagnosis_id": "case_test_001",
        "feishu_record_id": "fss_test_001",
        "rule_id": "rule_visa_high_vip",
        "sla_hours": 4,
        "notification_channel": "feishu",
        "sla_due": "2026-08-16T12:00:00Z",
    }
    return tra


class TestResolveTicket:
    """resolve_ticket intent 测试。"""

    def test_basic_resolve_closes_ticket(self, tra_with_kea):
        """基本关闭：工单 status 从 pending → closed。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "resolution": "已通过 RDR 解决",
            "auto_promote": False,
        })

        assert result["intent"] == "resolve_ticket"
        assert result["status"] == "closed"
        assert result["ticket_id"] == "tkt_test_001"
        assert result["resolution_recorded"] is True
        # 内存中工单状态已更新
        assert tra_with_kea._memory_store["tkt_test_001"]["status"] == "closed"

    def test_resolve_triggers_kea_promote(self, tra_with_kea, mock_kea, mock_case_repo):
        """auto_promote=True + 高置信度 case → KEA.promote_to_faq 被调。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "resolution": "已解决",
            "auto_promote": True,
        })

        # KEA 被调
        assert mock_kea.execute.called
        call_args = mock_kea.execute.call_args
        assert call_args[0][0]["intent"] == "promote_to_faq"
        assert call_args[0][0]["case_id"] == "case_test_001"

        # promote_result 在响应里
        assert result["promote_result"]["promoted"] is True
        assert result["promote_result"]["case_id"] == "case_test_001"

    def test_resolve_low_confidence_skips_promote(self, tra_with_kea, mock_kea):
        """case confidence < 0.9 → KEA 仍被调（自带三段审核），但结果会显示未 promote。"""
        # 修改 confidence 为 0.5
        tra_with_kea.case_repo.get_by_id.return_value.confidence = 0.5
        # 让 KEA 返回"拒绝"结果
        mock_kea.execute.return_value = {
            "intent": "promote_to_faq",
            "count": 0,
            "promoted": False,
            "rejected": True,
            "case_id": "case_test_001",
            "trace": {"decision": "rejected", "reason": "confidence < 0.7"},
        }

        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "auto_promote": True,
        })

        # KEA 被调，但结果 rejected
        assert mock_kea.execute.called
        assert result["promote_result"]["promoted"] is False
        assert result["promote_result"]["rejected"] is True

    def test_resolve_no_case_found_no_promote(self, tra_with_kea, mock_kea):
        """Day 18 P0：diagnosis_id 查不到 case → 自动生成 case 并 promote（关单即沉淀）。"""
        tra_with_kea.case_repo.get_by_id.return_value = None
        tra_with_kea.case_repo.list.return_value = []
        tra_with_kea.case_repo.create.return_value = True

        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "auto_promote": True,
        })

        # 工单仍关闭成功
        assert result["status"] == "closed"
        # Day 18 P0：自动生成 case → KEA 被调
        assert tra_with_kea.case_repo.create.called
        assert mock_kea.execute.called
        # 传给 KEA 的 case_id 是自动生成的（case_tkt_xxxx_<timestamp>）
        call_args = mock_kea.execute.call_args[0][0]
        assert call_args["case_id"].startswith("case_tkt_")

    def test_resolve_ticket_not_found(self, tra_with_kea):
        """不存在的 ticket_id → not_found。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_does_not_exist",
        })

        assert result["status"] == "not_found"
        assert "不存在" in result["trace"]["error"]

    def test_resolve_no_ticket_id(self, tra_with_kea):
        """缺 ticket_id → not_found。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
        })

        assert result["status"] == "not_found"
        assert "ticket_id" in result["trace"]["error"]

    def test_resolve_already_closed_marks_flag(self, tra_with_kea, mock_kea):
        """工单本来已 closed → 再调 resolve 应仍成功，closed_was_already=True。"""
        # 改成已 closed
        tra_with_kea._memory_store["tkt_test_001"]["status"] = "closed"

        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "auto_promote": False,
        })

        assert result["status"] == "closed"
        assert result["closed_was_already"] is True

    def test_resolve_auto_promote_false_no_kea_call(self, tra_with_kea, mock_kea):
        """auto_promote=False → 不调 KEA，trace 说明。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "auto_promote": False,
        })

        assert not mock_kea.execute.called
        assert "auto_promote=False" in result["trace"]["skip_promote_reason"]

    def test_resolve_no_kea_injected(self, mock_case_repo):
        """KEA 未注入 → skip 提示，工单照常关闭。"""
        tra = TRATool(
            ticket_repo=None,
            case_repo=mock_case_repo,
            kea=None,
        )
        tra._memory_store["tkt_test_002"] = {
            "problem_type": "拒付",
            "priority": "high",
            "status": "pending",
            "assignee": "技术团队",
            "diagnosis_id": "case_test_001",
        }

        result = tra.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_002",
        })

        # 工单关了
        assert result["status"] == "closed"
        # KEA 没注入 → skip 提示
        assert "KEA 未注入" in result["trace"]["skip_promote_reason"]
        assert result["promote_result"] is None

    def test_resolve_kea_exception_does_not_fail_ticket(self, tra_with_kea, mock_kea):
        """KEA 抛异常 → 工单更新仍成功，trace 有说明。"""
        mock_kea.execute.side_effect = RuntimeError("Chroma 不可用")

        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "auto_promote": True,
        })

        # 工单仍成功关闭
        assert result["status"] == "closed"
        # promote_result 是 None（异常被 catch）
        assert result["promote_result"] is None
        assert "异常" in result["trace"]["skip_promote_reason"]

    def test_resolve_resolution_recorded_in_metadata(self, tra_with_kea):
        """resolution 文本写入工单 memory。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "resolution": "RDR 拦截后用户重试成功",
            "auto_promote": False,
        })

        assert result["resolution_recorded"] is True
        assert tra_with_kea._memory_store["tkt_test_001"]["resolution"] == "RDR 拦截后用户重试成功"
        # resolved_at 已写
        assert "resolved_at" in tra_with_kea._memory_store["tkt_test_001"]

    def test_resolve_with_explicit_resolved_status(self, tra_with_kea):
        """status='resolved'（中间态）→ 工单状态应为 resolved（区分初次解 vs 已关闭）。"""
        result = tra_with_kea.execute({
            "intent": "resolve_ticket",
            "ticket_id": "tkt_test_001",
            "status": "resolved",
            "auto_promote": False,
        })

        assert result["status"] == "resolved"


class TestResolveTicketSchema:
    """input_schema 应包含 resolve_ticket。"""

    def test_input_schema_includes_resolve_ticket(self):
        tra = TRATool(ticket_repo=None)
        schema = tra.input_schema
        assert "resolve_ticket" in schema["properties"]["intent"]["enum"]

    def test_input_schema_includes_resolution_field(self):
        tra = TRATool(ticket_repo=None)
        schema = tra.input_schema
        assert "resolution" in schema["properties"]
        assert "auto_promote" in schema["properties"]


class TestResolveTicketRouterPath:
    """Day 17 v3：orchestrator routers.py 应识别 resolve_ticket 关键词并路由。"""

    def test_resolve_keyword_with_ticket_id_routes_resolve(self):
        """query 含「已解决」+ ticket_id → 应走 resolve_ticket。"""
        from app.agents.orchestrator.routers import route_tra, _extract_ticket_id_from_query
        from unittest.mock import MagicMock

        # 先验证 ticket_id 提取
        tid = _extract_ticket_id_from_query("tkt_abc1234 已解决了")
        assert tid == "tkt_abc1234"

        # 准备 registry mock
        registry = MagicMock()
        registry.__contains__ = lambda self, k: k == "ticket_routing"
        registry.safe_execute.return_value = {
            "intent": "resolve_ticket",
            "ticket_id": "tkt_abc1234",
            "status": "closed",
            "assignee": "技术团队-L2",
            "promote_result": {"promoted": True, "case_id": "case_test_001"},
            "trace": {"persisted_via": "memory"},
        }

        result = route_tra(
            query="tkt_abc1234 已解决了",
            ctx={"user_id": "ou_xxx"},
            matched=[],
            registry=registry,
        )

        # 子意图应是 resolve_ticket
        assert result["trace"]["sub_intent"] == "resolve_ticket"
        # 调用 Tool 时参数应有 auto_promote=True + ticket_id
        call_args = registry.safe_execute.call_args
        params = call_args[0][1]
        assert params["intent"] == "resolve_ticket"
        assert params["ticket_id"] == "tkt_abc1234"
        assert params["auto_promote"] is True

    def test_resolve_keyword_without_ticket_id_falls_back(self):
        """query 含「已解决」但无 ticket_id → 降级 query_status（友好提示）。"""
        from app.agents.orchestrator.routers import route_tra
        from unittest.mock import MagicMock

        registry = MagicMock()
        registry.__contains__ = lambda self, k: k == "ticket_routing"
        registry.safe_execute.return_value = {
            "intent": "query_status",
            "status": "not_found",
            "trace": {"error": "ticket_id 必填"},
        }

        result = route_tra(
            query="已解决了",
            ctx={"user_id": "ou_xxx"},
            matched=[],
            registry=registry,
        )

        # 降级 query_status
        assert result["trace"]["sub_intent"] == "query_status"

    def test_extract_ticket_id_patterns(self):
        """_extract_ticket_id_from_query 支持多种格式。"""
        from app.agents.orchestrator.routers import _extract_ticket_id_from_query

        assert _extract_ticket_id_from_query("tkt_a1b2c3d4 已关闭") == "tkt_a1b2c3d4"
        assert _extract_ticket_id_from_query("关闭 tkt_xyz123") == "tkt_xyz123"
        assert _extract_ticket_id_from_query("tkt_abc12345 工单已解决") == "tkt_abc12345"
        assert _extract_ticket_id_from_query("no ticket id here") is None
        assert _extract_ticket_id_from_query("") is None
        # 短的 id 不算（少于 4 字符 hex）
        assert _extract_ticket_id_from_query("tkt_abc") is None

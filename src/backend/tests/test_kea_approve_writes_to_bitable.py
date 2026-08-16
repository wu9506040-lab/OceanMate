"""approve_case / promote_to_faq 必须同步调用 frontend.sync_review_decision — Day 18 P1-final 回归。

背景：
- 录屏 T3.14 + T8 演示「真实数据飞轮」—— 商户关单 → bot 自动入审 → 多维表格 review_decisions 有记录
- 原 bug：approve_case / promote_to_faq 只写 SQLite + Chroma，没调 frontend.sync_review_decision()
- 修复：调用 _sync_review_decision_to_bitable（已注入 frontend 时生效）

用例：
- approve_case：注入 mock frontend → sync_review_decision 被调用 1 次，参数含 case_id/decision/reviewer/decided_at/problem_type/confidence
- promote_to_faq（auto_promoted ≥ 0.9）：同样 sync 1 次，decision="auto_promoted"
- promote_to_faq（pending_review 0.7-0.9）：sync 1 次，decision="pending_review"
- frontend=None（NoOp 场景）：不报错，不写（silent）
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agents.kea import KEATool
from app.models import Case, Merchant


# === 通用 fixtures ===

@pytest.fixture
def tmp_chroma_dir(tmp_path):
    """临时 Chroma 数据目录。"""
    d = tmp_path / "chroma"
    d.mkdir()
    return d


@pytest.fixture
def mock_frontend():
    """Mock BaseFrontend 实例（捕获 sync_review_decision 调用）。"""
    fe = MagicMock()
    fe.sync_review_decision = MagicMock(return_value=True)
    return fe


@pytest.fixture
def kea_with_frontend(repos, tmp_chroma_dir, mock_frontend):
    """KEA + 注入 mock frontend。"""
    return KEATool(
        case_repo=repos["case"],
        chroma_path=tmp_chroma_dir,
        embedding_meta_repo=repos["case"].db,
        frontend=mock_frontend,
    )


@pytest.fixture
def kea_no_frontend(repos, tmp_chroma_dir):
    """KEA 无 frontend 注入（测试 NoOp）。"""
    return KEATool(
        case_repo=repos["case"],
        chroma_path=tmp_chroma_dir,
        embedding_meta_repo=repos["case"].db,
        frontend=None,
    )


@pytest.fixture
def merchant(repos):
    """测试用商户。"""
    m = Merchant(id="m_bitable_test", country="BR", tier="standard")
    repos["merchant"].create(m)
    return m


@pytest.fixture
def pending_case(repos, merchant):
    """pending_review 候选 case（confidence 0.85）。"""
    case = Case(
        id="case_bitable_pending_001",
        problem_desc="BR Pix 风控拦截 ERR_X_PIX_001",
        diagnosis="Pix 风控规则 R002 触发",
        resolution="建议商户走备用通道 Boleto",
        country="BR",
        channel="Pix",
        error_code="ERR_X_PIX_001",
        problem_type="支付失败",
        confidence=0.85,
        merchant_id="m_bitable_test",
    )
    repos["case"].create(case)
    return case


@pytest.fixture
def high_confidence_case(repos, merchant):
    """auto_promote 候选 case（confidence 0.92 ≥ 0.9 阈值）。"""
    case = Case(
        id="case_bitable_auto_001",
        problem_desc="NL MasterCard 13.1 拒付",
        diagnosis="Mastercard 13.1 · 买家说没收到货",
        resolution="建议补 RDR + 风控申诉",
        country="NL",
        channel="Mastercard",
        error_code="13.1",
        problem_type="拒付",
        confidence=0.92,
        merchant_id="m_bitable_test",
    )
    repos["case"].create(case)
    return case


# === approve_case 同步多维表格 ===

class TestApproveCaseSyncsToBitable:
    """approve_case 必须调用 frontend.sync_review_decision。"""

    def test_approve_case_calls_sync_review_decision(self, kea_with_frontend, pending_case, mock_frontend):
        """approve_case 触发 1 次 sync_review_decision 调用。"""
        result = kea_with_frontend.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_operator_001",
        })

        assert result["approved"] is True
        # 关键断言：sync_review_decision 被调用 1 次
        assert mock_frontend.sync_review_decision.call_count == 1, (
            f"sync_review_decision 应被调用 1 次，实际={mock_frontend.sync_review_decision.call_count}"
        )

    def test_approve_case_sync_payload_contains_required_fields(
        self, kea_with_frontend, pending_case, mock_frontend
    ):
        """sync_review_decision 的 payload 必须含 case_id / decision / reviewer / decided_at / problem_type / confidence。"""
        kea_with_frontend.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_lead_001",
        })

        # 取出调用参数
        call_args = mock_frontend.sync_review_decision.call_args
        assert call_args is not None, "sync_review_decision 应被调用"
        payload = call_args[0][0]  # 第一个位置参数

        assert payload["case_id"] == pending_case.id
        assert payload["decision"] == "approved"
        assert payload["reviewer"] == "ou_lead_001"
        assert payload["problem_type"] == "支付失败"
        assert payload["confidence"] == 0.85
        # decided_at 必须是 ISO 格式字符串（含 T 或 -）
        assert "decided_at" in payload
        assert isinstance(payload["decided_at"], str)
        assert "T" in payload["decided_at"]

    def test_approve_without_frontend_does_not_crash(self, kea_no_frontend, pending_case):
        """frontend=None 时 approve_case 不报错（NoOp 静默）。"""
        result = kea_no_frontend.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_test",
        })

        # 仍应正常完成（SQLite + Chroma 写入正常）
        assert result["approved"] is True
        assert result["case_id"] == pending_case.id


# === promote_to_faq 同步多维表格 ===

class TestPromoteToFaqSyncsToBitable:
    """promote_to_faq 必须调用 frontend.sync_review_decision（auto_promoted / pending_review）。"""

    def test_auto_promote_high_confidence_calls_sync(
        self, kea_with_frontend, high_confidence_case, mock_frontend
    ):
        """auto_promoted（confidence ≥ 0.9）→ sync 1 次，decision='auto_promoted'。"""
        result = kea_with_frontend.execute({
            "intent": "promote_to_faq",
            "case_id": high_confidence_case.id,
        })

        assert result["promoted"] is True
        assert mock_frontend.sync_review_decision.call_count == 1

        payload = mock_frontend.sync_review_decision.call_args[0][0]
        assert payload["case_id"] == high_confidence_case.id
        assert payload["decision"] == "auto_promoted"
        assert payload["reviewer"] == "auto"  # 自动入审
        assert payload["confidence"] == 0.92

    def test_pending_review_calls_sync(self, kea_with_frontend, pending_case, mock_frontend):
        """pending_review（0.7 ≤ confidence < 0.9）→ sync 1 次，decision='pending_review'。"""
        result = kea_with_frontend.execute({
            "intent": "promote_to_faq",
            "case_id": pending_case.id,
        })

        # confidence=0.85 应该 pending_review
        assert mock_frontend.sync_review_decision.call_count == 1

        payload = mock_frontend.sync_review_decision.call_args[0][0]
        assert payload["case_id"] == pending_case.id
        assert payload["decision"] == "pending_review"
        assert payload["reviewer"] == "auto"

    def test_promote_without_frontend_does_not_crash(
        self, kea_no_frontend, high_confidence_case
    ):
        """frontend=None 时 promote_to_faq 不报错。"""
        result = kea_no_frontend.execute({
            "intent": "promote_to_faq",
            "case_id": high_confidence_case.id,
        })

        # 仍应正常完成
        assert result["promoted"] is True
        assert result["case_id"] == high_confidence_case.id


# === 边界 ===

class TestBitableSyncEdgeCases:
    """边界场景：前端 sync 失败 → 不影响主流程。"""

    def test_frontend_sync_failure_does_not_break_approve(
        self, repos, tmp_chroma_dir, pending_case
    ):
        """frontend.sync_review_decision 抛异常 → approve_case 仍应成功（SQLite/Chroma 写入不受影响）。"""
        # mock frontend：sync_review_decision 抛异常
        fe = MagicMock()
        fe.sync_review_decision = MagicMock(side_effect=Exception("飞书 API 限流"))

        kea = KEATool(
            case_repo=repos["case"],
            chroma_path=tmp_chroma_dir,
            embedding_meta_repo=repos["case"].db,
            frontend=fe,
        )

        # 不应抛异常（fail-soft：仅 warn log）
        result = kea.execute({
            "intent": "approve_case",
            "case_id": pending_case.id,
            "reviewer": "ou_test",
        })

        # SQLite + Chroma 写入不受影响
        assert result["approved"] is True
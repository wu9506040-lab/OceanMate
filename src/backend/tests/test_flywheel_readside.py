"""Day 19 数据飞轮接通测试（读取侧 + 反馈信号 + 误触发修复）。

覆盖三件事：
1. lookup_learned_faq：确定性匹配（同错误码/同问题类型 + resolution 非空），不命中不注入
2. _fmt_pda：命中 learned_faq 时答案优先展示"上次的实际办法"
3. record_feedback：商户 👍/👎 写进 review_decisions（down=rejected 回人工复审视野）
4. _URGENT_HINTS：日常词"支持/客服/联系"不再触发自动建工单
"""

from pathlib import Path

import pytest

from app.agents.kea.tool import KEATool
from app.agents.orchestrator.routers import lookup_learned_faq
from app.implementations.db.sqlite_db import SQLiteDatabase
from app.implementations.feishu.webhook import FeishuWebhookHandler


# ---------- 1. 读取侧匹配 ----------

class _StubRegistry:
    """只实现 in / safe_execute 的最小 registry。"""

    def __init__(self, faqs, fail=False):
        self._faqs = faqs
        self._fail = fail

    def __contains__(self, name):
        return name == "knowledge_evolution"

    def safe_execute(self, tool, params):
        if self._fail:
            raise RuntimeError("boom")
        return {"success": True, "data": {"faqs": self._faqs}}


def _faq(error_code="CB_13.1", problem_type="拒付", resolution="补充收单凭证申诉成功"):
    return {
        "case_id": "case_1",
        "text_excerpt": "visa 拒付",
        "case_info": {
            "problem_desc": "US 站 Visa 13.1 拒付多",
            "resolution": resolution,
            "error_code": error_code,
            "problem_type": problem_type,
        },
    }


class TestLookupLearnedFaq:

    def test_hit_by_error_code(self):
        got = lookup_learned_faq(
            _StubRegistry([_faq()]), "visa 13.1 拒付", country="US",
            error_code="CB_13.1", problem_type="")
        assert got and got["matched_by"] == "error_code"
        assert "申诉" in got["resolution"]

    def test_hit_by_problem_type(self):
        got = lookup_learned_faq(
            _StubRegistry([_faq()]), "老是拒付", country="US",
            error_code="", problem_type="拒付")
        assert got and got["matched_by"] == "problem_type"

    def test_no_match_different_code_not_injected(self):
        got = lookup_learned_faq(
            _StubRegistry([_faq(error_code="CB_13.1")]), "q", country="US",
            error_code="CB_4837", problem_type="其他")
        assert got is None

    def test_empty_resolution_never_injected(self):
        got = lookup_learned_faq(
            _StubRegistry([_faq(resolution="   ")]), "q", country="US",
            error_code="CB_13.1", problem_type="拒付")
        assert got is None

    def test_registry_failure_degrades_gracefully(self):
        assert lookup_learned_faq(
            _StubRegistry([], fail=True), "q", error_code="CB_13.1") is None


# ---------- 2. 答案渲染 ----------

class TestPdaAnswerShowsLearned:

    def test_fmt_pda_prefers_learned_resolution(self):
        text = FeishuWebhookHandler._fmt_pda(
            {"problem_type": "拒付", "confidence": 0.9},
            {"learned_faq": {
                "case_id": "case_1",
                "resolution": "补充物流签收凭证，14 天内提交申诉",
                "matched_by": "error_code",
            }})
        assert "这个问题我们之前解决过" in text
        assert "补充物流签收凭证" in text
        assert "同错误码" in text

    def test_fmt_pda_without_learned_unchanged(self):
        text = FeishuWebhookHandler._fmt_pda(
            {"problem_type": "拒付", "confidence": 0.9}, {})
        assert "之前解决过" not in text


# ---------- 3. 反馈信号 ----------

class TestRecordFeedback:

    @pytest.fixture
    def kea(self, tmp_path: Path):
        db = SQLiteDatabase(tmp_path / "t.db")
        return KEATool(embedding_meta_repo=db)

    def test_downvote_writes_rejected(self, kea):
        r = kea.execute({"intent": "record_feedback", "case_id": "c1",
                         "signal": "down", "note": "没解决"})
        assert r["decision"] == "rejected" and r["recorded"] is True
        rows = kea._db.query(
            "SELECT * FROM review_decisions WHERE case_id='c1'")
        assert rows[0]["decision"] == "rejected"
        assert rows[0]["note"].startswith("merchant_downvote")

    def test_upvote_writes_approved(self, kea):
        r = kea.execute({"intent": "record_feedback", "case_id": "c2",
                         "signal": "up"})
        assert r["decision"] == "approved"

    def test_bad_signal_rejected(self, kea):
        r = kea.execute({"intent": "record_feedback", "case_id": "c3",
                         "signal": "meh"})
        assert r.get("promoted") is False and "signal" in r["trace"]["error"]


# ---------- 4. 误触发修复 ----------

class TestUrgentHintsFixed:

    @pytest.mark.parametrize("word", ["支持", "客服", "联系", "工单", "人工", "急"])
    def test_generic_words_removed(self, word):
        assert word not in FeishuWebhookHandler._URGENT_HINTS

    def test_explicit_escalation_words_kept(self):
        for word in ("转人工", "紧急", "派单", "投诉"):
            assert word in FeishuWebhookHandler._URGENT_HINTS

    def test_question_with_zhichi_not_triggering(self):
        # 回归审计 bug#1：商户问"Visa 支持 3DS 吗"是产品咨询，不该命中升级关键词
        q = "Visa 支持 3DS 吗"
        assert not any(k in q for k in FeishuWebhookHandler._URGENT_HINTS)

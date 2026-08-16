"""KEA list_candidates 必须返回 created_at — Day 18 P1-final 修复回归。

背景：
- T8 录屏演示时，运营在多维表格里需要看到 case 的入审时间戳
- 原 bug：_list_candidates 返回的 candidate dict 不含 created_at
- 修复：加 `created_at: getattr(c, 'created_at', None) or ""`

用例：
- 普通 case → candidate dict 含 created_at 字段（ISO 字符串或空字符串）
- 没有 created_at 的 case（旧数据 / 异常）→ 优雅 fallback 到空字符串，不报错
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

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
def kea(repos, tmp_chroma_dir):
    """KEA 默认实例。"""
    return KEATool(
        case_repo=repos["case"],
        chroma_path=tmp_chroma_dir,
        embedding_meta_repo=repos["case"].db,
    )


@pytest.fixture
def merchant(repos):
    """测试用商户。"""
    m = Merchant(id="m_list_test", country="BR", tier="standard")
    repos["merchant"].create(m)
    return m


@pytest.fixture
def high_confidence_case(repos, merchant):
    """高置信度 case（0.85 · pending_review 候选）。"""
    case = Case(
        id="case_list_test_001",
        problem_desc="BR Pix 风控拦截 ERR_X_PIX_001",
        diagnosis="Pix 风控规则 R002 触发",
        resolution="建议商户走备用通道 Boleto",
        country="BR",
        channel="Pix",
        error_code="ERR_X_PIX_001",
        problem_type="支付失败",
        confidence=0.85,
        merchant_id="m_list_test",
    )
    repos["case"].create(case)
    return case


# === list_candidates 时间戳测试 ===

class TestListCandidatesHasCreatedAt:
    """list_candidates 必须返回 created_at 字段。"""

    def test_candidate_dict_has_created_at_field(self, kea, high_confidence_case):
        """每个 candidate dict 必须含 created_at 字段。"""
        result = kea.execute({
            "intent": "list_candidates",
            "min_confidence": 0.7,
            "limit": 10,
        })

        assert result["intent"] == "list_candidates"
        assert result["count"] >= 1

        candidates = result["candidates"]
        assert len(candidates) >= 1

        # 关键断言：每个 candidate 必须含 created_at
        for c in candidates:
            assert "created_at" in c, (
                f"candidate 应含 created_at 字段，实际 keys={list(c.keys())}"
            )

    def test_created_at_is_string_or_empty(self, kea, high_confidence_case):
        """created_at 必须是字符串（ISO 格式）或空字符串（fallback）。"""
        result = kea.execute({
            "intent": "list_candidates",
            "min_confidence": 0.7,
            "limit": 10,
        })

        for c in result["candidates"]:
            ts = c["created_at"]
            # 可能是 ISO 字符串 / 空字符串 / datetime 对象（取决于 case_repo.get_by_id 实现）
            assert ts is None or isinstance(ts, (str, datetime)), (
                f"created_at 必须是 str / datetime / None，实际={type(ts).__name__}: {ts}"
            )

    def test_created_at_is_iso_format_when_present(self, kea, repos, merchant):
        """如果 case 有 created_at（SQLite DEFAULT CURRENT_TIMESTAMP），返回应该是 ISO 字符串或 datetime 对象。"""
        # 创建 case（created_at 由 SQLite CURRENT_TIMESTAMP 自动填）
        case = Case(
            id="case_list_test_iso",
            problem_desc="NL MasterCard 拒付 ERR_X_MC_002",
            diagnosis="Mastercard 13.1 拒付",
            resolution="建议补 RDR + 风控申诉",
            country="NL",
            channel="Mastercard",
            error_code="13.1",
            problem_type="拒付",
            confidence=0.92,
            merchant_id="m_list_test",
        )
        repos["case"].create(case)

        result = kea.execute({
            "intent": "list_candidates",
            "min_confidence": 0.7,
            "limit": 10,
        })

        candidates_by_id = {c["case_id"]: c for c in result["candidates"]}
        assert "case_list_test_iso" in candidates_by_id

        c = candidates_by_id["case_list_test_iso"]
        ts = c["created_at"]
        assert ts is not None and ts != "", f"created_at 不应为空（SQLite DEFAULT 应自动填）：{ts}"
        # 可能是 ISO 字符串 / datetime 对象（取决于 SQLiteDatabase 实现）
        if isinstance(ts, datetime):
            # datetime 对象：转 ISO 字符串验证
            iso = ts.isoformat()
            assert "T" in iso, f"datetime 应能转 ISO 格式，实际={iso}"
        elif isinstance(ts, str):
            assert "T" in ts or "-" in ts, f"created_at 应为 ISO 格式，实际={ts}"
        else:
            pytest.fail(f"created_at 类型应为 str / datetime，实际={type(ts).__name__}")

    def test_no_breaking_existing_fields(self, kea, high_confidence_case):
        """原有字段（case_id / problem_type / confidence 等）不能被破坏。"""
        result = kea.execute({
            "intent": "list_candidates",
            "min_confidence": 0.7,
            "limit": 10,
        })

        for c in result["candidates"]:
            # 原有字段必须有
            assert "case_id" in c
            assert "problem_type" in c
            assert "confidence" in c
            assert "problem_desc" in c
            # 新增字段必须有
            assert "created_at" in c
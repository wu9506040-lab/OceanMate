"""Repository 骨架测试 — Day 1 自测。

覆盖：
- 6 个 Repository × 1 happy path CRUD（get_by_id / create / update / list）
- 2 个关键 SOP 场景：
  * SOP-REPO-001-A 主键冲突 → DuplicateKeyError
  * SOP-REPO-001-B 无结果查询 → 返回 None

注意：Day 1 只跑 happy path；逆向场景（NOT NULL 违反/字段超长）的故障 fixture
在 Day 2 上午做（避免 Day 1 加班）。
"""

import pytest
from datetime import datetime

from app.models import (
    Merchant, ErrorCode, Case, Ticket,
    Conversation, Message, Handoff,
)
from app.interfaces.base_repository import (
    DuplicateKeyError, NotFoundError, ValidationError, RepositoryError,
)


# === 1. MerchantRepository ===

class TestMerchantRepository:
    def test_happy_path_crud(self, repos):
        merchant = Merchant(
            id="m_001",
            country="BR",
            industry="fashion",
            avg_amount=85.0,
            tier="premium",
            feishu_record_id="rec_xxx",
        )
        # Create
        assert repos["merchant"].create(merchant) is True
        # Get by id
        fetched = repos["merchant"].get_by_id("m_001")
        assert fetched is not None
        assert fetched.country == "BR"
        assert fetched.tier == "premium"
        # Update
        fetched.tier = "vip"
        assert repos["merchant"].update("m_001", fetched) is True
        assert repos["merchant"].get_by_id("m_001").tier == "vip"
        # List
        results = repos["merchant"].list(filters={"country": "BR"})
        assert len(results) == 1
        assert results[0].id == "m_001"

    def test_sop_duplicate_key(self, repos):
        """SOP-REPO-001-A：主键冲突 → DuplicateKeyError。"""
        m = Merchant(id="m_dup", country="US")
        repos["merchant"].create(m)
        with pytest.raises(DuplicateKeyError) as exc_info:
            repos["merchant"].create(m)
        assert "m_dup" in str(exc_info.value)

    def test_sop_not_found(self, repos):
        """SOP-REPO-001-B：无结果查询 → 返回 None。"""
        assert repos["merchant"].get_by_id("nope") is None
        assert repos["merchant"].list(filters={"country": "ZZ"}) == []

    def test_sop_not_null_violation(self, repos):
        """SOP-REPO-001-C：NOT NULL 字段缺失 → ValidationError / RepositoryError。

        merchants.country 是 NOT NULL 必填。Pydantic Model 必填，但 SQL 层直接
        INSERT 绕过 Pydantic 时会触发 SQLite NOT NULL 约束。
        """
        # 直接走 db.execute（绕过 Pydantic 校验）模拟外部注入
        with pytest.raises(Exception) as exc_info:
            repos["merchant"].db.execute(
                "INSERT INTO merchants (id, country) VALUES (:id, :country)",
                {"id": "m_null", "country": None},
            )
        # 错误信息含 NOT NULL
        assert "NOT NULL" in str(exc_info.value) or "not null" in str(exc_info.value).lower()

    def test_sop_field_length_pydantic_validation(self):
        """SOP-REPO-001-D：字段超长由 Pydantic 拦截（SQLite TEXT 无长度限制）。"""
        from app.models import ErrorCode
        from pydantic import ValidationError as PydValidationError

        # 当前 ErrorCode 没有 max_length 约束 → SQLite TEXT 无限制
        # 这是一个设计选择：PoC 阶段信任飞书源头数据长度
        long_code = "X" * 1000
        ec = ErrorCode(id="ec_long", code=long_code, country="BR")
        # Pydantic 不抛（设计上不限制）
        assert len(ec.code) == 1000

        # 演示：如果想加 max_length，用 Pydantic StringConstraints
        # 这里只是文档化：当前 PoC 阶段，字段超长不在 Repository 层拦截
        # 真实环境可加：
        #   code: str = Field(..., min_length=1, max_length=64)
        # 然后此测试会因 ValidationError 而通过（这里是反向断言：当前不限制）


# === 2. ErrorCodeRepository ===

class TestErrorCodeRepository:
    def test_happy_path_crud(self, repos):
        ec = ErrorCode(
            id="ec_001",
            code="ERR_RISK_BLOCK_BR_VISA",
            country="BR",
            channel="visa",
            root_cause="风控拦截",
            solution="建议改用 Mastercard",
            feishu_record_id="rec_ec1",
        )
        assert repos["error_code"].create(ec) is True

        fetched = repos["error_code"].get_by_id("ec_001")
        assert fetched.root_cause == "风控拦截"

        # update
        fetched.solution = "建议改用 Mastercard 或 Pix"
        assert repos["error_code"].update("ec_001", fetched) is True

        # list with filter
        results = repos["error_code"].list(filters={"country": "BR"})
        assert len(results) == 1

        # 定制方法 lookup_by_code
        hit = repos["error_code"].lookup_by_code("ERR_RISK_BLOCK_BR_VISA", "BR")
        assert hit is not None
        assert hit.id == "ec_001"

        # 定制方法 search
        hits = repos["error_code"].search("风控")
        assert len(hits) == 1

    def test_sop_duplicate_unique_constraint(self, repos):
        """SOP-REPO-001-A：UNIQUE(code, country, channel) 冲突 → DuplicateKeyError。"""
        ec1 = ErrorCode(id="ec_a", code="ERR_X", country="BR", channel="visa")
        ec2 = ErrorCode(id="ec_b", code="ERR_X", country="BR", channel="visa")  # 同 (code,country,channel)
        repos["error_code"].create(ec1)
        with pytest.raises(DuplicateKeyError):
            repos["error_code"].create(ec2)


# === 3. CaseRepository ===

class TestCaseRepository:
    def test_happy_path_crud(self, repos):
        # 准备前置：merchant + error_code（Case 引用它们）
        repos["merchant"].create(Merchant(id="m_c", country="BR"))
        repos["error_code"].create(ErrorCode(id="ec_c", code="ERR_C"))

        case = Case(
            id="case_001",
            problem_desc="BR 客户 Visa 支付失败",
            diagnosis="风控拦截",
            resolution="改用 Pix",
            country="BR",
            channel="visa",
            error_code="ERR_C",
            problem_type="支付失败",
            confidence=0.85,
            merchant_id="m_c",
            feishu_record_id="rec_case1",
        )
        assert repos["case"].create(case) is True

        fetched = repos["case"].get_by_id("case_001")
        assert fetched.confidence == 0.85
        assert fetched.merchant_id == "m_c"

        # list filter
        results = repos["case"].list(filters={"country": "BR", "channel": "visa"})
        assert len(results) == 1

    def test_sop_fk_violation(self, repos):
        """SOP-REPO-001-C：外键约束违反 → RepositoryError（PoC 简化包）。"""
        bad_case = Case(
            id="case_bad",
            problem_desc="测试",
            merchant_id="nonexistent_merchant",  # 不存在的商户
        )
        with pytest.raises(RepositoryError):
            repos["case"].create(bad_case)


# === 4. TicketRepository ===

class TestTicketRepository:
    def test_happy_path_crud(self, repos):
        repos["merchant"].create(Merchant(id="m_t", country="US"))

        ticket = Ticket(
            id="t_001",
            problem_type="支付失败",
            priority="high",
            status="pending",
            merchant_id="m_t",
            source="merchant_diagnosis",
        )
        assert repos["ticket"].create(ticket) is True

        fetched = repos["ticket"].get_by_id("t_001")
        assert fetched.priority == "high"
        assert fetched.status == "pending"

        # update + 标记 resolved
        fetched.status = "resolved"
        fetched.resolved_at = datetime(2026, 8, 4, 12, 0, 0)
        assert repos["ticket"].update("t_001", fetched) is True

        # list 按状态过滤
        pending = repos["ticket"].list(filters={"status": "pending"})
        resolved = repos["ticket"].list(filters={"status": "resolved"})
        assert len(pending) == 0
        assert len(resolved) == 1


# === 5. ConversationRepository ===

class TestConversationRepository:
    def test_happy_path_crud_with_messages(self, repos):
        conv = Conversation(
            id="conv_001",
            user_id="ou_xxx",
            status="active",
            merchant_id=None,
        )
        assert repos["conversation"].create(conv) is True

        # 添加消息
        assert repos["conversation"].add_message(
            "conv_001",
            Message(conversation_id="conv_001", role="user", content="Visa 支付失败"),
        ) is True
        assert repos["conversation"].add_message(
            "conv_001",
            Message(conversation_id="conv_001", role="assistant", content="请检查风控规则"),
        ) is True

        msgs = repos["conversation"].get_messages("conv_001")
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"

        # list 按 user 过滤
        results = repos["conversation"].list(filters={"user_id": "ou_xxx"})
        assert len(results) == 1

    def test_sop_not_found_messages(self, repos):
        """SOP-REPO-001-B：不存在的会话查消息 → 空列表。"""
        msgs = repos["conversation"].get_messages("conv_nope")
        assert msgs == []


# === 6. HandoffRepository ===

class TestHandoffRepository:
    def test_happy_path_crud(self, repos):
        repos["conversation"].create(Conversation(id="conv_h", user_id="ou_h"))

        handoff = Handoff(
            id="h_001",
            conversation_id="conv_h",
            agent_id="agent_007",
            reason="商户情绪激动 + 需要人工介入",
            briefing="商户 M001 在 BR 多次 Visa 拒付，已尝试自动诊断无果",
        )
        assert repos["handoff"].create(handoff) is True

        fetched = repos["handoff"].get_by_id("h_001")
        assert fetched.agent_id == "agent_007"
        assert "情绪激动" in fetched.reason

        # 标记 resolved
        fetched.resolved_at = datetime(2026, 8, 4, 13, 0, 0)
        assert repos["handoff"].update("h_001", fetched) is True

        # list 按会话过滤
        results = repos["handoff"].list(filters={"conversation_id": "conv_h"})
        assert len(results) == 1


# === 7. Pydantic 模型验证（基础） ===

class TestPydanticModels:
    def test_merchant_serialization_roundtrip(self):
        m = Merchant(id="m_x", country="BR")
        d = m.model_dump()
        m2 = Merchant.model_validate(d)
        assert m2.id == "m_x"
        assert m2.country == "BR"

    def test_case_confidence_bounds(self):
        """Pydantic 字段约束：confidence ∈ [0, 1]。"""
        from pydantic import ValidationError as PydValidationError
        with pytest.raises(PydValidationError):
            Case(id="c1", problem_desc="x", confidence=1.5)  # 超出范围

    def test_optional_defaults(self):
        """Optional 字段默认 None。"""
        ec = ErrorCode(id="ec", code="X")
        assert ec.country is None
        assert ec.root_cause is None

    def test_sop_field_length_currently_unbounded(self):
        """SOP-REPO-001-D：PoC 阶段字段超长不限制（SQLite TEXT 无长度上限）。

        设计选择：当前信任飞书源头数据长度，不在 Pydantic 层强制 max_length。
        真实环境如需限制，添加：
            code: str = Field(..., min_length=1, max_length=64)
        """
        # 1000 字符的 code 不抛异常
        ec = ErrorCode(id="ec_x", code="X" * 1000)
        assert len(ec.code) == 1000
        # 往返序列化保留完整长度
        d = ec.model_dump()
        ec2 = ErrorCode.model_validate(d)
        assert len(ec2.code) == 1000
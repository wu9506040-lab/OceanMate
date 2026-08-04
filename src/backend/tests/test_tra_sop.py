"""TRATool SOP 测试 — Day 5 SOP-TRA-001/002。

覆盖：
- SOP-TRA-001-A：4 层规则匹配优先级（exact > priority_wildcard > problem_wildcard > default）
- SOP-TRA-001-B：VIP high 命中 VIP 专线（SLA=2h）
- SOP-TRA-001-C：持久化（DB + in-memory fallback）
- SOP-TRA-001-D：query_status 查询已建工单
- SOP-TRA-002-A：缺 problem_type → 友好提示（不抛 raw exception）
- SOP-TRA-002-B：路由规则不存在 → 兜底
- SOP-TRA-002-C：DB 失败 → in-memory 兜底
- 集成：Orchestrator → TRA 端到端

详见 docs/sop/SOP-TRA.md。
"""

import json
from pathlib import Path
import pytest

from app.agents.tra import TRATool
from app.agents.orchestrator import Orchestrator
from app.interfaces.base_tool import BaseTool
from app.models import Ticket


# === 通用 fixtures ===

@pytest.fixture
def rules_path():
    """返回路由规则 JSON 路径（用于默认实例验证）。"""
    return Path(__file__).resolve().parents[3] / "docs" / "data" / "ticket_routing_rules.json"


@pytest.fixture
def tra():
    """TRA 默认实例（in-memory + 默认规则路径）。"""
    return TRATool()


@pytest.fixture
def tra_with_repo(repos):
    """TRA 注入 TicketRepository（用测试 DB + 预置 1 个 merchant 行）。"""
    # tickets.merchant_id 有 FK → merchants(id)，必须先插一条
    from app.models import Merchant
    merchant = Merchant(
        id="m_test_001",
        country="BR",
        industry="fashion",
        avg_amount=85.0,
        tier="vip",
    )
    repos["merchant"].create(merchant)
    return TRATool(ticket_repo=repos["ticket"])


@pytest.fixture
def tra_no_rules(tmp_path):
    """TRA 指向不存在的规则路径（用于降级测试）。"""
    fake = tmp_path / "no_rules.json"
    return TRATool(rules_path=fake)


@pytest.fixture
def tra_custom_rules(tmp_path):
    """TRA 注入单条自定义规则（用于隔离测试）。"""
    p = tmp_path / "minimal_rules.json"
    p.write_text(json.dumps({
        "_meta": {"purpose": "test minimal"},
        "rules": [
            {
                "id": "rule_test_payfail_vip_high",
                "problem_type": "支付失败",
                "priority": "high",
                "tier": "vip",
                "assignee": "VIP-专线",
                "sla_hours": 2,
                "notification_channel": "飞书 VIP 群",
            },
            {
                "id": "rule_test_default",
                "problem_type": "*",
                "priority": "medium",
                "tier": "*",
                "assignee": "通用支持",
                "sla_hours": 24,
                "notification_channel": "飞书通用群",
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return TRATool(rules_path=p)


# === 接口合规 ===

class TestTRAToolInterface:
    """BaseTool 接口合规。"""

    def test_is_base_tool_subclass(self):
        assert issubclass(TRATool, BaseTool)

    def test_name_and_description(self, tra):
        assert tra.name == "ticket_routing"
        assert "工单" in tra.description and ("路由" in tra.description or "SLA" in tra.description)

    def test_intent_enum_in_input_schema(self, tra):
        schema = tra.input_schema
        intent_prop = schema["properties"]["intent"]
        assert "route_ticket" in intent_prop["enum"]
        assert "query_status" in intent_prop["enum"]

    def test_mcp_tool_spec_export(self, tra):
        spec = tra.to_mcp_tool_spec()
        assert spec["name"] == "ticket_routing"
        assert "capabilities" in spec
        # create_ticket 每次生成新 ID，不幂等
        assert spec["capabilities"]["idempotent"] is False

    def test_default_rules_loaded(self, tra, rules_path):
        """默认实例应已加载 10 条规则（见 docs/data/ticket_routing_rules.json）。"""
        assert rules_path.exists(), f"路由规则文件应存在: {rules_path}"
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)["rules"]
        assert tra.rule_count == len(rules)
        assert tra.rule_count >= 10


# === SOP-TRA-001-A · 4 层规则匹配优先级 ===

class TestRuleMatchPriority:
    """SOP-TRA-001-A：匹配优先级降级链。"""

    def test_exact_match_highest_priority(self, tra_custom_rules):
        """exact (problem_type + priority + tier) 3 元组都相等 → match_level=exact。"""
        result = tra_custom_rules.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "vip",
        })
        assert result["status"] == "pending"
        assert result["rule_id"] == "rule_test_payfail_vip_high"
        assert result["match_level"] == "exact"
        assert result["assignee"] == "VIP-专线"
        assert result["sla_hours"] == 2

    def test_priority_wildcard_fallback(self, tra):
        """exact 不命中 + (problem_type + priority + *) → match_level=priority_wildcard。

        验证路径：(支付失败, high, standard)
        - exact (支付失败, high, standard) 无（只有 vip/premium 有 exact）
        - priority_wildcard (支付失败, high, *) → rule_demo_payfail_any
        """
        result = tra.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "standard",
        })
        assert result["status"] == "pending"
        assert result["match_level"] == "priority_wildcard"
        assert result["rule_id"] == "rule_demo_payfail_any"
        assert result["assignee"] == "技术团队-L2"
        assert result["sla_hours"] == 4

    def test_default_fallback_when_no_specific_match(self, tra_custom_rules):
        """完全没匹配到 → default fallback（problem_type="*"，仍创建工单）。"""
        result = tra_custom_rules.execute({
            "intent": "route_ticket",
            "problem_type": "未知的奇怪问题",
            "priority": "high",
            "tier": "vip",
        })
        # default_fallback 是兜底规则命中，仍会创建工单（交给通用支持团队）
        assert result["status"] == "pending"
        assert result["match_level"] == "default_fallback"
        assert result["assignee"] == "通用支持"
        assert result["sla_hours"] == 24

    def test_problem_wildcard_degrades_to_medium(self, tra):
        """exact 失败 + priority 降到 medium + tier 通配 → match_level=problem_wildcard。

        验证路径：(拒付, low, vip)
        - exact (拒付, low, vip) 无
        - priority_wildcard (拒付, low, *) 无（拒付只有 high/medium，没有 low）
        - problem_wildcard (拒付, medium, *) → rule_demo_chargeback_medium
        """
        result = tra.execute({
            "intent": "route_ticket",
            "problem_type": "拒付",
            "priority": "low",
            "tier": "vip",
        })
        assert result["sla_hours"] == 12

    def test_vip_high_routes_to_vip_special_line(self, tra):
        """VIP high 命中 VIP 专线（SLA=2h）。"""
        result = tra.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "vip",
        })
        assert "VIP 专线" in result["assignee"]
        assert result["sla_hours"] == 2
        assert "电话" in result["notification_channel"]


# === SOP-TRA-001-B · 持久化（DB + fallback） ===

class TestPersistence:
    """SOP-TRA-001-B：工单持久化。"""

    def test_db_persist_returns_persisted_via_db(self, tra_with_repo):
        """DB 注入 → 写入 tkt_xxx 后续可查。"""
        result = tra_with_repo.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "vip",
            "merchant_id": "m_test_001",
            "diagnosis_id": "diag_demo_001",
        })
        assert result["status"] == "pending"
        assert result["ticket_id"].startswith("tkt_")
        assert result["trace"]["persisted_via"] == "both"
        assert result["trace"]["feishu_record_id"].startswith("fss_")

        # 验证 DB 真的有这条
        stored = tra_with_repo.ticket_repo.get_by_id(result["ticket_id"])
        assert stored is not None
        assert stored.problem_type == "支付失败"
        assert stored.assignee == "技术团队-L2（VIP 专线）"
        assert stored.status == "pending"
        assert stored.feishu_record_id is not None

    def test_memory_persist_when_no_repo(self, tra):
        """无 repo → 默认 in-memory。"""
        result = tra.execute({
            "intent": "route_ticket",
            "problem_type": "退款异常",
            "priority": "high",
            "tier": "standard",
            "merchant_id": "m_test_002",
        })
        assert result["trace"]["persisted_via"] == "memory"
        # 在 memory store 中应能查到
        assert result["ticket_id"] in tra._memory_store
        assert tra._memory_store[result["ticket_id"]]["assignee"] == "财务团队-退款"

    def test_db_failure_falls_back_to_memory(self, tra_with_repo, monkeypatch):
        """DB 抛异常 → fallback 到 memory（保证 Demo 不挂）。"""
        # 让 repo.create 抛异常
        def boom(_ticket):
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(tra_with_repo.ticket_repo, "create", boom)

        result = tra_with_repo.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "vip",
        })
        # 应仍返回成功的工单（fallback 到 memory）
        assert result["status"] == "pending"
        assert result["trace"]["persisted_via"] == "memory"


# === SOP-TRA-001-C · query_status 查工单 ===

class TestQueryStatus:
    """SOP-TRA-001-C：按 ID 查工单。"""

    def test_query_existing_ticket_returns_full_info(self, tra_with_repo):
        """查 DB 中已建的工单。"""
        # 先建一张
        created = tra_with_repo.execute({
            "intent": "route_ticket",
            "problem_type": "Webhook 回调失败",
            "priority": "high",
            "tier": "standard",
            "diagnosis_id": "diag_demo_wbh",
        })
        ticket_id = created["ticket_id"]

        # 再查
        result = tra_with_repo.execute({
            "intent": "query_status",
            "ticket_id": ticket_id,
        })
        assert result["status"] == "pending"
        assert result["ticket_id"] == ticket_id
        assert result["problem_type"] == "Webhook 回调失败"
        assert result["assignee"] == "技术团队-Webhook"
        assert result["rule_id"] == "rule_demo_webhook_high"
        assert result["match_level"] == "queried"
        assert result["sla_hours"] == 4

    def test_query_memory_ticket(self, tra):
        """查 in-memory 工单（PoC 默认模式）。"""
        created = tra.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "medium",
            "tier": "standard",
        })
        ticket_id = created["ticket_id"]

        result = tra.execute({
            "intent": "query_status",
            "ticket_id": ticket_id,
        })
        assert result["status"] == "pending"
        assert result["match_level"] == "queried"

    def test_query_nonexistent_ticket_returns_not_found(self, tra):
        """查不存在的 ID → 友好返回 status=not_found（不抛异常）。"""
        result = tra.execute({
            "intent": "query_status",
            "ticket_id": "tkt_nonexistent_xxx",
        })
        assert result["status"] == "not_found"
        assert result["match_level"] == "queried"
        assert "error" in result["trace"]

    def test_query_without_ticket_id_returns_not_found(self, tra):
        """缺 ticket_id → 友好错误（不崩）。"""
        result = tra.execute({
            "intent": "query_status",
        })
        assert result["status"] == "not_found"
        assert "ticket_id 必填" in result["trace"]["error"]


# === SOP-TRA-002 · 逆向（友好降级） ===

class TestFriendlyDegradation:
    """SOP-TRA-002：所有失败场景必须用户友好。"""

    def test_missing_problem_type_returns_friendly_error(self, tra):
        """route_ticket 缺 problem_type → 友好提示，不抛 raw exception。"""
        result = tra.execute({
            "intent": "route_ticket",
            "priority": "high",
            "tier": "vip",
        })
        assert result["status"] == "not_found"
        assert result["match_level"] == "no_match"
        assert "problem_type" in result["trace"]["hint"]
        # 必须返 trace 不是裸抛
        assert "rules_loaded" in result["trace"]

    def test_no_rules_loaded_returns_friendly_error(self, tra_no_rules):
        """规则 JSON 不存在 → 友好兜底。"""
        result = tra_no_rules.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "vip",
        })
        assert result["status"] == "not_found"
        assert tra_no_rules.rule_count == 0
        assert result["trace"]["rules_loaded"] == 0
        assert "规则" in result["trace"]["hint"]

    def test_reload_rules_picks_up_changes(self, tra, tmp_path):
        """热更新规则（飞书同步场景）。"""
        # 默认加载应该 OK
        original_count = tra.rule_count
        assert original_count > 0

        # 写入一条新规则到临时文件（Windows 下默认 GBK，必须显式 utf-8）
        new_rules = tmp_path / "new_rules.json"
        new_rules.write_text(json.dumps({
            "_meta": {"purpose": "reload test"},
            "rules": [
                {
                    "id": "rule_reloaded_only",
                    "problem_type": "支付失败",
                    "priority": "high",
                    "tier": "vip",
                    "assignee": "Reload-Test",
                    "sla_hours": 1,
                    "notification_channel": "test",
                },
            ],
        }, ensure_ascii=False), encoding="utf-8")

        # reload → 成功
        assert tra.reload_rules(new_path=new_rules) is True
        assert tra.rule_count == 1

        # 用新规则匹配
        result = tra.execute({
            "intent": "route_ticket",
            "problem_type": "支付失败",
            "priority": "high",
            "tier": "vip",
        })
        assert result["assignee"] == "Reload-Test"
        assert result["sla_hours"] == 1

        # 还原回默认路径（显式传 DEFAULT）
        from app.agents.tra.tool import DEFAULT_RULES_PATH
        tra.reload_rules(new_path=DEFAULT_RULES_PATH)
        assert tra.rule_count == original_count

    def test_unknown_intent_raises_value_error(self, tra):
        """未知 intent → ValueError（Tool 输入校验失败）。"""
        with pytest.raises(ValueError, match="Unknown intent"):
            tra.execute({"intent": "nonsense"})

    def test_invalid_input_rejected_by_jsonschema(self, tra):
        """Tool 层 jsonschema 校验失败。"""
        from jsonschema import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            tra.execute({"intent": 123})  # intent 应是 string


# === 集成：Orchestrator → TRA 端到端 ===

class TestTRAEnd2End:
    """Orchestrator + TRA 链式调用。"""

    def test_orchestrator_routes_to_tra_via_keyword(self):
        """Orchestrator 关键词分类为 ticket_routing → 调 TRA → 创建工单。"""
        orch = Orchestrator()
        tra_tool = TRATool()
        orch.register_tool(tra_tool)

        result = orch.route(
            "我的工单状态如何",
            merchant_context={
                "merchant_id": "m_demo",
                "problem_type": "支付失败",
                "priority": "high",
                "tier": "vip",
                "diagnosis_id": "diag_001",
            },
        )
        assert result["intent"] == "ticket_routing"
        assert result["tool_name"] == "ticket_routing"
        # 由于 ctx 有 problem_type → route_ticket
        assert result["trace"]["sub_intent"] == "route_ticket"
        # Tool 执行成功
        assert result["tool_result"]["success"] is True
        data = result["tool_result"]["data"]
        assert data["status"] == "pending"
        assert "VIP" in data["assignee"]

    def test_orchestrator_query_status_via_ctx(self):
        """ctx 含 ticket_id → TRA 自动选 query_status。"""
        orch = Orchestrator()
        tra_tool = TRATool()
        orch.register_tool(tra_tool)

        # 1) 先建一张
        create_result = orch.route(
            "新建工单",
            merchant_context={
                "merchant_id": "m_demo",
                "problem_type": "支付失败",
                "priority": "high",
                "tier": "vip",
            },
        )
        ticket_id = create_result["tool_result"]["data"]["ticket_id"]

        # 2) 再问
        result = orch.route(
            "查工单状态",
            merchant_context={"ticket_id": ticket_id},
        )
        assert result["trace"]["sub_intent"] == "query_status"
        data = result["tool_result"]["data"]
        assert data["status"] == "pending"
        assert data["ticket_id"] == ticket_id

    def test_orchestrator_tra_not_registered_returns_friendly_error(self):
        """TRA 未注册 → 友好错误，不崩。"""
        orch = Orchestrator()
        result = orch.route("我的工单状态")
        assert result["intent"] == "ticket_routing"
        assert result["tool_result"]["success"] is False
        assert result["tool_result"]["error_code"] == "TOOL_NOT_REGISTERED"

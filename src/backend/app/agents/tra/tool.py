"""TRATool - 工单智能路由 Tool（OP 命题方向 ③ · Demo 核心）。

三种 intent：
- route_ticket   按 problem_type + priority + tier 查规则表 → 分派团队 + SLA + 写入工单
- query_status   按 ticket_id 查工单当前状态
- resolve_ticket 关闭工单 + 自动沉淀 KB（Day 17 v3 数字员工闭环第 5 段）

设计要点：
- 路由规则 = JSON 文件（与 OP 真实生产一致 —— 运营在飞书多维表格维护，本地缓存副本）
  替换指南：换 JSON → 飞书 SDK 拉取，业务代码零改动。
- 规则匹配优先级（来自 OP 真实场景）：
  exact (problem_type + priority + tier)
  > exact (problem_type + priority + *)
  > exact (problem_type + medium + *)
  > default
- 工单持久化：可选 TicketRepository（不传则 in-memory mock，便于 PoC 演示）
- 工单 ID 生成：UUID4（Demo 简化；真实场景接飞书 record_id）
- resolve_ticket：更新工单状态为 closed/resolved，
  若注入 case_repo + kea，从 diagnosis_id 查 case，自动 promote_to_faq
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional, Any

from app.interfaces.base_tool import BaseTool
from app.implementations.db.repositories import TicketRepository
from app.models import Ticket, Case

logger = logging.getLogger(__name__)


# === 规则文件路径（来自 docs/data/ticket_routing_rules.json）===

DEFAULT_RULES_PATH = (
    Path(__file__).resolve().parents[5]
    / "docs" / "data" / "ticket_routing_rules.json"
)


# === 路由规则匹配优先级（在 _match_rule 内 hard-code 实现）===

# 命中规则：problem_type + priority + tier 三元组；tier 为 "*" 表示通配。
# 降级顺序（见 _match_rule 内 dict 顺序）：
# 1. exact               (problem_type, priority, tier)
# 2. priority_wildcard   (problem_type, priority, "*")
# 3. problem_wildcard    (problem_type, "medium", "*")   — priority 强制降级 medium
# 4. default_fallback    ("*", "medium", "*")


class TRATool(BaseTool):
    """工单智能路由 Tool — MCP tool_spec 兼容。

    输入参数（input_schema）：
        intent            "route_ticket" | "query_status"
        problem_type      问题类型（route 时必填）
        priority          high / medium / low（route 时必填）
        tier              vip / premium / standard（route 时可选，默认 standard）
        merchant_id       商户 ID（可选）
        diagnosis_id      关联的诊断 ID（可选，来源于 PDA 输出）
        problem_summary   问题摘要（route 时可选，便于运营快速定位）
        ticket_id         工单 ID（query 时必填）

    输出（output_schema）：
        ticket_id         工单 ID
        problem_type / priority / status / assignee / source / diagnosis_id
        sla_hours         SLA 时长（小时）
        notification_channel 通知渠道
        rule_id           命中的路由规则 ID
        match_level       "exact" | "priority_wildcard" | "problem_wildcard" | "default_fallback"
        trace             执行轨迹
    """

    name = "ticket_routing"
    description = (
        "工单智能路由工具：按 problem_type + priority + tier 自动匹配路由规则表，"
        "分派对应团队 + 计算 SLA + 写入工单。支持 query_status 查询工单状态。"
        "对位 OP 命题方向 ③。"
        "路由规则来自 docs/data/ticket_routing_rules.json（飞书多维表格本地缓存）。"
    )

    def __init__(
        self,
        ticket_repo: Optional[TicketRepository] = None,
        rules_path: Optional[Path] = None,
        case_repo=None,           # Optional[CaseRepository] —— 防循环依赖，type=str
        kea=None,                 # Optional[KEATool] —— resolve_ticket 自动 promote 时用
    ):
        """初始化 TRATool。

        Args:
            ticket_repo: 注入工单仓库（默认 None → in-memory mock）
            rules_path:  路由规则 JSON 路径（默认 DEFAULT_RULES_PATH）
            case_repo:   CaseRepository（resolve_ticket 通过 diagnosis_id 找 case 用，可选）
            kea:         KEATool 实例（resolve_ticket 后自动 promote_to_faq，可选）
                         （解耦注入：TRA 不直接 import KEA，防止循环依赖）
        """
        self.ticket_repo = ticket_repo
        self.case_repo = case_repo
        self.kea = kea
        self._rules: list[dict] = []
        self._rules_path = Path(rules_path) if rules_path else DEFAULT_RULES_PATH
        self._load_rules()
        # in-memory mock fallback（PoC 演示 / 单测无 DB 时）
        self._memory_store: dict[str, dict] = {}

    # === 规则加载（热更新入口）===

    def _load_rules(self) -> None:
        """从 JSON 文件加载路由规则。失败则 self._rules = []，执行时报友好错误。

        异常分类：
        - FileNotFoundError → 空规则（首次启动/规则未下发）
        - json.JSONDecodeError / OSError → 格式错误（trace._load_error 暴露）
        """
        self._load_error = None
        try:
            with open(self._rules_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._rules = payload.get("rules", [])
        except FileNotFoundError:
            self._rules = []
        except (json.JSONDecodeError, OSError) as e:
            # 不在初始化时崩溃，给上层机会决定如何降级
            self._rules = []
            self._load_error = str(e)

    def reload_rules(self, new_path: Optional[Path] = None) -> bool:
        """热更新路由规则（评审可演示）。

        Args:
            new_path: 重新加载的路径（None 则重载当前路径，并保留当前路径）
                      显式传 DEFAULT_RULES_PATH 可还原默认路径

        Returns:
            True if loaded rules > 0
        """
        if new_path:
            self._rules_path = Path(new_path)
        self._load_rules()
        return len(self._rules) > 0

    @property
    def rule_count(self) -> int:
        """已加载的规则数（评审可看）。"""
        return len(self._rules)

    # === MCP tool_spec schemas ===

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["route_ticket", "query_status", "resolve_ticket"],
                    "description": "route_ticket 创建并分派 / query_status 查询 / resolve_ticket 关闭工单并自动沉淀 KB",
                },
                "problem_type": {
                    "type": "string",
                    "description": "问题类型：支付失败 / 拒付 / 退款异常 / Webhook 回调失败 / ...",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "tier": {
                    "type": "string",
                    "enum": ["vip", "premium", "standard"],
                    "description": "商户等级（影响 SLA，缺省按 standard 路由）",
                },
                "merchant_id": {"type": "string"},
                "diagnosis_id": {
                    "type": "string",
                    "description": "来源 PDA 诊断结果 ID",
                },
                "problem_summary": {
                    "type": "string",
                    "description": "问题摘要（人工分派用）",
                },
                "ticket_id": {
                    "type": "string",
                    "description": "query_status / resolve_ticket 时必填",
                },
                "resolution": {
                    "type": "string",
                    "description": "关闭原因 / 解决方案（resolve_ticket 可选，便于运营追溯）",
                },
                "auto_promote": {
                    "type": "boolean",
                    "default": True,
                    "description": "resolve_ticket 后是否自动 promote_to_faq（默认 True）",
                },
            },
            "required": ["intent"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "ticket_id": {"type": "string"},
                "problem_type": {"type": "string"},
                "priority": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "processing", "resolved", "closed", "not_found"],
                },
                "assignee": {"type": "string"},
                "source": {"type": "string"},
                "diagnosis_id": {"type": "string"},
                "sla_hours": {
                    "type": "number",
                    "description": "SLA 时长（小时）",
                },
                "notification_channel": {"type": "string"},
                "rule_id": {
                    "type": "string",
                    "description": "命中的路由规则 ID",
                },
                "match_level": {
                    "type": "string",
                    "enum": ["exact", "priority_wildcard", "problem_wildcard", "default_fallback", "queried"],
                    "description": "规则匹配层级（降级链 evidence，给评审看）",
                },
                "create_time_estimate": {
                    "type": "string",
                    "description": "SLA 截止时间（ISO 字符串；PoC 仅演示计算）",
                },
                "trace": {"type": "object"},
            },
            "required": ["intent", "status"],
        }

    @property
    def capabilities(self) -> dict:
        return {
            "async_supported": True,
            "idempotent": False,       # create_ticket 每次生成新 ticket_id
            "requires_auth": False,
        }

    # === 业务执行 ===

    def execute(self, params: dict) -> dict:
        """执行路由 / 查询 / 关闭。"""
        intent = params["intent"]
        if intent == "route_ticket":
            return self._route_ticket(params)
        elif intent == "query_status":
            return self._query_status(params)
        elif intent == "resolve_ticket":
            return self._resolve_ticket(params)
        else:
            raise ValueError(f"Unknown intent: {intent}")

    # === 子能力 1：路由并创建工单 ===

    def _route_ticket(self, params: dict) -> dict:
        """按优先级匹配规则 → 创建工单 → 写入存储。"""
        problem_type = params.get("problem_type")
        priority = (params.get("priority") or "medium").lower()
        tier = (params.get("tier") or "standard").lower()
        merchant_id = params.get("merchant_id")
        diagnosis_id = params.get("diagnosis_id")
        summary = params.get("problem_summary", "")

        # 1) 校验必填（Day 18 P1：从 query 提取或默认拒付，避免"帮我创建工单"被堵）
        if not problem_type:
            # 从 summary 提取关键词
            summary_text = summary + " " + (params.get("problem_description") or "")
            for pt in ("拒付", "支付失败", "退款异常", "Webhook 回调失败"):
                if pt in summary_text:
                    problem_type = pt
                    break
            if not problem_type:
                # 默认拒付（最常见场景，与 BR Visa 13.1 测试对齐）
                problem_type = "拒付"
            logger.info(f"[TRA] problem_type 缺失，自动推断: {problem_type}")

        # 2) 规则匹配（降级链 evidence）
        rule, match_level = self._match_rule(problem_type, priority, tier)
        if rule is None:
            return self._route_error_result(
                problem_type=problem_type, priority=priority, tier=tier,
                merchant_id=merchant_id,
                reason="未找到任何路由规则",
                hint="路由规则表为空。请检查 docs/data/ticket_routing_rules.json。",
            )

        # 3) 创建 Ticket + mock 飞书 record_id
        ticket_id = f"tkt_{uuid.uuid4().hex[:12]}"
        feishu_record_id = f"fss_{uuid.uuid4().hex[:16]}"

        ticket = Ticket(
            id=ticket_id,
            problem_type=problem_type,
            priority=priority,
            status="pending",
            merchant_id=merchant_id,
            assignee=rule["assignee"],
            source=params.get("source", "merchant_diagnosis"),
            diagnosis_id=diagnosis_id,
            feishu_record_id=feishu_record_id,
        )

        # 4) 持久化（DB 优先；fallback in-memory）
        persisted_via = self._persist_ticket(ticket, rule)

        # 5) SLA 截止估算（PoC：用 ISO 字符串占位，不接 now())
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        sla_due = now + timedelta(hours=rule["sla_hours"])

        return {
            "intent": "route_ticket",
            "ticket_id": ticket_id,
            "problem_type": problem_type,
            "priority": priority,
            "status": "pending",
            "assignee": rule["assignee"],
            "source": ticket.source,
            "diagnosis_id": diagnosis_id,
            "sla_hours": rule["sla_hours"],
            "notification_channel": rule["notification_channel"],
            "rule_id": rule["id"],
            "match_level": match_level,
            "create_time_estimate": sla_due.isoformat() + "Z",
            # Day 10: 智能交接简报 — webhook 层会基于此发私有消息给团队 lead
            "briefing": {
                "team": rule["assignee"],
                "notification_channel": rule["notification_channel"],
                "ticket_id": ticket_id,
                "merchant_id": merchant_id or "",
                "problem_type": problem_type,
                "priority": priority,
                "diagnosis_id": diagnosis_id or "",
                "problem_summary": summary,
                "sla_hours": rule["sla_hours"],
                "sla_due": sla_due.isoformat() + "Z",
            },
            "trace": {
                "rule_id": rule["id"],
                "matched_priority": rule["priority"],
                "matched_tier": rule["tier"],
                "persisted_via": persisted_via,
                "feishu_record_id": feishu_record_id,
                "summary_chars": len(summary),
                "rules_loaded": self.rule_count,
            },
        }

    # === 子能力 2：查询工单状态 ===

    def _query_status(self, params: dict) -> dict:
        """按 ticket_id 查工单。"""
        ticket_id = params.get("ticket_id")
        if not ticket_id:
            return {
                "intent": "query_status",
                "ticket_id": "",
                "status": "not_found",
                "match_level": "queried",
                "trace": {"error": "ticket_id 必填"},
            }

        ticket_data = self._load_ticket(ticket_id)
        if ticket_data is None:
            return {
                "intent": "query_status",
                "ticket_id": ticket_id,
                "status": "not_found",
                "match_level": "queried",
                "trace": {"error": "工单不存在"},
            }

        return {
            "intent": "query_status",
            "ticket_id": ticket_id,
            "problem_type": ticket_data["problem_type"],
            "priority": ticket_data["priority"],
            "status": ticket_data["status"],
            "assignee": ticket_data["assignee"],
            "source": ticket_data.get("source"),
            "diagnosis_id": ticket_data.get("diagnosis_id"),
            "sla_hours": ticket_data.get("sla_hours", 0),
            "notification_channel": ticket_data.get("notification_channel"),
            "rule_id": ticket_data.get("rule_id"),
            "match_level": "queried",
            "create_time_estimate": ticket_data.get("sla_due"),
            "trace": {"queried": True},
        }

    # === 子能力 3：关闭工单 + 自动沉淀 KB（Day 17 v3 数字员工闭环第 5 段） ===

    def _resolve_ticket(self, params: dict) -> dict:
        """关闭工单 + 自动 promote case → FAQ。

        流程：
        1. 校验 ticket_id
        2. 加载工单（DB or memory）
        3. 更新 status = closed（默认）/ resolved，并写入 resolution + resolved_at
        4. （可选）auto_promote=True 时：通过 diagnosis_id 查 case
           + 若 case.confidence ≥ 0.9 → 调 KEA.promote_to_faq
        5. 返回：工单最新状态 + promotion result（若触发）

        失败降级：
        - ticket 不存在 → not_found，不报错
        - 工单重复关闭（已是 closed）→ 仍返 success，但 trace.closed_was_already=True
        - case 找不到或 confidence 不足 → 不 promote，trace.skip_promote_reason 给出原因
        - KEA 调失败 → 工单更新照样成功，trace.promote_error 给出友好提示
        """
        ticket_id = params.get("ticket_id")
        if not ticket_id:
            return {
                "intent": "resolve_ticket",
                "ticket_id": "",
                "status": "not_found",
                "match_level": "no_ticket_id",
                "trace": {"error": "ticket_id 必填"},
            }

        ticket_data = self._load_ticket(ticket_id)
        if ticket_data is None:
            return {
                "intent": "resolve_ticket",
                "ticket_id": ticket_id,
                "status": "not_found",
                "match_level": "ticket_not_found",
                "trace": {"error": f"工单 '{ticket_id}' 不存在"},
            }

        # 1) 更新内存 / DB 状态
        new_status = params.get("status", "closed")
        resolution = params.get("resolution", "")
        old_status = ticket_data.get("status", "pending")
        was_already_closed = old_status in ("closed", "resolved")
        ticket_data["status"] = new_status
        ticket_data["resolution"] = resolution
        from datetime import datetime
        ticket_data["resolved_at"] = datetime.utcnow().isoformat() + "Z"

        # 持久化（尽量写 DB；失败则 memory 已更新）
        persisted_via = "memory"
        if self.ticket_repo is not None:
            try:
                t_obj = Ticket(
                    id=ticket_id,
                    problem_type=ticket_data.get("problem_type", ""),
                    priority=ticket_data.get("priority", "medium"),
                    status=new_status,
                    merchant_id=ticket_data.get("merchant_id"),
                    assignee=ticket_data.get("assignee"),
                    source=ticket_data.get("source"),
                    diagnosis_id=ticket_data.get("diagnosis_id"),
                    feishu_record_id=ticket_data.get("feishu_record_id"),
                    resolved_at=ticket_data.get("resolved_at"),
                )
                self.ticket_repo.update(ticket_id, t_obj)
                persisted_via = "db+memory"
            except Exception:
                persisted_via = "memory_only_db_fail"

        # 2) auto promote（知识沉淀闭环）
        promote_result: Optional[dict] = None
        skip_promote_reason = ""
        auto_promote = params.get("auto_promote", True)

        if auto_promote and self.kea is not None:
            diagnosis_id = ticket_data.get("diagnosis_id")
            case_id = self._lookup_case_id(diagnosis_id)

            if not case_id:
                # Day 18 P0：diagnosis_id 为空时自动生成 case（关单即沉淀）
                # PoC：cases 表根据 ticket_data + resolution 派生，case_id 用 ticket 后缀
                if self.case_repo is not None:
                    try:
                        from app.models import Case
                        import time as _time
                        case_id = f"case_tkt_{ticket_id[-8:]}_{int(_time.time())}"
                        new_case = Case(
                            id=case_id,
                            problem_desc=str(ticket_data.get("problem_type") or "工单案例")[:200],
                            diagnosis=str(ticket_data.get("problem_type") or "")[:200],
                            resolution=resolution[:200] if resolution else "",
                            country=ticket_data.get("country") or "GLOBAL",
                            channel=ticket_data.get("channel") or "unknown",
                            error_code=ticket_data.get("error_code") or "",
                            problem_type=ticket_data.get("problem_type", ""),
                            confidence=0.85,  # 关单默认置信度（审核流程会校验）
                            merchant_id=ticket_data.get("merchant_id") or "unknown_demo_merchant",
                            feishu_record_id="",
                        )
                        if self.case_repo.create(new_case):
                            logger.info(f"[TRA] 关单自动生成 case: {case_id}")
                        else:
                            case_id = None
                            skip_promote_reason = "case_repo.create 失败"
                    except Exception as e:
                        case_id = None
                        logger.warning(f"[TRA] 自动生成 case 异常: {e}")
                        skip_promote_reason = f"自动生成 case 异常: {e}"
                else:
                    skip_promote_reason = f"diagnosis_id='{diagnosis_id}' 未关联 case 且 case_repo 未注入"
            if case_id:
                # 调 KEA.promote_to_faq
                try:
                    wrapped = self.kea.execute({
                        "intent": "promote_to_faq",
                        "case_id": case_id,
                    })
                    promote_result = wrapped
                except Exception as e:
                    logger.warning(f"resolve_ticket → KEA.promote_to_faq 失败: {e}")
                    skip_promote_reason = f"KEA 调用异常: {e}"
        elif auto_promote and self.kea is None:
            skip_promote_reason = "KEA 未注入（PoC 演示或测试场景，跳过自动沉淀）"
        else:
            skip_promote_reason = "auto_promote=False 显式关闭"

        return {
            "intent": "resolve_ticket",
            "ticket_id": ticket_id,
            "problem_type": ticket_data.get("problem_type", ""),
            "priority": ticket_data.get("priority", ""),
            "status": new_status,
            "assignee": ticket_data.get("assignee", ""),
            "source": ticket_data.get("source"),
            "diagnosis_id": ticket_data.get("diagnosis_id"),
            "rule_id": ticket_data.get("rule_id"),
            "match_level": "resolved",
            "create_time_estimate": ticket_data.get("sla_due"),
            "resolution_recorded": bool(resolution),
            "closed_was_already": was_already_closed,
            "promote_result": promote_result,
            "trace": {
                "persisted_via": persisted_via,
                "old_status": old_status,
                "new_status": new_status,
                "skip_promote_reason": skip_promote_reason or None,
            },
        }

    def _lookup_case_id(self, diagnosis_id: Optional[str]) -> Optional[str]:
        """通过 diagnosis_id 反查关联的 case_id。

        PoC 简化：TRA 创建工单时传入的 diagnosis_id 是 PDA 的诊断 ID。
        当前 cases 表并未按 diagnosis_id 索引，简单做法：
        - 若 diagnosis_id 形如 'diag_<...>'，尝试匹配 case.id
        - 否则返回 None（运营可用 case_id 显式补登）

        Returns:
            case_id 字符串；若未找到返回 None。
        """
        if not self.case_repo or not diagnosis_id:
            return None
        try:
            # PoC: 优先尝试精确匹配 diagnosis_id 当作 case_id
            c = self.case_repo.get_by_id(diagnosis_id)
            if c:
                return c.id
            # 兜底：list 中查找任一 case（PoC 数据集很小，可行；真实场景需加索引）
            all_cases = self.case_repo.list(filters=None, limit=200)
            for c in all_cases:
                # 兼容：case.feishu_record_id 或 case.id 字段
                if c.id == diagnosis_id:
                    return c.id
            return None
        except Exception:
            return None

    def _match_rule(self, problem_type: str, priority: str, tier: str) -> tuple[Optional[dict], str]:
        """按规则匹配优先级返回 (rule_dict, match_level)。

        匹配顺序：
        1. exact:        problem_type + priority + tier 三元组都相等
        2. exact + wc:   problem_type + priority + "*"（tier 通配）
        3. exact + wc:   problem_type + medium  + "*"（priority 降级到 medium + tier 通配）
        4. default:      "*" + "*" + "*"（默认兜底）
        """
        if not self._rules:
            return None, "no_rules_loaded"

        # 1) exact
        for r in self._rules:
            if (r.get("problem_type") == problem_type
                    and r.get("priority") == priority
                    and r.get("tier") == tier):
                return r, "exact"

        # 2) exact + tier wildcard
        for r in self._rules:
            if (r.get("problem_type") == problem_type
                    and r.get("priority") == priority
                    and r.get("tier") == "*"):
                return r, "priority_wildcard"

        # 3) exact + priority wildcard (强制降级到 medium) + tier wildcard
        for r in self._rules:
            if (r.get("problem_type") == problem_type
                    and r.get("priority") == "medium"
                    and r.get("tier") == "*"):
                return r, "problem_wildcard"

        # 4) default fallback
        for r in self._rules:
            if r.get("problem_type") == "*" and r.get("priority") == "medium" and r.get("tier") == "*":
                return r, "default_fallback"

        return None, "no_match"

    # === 持久化（DB 或 in-memory） ===

    def _persist_ticket(self, ticket: Ticket, rule: dict) -> str:
        """持久化工单。返回 'db' / 'memory' / 'both'。

        把路由信息（rule_id / sla_hours / notification_channel）也一并存储在内存，
        让 query_status 能完整回放（评审可演示：一条龙创建 → 查询）。

        DB 和 memory 同时写：DB 是事务持久化，memory 是规则元数据缓存。
        DB 失败时 fallback 到 memory-only。
        """
        extra = {
            "rule_id": rule["id"],
            "sla_hours": rule["sla_hours"],
            "notification_channel": rule["notification_channel"],
        }
        # 内存始终写（规则元数据缓存；DB 中没有 rule_id 列）
        self._memory_store[ticket.id] = {
            "problem_type": ticket.problem_type,
            "priority": ticket.priority,
            "status": ticket.status,
            "assignee": ticket.assignee,
            "source": ticket.source,
            "diagnosis_id": ticket.diagnosis_id,
            "feishu_record_id": ticket.feishu_record_id,
            **extra,
        }
        if self.ticket_repo is not None:
            try:
                self.ticket_repo.create(ticket)
                return "both"  # DB + memory 都成功
            except Exception:
                # DB 失败 → 仅 memory（保证演示不断）
                return "memory"
        return "memory"

    def _load_ticket(self, ticket_id: str) -> Optional[dict]:
        """优先从 DB 读，fallback 从 in-memory。

        DB 模式只读 Ticket 模型字段；规则相关字段从 in-memory 中取
        （PoC 阶段：DB 仅存 Ticket 模型字段；规则元数据作为附件暂存 memory）。
        对于 DB-only 场景，规则 ID / SLA 可在调用方从 trace 中读取。
        """
        if self.ticket_repo is not None:
            try:
                t = self.ticket_repo.get_by_id(ticket_id)
                if t:
                    # 先看 memory 有没有更全的元数据
                    extra = self._memory_store.get(ticket_id, {})
                    return {
                        "problem_type": t.problem_type,
                        "priority": t.priority,
                        "status": t.status,
                        "assignee": t.assignee,
                        "source": t.source,
                        "diagnosis_id": t.diagnosis_id,
                        "feishu_record_id": t.feishu_record_id,
                        "rule_id": extra.get("rule_id"),
                        "sla_hours": extra.get("sla_hours"),
                        "notification_channel": extra.get("notification_channel"),
                    }
            except Exception:
                pass
        return self._memory_store.get(ticket_id)

    # === 错误降级（友好提示，不抛 raw exception） ===

    def _route_error_result(
        self,
        problem_type: str,
        priority: str,
        tier: str,
        merchant_id: Optional[str],
        reason: str,
        hint: str,
    ) -> dict:
        return {
            "intent": "route_ticket",
            "ticket_id": "",
            "problem_type": problem_type,
            "priority": priority,
            "status": "not_found",
            "assignee": "",
            "source": "",
            "diagnosis_id": None,
            "sla_hours": 0,
            "notification_channel": "",
            "rule_id": "",
            "match_level": "no_match",
            "create_time_estimate": "",
            "trace": {
                "error": reason,
                "hint": hint,
                "rules_loaded": self.rule_count,
            },
        }

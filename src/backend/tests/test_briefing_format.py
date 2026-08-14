"""Day 17 v3 交接简报 + 触发逻辑测试。

覆盖：
1. _format_briefing_text 5 段式输出（👤 商户 / ❓ 问题 / 🤖 AI 已诊断 / 📋 已尝试 / ⚠️ 还缺 / 🎯 下一步）
2. 低置信度触发交接（missing_evidence）
3. 商户侧 fmt_tra：低置信度 → "转专家跟进"；高置信度 → "✅ 工单已创建"
4. confidence_label 中文标签映射
5. reason_name 中文化
"""
from unittest.mock import MagicMock

import pytest

from app.implementations.feishu.webhook import (
    FeishuWebhookHandler,
    _confidence_label,
    _translate_reason_name,
)

# `_format_briefing_text` 是 class 内 staticmethod，直接访问
_format_briefing_text = FeishuWebhookHandler._format_briefing_text


# === _confidence_label ===

class TestConfidenceLabel:
    def test_high_returns_very_high(self):
        assert _confidence_label(0.9) == "很高"

    def test_medium_high(self):
        assert _confidence_label(0.7) == "较高"

    def test_medium(self):
        assert _confidence_label(0.5) == "中等"

    def test_low(self):
        assert _confidence_label(0.3) == "较低"

    def test_boundary_85(self):
        assert _confidence_label(0.85) == "很高"

    def test_invalid_returns_low(self):
        """None / 非 float → "较低"（友好降级，不抛异常，避免 briefing 渲染炸掉）。"""
        assert _confidence_label(None) == "较低"
        assert _confidence_label("garbage") == "较低"


# === _translate_reason_name ===

class TestTranslateReasonName:
    def test_known_english_to_chinese(self):
        assert _translate_reason_name("Merchandise/Services Not Received") == "商品/服务未收到"

    def test_known_mc(self):
        assert _translate_reason_name("No Cardholder Authorization") == "未获得持卡人授权"

    def test_unknown_passthrough(self):
        assert _translate_reason_name("Some Unknown Reason") == "Some Unknown Reason"

    def test_empty(self):
        assert _translate_reason_name("") == ""


# === _format_briefing_text (5 段式) ===

class TestFormatBriefingText:
    @staticmethod
    def _make_briefing(**overrides) -> dict:
        base = {
            "ticket_id": "tkt_abc123",
            "team": "技术团队-L2",
            "priority": "high",
            "sla_hours": 4,
            "sla_due": "2026-08-15T18:00:00+08:00",
            "diagnosis_id": "diag_20260815_xxxxxx",
            "problem_type": "拒付",
            "user_query": "Visa 13.1 拒付好多，咋办？",
            "merchant_context": {
                "merchant_id": "M001",
                "country": "NL",
                "industry": "retail",
                "avg_amount": 50,
                "target_users": "B2C",
            },
            "ai_channel": "Visa",
            "ai_error_code": "13.1",
            "ai_reason_name_cn": "商品/服务未收到",
            "ai_confidence": 0.65,
            "ai_confidence_label": "较高",
            "ai_recommended_actions": [
                "准备申诉材料（物流单号 + 签收记录）",
                "在 OP 商户后台 → 风控管理开启 RDR",
                "发货后主动给买家发物流信息",
            ],
            "ai_missing_fields": [],
        }
        base.update(overrides)
        return base

    def test_5_sections_present(self):
        """5 段式标题必须齐全：👤 / ❓ / 🤖 / 📋 / 🎯 + 工单元数据。"""
        text = _format_briefing_text(
            self._make_briefing(),
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        assert "【AI 交接简报" in text
        assert "👤 **商户**" in text
        assert "❓ **问题类型**" in text
        assert "❓ **问题原文**" in text
        assert "🤖 **AI 已诊断**" in text
        assert "📋 **已尝试方案**" in text
        assert "🎯 **建议下一步**" in text
        assert "📨 **工单**" in text

    def test_merchant_profile_serialized(self):
        """商户画像：国家/行业/客单/客户 都拼上。"""
        briefing = self._make_briefing()
        briefing["merchant_context"] = {
            "merchant_id": "M_BR_001",
            "country": "BR",
            "industry": "subscription",
            "avg_amount": 29.9,
            "target_users": "B2C",
        }
        text = _format_briefing_text(
            briefing,
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        assert "**BR**" in text
        assert "**subscription**" in text
        assert "$29.9" in text

    def test_confidence_pct_shown(self):
        """置信度：标签 + 百分数。"""
        text = _format_briefing_text(
            self._make_briefing(ai_confidence=0.85, ai_confidence_label="很高"),
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        assert "**很高**" in text
        assert "85%" in text

    def test_attempted_actions_dedup_and_limit(self):
        """已尝试方案：保序去重 + 限 3 条。"""
        text = _format_briefing_text(
            self._make_briefing(ai_recommended_actions=[
                "动作 1", "动作 2", "动作 3", "动作 4", "动作 5",
                "动作 1",  # 重复
            ]),
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        # 只列 3 条
        assert "动作 1" in text
        assert "动作 4" not in text  # 限 3 条，第 4 条开始就没了
        assert "动作 5" not in text

    def test_missing_fields_block_present(self):
        """缺什么：missing_fields 非空时显示。"""
        text = _format_briefing_text(
            self._make_briefing(ai_missing_fields=["具体错误码", "订单号"]),
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        assert "⚠️ **还缺什么**" in text
        assert "具体错误码" in text
        assert "订单号" in text

    def test_missing_block_from_low_conf(self):
        """缺什么为空但置信度 < 0.7 → 提示"AI 置信度偏低"。"""
        text = _format_briefing_text(
            self._make_briefing(ai_confidence=0.5, ai_missing_fields=[]),
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        assert "⚠️ **还缺什么**" in text
        assert "AI 置信度偏低" in text

    def test_no_attempted_no_block(self):
        """已尝试方案为空 → 不显示该段（避免空标题）。"""
        text = _format_briefing_text(
            self._make_briefing(ai_recommended_actions=[]),
            chat_id="oc_xxx",
            merchant_user_id="ou_xxx",
        )
        assert "📋 **已尝试方案**" not in text

    def test_chat_and_open_id_truncated(self):
        """对话来源：chat_id / open_id 截断 24 字符。"""
        long_chat = "oc_" + "x" * 50
        long_user = "ou_" + "y" * 50
        text = _format_briefing_text(
            self._make_briefing(),
            chat_id=long_chat,
            merchant_user_id=long_user,
        )
        # 出现截断（24 字符内含 `...` 不必要 — 这里只是确认不爆栈）
        assert "chat_id=" in text
        assert "open_id=" in text
        # 不应包含完整 50 字符
        assert ("x" * 50) not in text
        assert ("y" * 50) not in text


# === _fmt_tra 商户侧展示 ===

class TestFmtTra:
    """商户看到的工单消息：低置信度 vs 高置信度。"""

    @staticmethod
    def _make_tra_result(confidence, root_causes=None, briefing=None):
        """模拟链式 TRA 结果（含 briefing/AI 上下文）。"""
        br = briefing or {}
        return {
            "intent": "ticket_routing",
            "tool_result": {
                "success": True,
                "data": {
                    "ticket_id": "tkt_test_001",
                    "assignee": "技术团队-L2",
                    "sla_hours": 4,
                    "problem_type": "拒付",
                    "briefing": {
                        "ai_root_causes": root_causes or [],
                        "ai_confidence": confidence,
                        **br,
                    },
                },
            },
            "trace": {},
        }

    def test_high_confidence_short_message(self):
        """高置信度（≥0.7）→ 商户看到简洁 '✅ 工单已创建'。"""
        result = self._make_tra_result(0.85, root_causes=["商品未收到"])
        text = FeishuWebhookHandler.format_reply(result)
        assert "✅ 工单已创建" in text
        assert "tkt_test_001" in text
        # 不应说"转专家跟进"
        assert "转专家" not in text

    def test_low_confidence_handoff_message(self):
        """低置信度（<0.7）→ 商户看到'转专家跟进'。"""
        result = self._make_tra_result(0.5, root_causes=["商品未收到"])
        text = FeishuWebhookHandler.format_reply(result)
        assert "🤝" in text
        assert "转" in text
        assert "技术团队-L2" in text  # 负责人
        assert "tkt_test_001" in text

    def test_no_root_causes_handoff_message(self):
        """根因为空 → 也算低置信度 → 转专家。"""
        result = self._make_tra_result(0.85, root_causes=[])
        text = FeishuWebhookHandler.format_reply(result)
        assert "🤝" in text
        assert "转" in text


# === _maybe_chain_to_tra 触发逻辑（low conf + missing evidence） ===

class TestTriggerLogic:
    """低置信度 / 缺证据也会触发交接。"""

    def _make_handler(self):
        orch = MagicMock()
        frontend = MagicMock()
        handler = FeishuWebhookHandler(orchestrator=orch, frontend=frontend)
        # mock registry：让 TRA 调用存在
        handler.orchestrator.registry.get = MagicMock(return_value=lambda: None)
        handler.orchestrator.registry.safe_execute = MagicMock(return_value={
            "success": True,
            "data": {
                "ticket_id": "tkt_chain_test",
                "assignee": "技术团队-L2",
                "sla_hours": 4,
                "briefing": {
                    "ticket_id": "tkt_chain_test",
                    "team": "技术团队-L2",
                    "priority": "medium",
                    "sla_hours": 4,
                },
            },
        })
        return handler

    def test_low_confidence_triggers_chain(self):
        """PDA confidence < 0.5 → 也触发链式 TRA。"""
        handler = self._make_handler()
        pda_result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": True, "data": {
                "problem_type": "支付失败",
                "confidence": 0.3,  # 低于 0.5
                "root_causes": ["签名验证失败"],
                "error_code": "INVALID_SIGNATURE",
            }},
            "trace": {"params": {"merchant_id": "M001"}},
        }
        chain = handler._maybe_chain_to_tra(
            pda_result, user_query="支付失败了", user_id="ou_xxx", chat_id="oc_xxx"
        )
        assert chain is not None, "低置信度应触发交接"
        assert chain["intent"] == "ticket_routing"

    def test_missing_error_code_triggers_chain(self):
        """无 error_code → 也触发交接。"""
        handler = self._make_handler()
        pda_result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": True, "data": {
                "problem_type": "Webhook 回调失败",
                "confidence": 0.8,
                "root_causes": ["回调超时"],
                # 注意：没有 error_code
            }},
            "trace": {"params": {"merchant_id": "M001"}},
        }
        chain = handler._maybe_chain_to_tra(
            pda_result, user_query="回调有问题", user_id="ou_xxx", chat_id="oc_xxx"
        )
        assert chain is not None, "无 error_code 应触发交接"

    def test_high_confidence_with_keywords_triggers(self):
        """高置信度 + 商户说"紧急"→ 触发（关键词优先）。"""
        handler = self._make_handler()
        pda_result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": True, "data": {
                "problem_type": "支付失败",
                "confidence": 0.9,
                "root_causes": ["签名验证失败"],
                "error_code": "INVALID_SIGNATURE",
            }},
            "trace": {"params": {"merchant_id": "M001"}},
        }
        chain = handler._maybe_chain_to_tra(
            pda_result, user_query="紧急！支付失败", user_id="ou_xxx", chat_id="oc_xxx"
        )
        assert chain is not None
        # 关键词命中 → priority=high
        assert chain["trace"]["priority"] == "high"

    def test_high_confidence_clear_evidence_no_keyword_no_chain(self):
        """高置信度 + 证据齐 + 无紧急词 + 非硬触发 problem_type → 不触发（让 PDA 自己给方案）。"""
        handler = self._make_handler()
        pda_result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": True, "data": {
                # 用 "退款异常"（不在 _PDA_CHAIN_PROBLEM_TYPES 里）
                # 也避开了"支付失败"硬触发，让 missing_evidence 检查生效
                "problem_type": "退款异常",
                "confidence": 0.9,
                "root_causes": ["退款流程未配置"],
                "error_code": "REFUND_NOT_CONFIGURED",
            }},
            "trace": {"params": {"merchant_id": "M001"}},
        }
        chain = handler._maybe_chain_to_tra(
            pda_result, user_query="退款异常，帮忙看看", user_id="ou_xxx", chat_id="oc_xxx"
        )
        assert chain is None, "这种情况下应让 PDA 直接给方案，不打扰人工"

    def test_problem_type_chain_triggers(self):
        """拒付/支付失败/Webhook 回调失败 → 必触发（即使高置信度）。"""
        handler = self._make_handler()
        pda_result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": True, "data": {
                "problem_type": "拒付",
                "confidence": 0.9,
                "root_causes": ["商品未收到"],
                "error_code": "13.1",
            }},
            "trace": {"params": {"merchant_id": "M001"}},
        }
        chain = handler._maybe_chain_to_tra(
            pda_result, user_query="拒付了好多", user_id="ou_xxx", chat_id="oc_xxx"
        )
        assert chain is not None, "拒付问题必触发交接"


# === upstream_diagnosis 传递（简报能拿到所有字段） ===

class TestUpstreamDiagnosisPropagation:
    """链式 TRA 上游诊断信息完整传递。"""

    def test_upstream_diagnosis_has_all_fields(self):
        """upstream_diagnosis 含 problem_type / root_causes / confidence / channel / error_code / reason_name_cn / missing_fields。"""
        handler = TestTriggerLogic()._make_handler()
        pda_result = {
            "intent": "payment_diagnosis",
            "tool_result": {"success": True, "data": {
                "problem_type": "拒付",
                "confidence": 0.65,
                "root_causes": ["买家说没收到"],
                "recommended_actions": ["准备物流证据", "开启 RDR"],
                "error_code": "13.1",
                "channel": "Visa",
                "missing_fields": [],
            }},
            "trace": {
                "params": {"merchant_id": "M001"},
                "code_specific_enriched": {
                    "error_code": "13.1",
                    "channel": "Visa",
                    "reason_name": "Merchandise/Services Not Received",
                },
            },
        }
        chain = handler._maybe_chain_to_tra(
            pda_result,
            user_query="Visa 13.1 拒付好多",
            user_id="ou_test_user",
            chat_id="oc_test_chat",
        )
        assert chain is not None
        upstream = chain["trace"]["upstream_diagnosis"]
        assert upstream["problem_type"] == "拒付"
        assert upstream["confidence"] == 0.65
        assert upstream["confidence_label"] in ("较高", "中等", "很高", "较低")
        assert upstream["channel"] == "Visa"
        assert upstream["error_code"] == "13.1"
        assert upstream["reason_name_cn"] == "商品/服务未收到"
        assert "准备物流证据" in upstream["recommended_actions"]

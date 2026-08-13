"""业务规则回归测试（Day 14 P1-5）。

背景：Day 14 真实飞书对话暴露了 4 类「AI 一本正经胡说」的问题：
1. 巴西 Pix / 荷兰 iDEAL 等本地支付被推荐「开启 3DS 验证」（3DS 只适用于卡组织）
2. 场景类问题（周末延迟）检索走错 collection，拿不到真实案例
3. Demo 占位数据（merchant.example.com）泄漏进商户可见的回答
4. error_code 缺失时被伪造成 ERR_UNKNOWN，导致证据全 miss 后瞎编

这个文件锁死这 4 条业务规则，防止后续改动回退。
"""

from __future__ import annotations

import pytest

from app.agents.orchestrator.orchestrator import Orchestrator
from app.agents.pda.tool import PDATool
from app.implementations.feishu.webhook import FeishuWebhookHandler, _sanitize
from legacy.agents.payment_diagnosis.evidence_store import (
    NON_CARD_CHANNELS,
    EvidenceStore,
)
from legacy.agents.payment_diagnosis.schemas import ProblemRecord


# 3DS 相关表述（中英文都算）
_3DS_TERMS = ("3ds", "3-d secure", "三域", "3d secure")


def _all_text(result: dict) -> str:
    """把诊断结果里所有商户可见文本拼起来（不含 evidence_chain 内部证据）。"""
    parts = list(result.get("root_causes", [])) + list(result.get("recommended_actions", []))
    return " ".join(parts).lower()


@pytest.fixture(scope="module")
def pda() -> PDATool:
    return PDATool()


# === 规则 1：本地/钱包支付方式不得推荐 3DS ===


class TestNonCardChannelsNo3DS:
    """Pix / iDEAL / UnionPay 等本地支付不走卡组织 3DS 认证。"""

    def test_pix_channel_does_not_recommend_3ds(self, pda):
        """BR Pix 周末延迟 → 不得出现 3DS（Pix 是巴西央行即时支付，无 3DS 概念）。"""
        result = pda.execute({
            "merchant_id": "m_rule_pix",
            "country": "BR",
            "channel": "Pix",
            "error_code": "",
            "query_text": "巴西 Pix 周末凌晨延迟",
        })
        text = _all_text(result)
        for term in _3DS_TERMS:
            assert term not in text, f"Pix 渠道不应推荐 3DS，实际输出: {text}"

    def test_ideal_channel_does_not_recommend_3ds(self, pda):
        """NL iDEAL → 不得出现 3DS（iDEAL 是银行直连，走 SCA 不是卡组织 3DS）。"""
        result = pda.execute({
            "merchant_id": "m_rule_ideal",
            "country": "NL",
            "channel": "iDEAL",
            "error_code": "",
            "query_text": "荷兰 iDEAL 支付失败率高",
        })
        text = _all_text(result)
        for term in _3DS_TERMS:
            assert term not in text, f"iDEAL 渠道不应推荐 3DS，实际输出: {text}"

    @pytest.mark.parametrize("channel", sorted(NON_CARD_CHANNELS))
    def test_config_snapshot_filters_3ds_for_non_card(self, channel):
        """证据源层面：非卡渠道拿不到 3DS 配置证据（根因治理，不靠 LLM 自觉）。"""
        store = EvidenceStore()
        items = store.lookup_config_snapshot("BR", channel=channel, problem_type="支付失败")
        for item in items:
            assert "3ds" not in (item.description or "").lower(), (
                f"{channel} 不应拿到 3DS 配置证据: {item.description}"
            )

    def test_config_snapshot_keeps_3ds_for_card_channel(self):
        """反向验证：Visa 等卡组织渠道仍然拿得到 3DS 配置（别过度过滤）。"""
        store = EvidenceStore()
        items = store.lookup_config_snapshot("BR", channel="Visa", problem_type="支付失败")
        assert any("3DS" in (i.description or "") for i in items), (
            "卡组织渠道应保留 3DS 配置证据"
        )


# === 规则 2：真实拒付码必须给出正确诊断 ===


class TestRealChargebackCodes:
    """Visa 13.1 / MC 4837 是 Demo 主场景，诊断内容必须落到真实业务语义。"""

    def test_visa_13_1_diagnosis_correct(self, pda):
        """Visa 13.1 = Merchandise/Services Not Received（未收到商品/服务）。"""
        result = pda.execute({
            "merchant_id": "m_rule_visa",
            "country": "US",
            "channel": "Visa",
            "error_code": "CB_13.1",
            "query_text": "美国 Visa 13.1 拒付好多怎么解决",
        })
        assert result["problem_type"] == "拒付"
        assert result["confidence"] >= 0.6, "命中真实拒付码应给出高置信度"
        # 证据链必须含真实规则或知识库命中（不是只有 config 占位）
        types = {e["type"] for e in result["evidence_chain"]}
        assert types & {"risk_rule", "knowledge_base"}, f"证据链无真实证据: {types}"
        text = _all_text(result)
        assert any(kw in text for kw in ("未收到", "拒付", "交付", "13.1")), (
            f"13.1 诊断未落到「未收到商品/服务」语义: {text}"
        )

    def test_mc_4837_diagnosis_correct(self, pda):
        """MC 4837 = No Cardholder Authorization（持卡人未授权）。"""
        result = pda.execute({
            "merchant_id": "m_rule_mc",
            "country": "GB",
            "channel": "Mastercard",
            "error_code": "CB_4837",
            "query_text": "英国 MC 4837 持卡人未授权怎么办",
        })
        assert result["problem_type"] == "拒付"
        types = {e["type"] for e in result["evidence_chain"]}
        assert types & {"risk_rule", "knowledge_base"}, f"证据链无真实证据: {types}"
        text = _all_text(result)
        assert any(kw in text for kw in ("授权", "拒付", "欺诈", "4837")), (
            f"4837 诊断未落到「持卡人未授权」语义: {text}"
        )


# === 规则 3：Demo 占位数据不得泄漏给商户 ===


class TestNoTestDataLeak:
    """商户可见文本里不允许出现 example.com / <DEMO_xxx> / 内部证据 ID。"""

    FORBIDDEN = ("example.com", "placeholder", "<demo_", "demo 占位")

    def test_no_example_com_in_output(self, pda):
        """Webhook 类问题最容易带出 webhook_url = https://merchant.example.com/webhook。"""
        result = pda.execute({
            "merchant_id": "m_rule_wh",
            "country": "US",
            "channel": "Visa",
            "error_code": "ERR_DEMO_WEBHOOK_TIMEOUT_001",
            "query_text": "美国 Webhook 回调失败",
        })
        reply = FeishuWebhookHandler._fmt_pda(result, {})
        low = reply.lower()
        for bad in self.FORBIDDEN:
            assert bad not in low, f"回复泄漏测试数据 '{bad}': {reply}"

    def test_sanitize_strips_placeholder_url(self):
        raw = "请检查 Webhook 地址 https://merchant.example.com/webhook 是否可达"
        assert "example.com" not in _sanitize(raw)

    def test_sanitize_strips_internal_evidence_id(self):
        raw = "命中规则 risk_rule_demo_001 与 config_demo_3DS_disabled_001"
        cleaned = _sanitize(raw)
        assert "risk_rule_demo_001" not in cleaned
        assert "config_demo_3DS_disabled_001" not in cleaned

    def test_sanitize_strips_markdown_stars(self):
        """飞书纯文本消息不渲染 Markdown，星号会字面显示。"""
        assert "**" not in _sanitize("**重点**：请联系客服")


# === 规则 4：error_code 缺失不得伪造 ERR_UNKNOWN ===


class TestNoFakeErrorCode:
    """Day 14 P0：_route_pda 曾用 ctx 默认值 ZZ/unknown/ERR_UNKNOWN 导致证据全 miss。"""

    def test_route_pda_does_not_inject_err_unknown(self):
        orch = Orchestrator(use_llm_fallback=False, chain_mode="single")
        orch.register_tool(PDATool())
        result = orch.route("巴西 Pix 周末凌晨延迟")
        params = result.get("trace", {}).get("params", {})
        assert params.get("error_code") != "ERR_UNKNOWN", "不得伪造 ERR_UNKNOWN"
        assert params.get("country") != "ZZ", "不得伪造 ZZ 国家码"
        assert params.get("query_text"), "必须把商户原话传给 PDA 做知识库检索"

    def test_scene_query_hits_case_collection(self):
        """场景类问题（延迟）必须去 cases_vec 检索，而不是只查 error_codes_vec。"""
        from app.implementations.rag.chroma_rag import COLLECTION_CASES

        store = EvidenceStore()
        problem = ProblemRecord(
            merchant_id="m1", country="BR", channel="Pix",
            error_code="", query_text="巴西 Pix 周末凌晨延迟",
        )
        assert COLLECTION_CASES in store.pick_collections(problem)

    def test_code_query_hits_error_code_collection(self):
        """错误码类问题必须查 error_codes_vec。"""
        from app.implementations.rag.chroma_rag import COLLECTION_ERROR_CODES

        store = EvidenceStore()
        problem = ProblemRecord(
            merchant_id="m1", country="US", channel="Visa",
            error_code="CB_13.1", query_text="美国 Visa 13.1 拒付",
        )
        assert COLLECTION_ERROR_CODES in store.pick_collections(problem)

    def test_irrelevant_recall_is_dropped(self):
        """不存在的国家/渠道/错误码 → 不应把无关知识当证据（否则 LLM 会编）。"""
        store = EvidenceStore()
        problem = ProblemRecord(
            merchant_id="m1", country="ZZ", channel="UnknownChannel",
            error_code="ERR_NONEXISTENT", query_text="支付有问题",
        )
        items = store.lookup_knowledge_base(problem)
        assert items == [], f"无关召回未被过滤: {[i.id for i in items]}"

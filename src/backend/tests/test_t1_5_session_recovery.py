"""Day 18 P2 回归测试：T1.5 模板选择（4 个用例）。

回归 T1.5 bug：商户先说「NL MasterCard 拒付」→ bot 反问 →
商户补「错误码是 13.1」→ 期望 bot 给出 PDA 5段 诊断
（problem_type='拒付'，category=not_received，channel=Mastercard）

历史 bug：_PDA_TEMPLATES 缺少跨 channel 兜底，导致三层 fallback 全 miss → 默认模板。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from app.agents.orchestrator import Orchestrator
from app.agents.orchestrator.routers import extract_pda_params
from app.implementations.feishu.webhook import (
    FeishuWebhookHandler,
    _PDA_DEFAULT_TEMPLATE,
)


@pytest.fixture
def orch():
    from app.agents.pda.tool import PDATool
    from app.agents.msa.tool import MSATool
    o = Orchestrator(use_llm_fallback=False)
    o.register_tool(PDATool())
    o.register_tool(MSATool())
    return o


def _default_template_used(reply: str) -> bool:
    """检测 reply 是否用了兜底默认模板（用 empathy 检测足够）。"""
    return _PDA_DEFAULT_TEMPLATE["empathy"].format(problem_type="拒付") in reply \
        or "对商户影响较大，我来帮你处理" in reply


def test_t1_5_cross_channel_picks_specific_template(orch):
    """T1.5 真实场景：channel=Mastercard + error_code=13.1 → 应给 not_received 通用模板。

    修复前：三层 fallback 全 miss → 默认模板（"拒付对商户影响较大"）
    修复后：命中新增的 ("拒付", "not_received", "Mastercard") 或 ("拒付", "not_received", None)
    """
    query_1 = "NL MasterCard 拒付，没收到错误码"
    e1 = extract_pda_params(query_1)
    query_2 = "错误码是 13.1，订单号 ORD-12345"

    merchant_ctx = {
        "merchant_id": "M_e2e_test",
        "country": e1["country"],
        "channel": e1["channel"],
    }
    result = orch.route(user_query=query_2, merchant_context=merchant_ctx)
    data = (result.get("tool_result") or {}).get("data") or {}

    # 走 PDA 主路径
    assert result.get("intent") == "payment_diagnosis", \
        f"期望 intent=payment_diagnosis，实际={result.get('intent')}"
    assert data.get("problem_type") == "拒付", \
        f"期望 problem_type='拒付'，实际={data.get('problem_type')!r}"

    # 关键：不应再走默认模板
    reply = FeishuWebhookHandler.format_reply(result)
    assert not _default_template_used(reply), \
        f"bot 不该用兜底默认模板！reply={reply[:200]}"
    # 应该命中 not_received 通用模板（含 "准备申诉材料" 或 "准备物流签收记录"）
    assert "准备申诉材料" in reply or "物流签收记录" in reply or "没收到货" in reply, \
        f"期望 not_received 模板，reply={reply[:200]}"


def test_t1_5_pure_visa_13_1_picks_visa_template(orch):
    """纯 Visa 13.1 场景：channel=Visa + error_code=13.1 → 精确命中 Visa 模板。"""
    query = "美国 Visa 13.1 拒付好多"
    result = orch.route(user_query=query, merchant_context={"merchant_id": "M_pure_visa"})
    data = (result.get("tool_result") or {}).get("data") or {}

    assert result.get("intent") == "payment_diagnosis"
    assert data.get("problem_type") == "拒付"

    reply = FeishuWebhookHandler.format_reply(result)
    # 精确命中 Visa 13.1 模板
    assert "Visa 13.1 拒付" in reply, f"期望标题含 'Visa 13.1 拒付'，reply={reply[:200]}"
    assert "Visa RDR" in reply, f"期望包含 Visa RDR，reply={reply[:200]}"
    assert not _default_template_used(reply)


def test_t1_5_pure_mc_4837_picks_mc_template(orch):
    """纯 MC 4837 场景：channel=Mastercard + error_code=4837 → 精确命中 MC 模板。"""
    query = "美国 MC 4837 拒付"
    result = orch.route(user_query=query, merchant_context={"merchant_id": "M_pure_mc"})
    data = (result.get("tool_result") or {}).get("data") or {}

    assert result.get("intent") == "payment_diagnosis"
    assert data.get("problem_type") == "拒付"

    reply = FeishuWebhookHandler.format_reply(result)
    # 精确命中 MC 4837 模板
    assert "4837 拒付" in reply, f"期望标题含 '4837 拒付'，reply={reply[:200]}"
    assert "Collaboration" in reply, f"期望包含 Collaboration，reply={reply[:200]}"
    assert not _default_template_used(reply)


def test_t1_5_no_ctx_clarifies(orch):
    """回归 T1.1 行为：无 ctx 时，bot 应反问（不被 query 1 误导）。"""
    query = "错误码是 13.1，订单号 ORD-12345"
    result = orch.route(user_query=query, merchant_context={})

    # 应该反问
    assert result.get("intent") == "payment_diagnosis_clarify", \
        f"无 country/channel 时期望反问，实际={result.get('intent')}"
    msg = result.get("clarify_message", "")
    assert "country" in msg or "国家" in msg, \
        f"反问消息应提 country，实际 msg={msg[:150]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
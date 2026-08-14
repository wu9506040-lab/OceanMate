"""Day 17 v2 PDA 格式测试（解决方案式输出）。

设计原则（用户反馈"不要念诊断报告，要给方案"）：
1. 不再有"诊断结果""置信度""问题分析"等标题
2. 英文术语大白话化（13.1 → "买家说没收到货"）
3. 建议用"第一步/第二步/第三步"分步
4. 每步说明在哪里操作（OP 商户后台→xxx）
5. CTA 直接问"需要我帮您创建工单吗？"
6. 同理心开头一句话就够
"""
import pytest

from app.implementations.feishu.webhook import (
    FeishuWebhookHandler,
    _get_pda_template,
)


class TestFmtPdaSolutionStyle:
    """验证解决方案式输出（不含诊断报告标题）。"""

    def test_visa_13_1_full_output(self):
        """Visa 13.1 → 分步方案 + 明确 CTA。"""
        data = {
            "problem_type": "拒付",
            "confidence": 0.8,
            "next_agent": "TRA",
        }
        trace = {
            "code_specific_enriched": {
                "channel": "Visa",
                "error_code": "13.1",
                "reason_name": "Merchandise/Services Not Received",
                "category": "not_received",
            }
        }
        out = FeishuWebhookHandler._fmt_pda(data, trace)
        print(f"\n>>> Visa 13.1 输出：\n{out}\n")

        # 1. 没有"诊断报告"标题
        assert "诊断结果" not in out, f"还在用诊断报告标题"
        assert "置信度" not in out, f"还在用置信度"
        assert "📋 问题分析" not in out, f"还在念问题分析"
        # 2. 没有英文术语
        assert "Merchandise" not in out, f"英文术语泄漏"
        assert "13.1" in out, f"错误码应保留"
        assert "没收到货" in out, f"大白话解释缺失"
        # 3. 分步方案
        assert "第一步" in out and "第二步" in out and "第三步" in out
        # 4. 在哪里操作
        assert "OP 商户后台" in out, f"未说明操作位置"
        # 5. CTA 不说"回复派单"
        assert "需要我帮你创建工单" in out or "需要我帮您创建工单" in out
        assert "回复「派单」" not in out, f"还在用旧 CTA"
        # 6. 同理心开头（一句话）
        assert "帮您" in out or "头疼" in out, f"缺同理心"

    def test_mc_4837_full_output(self):
        """MC 4837 → 未授权类拒付方案。"""
        data = {"problem_type": "拒付", "confidence": 0.8, "next_agent": "TRA"}
        trace = {
            "code_specific_enriched": {
                "channel": "Mastercard",
                "error_code": "4837",
                "reason_name": "No Cardholder Authorization",
                "category": "not_authorized",
            }
        }
        out = FeishuWebhookHandler._fmt_pda(data, trace)
        print(f"\n>>> MC 4837 输出：\n{out}\n")

        assert "4837" in out
        assert "持卡人不认" in out, f"未用大白话解释"
        assert "3DS" in out, f"未提及 3DS 检查"
        assert "第一步" in out and "第二步" in out and "第三步" in out
        assert "OP 商户后台" in out
        assert "Collaboration" in out, f"未提 CFR 拦截"

    def test_br_pix_weekend(self):
        """BR Pix 周末延迟 → 场景类方案。"""
        data = {"problem_type": "支付失败", "confidence": 0.7, "next_agent": "TRA"}
        trace = {
            "code_specific_enriched": {
                "category": "pix_weekend",
            }
        }
        out = FeishuWebhookHandler._fmt_pda(data, trace)
        print(f"\n>>> BR Pix 延迟输出：\n{out}\n")

        assert "Pix" in out
        assert "巴西央行" in out, f"未解释根因"
        assert "第一步" in out and "第二步" in out and "第三步" in out
        assert "OP 商户后台" in out
        assert "交易明细" in out, f"未指明查询位置"

    def test_default_template_when_no_match(self):
        """未知类型 → 用默认模板（不念诊断报告）。"""
        data = {"problem_type": "未知问题", "confidence": 0.6}
        out = FeishuWebhookHandler._fmt_pda(data, {})
        print(f"\n>>> 默认模板输出：\n{out}\n")

        assert "未知问题" in out
        assert "第一步" in out and "第二步" in out and "第三步" in out
        assert "需要我帮你创建工单" in out or "需要我帮您创建工单" in out

    def test_low_confidence_degrades_to_warning(self):
        """低置信度不进入模板（避免给错误方案）。"""
        data = {"problem_type": "拒付", "confidence": 0.3}
        out = FeishuWebhookHandler._fmt_pda(data, {
            "code_specific_enriched": {
                "channel": "Visa", "error_code": "13.1",
                "category": "not_received",
                "reason_name": "Merchandise/Services Not Received",
            }
        })
        print(f"\n>>> 低置信度输出：\n{out}\n")

        # 不应进模板（不应有"第一步/第二步"）
        assert "第一步" not in out, f"低置信度不应给方案"
        # 应有警告
        assert "证据不够" in out or "建议补充" in out or "派单" in out

    def test_no_old_format_markers(self):
        """任何场景下都不应再出现旧的诊断报告标记。"""
        data = {"problem_type": "拒付", "confidence": 0.8}
        trace = {
            "code_specific_enriched": {
                "channel": "Visa", "error_code": "13.1",
                "category": "not_received",
                "reason_name": "Merchandise/Services Not Received",
            }
        }
        out = FeishuWebhookHandler._fmt_pda(data, trace)
        # 旧标记应全部移除
        old_markers = [
            "🔍 诊断结果",
            "📋 问题分析",
            "✅ 建议操作",
            "置信度：",
            "准确度：",  # v1 标记
            "💡 提示：回复",
        ]
        for marker in old_markers:
            assert marker not in out, f"旧格式标记泄漏: {marker}"


class TestPdaTemplateLookup:
    """_get_pda_template() 三层 fallback。"""

    def test_exact_match(self):
        tmpl = _get_pda_template("拒付", "not_received", "Visa")
        assert "13.1" in tmpl["title"]

    def test_category_match_channel_none(self):
        tmpl = _get_pda_template("支付失败", "pix_weekend", "Pix")
        # 没 (支付失败, pix_weekend, Pix) → 落到 (支付失败, pix_weekend, None)
        assert "Pix" in tmpl["title"]

    def test_default_fallback(self):
        tmpl = _get_pda_template("完全未知", "完全未知", "完全未知")
        assert "完全未知" in tmpl["title"]
        assert len(tmpl["steps"]) == 3


class TestEmpathyNotOverDone:
    """同理心开头只需一句话（不能 2 段）。"""

    def test_empathy_one_sentence(self):
        data = {"problem_type": "拒付", "confidence": 0.8}
        trace = {
            "code_specific_enriched": {
                "channel": "Visa", "error_code": "13.1",
                "category": "not_received",
                "reason_name": "Merchandise/Services Not Received",
            }
        }
        out = FeishuWebhookHandler._fmt_pda(data, trace)
        # 取第 1 段（空行前）
        first_para = out.split("\n\n")[0]
        # 一句话 ≤ 30 字
        assert len(first_para) <= 30, f"同理心开头太长: {first_para!r}"
        # 不重复
        assert first_para.count("拒付") <= 1
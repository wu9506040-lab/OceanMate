"""Day 16「像真人客服」polishing 层测试。

验证 4 个 Fix：
- Fix E：告别语识别（不调 Tool，直接返短文本）
- Fix F：去重派单（5 分钟内同 query 不重复 TRA）
- Fix G：商户反驳识别（识别"不是的"+ 提取补充事实注入 ctx）
- Fix H：同理心开头（紧急词触发诊断前加同理心短句）
"""
import json
import os
import tempfile
import time

import pytest

from app.agents.orchestrator.polishing import (
    PolishResult,
    detect_rebuttal,
    has_urgent_signal,
    is_farewell,
    lookup_recent_ticket,
    polish_query,
    record_recent_ticket,
)


class TestIsFarewell:
    """Fix E：告别语识别。"""

    def test_好的_is_farewell(self):
        assert is_farewell("好的") is True

    def test_谢谢_is_farewell(self):
        assert is_farewell("谢谢") is True

    def test_好的谢谢_is_farewell(self):
        assert is_farewell("好的谢谢") is True

    def test_thanks_is_farewell(self):
        assert is_farewell("thanks") is True

    def test_thank_you_is_farewell(self):
        assert is_farewell("thank you") is True

    def test_thumbs_emoji_is_farewell(self):
        assert is_farewell("👌") is True

    def test_pray_emoji_is_farewell(self):
        assert is_farewell("🙏") is True

    def test_long_query_with_好的_is_not_farewell(self):
        """长度 > 15 字符 → 即使含「好的」也不算告别语。"""
        assert is_farewell("好的我也觉得是13.1") is False

    def test_real_question_is_not_farewell(self):
        """真实问题不是告别语。"""
        assert is_farewell("美国Visa 13.1拒付怎么解决") is False

    def test_empty_string_not_farewell(self):
        assert is_farewell("") is False

    def test_whitespace_only_not_farewell(self):
        assert is_farewell("   ") is False


class TestDetectRebuttal:
    """Fix G：商户反驳识别。"""

    def test_simple_rebuttal_with_fact(self):
        """反驳 + 事实 → True。"""
        assert detect_rebuttal("不是的，我们已经发了物流") is True

    def test_但是_with_fact(self):
        """「但是」+ 事实 → True。"""
        assert detect_rebuttal("但是我们已经开了 3DS 认证") is True

    def test_rebuttal_without_fact(self):
        """纯反驳无事实信号 → False（避免误判）。"""
        assert detect_rebuttal("不是的") is False

    def test_fact_without_rebuttal(self):
        """纯事实无反驳 → False（普通陈述）。"""
        assert detect_rebuttal("我已经发了物流") is False

    def test_long_query_with_已经_is_rebuttal(self):
        """长 query + 「已经」类时间信号 → True。"""
        assert detect_rebuttal("拒付原因码 13.1 但是这个订单我们之前就发了物流") is True

    def test_normal_question_not_rebuttal(self):
        """普通问题 → False。"""
        assert detect_rebuttal("美国Visa 13.1拒付怎么解决") is False


class TestHasUrgentSignal:
    """Fix H：紧急语气识别。"""

    def test_紧急_is_urgent(self):
        assert has_urgent_signal("紧急需要处理") is True

    def test_急_is_urgent(self):
        assert has_urgent_signal("很急") is True

    def test_爆了_is_urgent(self):
        assert has_urgent_signal("拒付爆了") is True

    def test_崩了_is_urgent(self):
        assert has_urgent_signal("支付崩了") is True

    def test_normal_question_not_urgent(self):
        assert has_urgent_signal("请问 Pix 怎么接入") is False

    def test_empty_not_urgent(self):
        assert has_urgent_signal("") is False


class TestPolishQueryMain:
    """polish_query() 主入口综合测试。"""

    def test_farewell_returns_farewell_reply(self):
        """告别语 → is_farewell=True, farewell_reply 非空。"""
        p = polish_query("好的")
        assert p.is_farewell is True
        assert p.farewell_reply
        assert "不客气" in p.farewell_reply

    def test_farewell_skips_other_detectors(self):
        """告别语不再走其他检测（避免误判「好的谢谢」含「已」/「谢谢」等）。"""
        p = polish_query("好的谢谢")
        assert p.is_farewell is True
        assert p.is_rebuttal is False
        assert p.urgent_prepend is None

    def test_rebuttal_sets_supplement(self):
        """反驳 → is_rebuttal=True, merchant_supplement 非空含 query 摘要。"""
        p = polish_query("不是的，我们已经发了物流")
        assert p.is_farewell is False
        assert p.is_rebuttal is True
        assert p.merchant_supplement
        assert "已经发了物流" in p.merchant_supplement
        assert p.urgent_prepend is None

    def test_urgent_sets_prepend(self):
        """紧急信号 → urgent_prepend 非空含同理心短句。"""
        p = polish_query("美国Visa 13.1拒付爆了紧急")
        assert p.is_farewell is False
        assert p.urgent_prepend
        assert "理解" in p.urgent_prepend or "🤝" in p.urgent_prepend

    def test_normal_question_returns_minimal_polish(self):
        """普通问题 → PolishResult 大部分字段为空。"""
        p = polish_query("Pix 怎么接入")
        assert p.is_farewell is False
        assert p.is_rebuttal is False
        assert p.urgent_prepend is None
        assert p.recent_ticket_id is None
        assert p.merchant_supplement is None

    def test_combined_rebuttal_and_urgent(self):
        """同时含反驳 + 紧急 → 两个字段都填。"""
        p = polish_query("不是的，我们已经发了物流，但拒付还是爆了，紧急需要处理")
        assert p.is_rebuttal is True
        assert p.urgent_prepend is not None


class TestDedupLogic:
    """Fix F：SQLite 去重派单（5 分钟窗口）。"""

    def test_first_record_then_lookup_returns_id(self):
        """记录后立即查应返回 ticket_id。"""
        uid = "ou_test_dedup_1"
        q = "美国Visa 13.1拒付怎么解决"
        # 用唯一 query 避免与其他测试串扰
        unique_q = f"{q}_{time.time()}"
        record_recent_ticket(uid, unique_q, "tkt_test_dedup_1")
        result = lookup_recent_ticket(uid, unique_q)
        assert result == "tkt_test_dedup_1"

    def test_different_user_no_match(self):
        """不同 user 查不到别人的 ticket。"""
        uid1 = f"ou_test_dedup_u1_{time.time()}"
        uid2 = f"ou_test_dedup_u2_{time.time()}"
        q = "拒付问题"
        record_recent_ticket(uid1, q, "tkt_u1")
        result = lookup_recent_ticket(uid2, q)
        assert result is None

    def test_different_query_no_match(self):
        """同 user 不同 query 查不到。"""
        uid = f"ou_test_dedup_3_{time.time()}"
        record_recent_ticket(uid, "query A", "tkt_a")
        result = lookup_recent_ticket(uid, "query B")
        assert result is None

    def test_polish_query_with_user_id_returns_recent_ticket(self):
        """polish_query(user_id=...) 应能查回刚记录的 ticket。"""
        uid = f"ou_test_dedup_polish_{time.time()}"
        q = "BR Pix 延迟不到账"
        record_recent_ticket(uid, q, "tkt_polish_dedup_1")
        p = polish_query(q, user_id=uid)
        assert p.recent_ticket_id == "tkt_polish_dedup_1"
        # 关键：去重命中时不应再走 is_farewell/is_rebuttal
        assert p.is_farewell is False
        assert p.is_rebuttal is False


class TestPolishResultDataclass:
    """PolishResult 数据类默认值。"""

    def test_default_values(self):
        p = PolishResult()
        assert p.is_farewell is False
        assert p.farewell_reply is None
        assert p.recent_ticket_id is None
        assert p.is_rebuttal is False
        assert p.urgent_prepend is None
        assert p.merchant_supplement is None

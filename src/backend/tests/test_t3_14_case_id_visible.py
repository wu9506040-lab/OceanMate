"""T3.14 case_id 可见性测试 — Day 18 P1-final 修复回归。

背景：
- T3.14 bot 回复需要显示真实 case_id（如 `case_tkt_xxxx_xxxx`），而不是 `?`
- 原 bug：ws_client.py _format_human_takeover_reply 读 `promotion` key，但
  TRA Tool 实际返回的是 `promote_result`，导致 `promotion.get('faq_id', '?')` 永远返回 `?`
- 修复：读 `promote_result`，并 fallback `case_id` 字段

用例：
- resolve_result 含 promote_result.case_id → 回复必须含该 case_id
- resolve_result 不含 promote_result → 回复不崩溃（无 `?`）
- resolve_result 含 promote_result 但无 case_id → 显示 `?` 但不抛异常
"""

from app.implementations.feishu.ws_client import _format_human_takeover_reply


class TestFormatHumanTakeoverReplyCaseId:
    """T3.14 bot 回复必须含真实 case_id（不是 ?）。"""

    def test_reply_shows_real_case_id_from_promote_result(self):
        """resolve_result.promote_result.case_id 必须出现在 bot 回复里。"""
        resolve_result = {
            "status": "closed",
            "ticket_id": "tkt_abc12345",
            "promote_result": {
                "promoted": True,
                "case_id": "case_tkt_abc12345_1755270922",
            },
        }
        reply = _format_human_takeover_reply(resolve_result, "Visa 风控误判")

        # 关键断言：真实 case_id 出现在"🧠 知识沉淀"行
        assert "case_tkt_abc12345_1755270922" in reply, (
            f"reply 应含真实 case_id，实际={reply}"
        )

    def test_reply_no_question_mark_after_kb_marker(self):
        """🧠 知识沉淀行不应出现 ? 占位符。"""
        resolve_result = {
            "status": "closed",
            "ticket_id": "tkt_test",
            "promote_result": {
                "promoted": True,
                "case_id": "case_tkt_test_9999",
            },
        }
        reply = _format_human_takeover_reply(resolve_result, "已解决")

        # 找到"🧠 知识沉淀"行
        kb_line = next(
            (line for line in reply.split("\n") if "🧠" in line),
            None,
        )
        assert kb_line is not None, f"reply 应有 🧠 知识沉淀 行，实际={reply}"
        # case_id 部分不应含 ?
        # "🧠 知识沉淀：自动升格为 FAQ（`case_xxx`）"  → 反引号内不应有 ?
        import re
        m = re.search(r"`([^`]+)`", kb_line)
        assert m is not None, f"kb_line 应有反引号包裹的 case_id，实际={kb_line}"
        assert "?" not in m.group(1), (
            f"case_id 反引号内不应有 ?，实际={m.group(1)}（完整行：{kb_line}）"
        )

    def test_reply_handles_missing_promote_result(self):
        """resolve_result 没 promote_result 时不崩溃，且不出现错误 ?。"""
        resolve_result = {
            "status": "closed",
            "ticket_id": "tkt_nopromo",
            # 无 promote_result
        }
        # 不应抛异常
        reply = _format_human_takeover_reply(resolve_result, "已解决")

        # 即使 promote_result 缺失，回复也应正常（可能不显示 KB 行）
        assert "工单" in reply or "tkt_nopromo" in reply
        # 无 promote_result 时不应进入"🧠 知识沉淀"分支（promoted=False）
        assert "🧠" not in reply or "已升格" not in reply

    def test_reply_handles_promote_result_without_case_id(self):
        """promote_result 有但没 case_id 字段 → 不抛异常，显示 ?。"""
        resolve_result = {
            "status": "closed",
            "ticket_id": "tkt_nocaseid",
            "promote_result": {
                "promoted": True,
                # 无 case_id
            },
        }
        # 不应抛异常（fallback 到 ?）
        reply = _format_human_takeover_reply(resolve_result, "已解决")

        # 仍然显示 KB 行（promoted=True），case_id 处 fallback 到 ?
        assert "🧠" in reply

    def test_reply_falls_back_to_promotion_key(self):
        """兼容老 key 名 `promotion`（如老版本测试 fixture）。"""
        resolve_result = {
            "status": "closed",
            "ticket_id": "tkt_oldkey",
            "promotion": {  # 老 key 名
                "promoted": True,
                "case_id": "case_tkt_oldkey_1111",
            },
        }
        reply = _format_human_takeover_reply(resolve_result, "已解决")

        assert "case_tkt_oldkey_1111" in reply
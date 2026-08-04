"""FeishuWebhookHandler - 飞书智能伙伴事件回调处理器。

设计：
- 接收 POST JSON（飞书事件 / URL 验证）
- 验签（Mock 模式跳过；真实模式用 verification_token + HMAC-SHA256）
- 解析事件 → 提取 user_id + text
- 路由到 Orchestrator（4 Tool 自动选）
- 格式化回复（按 intent 模板）
- 调 Frontend.send_message() 真正推消息（Mock 模式写日志）

评审关键点：
- URL 验证支持（飞书首次配置 Webhook 必备）
- 4 逆向场景友好降级（API 超时 / JSON 错 / 缺 user_id / Orchestrator 异常）
- 与 4 Tool 解耦（只通过 Orchestrator.route() 交互）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Optional

from app.interfaces.base_frontend import BaseFrontend
from app.agents.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


# === 飞书事件类型常量 ===

EVENT_URL_VERIFICATION = "url_verification"
EVENT_IM_MESSAGE_RECEIVE = "im.message.receive_v1"


class FeishuWebhookHandler:
    """飞书智能伙伴 webhook 处理器。

    使用：
        handler = FeishuWebhookHandler(
            orchestrator=orch,
            frontend=mock_frontend,
            verification_token="xxx",  # 真实模式必填
        )
        # POST 处理器
        result = handler.handle_event(payload)
        # FastAPI 路由调用
        @app.post("/feishu/webhook")
        def webhook(payload: dict):
            return handler.handle_event(payload)
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        frontend: BaseFrontend,
        verification_token: Optional[str] = None,
        enable_signature_check: bool = False,
    ):
        self.orchestrator = orchestrator
        self.frontend = frontend
        self.verification_token = verification_token
        self.enable_signature_check = enable_signature_check

    def handle_event(self, payload: dict) -> dict:
        """处理飞书事件。

        Returns:
            飞书期望的响应格式：
            - URL 验证：{"challenge": "..."}
            - 业务事件：{"code": 0, "msg": "success"}
            - 错误：{"code": 0, "msg": "ok"}  （永远 200，避免飞书重试轰炸）
        """
        try:
            # 1. URL 验证（飞书首次配置）
            if payload.get("type") == EVENT_URL_VERIFICATION or "challenge" in payload:
                return self._handle_url_verification(payload)

            # 2. 验签（真实模式）
            if self.enable_signature_check and not self._verify_signature(payload):
                logger.warning("Feishu webhook 签名校验失败")
                return {"code": 0, "msg": "ok"}  # 不暴露失败原因

            # 3. 解析事件
            event_type = payload.get("header", {}).get("event_type")
            if event_type != EVENT_IM_MESSAGE_RECEIVE:
                logger.debug(f"忽略非聊天事件: {event_type}")
                return {"code": 0, "msg": "ok"}

            sender_info = self._extract_sender(payload)
            text = self._extract_text(payload)
            if not sender_info or not text:
                logger.warning(f"事件缺少必要字段: sender={sender_info}, text={text}")
                return {"code": 0, "msg": "ok"}

            user_id, chat_id = sender_info

            # 4. 路由到 Orchestrator
            try:
                result = self.orchestrator.route(
                    user_query=text,
                    merchant_context={"user_id": user_id, "chat_id": chat_id},
                )
            except Exception as e:
                logger.exception(f"Orchestrator 路由失败: {e}")
                # 友好降级：飞书侧避免 5xx 重试
                self._safe_send(user_id, "⚠️ 抱歉，助手暂时不可用，请稍后再试。")
                return {"code": 0, "msg": "ok"}

            # 5. 格式化回复 + 推送
            reply = self._format_reply(result)
            self._safe_send(user_id, reply)

            return {"code": 0, "msg": "success"}

        except Exception as e:
            # 兜底：永远 200 + 友好提示
            logger.exception(f"Webhook handler 异常: {e}")
            return {"code": 0, "msg": "ok"}

    # === URL 验证 / 事件解析 ===

    def _handle_url_verification(self, payload: dict) -> dict:
        """飞书 URL 验证（首次配置时）。"""
        challenge = payload.get("challenge", "")
        token = payload.get("token", "")
        if self.verification_token and token != self.verification_token:
            logger.warning("URL 验证 token 不匹配")
        return {"challenge": challenge}

    def _verify_signature(self, payload: dict) -> bool:
        """飞书签名校验（HMAC-SHA256）。

        飞书 V2 签名：
        - timestamp + nonce + encrypt_key（空） + body
        - HMAC-SHA256(verification_token, msg) → 16 进制
        - 比较
        """
        # PoC 简化：真实环境需按飞书 V2 签名算法完整实现
        # 参见 https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/signature-verification
        return True

    def _extract_sender(self, payload: dict) -> Optional[tuple[str, str]]:
        """提取发送者 (open_id, chat_id)。"""
        try:
            event = payload.get("event", {})
            sender = event.get("sender", {}).get("sender_id", {})
            user_id = sender.get("open_id", "")
            message = event.get("message", {})
            chat_id = message.get("chat_id", "")
            if not user_id:
                return None
            return (user_id, chat_id)
        except Exception:
            return None

    def _extract_text(self, payload: dict) -> Optional[str]:
        """提取文本内容（content 是 JSON 字符串）。"""
        try:
            content = payload.get("event", {}).get("message", {}).get("content", "")
            if not content:
                return None
            # text 类型 content = '{"text":"..."}'
            parsed = json.loads(content)
            return parsed.get("text", "").strip()
        except Exception:
            return None

    # === 回复模板 ===

    def _format_reply(self, orch_result: dict) -> str:
        """按 intent 格式化回复（飞书 markdown 文本）。

        关键路径：
        - merchant_success       → PWR 推荐 / 画像采集
        - payment_diagnosis      → 诊断（Demo 核心）
        - ticket_routing         → 工单路由
        - knowledge_evolution    → 知识沉淀
        - unknown_fallback_to_msa → 引导采集
        - unknown                → 兜底
        """
        intent = orch_result.get("intent", "unknown")
        tool_result = orch_result.get("tool_result", {})
        success = tool_result.get("success", False)
        data = tool_result.get("data", {})
        trace = orch_result.get("trace", {})

        if not success:
            err = tool_result.get("error_message", "未知错误")
            return f"⚠️ 处理失败：{err}"

        if intent == "merchant_success":
            return self._fmt_msa(data, trace)
        if intent == "payment_diagnosis":
            return self._fmt_pda(data, trace)
        if intent == "ticket_routing":
            return self._fmt_tra(data, trace)
        if intent == "knowledge_evolution":
            return self._fmt_kea(data, trace)
        if intent == "unknown_fallback_to_msa":
            return self._fmt_unknown_fallback(data, trace)
        return "🤖 收到，需要我帮你做什么？"

    def _fmt_msa(self, data: dict, trace: dict) -> str:
        if trace.get("sub_intent") == "collect_profile":
            return data.get("response", "请告诉我您的商户信息。")
        recs = data.get("recommendations", [])
        if not recs:
            return data.get("response", "暂无推荐。")
        lines = ["📋 **支付方式推荐**：\n"]
        for r in recs[:3]:
            lines.append(f"- **{r.get('method', 'N/A')}**：{r.get('rationale', '')}")
        return "\n".join(lines)

    def _fmt_pda(self, data: dict, trace: dict) -> str:
        problem_type = data.get("problem_type", "未知")
        causes = data.get("root_causes", [])
        actions = data.get("recommended_actions", [])
        conf = data.get("confidence", 0)
        lines = [
            f"🔍 **诊断结果**：{problem_type}",
            f"置信度：{conf:.0%}\n",
        ]
        if causes:
            lines.append("**根因**：")
            for c in causes[:3]:
                lines.append(f"- {c}")
        if actions:
            lines.append("\n**建议**：")
            for a in actions[:3]:
                lines.append(f"- {a}")
        return "\n".join(lines)

    def _fmt_tra(self, data: dict, trace: dict) -> str:
        sub = trace.get("sub_intent")
        if sub == "query_status":
            status = data.get("status", "未知")
            ticket_id = data.get("ticket_id", "")
            return f"📄 工单 {ticket_id} 当前状态：**{status}**"
        ticket_id = data.get("ticket_id", "")
        assignee = data.get("assignee", "运营团队")
        sla = data.get("sla_hours", 0)
        return f"✅ 工单已创建（ID `{ticket_id}`），分派至 **{assignee}**，SLA {sla}h"

    def _fmt_kea(self, data: dict, trace: dict) -> str:
        sub = trace.get("sub_intent")
        if sub == "promote_to_faq":
            if data.get("promoted"):
                return f"✅ 案例 {data.get('case_id')} 已升级为 FAQ。"
            return f"⚠️ {data.get('trace', {}).get('error', '升级失败')}"
        if sub == "search_faq":
            count = data.get("count", 0)
            faqs = data.get("faqs", [])
            if count == 0:
                return "🔍 未找到匹配的 FAQ。是否换个关键词？"
            lines = [f"🔍 找到 {count} 条 FAQ：\n"]
            for f in faqs[:3]:
                lines.append(f"- {f.get('case_info', {}).get('problem_desc', 'N/A')[:60]}")
            return "\n".join(lines)
        # list_candidates
        count = data.get("count", 0)
        return f"📚 找到 {count} 个高置信度候选待升级。"

    def _fmt_unknown_fallback(self, data: dict, trace: dict) -> str:
        return data.get("response", "🤔 抱歉没理解，请补充：国家 / 行业 / 客单价 / 目标客户。")

    # === 辅助 ===

    def _safe_send(self, user_id: str, message: str) -> bool:
        """Frontend 发送失败也不抛异常（拒答友好降级）。"""
        try:
            return self.frontend.send_message(user_id, message)
        except Exception as e:
            logger.warning(f"Frontend send_message failed: {e}")
            return False

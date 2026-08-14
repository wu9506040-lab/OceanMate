"""FeishuWebhookHandler - 飞书事件回调处理器（兼容 webhook + 长连接共享）。

设计：
- 接收 POST JSON（飞书事件 / URL 验证）— webhook 模式
- 复用为 ws_client.py 的事件格式化器（format_reply）
- 解析事件 → 提取 user_id + text
- 路由到 Orchestrator（4 Tool 自动选）
- 格式化回复（按 intent 模板）
- 调 Frontend.send_message() 真正推消息（Mock 模式写日志）

Day 9 决策：长连接（ws_client.py）为主路径，本 webhook 路由保留作为：
1. Mock 演示（无凭证自动启用 MockFrontend，日志可看完整事件流）
2. 飞书后台 webhook 模式回退（未来如启用，需重写签名 + 加密）

⚠️ 安全提示：
- 当前签名校验代码（_verify_signature）已移除（Day 9 发现实现错误：HMAC≠SHA256）
- 如启用 webhook + Encrypt Key 模式，需按飞书官方文档重写：
  signature = SHA256(timestamp + nonce + encrypt_key + body_str)
- 当前实现：仅 Verification Token 用于 URL 验证（明文传输，仅防误调）

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
import re
from typing import Any, Optional

from fastapi import HTTPException

from app.interfaces.base_frontend import BaseFrontend
from app.agents.orchestrator.orchestrator import Orchestrator
from app.agents.orchestrator.polishing import (
    polish_query,
    record_recent_ticket,
)

logger = logging.getLogger(__name__)


# === 测试数据过滤器（Day 14 P0 修复）===

_TEST_DATA_PATTERNS = [
    r"https?://[a-zA-Z0-9_.-]*example\.(com|net|org)[^\s]*",  # example.com 占位 URL
    r"https?://[a-zA-Z0-9_-]+\.placeholder\.[a-z]+[^\s]*",
    r"merchant\.example\.com",
    r"placeholder\.(com|net|org|io)",
    r"//.*Demo.*占位",
    r"\|.*Demo\s*占位[^\n]*",
    r"（?Demo\s*占位[^）\n]*）?",  # 裸露的"Demo 占位"字样
    r"<DEMO_[A-Z_]+>",  # <DEMO_MERCHANT_ID> 等占位符
    r"3DS_enabled\s*=\s*\w+",  # 技术参数
    r"webhook_url\s*=\s*https?://[^\s]+",
    r"[a-z_]+_demo_[a-z0-9_.]+",  # risk_rule_demo_001 / config_demo_xxx 内部 ID
]


def _sanitize(text: str) -> str:
    """过滤测试数据 / 技术黑话，转成商户友好版本。

    规则：
    - example.com / placeholder / Demo 占位 / <DEMO_xxx> → "（请联系 OP 配置）"
    - 内部证据 ID（xxx_demo_001）→ 不暴露给商户
    - 3DS_enabled = false → 走 LLM Prompt 转人话，这里兜底删掉技术参数
    """
    if not text:
        return text
    cleaned = text
    for pat in _TEST_DATA_PATTERNS:
        cleaned = re.sub(pat, "（请联系 OP 配置）", cleaned)
    # 把"OP merchant_config API" 之类改成 OP 后台，避免暴露 API 名称
    cleaned = cleaned.replace("OP merchant_config API", "OP 商户后台")
    cleaned = cleaned.replace("merchant_config API", "OP 商户后台")
    # 飞书纯文本不渲染 Markdown → 去掉星号避免出现字面 **xxx**
    cleaned = cleaned.replace("**", "").replace("`", "")
    # 连续重复的占位提示合并
    cleaned = re.sub(r"(（请联系 OP 配置）\s*){2,}", "（请联系 OP 配置）", cleaned)
    # 截断过长内容
    if len(cleaned) > 200:
        cleaned = cleaned[:200] + "..."
    return cleaned.strip()


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
        encrypt_key: Optional[str] = None,
    ):
        self.orchestrator = orchestrator
        self.frontend = frontend
        self.verification_token = verification_token
        self.enable_signature_check = enable_signature_check
        # Day 15 P0-4：用于签名校验的 Encrypt Key
        # （飞书 Webhook 签名算法：SHA256(timestamp + nonce + encrypt_key + body_str).hexdigest()）
        self.encrypt_key = encrypt_key

    @staticmethod
    def verify_signature(
        timestamp: str,
        nonce: str,
        encrypt_key: str,
        body_str: str,
        signature: str,
    ) -> bool:
        """Day 15 P0-4：飞书 Webhook 签名校验（正确算法）。

        算法：SHA256(timestamp + nonce + encrypt_key + body_str).hexdigest()
        参考：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions

        Args:
            timestamp: 请求头 X-Lark-Request-Timestamp
            nonce: 请求头 X-Lark-Request-Nonce
            encrypt_key: .env FEISHU_ENCRYPT_KEY
            body_str: 原始 body 字符串（必须与飞书发送的字节一致）
            signature: 请求头 X-Lark-Signature

        Returns:
            True = 校验通过；False = 失败
        """
        if not all([timestamp, nonce, encrypt_key, body_str, signature]):
            return False
        content = timestamp + nonce + encrypt_key + body_str
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # 防止长度泄露，恒定时比较（Python 3.9+ compare_digest 在 hmac 模块）
        return hmac.compare_digest(expected, signature)

    def handle_event(
        self,
        payload: dict,
        *,
        body_str: Optional[str] = None,
        timestamp: Optional[str] = None,
        nonce: Optional[str] = None,
        signature: Optional[str] = None,
    ) -> dict:
        """处理飞书事件。

        Args:
            payload: 解析后的 JSON dict
            body_str: 原始 body 字符串（验签用，必须与飞书发送的字节一致）
            timestamp: 请求头 X-Lark-Request-Timestamp
            nonce: 请求头 X-Lark-Request-Nonce
            signature: 请求头 X-Lark-Signature

        Returns:
            飞书期望的响应格式：
            - URL 验证：{"challenge": "..."}
            - 业务事件：{"code": 0, "msg": "success"}
            - 错误：{"code": 0, "msg": "ok"}  （永远 200，避免飞书重试轰炸）
        """
        try:
            # 1. URL 验证（飞书首次配置，验签前先放行）
            if payload.get("type") == EVENT_URL_VERIFICATION or "challenge" in payload:
                return self._handle_url_verification(payload)

            # 2. 验签（Day 15 P0-4 重写）— SHA256(timestamp+nonce+encrypt_key+body_str)
            #    必须 4 个 header/字段齐全 + body_str 传入；Demo 模式 enable_signature_check=False 跳过
            if self.enable_signature_check:
                if not (timestamp and nonce and signature):
                    logger.warning("签名校验开启但缺少 timestamp/nonce/signature header")
                    return {"code": 401, "msg": "missing signature headers"}
                if body_str is None:
                    logger.warning("签名校验开启但 body_str 未传入")
                    return {"code": 400, "msg": "missing body_str for verification"}
                if not self.encrypt_key:
                    logger.error("签名校验开启但 encrypt_key 未配置")
                    return {"code": 500, "msg": "encrypt_key not configured"}
                ok = self.verify_signature(
                    timestamp=timestamp,
                    nonce=nonce,
                    encrypt_key=self.encrypt_key,
                    body_str=body_str,
                    signature=signature,
                )
                if not ok:
                    logger.warning(f"签名校验失败: ts={timestamp}, nonce={nonce}")
                    return {"code": 401, "msg": "signature verification failed"}

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

            # 3.5 Day 16「像真人客服」polishing 层（Fix E/F/G/H）
            # 在 Orchestrator 之前过滤掉告别语 / 去重派单 / 提取补充事实 / 检测同理心信号
            polish = polish_query(text, user_id=user_id)

            # Fix E：告别语识别 → 直接返短文本，不调 Orchestrator
            if polish.is_farewell:
                self._safe_send(user_id, polish.farewell_reply or "🙌 不客气！")
                logger.info(f"[polishing] 告别语识别: user={user_id[:12]} text={text[:20]}")
                return {"code": 0, "msg": "success"}

            # Fix F：5 分钟内同 user+query 已派过工单 → 返查询链接（不重复派）
            if polish.recent_ticket_id:
                dedup_reply = (
                    f"💡 您刚才已经就该问题提交过工单 **{polish.recent_ticket_id}**，"
                    f"我们的同事正在跟进，无需重复提交。\n\n"
                    "如有新信息（如物流单号 / 已开 3DS / 退款记录），"
                    "请直接发给我，我会更新到原工单上。"
                )
                self._safe_send(user_id, dedup_reply)
                logger.info(
                    f"[polishing] 去重派单命中: user={user_id[:12]} "
                    f"ticket={polish.recent_ticket_id}"
                )
                return {"code": 0, "msg": "success"}

            # Fix G：商户反驳 / 补充事实 → 注入 ctx
            ctx = {"user_id": user_id, "chat_id": chat_id}
            if polish.merchant_supplement:
                ctx["merchant_supplement"] = polish.merchant_supplement
                ctx["is_rebuttal"] = True
                logger.info(f"[polishing] 商户反驳识别: user={user_id[:12]} text={text[:40]}")

            # Fix H：同理心信号 → 存到 ctx，format_reply 后 prepend
            urgent_prepend = polish.urgent_prepend

            # 4. 路由到 Orchestrator
            try:
                result = self.orchestrator.route(
                    user_query=text,
                    merchant_context=ctx,
                )
            except Exception as e:
                logger.exception(f"Orchestrator 路由失败: {e}")
                # 友好降级：飞书侧避免 5xx 重试
                self._safe_send(user_id, "⚠️ 抱歉，助手暂时不可用，请稍后再试。")
                return {"code": 0, "msg": "ok"}

            # 4.5 Day 10 PDA → TRA 自动链：商户问题被诊断后，若命中「紧急/转人工/拒付/支付失败」
            #     → 自动调 TRA 创建工单 + briefing（亮点：AI 一条龙诊断 + 派单）
            #
            # Day 15 P0-C2 修复：之前直接 result=chain_result 导致商户只看到「✅ 工单已创建」
            # 看不到 PDA 诊断文字。修复：chain_result 不替换 result，单独作为第 2 条消息发送
            # → 商户先看到诊断文字+配图，再看到自动派单确认（设计预期：1问 → 多条消息串）
            chain_result = self._maybe_chain_to_tra(result, user_query=text, user_id=user_id, chat_id=chat_id)
            chain_text = None
            if chain_result:
                # 关键：保留 PDA result 不变（商户第 1 条消息看 PDA 诊断 + 配图）
                # chain_result 仅用来发第 2 条「工单已创建」消息
                chain_text = FeishuWebhookHandler.format_reply(chain_result)

            # 5. 格式化回复 + 推送
            # Fix H：同理心信号 → 在 reply 前加同理心短句
            reply = FeishuWebhookHandler.format_reply(result)
            if urgent_prepend:
                reply = urgent_prepend + reply
            self._safe_send(user_id, reply)

            # 5.0 Day 15 P0-C2 修复：链式 TRA 工单创建结果作为「追加消息」单独发送
            # 让商户先看到 PDA 诊断 + 配图，再看到自动派单确认
            if chain_text:
                self._safe_send(user_id, chain_text)

            # Fix F：去重派单 — 若本轮创建了 TRA 工单，记入 SQLite 用于下次去重
            created_ticket_id = self._extract_created_ticket_id(result)
            if not created_ticket_id and chain_result:
                created_ticket_id = self._extract_created_ticket_id(chain_result)
            if created_ticket_id:
                record_recent_ticket(user_id, text, created_ticket_id)
                logger.info(
                    f"[polishing] 记录工单去重: user={user_id[:12]} "
                    f"ticket={created_ticket_id}"
                )

            # 5.1 Day 9 增强：若结果含 error_code/image_path（拒付码诊断），推配图
            image_path = result.get("error_image_path") or result.get("image_path")
            if image_path and hasattr(self.frontend, "send_image"):
                try:
                    import os
                    full_path = image_path if os.path.isabs(image_path) else self._resolve_workspace_path(image_path)
                    if os.path.exists(full_path):
                        ok = self.frontend.send_image(user_id, full_path)
                        logger.info(f"send_image ok={ok} path={full_path}")
                    else:
                        logger.warning(f"image_path 不存在: {full_path}")
                except Exception as e:
                    logger.warning(f"send_image 失败: {e}")

            # 5.2 Day 10 智能交接简报：TRA 创建工单后 → 向团队 lead 发私有简报
            # Day 15 P0-C2：优先从 chain_result（链式 TRA）取 briefing；若 result 是链式触发后
            # 已合并的 TRA result，briefing 也能从 tool_result.data.briefing 拿到
            briefing = self._extract_briefing(result)
            if not briefing and chain_result:
                briefing = self._extract_briefing(chain_result)
            if briefing:
                # 注意：不要重复给商户发「简报已发送」消息（chain_text 已包含工单创建信息）
                self._send_briefing_to_team_silent(briefing, chat_id=chat_id)

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

    # ⚠️ Day 9 决策：移除 _verify_signature 方法（原 HMAC-SHA256 实现错误）
    #   - 正确算法：SHA256(timestamp + nonce + encrypt_key + body_str).hexdigest()
    #   - 当前项目用长连接（ws_client.py），SDK 内置签名 + 加密，无需自实现
    #   - 如未来启用 webhook + Encrypt Key，按官方文档重写
    #   参考：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/event-subscriptions

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

    # === 回复模板（公开方法 · ws_client 复用） ===

    @staticmethod
    def format_reply(orch_result: dict) -> str:
        """按 intent 格式化回复（飞书 markdown 文本）。

        公开方法：webhook handler 和 ws_client 都用此格式化。
        不依赖 handler 实例状态，纯函数。

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
            return FeishuWebhookHandler._fmt_msa(data, trace)
        if intent == "payment_diagnosis":
            return FeishuWebhookHandler._fmt_pda(data, trace)
        if intent == "payment_diagnosis_clarify":
            # Day 14 P0-3：参数缺失 → 直接返回反问消息，不走瞎编
            return orch_result.get("clarify_message", "🤔 需要更多信息，请补充具体错误码/国家/渠道。")
        if intent == "ticket_routing":
            return FeishuWebhookHandler._fmt_tra(data, trace)
        if intent == "knowledge_evolution":
            return FeishuWebhookHandler._fmt_kea(data, trace)
        if intent == "unknown_fallback_to_msa":
            return FeishuWebhookHandler._fmt_unknown_fallback(data, trace)
        return "🤖 收到，需要我帮你做什么？"

    @staticmethod
    def _fmt_msa(data: dict, trace: dict) -> str:
        if trace.get("sub_intent") == "collect_profile":
            return data.get("response", "请告诉我您的商户信息。")
        recs = data.get("recommendations", [])
        if not recs:
            return data.get("response", "暂无推荐。")
        lines = ["📋 支付方式推荐：", ""]
        for i, r in enumerate(recs[:3], 1):
            lines.append(f"  {i}. {r.get('method', 'N/A')} — {r.get('rationale', '')}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_pda(data: dict, trace: dict) -> str:
        """格式化 PDA 诊断结果（Day 14 P0 飞书友好版）。

        设计原则：
        1. 飞书 IM 私聊不渲染 Markdown 星号，用 emoji + 换行 + 编号
        2. 过滤测试数据（example.com / placeholder / Demo 占位）
        3. confidence 低（≤0.5）时显示"建议转人工"
        """
        problem_type = data.get("problem_type", "未知")
        causes = data.get("root_causes", [])
        actions = data.get("recommended_actions", [])
        conf = data.get("confidence", 0)

        # 过滤测试数据 + 截断
        causes_clean = [_sanitize(c) for c in causes[:3] if c]
        actions_clean = [_sanitize(a) for a in actions[:4] if a]

        lines = [
            f"🔍 诊断结果：{problem_type}",
            f"置信度：{conf:.0%}",
            "",
        ]

        # 低置信度 → 提示转人工
        if conf <= 0.5:
            lines.append("⚠️ 当前证据不足，建议转人工协助：")
            lines.append("  1. 提供具体错误码 / 订单号 / 国家 + 渠道")
            lines.append("  2. 我帮您创建工单，2h 内跟进")
            if causes_clean:
                lines.append("")
                lines.append("📋 初步分析：")
                for i, c in enumerate(causes_clean, 1):
                    lines.append(f"  {i}. {c}")
            return "\n".join(lines)

        if causes_clean:
            lines.append("📋 问题分析：")
            for i, c in enumerate(causes_clean, 1):
                lines.append(f"  {i}. {c}")
            lines.append("")

        if actions_clean:
            lines.append("✅ 建议操作：")
            for i, a in enumerate(actions_clean, 1):
                lines.append(f"  {i}. {a}")

        # 末尾加 ticket 引导（如果有 next_agent）
        if data.get("next_agent"):
            lines.append("")
            lines.append("💡 提示：回复\"派单\"，我帮您创建工单跟进")

        return "\n".join(lines)

    @staticmethod
    def _fmt_tra(data: dict, trace: dict) -> str:
        sub = trace.get("sub_intent")
        if sub == "query_status":
            status = data.get("status", "未知")
            ticket_id = data.get("ticket_id", "")
            # Day 14 #9：没 ticket_id 或 not_found 时给友好反问
            if not ticket_id or status == "not_found":
                return (
                    "🤔 要查询工单状态，请提供工单 ID。\n\n"
                    "💡 工单 ID 格式示例：tkt_a1b2c3d4e5f6\n\n"
                    "📌 没有工单 ID？回复「我的工单」我帮您列出最近 7 天的工单。"
                )
            assignee = data.get("assignee", "")
            problem_type = data.get("problem_type", "")
            return (
                f"📄 工单 {ticket_id}\n"
                f"  状态：{status}\n"
                f"  类型：{problem_type}\n"
                f"  负责人：{assignee}"
            )
        ticket_id = data.get("ticket_id", "")
        assignee = data.get("assignee", "运营团队")
        sla = data.get("sla_hours", 0)
        return f"✅ 工单已创建（ID {ticket_id}），分派至 {assignee}，SLA {sla}h"

    @staticmethod
    def _fmt_kea(data: dict, trace: dict) -> str:
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
            lines = [f"🔍 找到 {count} 条 FAQ：", ""]
            for i, f in enumerate(faqs[:3], 1):
                excerpt = (f.get("case_info") or {}).get("problem_desc") or f.get("text_excerpt", "")
                lines.append(f"  {i}. {_sanitize(str(excerpt))[:80]}")
            return "\n".join(lines)
        # list_candidates
        count = data.get("count", 0)
        return f"📚 找到 {count} 个高置信度候选待升级。"

    @staticmethod
    def _fmt_unknown_fallback(data: dict, trace: dict) -> str:
        return data.get("response", "🤔 抱歉没理解，请补充：国家 / 行业 / 客单价 / 目标客户。")

    # === 辅助 ===

    def _safe_send(self, user_id: str, message: str) -> bool:
        """Frontend 发送失败也不抛异常（拒答友好降级）。"""
        try:
            return self.frontend.send_message(user_id, message)
        except Exception as e:
            logger.warning(f"Frontend send_message failed: {e}")
            return False

    @staticmethod
    def _resolve_workspace_path(rel_path: str) -> str:
        """解析相对路径到项目根目录。

        data/error_images/<id>.png -> E:/ai-pioneer/data/error_images/<id>.png

        webhook.py 在 src/backend/app/implementations/feishu/，
        parents[4] = src/，parents[5] = ai-pioneer/（项目根），
        error_images 在项目根 data/ 下。
        """
        from pathlib import Path
        workspace = Path(__file__).resolve().parents[5]  # E:/ai-pioneer
        return str(workspace / rel_path)

    # === Day 10 智能交接简报 ===

    # === 触发链式 TRA 的关键词（商户明示 + AI 推断） ===

    _URGENT_HINTS = ("紧急", "急", "尽快", "马上", "工单", "派单", "转人工", "人工", "客服", "联系", "支持")
    # PDA 输出的 problem_type 触发链式 TRA（自动判断「需要人工跟进」）
    _PDA_CHAIN_PROBLEM_TYPES = ("拒付", "支付失败", "Webhook 回调失败")

    def _maybe_chain_to_tra(
        self,
        pda_result: dict,
        *,
        user_query: str,
        user_id: str,
        chat_id: str,
    ) -> Optional[dict]:
        """PDA 后自动链式调 TRA 创建工单（亮点：商户问一次，AI 诊断 + 派单 + 简报一条龙）。

        触发条件（满足任一）：
        1. 商户原话含紧急 / 转人工 / 人工关键词
        2. PDA 输出 problem_type ∈ {拒付, 支付失败, Webhook 回调失败}
        3. PDA confidence ≥ 0.6（说明已确定诊断，可以快速派单）

        Args:
            pda_result: PDA Orchestrator 结果
            user_query: 商户原话
            user_id: 商户 open_id
            chat_id: 会话 ID

        Returns:
            新的 combined result（dict），格式类似 Orchestrator 输出，含 tool_result 是 TRA，
            trace.upstream_diagnosis 是 PDA 信息；
            若不触发 / 失败 → 返回 None（主流程继续用 PDA result）
        """
        if pda_result.get("intent") != "payment_diagnosis":
            return None
        if not self.orchestrator.registry.get("ticket_routing"):
            return None

        pda_data = (pda_result.get("tool_result") or {}).get("data") or {}
        problem_type = pda_data.get("problem_type", "")
        confidence = pda_data.get("confidence", 0)
        diagnosis_id = (pda_result.get("trace") or {}).get("params", {}).get("merchant_id", "diag_auto")
        # 用 merchant_id + timestamp 模拟 diagnosis_id（PoC 简化）
        from datetime import datetime
        diagnosis_id = f"diag_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{user_id[-6:]}"

        # 触发判断
        keyword_hit = any(k in user_query for k in self._URGENT_HINTS)
        problem_hit = problem_type in self._PDA_CHAIN_PROBLEM_TYPES
        if not (keyword_hit or problem_hit):
            return None
        # confidence 太低不自动派单（让商户先补信息）
        if confidence < 0.5 and not keyword_hit:
            return None

        # 优先级：商户说"紧急" → high；否则按 problem_type 默认
        priority = "high" if keyword_hit else ("high" if problem_type == "拒付" else "medium")
        tier = "vip" if "VIP" in user_query else "standard"

        # 调 TRA
        tra_params = {
            "intent": "route_ticket",
            "problem_type": problem_type or "支付失败",
            "priority": priority,
            "tier": tier,
            "merchant_id": (pda_result.get("trace") or {}).get("params", {}).get("merchant_id"),
            "diagnosis_id": diagnosis_id,
            "problem_summary": (user_query[:200] if user_query else ""),
        }
        tra_params = {k: v for k, v in tra_params.items() if v is not None and v != ""}
        try:
            tra_wrapped = self.orchestrator.registry.safe_execute("ticket_routing", tra_params)
        except Exception as e:
            logger.warning(f"链式 TRA 调用失败: {e}")
            return None
        if not tra_wrapped.get("success"):
            logger.warning(f"链式 TRA 返回失败: {tra_wrapped}")
            return None

        # 把 PDA 信息塞到 TRA result 的 trace.upstream_diagnosis，方便 briefing 渲染
        tra_data = tra_wrapped.get("data") or {}
        # combined result：以 TRA 为顶，附 PDA 上下文
        return {
            "intent": "ticket_routing",  # 主意图切到 TRA
            "tool_name": "ticket_routing",
            "tool_result": tra_wrapped,
            "error_image_path": pda_result.get("error_image_path", ""),  # 保留配图
            "trace": {
                "matched_keywords": pda_result.get("trace", {}).get("matched_keywords", []),
                "chain": "pda_to_tra",
                "priority": priority,
                "tier": tier,
                "diagnosis_id": diagnosis_id,
                "upstream_diagnosis": {
                    "problem_type": problem_type,
                    "root_causes": pda_data.get("root_causes", []),
                    "confidence": confidence,
                    "recommended_actions": pda_data.get("recommended_actions", []),
                    "evidence_chain": pda_data.get("evidence_chain", []),
                },
            },
        }

    @staticmethod
    def _extract_created_ticket_id(orch_result: dict) -> Optional[str]:
        """Day 16 Fix F：从 Orchestrator 结果提取「本轮创建的工单 ID」（用于去重）。

        只关心 TRA 创建的工单（sub_intent=route_ticket + ticket_id 非空 + status=pending）。
        TRA query_status 不算创建。
        """
        if not orch_result or orch_result.get("intent") != "ticket_routing":
            return None
        trace = orch_result.get("trace") or {}
        if trace.get("sub_intent") != "route_ticket":
            return None
        tool_result = orch_result.get("tool_result") or {}
        if not tool_result.get("success"):
            return None
        data = tool_result.get("data") or {}
        if not isinstance(data, dict):
            return None
        ticket_id = data.get("ticket_id", "")
        if not ticket_id or not str(ticket_id).startswith("tkt_"):
            return None
        return str(ticket_id)

    def _extract_briefing(self, orch_result: dict) -> Optional[dict]:
        """从 Orchestrator 结果提取 briefing（兼容 wrapped result.data 结构）。

        TRA Tool 返回结构：
        {
          "intent": "ticket_routing",
          "tool_result": {"success": True, "data": {"status": "pending", "briefing": {...}, ...}}
        }

        PDA + TRA 联动时，trace 里还带 on_diagnosis → on_routing 链路。
        """
        tool_result = orch_result.get("tool_result") or {}
        if not tool_result.get("success"):
            return None
        data = tool_result.get("data") or {}
        if not isinstance(data, dict):
            return None
        briefing = data.get("briefing")
        if not briefing or data.get("status") != "pending":
            return None
        # 联动上下文：若上游有 PDA 诊断结果，把根因 / 置信度附上
        trace = orch_result.get("trace") or {}
        upstream = trace.get("upstream_diagnosis") or {}
        if upstream:
            briefing["ai_root_causes"] = upstream.get("root_causes", [])[:3]
            briefing["ai_confidence"] = upstream.get("confidence")
            briefing["ai_recommended_actions"] = upstream.get("recommended_actions", [])[:3]
        return briefing

    def _send_briefing_to_team(self, briefing: dict, *, chat_id: str, merchant_user_id: str) -> bool:
        """向团队 lead 发私有交接简报（商户看不到）。

        流程：
        1. 拼接富文本简报（markdown）
        2. 通过 env FEISHU_TEAM_<NORMALIZED>_OPEN_ID 解析团队 lead 的 open_id
        3. frontend.send_private(open_id, text) 发私有消息

        失败降级：team_open_id 未配 → 只在商户消息中追加「正在转接」，
                  send_private 失败 → log warning 不影响主流程。

        Day 15 P0-C2：注意此方法会推一条消息给商户（"💼 已发送至 X"）。
        链式触发场景（商户已经看到 chain_text "✅ 工单已创建"）请用 _send_briefing_to_team_silent
        避免商户收到重复消息。
        """
        team = briefing.get("team", "")
        team_open_id = self._resolve_team_open_id(team)
        if not team_open_id:
            logger.info(
                f"交接简报：团队 '{team}' 未配置 lead open_id（设 FEISHU_TEAM_<NORMALIZED>_OPEN_ID 即可启用真实通知）；"
                "降级为商户消息中追加「正在转接」提示。"
            )
            # 降级：商户消息追加「转接中」+ 标注团队
            self._safe_send(
                merchant_user_id,
                f"💼 正在为您转接 **{team}** 团队（内部通知未送达 lead，"
                "将自动转至通用支持）...",
            )
            return False

        text = self._format_briefing_text(briefing, chat_id=chat_id, merchant_user_id=merchant_user_id)
        try:
            ok = self.frontend.send_private(team_open_id, text)
            logger.info(
                f"交接简报 → team='{team}' open_id={team_open_id[:8]}... ok={ok} "
                f"ticket_id={briefing.get('ticket_id')}"
            )
            if ok:
                # 商户消息追加一句确认
                self._safe_send(
                    merchant_user_id,
                    f"💼 人工交接简报已发送至 **{team}** 团队，预计 {briefing.get('sla_hours', '?')}h 内回复您。",
                )
            return ok
        except Exception as e:
            logger.warning(f"send_private 失败: {e}")
            return False

    def _send_briefing_to_team_silent(self, briefing: dict, *, chat_id: str) -> bool:
        """Day 15 P0-C2：仅向团队 lead 发私有简报，不向商户追加「已发送」消息。

        用于链式触发场景：商户已经收到 chain_text（"✅ 工单已创建 ..."），
        重复发「已发送」会变 3 条消息（PDA 文字 + 配图 + 派单 + 已发送），这里只发 lead 不发商户。
        """
        team = briefing.get("team", "")
        team_open_id = self._resolve_team_open_id(team)
        if not team_open_id:
            logger.info(
                f"交接简报：团队 '{team}' 未配置 lead open_id，降级静默"
                "（商户已收到 chain_text 派单确认，无需追加）"
            )
            return False

        text = self._format_briefing_text(briefing, chat_id=chat_id, merchant_user_id="")
        try:
            ok = self.frontend.send_private(team_open_id, text)
            logger.info(
                f"交接简报（silent） → team='{team}' open_id={team_open_id[:8]}... ok={ok} "
                f"ticket_id={briefing.get('ticket_id')}"
            )
            return ok
        except Exception as e:
            logger.warning(f"send_private 失败: {e}")
            return False

    @staticmethod
    def _resolve_team_open_id(team: str) -> str:
        """按团队名查 lead open_id。规则：FEISHU_TEAM_<NORMALIZED>_OPEN_ID。

        normalize 策略：
        1. 提取 team 字符串里的所有 ASCII 字母数字作为「短标识」
           （例："技术团队-L2" → "L2"，"技术团队-Webhook" → "Webhook"）
        2. 若无 ASCII 字符 → 用整个 team 字符串（中文）的 hash-like 形式
           实际：fallback 用全名替换非 ASCII 为 _ 后 uppercase
           （例："财务团队-争议处理" → "_____"→ 实际是 "__"，但不易记，所以用 Pinyin 注释）

        Returns:
            open_id 字符串（无则空串）
        """
        import os
        import re
        # 1) 优先提取 ASCII 字母数字
        ascii_part = re.sub(r"[^A-Za-z0-9]+", "", team).upper()
        if ascii_part:
            env_key = f"FEISHU_TEAM_{ascii_part}_OPEN_ID"
            val = os.getenv(env_key, "").strip()
            if val:
                return val
        # 2) fallback：把整个 team（含中文）做归一化
        # 中文用每个汉字首字符映射（不精确但比空好）
        # 例如：财务团队-争议处理 → "财务团队-争议处理"
        # 实际策略：定义一个简单的中文 → Pinyin 缩写映射（演示场景够用）
        pinyin_map = {
            "技术团队": "TECH",
            "财务团队": "FINANCE",
            "通用支持团队": "DEFAULT",
            "争议处理": "DISPUTE",
            "退款": "REFUND",
            "L1": "L1",
            "L2": "L2",
            "Webhook": "WEBHOOK",
            "VIP": "VIP",
        }
        translated = team
        for cn, en in pinyin_map.items():
            translated = translated.replace(cn, en)
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", translated).upper().strip("_")
        env_key = f"FEISHU_TEAM_{normalized}_OPEN_ID"
        return os.getenv(env_key, "").strip()

    @staticmethod
    def _format_briefing_text(briefing: dict, *, chat_id: str, merchant_user_id: str) -> str:
        """拼装交接简报（富文本 markdown）。

        包含：商户信息 / 问题摘要 / AI 已分析 / SLA / 触发来源。
        """
        lines = [
            "📨 **新工单交接简报**",
            "",
            f"**工单 ID**：`{briefing.get('ticket_id', '')}`",
            f"**商户 ID**：`{briefing.get('merchant_id', '?')}`",
            f"**对话来源**：chat_id=`{(chat_id or '?')[:20]}`, user_open_id=`{(merchant_user_id or '?')[:20]}`",
            "",
            f"**问题类型**：{briefing.get('problem_type', '?')}",
            f"**优先级**：{briefing.get('priority', '?')}",
            f"**SLA**：{briefing.get('sla_hours', '?')} 小时（截止 {briefing.get('sla_due', '?')}）",
            f"**通知渠道**：{briefing.get('notification_channel', '?')}",
        ]
        if briefing.get("problem_summary"):
            lines += ["", "**问题摘要**：", briefing["problem_summary"]]
        # AI 已分析部分（PDA → TRA 联动时填充）
        if briefing.get("ai_root_causes"):
            lines += ["", "**🤖 AI 根因分析**："]
            for c in briefing["ai_root_causes"]:
                lines.append(f"- {c}")
            conf = briefing.get("ai_confidence")
            if conf is not None:
                lines.append(f"\n（置信度 {conf:.0%}）")
        if briefing.get("ai_recommended_actions"):
            lines += ["", "**💡 AI 建议处理**："]
            for a in briefing["ai_recommended_actions"]:
                lines.append(f"- {a}")
        if briefing.get("diagnosis_id"):
            lines += ["", f"**关联诊断 ID**：`{briefing['diagnosis_id']}`"]
        return "\n".join(lines)

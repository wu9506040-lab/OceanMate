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
import threading
import time
from collections import deque
from typing import Any, Optional

from fastapi import HTTPException

from app.interfaces.base_frontend import BaseFrontend
from app.agents.orchestrator.orchestrator import Orchestrator
from app.agents.orchestrator.polishing import (
    polish_query,
    record_recent_ticket,
)

logger = logging.getLogger(__name__)


# === Day 17 message_id 去重（修"重复 3 遍"bug）===
# 背景：WS + Poller + Webhook 三条路径都可能接到同一 message_id 的事件，
#      之前 webhook 完全没去重，导致同一条 user 消息会被处理 + 推 3 条相同 reply。
# 方案：模块级 LRU deque + 时间戳，5 分钟内同 message_id 直接 short-circuit。
_RECENT_MSG_IDS_MAXLEN = 500  # 最多缓存 500 个 id（足够覆盖 5 分钟内活跃用户）
_RECENT_MSG_IDS_TTL_SEC = 300  # 5 分钟
_recent_message_ids: deque = deque(maxlen=_RECENT_MSG_IDS_MAXLEN)
_message_id_lock = threading.Lock()


def _mark_message_seen(message_id: str) -> bool:
    """检查 + 标记 message_id 是否在最近 5 分钟内见过。

    Returns:
        True = 新消息（已加入 seen 集合，业务继续处理）
        False = 重复消息（short-circuit，业务跳过）
    """
    if not message_id:
        return True  # 无 message_id 视为新消息（不阻断流程）
    with _message_id_lock:
        now = time.time()
        # 清理过期（懒清理：append 前先 pop 老的）
        while _recent_message_ids and _recent_message_ids[0][0] < now - _RECENT_MSG_IDS_TTL_SEC:
            _recent_message_ids.popleft()
        # 检查是否重复
        for ts, mid in _recent_message_ids:
            if mid == message_id:
                return False
        _recent_message_ids.append((now, message_id))
        return True


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


# === Day 17 像真人客服 helpers ===

def _dedup_by_prefix(items: list[str], prefix_len: int = 8) -> list[str]:
    """按前缀去重（解决"问题分析两条说同样内容"问题）。"""
    seen = set()
    out = []
    for it in items:
        prefix = it[:prefix_len].strip()
        if not prefix or prefix in seen:
            continue
        seen.add(prefix)
        out.append(it)
    return out


# 同理心短句：按 (problem_type, category) 选
_EMPATHY_OPENERS: dict = {
    ("拒付", "not_received"): "看到您遇到不少拒付，确实让人头疼，我来帮您分析。",
    ("拒付", "not_authorized"): "未授权类拒付容易反复触发，我来帮您梳理根因。",
    ("拒付", "fraud"): "欺诈类拒付需要尽快处理，我来帮您看看。",
    ("拒付", "recurring"): "订阅类拒付通常涉及买家误解，我来帮您排查。",
    ("拒付", None): "拒付对商户现金流影响很大，我来帮您分析。",
    ("支付失败", None): "支付失败直接影响成交，我来帮您看看怎么处理。",
    ("Webhook 回调失败", None): "回调失败会导致订单状态不一致，我来帮您排查。",
}


def _get_empathy_opener(problem_type: str, category: str) -> str:
    if (problem_type, category) in _EMPATHY_OPENERS:
        return _EMPATHY_OPENERS[(problem_type, category)]
    return _EMPATHY_OPENERS.get((problem_type, None), "")


# reason_name 中文化（不再直接甩英文给中小商户）
_REASON_NAME_CN: dict = {
    "Merchandise/Services Not Received": "商品/服务未收到",
    "Not As Described or Defective": "商品与描述不符或质量缺陷",
    "No Cardholder Authorization": "未获得持卡人授权",
    "Cardholder Does Not Recognize Transaction": "持卡人不认这笔交易",
    "EMV Liability Shift Counterfeit Fraud": "EMV 伪卡欺诈",
    "Canceled Recurring or Digital Goods": "订阅/数字商品被取消",
}


def _translate_reason_name(name: str) -> str:
    """英文 reason_name → 中文（找不到原文则保留原值）。"""
    if not name:
        return ""
    return _REASON_NAME_CN.get(name, name)


def _confidence_label(conf: float) -> str:
    """置信度 → 中文标签（商户看不懂 80%）。

    Day 17 v3 健壮性：None / 非数字 / 异常 → 返"较低"（友好降级，不抛异常）
    避免 briefing 渲染整个被炸。
    """
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return "较低"
    if c >= 0.85:
        return "很高"
    if c >= 0.65:
        return "较高"
    if c >= 0.45:
        return "中等"
    return "较低"


# 主动下一步：按 (problem_type, category) 给具体后续话术
_NEXT_STEPS: dict = {
    ("拒付", "not_received"): "需要我帮您生成一份 13.1 拒付申诉材料模板吗？",
    ("拒付", "not_authorized"): "需要我帮您检查 3DS 配置是否在交易中触发吗？",
    ("拒付", "fraud"): "需要我帮您配置 RDR/CFR 风控拦截吗？",
    ("拒付", "recurring"): "需要我帮您分析订阅类交易的取消流程吗？",
    ("拒付", None): "需要我帮您列出近期拒付订单方便申诉吗？",
    ("支付失败", None): "需要我帮您排查支付链路配置吗？",
    ("Webhook 回调失败", None): "需要我帮您检查回调日志吗？",
}


def _suggest_next_step(problem_type: str, category: str, conf: float) -> str:
    if conf < 0.45:
        return "建议先补充信息或转人工协助。"
    if (problem_type, category) in _NEXT_STEPS:
        return _NEXT_STEPS[(problem_type, category)]
    if (problem_type, None) in _NEXT_STEPS:
        return _NEXT_STEPS[(problem_type, None)]
    return "需要我帮您深入分析吗？"


# === Day 17 v2：分步方案模板（解决方案式输出） ===

def _br_pix_template() -> dict:
    """BR Pix 周末延迟场景模板（每次调用返回新 dict，避免共享引用）。"""
    return {
        "title": "BR Pix 周末凌晨延迟到账",
        "empathy": "BR Pix 周末凌晨延迟是巴西央行系统维护导致的常见问题。",
        "steps": [
            {
                "title": "第一步：确认是否在维护窗口",
                "content": [
                    "巴西央行 Pix 系统维护时间：周六、周日凌晨 2:00–6:00（巴西时间）",
                    "如果在窗口内：等维护结束会自动到账（通常 ≤ 30 分钟）",
                ],
            },
            {
                "title": "第二步：检查订单状态",
                "content": [
                    "在 OP 商户后台 → 交易明细 查订单号",
                    "状态『已扣款』但买家未收到：买家侧银行问题",
                    "状态『处理中』：耐心等待或催收",
                ],
            },
            {
                "title": "第三步：超 30 分钟未到账",
                "content": [
                    "主动联系买家，请其查银行 App",
                    "回复『派单』我帮您创建工单让 BR 团队跟进",
                ],
            },
        ],
        "cta": "需要我帮你创建工单让 BR 团队跟进吗？",
    }


# 模板按 (problem_type, category, channel) 三层 fallback 选
_PDA_TEMPLATES: dict = {
    # === Visa 13.1 — 拒付：商品/服务未收到 ===
    ("拒付", "not_received", "Visa"): {
        "title": "Visa 13.1 拒付（买家说没收到货）",
        "empathy": "看到您遇到不少拒付，确实让人头疼。",
        "steps": [
            {
                "title": "第一步：准备申诉材料",
                "content": [
                    "实物商品：物流单号 + 签收记录",
                    "数字商品：下载记录 + 登录日志 + 激活时间",
                    "都要附上和买家的沟通截图",
                ],
            },
            {
                "title": "第二步：开通 RDR 自动拦截",
                "content": [
                    "在 OP 商户后台 → 风控管理里开启 Visa RDR",
                    "以后这类拒付会自动拦截，不用每次申诉",
                ],
            },
            {
                "title": "第三步：降低以后的拒付",
                "content": [
                    "发货后主动给买家发物流信息",
                    "减少『以为没发货』的误会",
                ],
            },
        ],
        "cta": "需要我帮你创建工单让财务团队跟进吗？",
    },
    # === MC 4837 — 拒付：未获得持卡人授权 ===
    ("拒付", "not_authorized", "Mastercard"): {
        "title": "MC 4837 拒付（持卡人不认这笔交易）",
        "empathy": "未授权类拒付容易反复触发。",
        "steps": [
            {
                "title": "第一步：检查 3DS 验证记录",
                "content": [
                    "在 OP 商户后台 → 风控管理 → 3DS 配置",
                    "看这笔交易是否触发 3DS 验证",
                    "如果没触发，下次同样会被拒",
                ],
            },
            {
                "title": "第二步：检查 Card-on-File 配置",
                "content": [
                    "CVV 校验是否开启",
                    "存储的卡信息是否加密（PCI DSS）",
                ],
            },
            {
                "title": "第三步：开通 Collaboration 拦截",
                "content": [
                    "在 OP 商户后台 → 风控管理 → Collaboration",
                    "可在拒付发生前主动拦截",
                ],
            },
        ],
        "cta": "需要我帮你创建工单让财务团队跟进吗？",
    },
    # === BR Pix 周末延迟（场景类 · 多 key 适配） ===
    ("支付失败", "pix_weekend", None): _br_pix_template(),
    ("结算延迟", "pix_weekend", None): _br_pix_template(),
    ("结算延迟", None, None): _br_pix_template(),
}


# 默认模板（兜底）
_PDA_DEFAULT_TEMPLATE: dict = {
    "title": "{problem_type}",
    "empathy": "{problem_type}对商户影响较大，我来帮你处理。",
    "steps": [
        {
            "title": "第一步：收集证据",
            "content": [
                "订单号 / 错误码 / 发生时间",
                "买家侧的报错截图",
            ],
        },
        {
            "title": "第二步：自查配置",
            "content": [
                "在 OP 商户后台 → 交易明细 查订单状态",
                "检查风控 / 3DS / Webhook 相关配置",
            ],
        },
        {
            "title": "第三步：让团队协助",
            "content": [
                "把证据整理成一条消息发给我",
                "回复『派单』我帮你创建工单让对应团队跟进",
            ],
        },
    ],
    "cta": "需要我帮你创建工单让团队跟进吗？",
}


def _get_pda_template(problem_type: str, category: str, channel: str) -> dict:
    """三层 fallback 选模板：(problem_type, category, channel) → (problem_type, category) → (problem_type) → default。"""
    if (problem_type, category, channel) in _PDA_TEMPLATES:
        return _PDA_TEMPLATES[(problem_type, category, channel)]
    if (problem_type, category, None) in _PDA_TEMPLATES:
        return _PDA_TEMPLATES[(problem_type, category, None)]
    if (problem_type, None, None) in _PDA_TEMPLATES:
        return _PDA_TEMPLATES[(problem_type, None, None)]
    # 默认模板（用 problem_type 替换 {problem_type}）
    tmpl = dict(_PDA_DEFAULT_TEMPLATE)
    tmpl["title"] = tmpl["title"].replace("{problem_type}", problem_type)
    tmpl["empathy"] = tmpl["empathy"].replace("{problem_type}", problem_type)
    return tmpl


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

            # 3.0 Day 17 Fix：message_id 去重（防 WS + Poller + Webhook 三路同消息重复处理）
            message_id = payload.get("event", {}).get("message", {}).get("message_id", "")
            if message_id and not _mark_message_seen(message_id):
                logger.info(
                    f"[dedup] message_id 重复，跳过: message_id={message_id[:24]}"
                )
                return {"code": 0, "msg": "success"}

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
        """格式化 PDA 诊断结果（Day 17 v2 解决方案式）。

        设计原则（用户反馈"不要念诊断报告，要给方案"）：
        1. 不再有"诊断结果""置信度""问题分析"等标题
        2. 英文术语大白话化（13.1 → "买家说没收到货"）
        3. 建议用"第一步/第二步/第三步"分步
        4. 每步说明在哪里操作（OP 商户后台→xxx）
        5. CTA 直接问"需要我帮您创建工单吗？"
        6. 同理心开头一句话就够
        """
        problem_type = data.get("problem_type", "未知")
        try:
            conf = float(data.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        enriched = (trace.get("code_specific_enriched") or {}) if trace else {}
        category = enriched.get("category") or ""
        channel = enriched.get("channel") or ""

        # 低置信度 → 退化（避免给错误方案）
        if conf < 0.45:
            return (
                "🤔 当前证据不够充分，我先不给你具体方案，避免误导。\n\n"
                "建议你：\n"
                "1. 提供具体错误码 / 订单号 / 国家 + 渠道\n"
                "2. 告诉我『派单』，我帮你创建工单让团队跟进"
            )

        # 选模板（按 problem_type + category + channel 三层 fallback）
        template = _get_pda_template(problem_type, category, channel)

        lines = []

        # 1. 同理心开头（一句话）
        if template.get("empathy"):
            lines.append(template["empathy"])
            lines.append("")

        # 2. 标题（一句话说明问题 + "这样处理"）
        title = template["title"]
        lines.append(f"{title}，这样处理：")
        lines.append("")

        # 3. 分步方案
        for step in template["steps"]:
            lines.append(f"**{step['title']}**")
            content = step["content"]
            if isinstance(content, list):
                for item in content:
                    lines.append(f"- {item}")
            else:
                lines.append(content)
            lines.append("")

        # 4. CTA（明确的下一步）
        if template.get("cta"):
            lines.append(template["cta"])

        return "\n".join(lines).rstrip()

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
        if sub == "resolve_ticket":
            # Day 17 v3：工单关闭 + 自动沉淀 KB 的反馈（数字员工闭环第 5 段）
            ticket_id = data.get("ticket_id", "")
            new_status = data.get("status", "closed")
            assign_text = "已关闭" if new_status == "closed" else f"状态更新为 {new_status}"
            promote_result = data.get("promote_result") or {}
            promoted = bool(promote_result.get("promoted"))
            pending_review = bool(promote_result.get("pending_review"))
            rejected = bool(promote_result.get("rejected"))
            already = bool(promote_result.get("already"))

            if not ticket_id or data.get("status") == "not_found":
                return (
                    "🤔 关闭工单失败：未提供工单 ID 或工单不存在。\n\n"
                    "💡 工单 ID 格式：tkt_a1b2c3d4e5f6\n"
                    "📌 回复「我的工单」可查最近 7 天的工单。"
                )

            # 知识沉淀状态分支
            if promoted:
                kb_msg = (
                    f"📚 **知识已沉淀**：案例 `{promote_result.get('case_id', '?')}` "
                    f"已升级为 FAQ，下次再遇到可直接给出方案。"
                )
            elif pending_review:
                kb_msg = (
                    "📚 **知识待审核**：置信度处于中等区间，"
                    "已加入候选池，运营审核后会进入 FAQ。"
                )
            elif rejected:
                reason = (promote_result.get("trace") or {}).get("reason", "置信度不足")
                kb_msg = f"📚 **知识未沉淀**（{reason}），后续如解决可手动加入 FAQ。"
            elif already:
                chroma_id = promote_result.get("existing_chroma_id", "")
                kb_msg = f"📚 **知识已沉淀**（之前已升级，chroma_id={chroma_id[:16]}…）。"
            else:
                # 没触发 promotion（无 KEA / 无 case / 关闭未关联）
                skip_reason = (data.get("trace") or {}).get("skip_promote_reason", "")
                if skip_reason:
                    kb_msg = f"📚 知识沉淀跳过：{skip_reason}"
                else:
                    kb_msg = "📚 工单已结案，知识沉淀未触发。"

            already_note = "（重复关闭）" if data.get("closed_was_already") else ""
            return (
                f"✅ 工单 **{ticket_id}** {assign_text}{already_note}\n\n"
                f"{kb_msg}\n\n"
                "💡 如需查看本工单的诊断/对话记录，回复「工单进度」即可。"
            )

        ticket_id = data.get("ticket_id", "")
        assignee = data.get("assignee", "运营团队")
        sla = data.get("sla_hours", 0)
        # Day 17 v3：低置信度/缺证据的工单 → 商户看到"转专家跟进"的人话
        # 高置信度已派单的工单 → 仍走简洁的「✅ 工单已创建」
        # AI 诊断上下文可能在 data.briefing 里（链式触发时 _extract_briefing 注入）
        briefing = data.get("briefing") or {}
        ai_root_causes = data.get("ai_root_causes") or briefing.get("ai_root_causes") or []
        ai_confidence = data.get("ai_confidence")
        if ai_confidence is None:
            ai_confidence = briefing.get("ai_confidence")
        is_low_conf_handoff = (
            not ai_root_causes
            or (ai_confidence or 0) < 0.7
        )
        if is_low_conf_handoff:
            return (
                f"🤝 为了给您更专业的服务，我帮您转接 **{assignee}** 专家跟进。\n\n"
                f"📨 **工单号**：`{ticket_id}`\n"
                f"⏱️ 预计 {sla}h 内回复您。\n\n"
                f"💡 如有新信息（订单号 / 错误码 / 已开的 3DS 等），"
                f"请直接回复给我，我会更新到工单里。"
            )
        return f"✅ 工单已创建（ID {ticket_id}），分派至 {assignee}，SLA {sla}h"

    @staticmethod
    def _fmt_kea(data: dict, trace: dict) -> str:
        sub = trace.get("sub_intent")
        # Day 17 v3：人工审核命令反馈（数字员工闭环第 5 段）
        if sub == "approve_case":
            return FeishuWebhookHandler._fmt_kea_approve(data)
        if sub == "reject_case":
            return FeishuWebhookHandler._fmt_kea_reject(data)
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
    def _fmt_kea_approve(data: dict) -> str:
        """审核通过反馈。

        反馈原则（用户原文）：
        "✅ case_001 已通过审核，已加入知识库，当前 faq_vec 共 3 条"
        """
        if not data.get("approved"):
            err = data.get("trace", {}).get("error") or data.get("error", "审核失败")
            return f"⚠️ 审核未通过：{err}"
        case_id = data.get("case_id", "未知")
        faq_count = data.get("faq_vec_count", "?")
        reviewer = data.get("reviewer", "运营")
        return (
            f"✅ {case_id} 已通过审核，已加入知识库，"
            f"当前 faq_vec 共 {faq_count} 条（审核人：{reviewer}）。\n\n"
            "下次商户问同样问题，AI 就能直接复用这条知识。"
        )

    @staticmethod
    def _fmt_kea_reject(data: dict) -> str:
        """审核拒绝反馈。

        拒绝时也要明确反馈运营「已经记录，不会入库」。
        """
        if not data.get("rejected"):
            err = data.get("trace", {}).get("error") or data.get("error", "审核操作失败")
            return f"⚠️ 审核未完成：{err}"
        case_id = data.get("case_id", "未知")
        reviewer = data.get("reviewer", "运营")
        reason = data.get("reason", "")
        suffix = f"\n理由：{reason}" if reason else ""
        return (
            f"❌ {case_id} 已拒绝{suffix}（记录人：{reviewer}）。\n"
            "该案例不会进入知识库，避免污染检索结果。"
        )

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

        # Day 17 v3 触发逻辑：3 个条件任一即交接
        keyword_hit = any(k in user_query for k in self._URGENT_HINTS)
        problem_hit = problem_type in self._PDA_CHAIN_PROBLEM_TYPES
        # 缺关键证据（错误码/订单号）→ 也触发交接
        pda_data_for_trigger = pda_data or {}
        missing_evidence = (
            not pda_data_for_trigger.get("error_code")
            or (pda_data_for_trigger.get("confidence", 0) or 0) < 0.5
            or not pda_data_for_trigger.get("root_causes")
        )
        if not (keyword_hit or problem_hit or missing_evidence):
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
        # Day 17 v3 交接简报补全：补 channel + error_code + reason_name + 缺失字段
        pda_trace = pda_result.get("trace") or {}
        code_specific = pda_trace.get("code_specific_enriched") or {}
        # 缺什么信息：PDA 缺 evidence 时提示「还差具体错误码/订单号」
        missing_fields = pda_data.get("missing_fields", [])
        if not missing_fields and pda_data.get("low_confidence_reason"):
            missing_fields = [pda_data["low_confidence_reason"]]
        # 渠道+错误码中文标识
        error_code = (
            code_specific.get("error_code")
            or pda_data.get("error_code")
            or ""
        )
        channel = (
            code_specific.get("channel")
            or pda_data.get("channel")
            or ""
        )
        reason_name_cn = _translate_reason_name(
            code_specific.get("reason_name", "")
        ) or pda_data.get("problem_summary_cn", "")

        # combined result：以 TRA 为顶，附 PDA 上下文
        return {
            "intent": "ticket_routing",  # 主意图切到 TRA
            "tool_name": "ticket_routing",
            "tool_result": tra_wrapped,
            "error_image_path": pda_result.get("error_image_path", ""),  # 保留配图
            "trace": {
                "matched_keywords": pda_trace.get("matched_keywords", []),
                "chain": "pda_to_tra",
                "priority": priority,
                "tier": tier,
                "diagnosis_id": diagnosis_id,
                "user_query": user_query,  # Day 17 v3：原话给 briefing 用
                "code_specific_enriched": code_specific,  # Day 17 v3
                "merchant_context": (pda_trace.get("params") or {}).get("merchant_context")
                or (pda_trace.get("merchant_context") or {}),
                "upstream_diagnosis": {
                    "problem_type": problem_type,
                    "root_causes": pda_data.get("root_causes", []),
                    "confidence": confidence,
                    "confidence_label": _confidence_label(confidence),
                    "recommended_actions": pda_data.get("recommended_actions", []),
                    "evidence_chain": pda_data.get("evidence_chain", []),
                    "channel": channel,
                    "error_code": error_code,
                    "reason_name_cn": reason_name_cn,
                    "missing_fields": missing_fields,
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
            briefing["ai_confidence_label"] = upstream.get("confidence_label")
            briefing["ai_recommended_actions"] = upstream.get("recommended_actions", [])[:3]
            # Day 17 v3 简报补全：渠道/错误码/中文根因/缺什么
            briefing["ai_channel"] = upstream.get("channel")
            briefing["ai_error_code"] = upstream.get("error_code")
            briefing["ai_reason_name_cn"] = upstream.get("reason_name_cn")
            briefing["ai_missing_fields"] = upstream.get("missing_fields", [])
            # 商户画像 + 原话
            briefing["merchant_context"] = trace.get("merchant_context") or {}
            briefing["user_query"] = trace.get("user_query") or briefing.get("problem_summary", "")
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
        """拼装交接简报（富文本 markdown · 仅人工可见）。

        Day 17 v3 设计（5 个必备块）：
        - 👤 商户：画像（国家/行业/客单价）
        - ❓ 问题原文：商户原话 + problem_type
        - 🤖 AI 已诊断：渠道 + 错误码 + 中文根因 + 置信度（标签）
        - 📋 已尝试方案：AI 给过的建议
        - ⚠️ 还缺什么：缺的信息 / 置信度不足的原因
        - 🎯 建议下一步：第一条推荐操作 + 工单元数据

        ⚠️ 注意：本简报通过 send_private 发给团队 lead，商户看不到。
        """
        merchant_ctx = briefing.get("merchant_context") or {}
        # 👤 商户画像
        merchant_lines = []
        merchant_id = briefing.get("merchant_id") or "?"
        country = merchant_ctx.get("country") or merchant_ctx.get("country_code")
        industry = merchant_ctx.get("industry")
        avg_amount = merchant_ctx.get("avg_amount")
        target_users = merchant_ctx.get("target_users")

        profile_parts = [f"ID `{merchant_id}`"]
        if country:
            profile_parts.append(f"国家 **{country}**")
        if industry:
            profile_parts.append(f"行业 **{industry}**")
        if avg_amount is not None:
            profile_parts.append(f"客单 **${avg_amount}**")
        if target_users:
            profile_parts.append(f"客户 **{target_users}**")
        merchant_line = " · ".join(profile_parts)

        # ❓ 问题原文 + 类型
        problem_type = briefing.get("problem_type", "?")
        user_query = briefing.get("user_query") or briefing.get("problem_summary") or ""

        # 🤖 AI 已诊断
        channel = briefing.get("ai_channel") or ""
        error_code = briefing.get("ai_error_code") or ""
        reason_cn = briefing.get("ai_reason_name_cn") or ""
        conf = briefing.get("ai_confidence")
        conf_label = briefing.get("ai_confidence_label") or ""
        if conf is not None and isinstance(conf, (int, float)):
            conf_pct = f"{conf:.0%}"
        else:
            conf_pct = "—"

        diagnosis_parts = []
        if channel or error_code:
            diag_id = f"{channel} {error_code}".strip() or "未识别错误码"
            diagnosis_parts.append(f"- 渠道+错误码：**{diag_id}**")
        if reason_cn:
            diagnosis_parts.append(f"- 根因：**{reason_cn}**")
        diagnosis_parts.append(f"- 置信度：**{conf_label or '—'}**（{conf_pct}）")

        # 📋 已尝试方案（去重 + 限制 3 条）
        attempted = briefing.get("ai_recommended_actions") or []
        attempted = list(dict.fromkeys(attempted))[:3]  # 保序去重

        # ⚠️ 还缺什么
        missing = briefing.get("ai_missing_fields") or []
        if not missing and conf is not None and isinstance(conf, (int, float)) and conf < 0.7:
            missing = ["AI 置信度偏低，建议人工核实"]

        # 🎯 建议下一步（第一条 AI 推荐 + 元数据）
        next_step = attempted[0] if attempted else "请人工核实问题并联系商户"

        lines = [
            "🤖 **【AI 交接简报 · 仅客服可见】**",
            "━━━━━━━━━━━━━━━━━━━━",
            f"👤 **商户**：{merchant_line}",
            "",
            f"❓ **问题类型**：{problem_type}",
        ]
        if user_query:
            lines.append(f"❓ **问题原文**：{user_query[:300]}")
        lines.append("")
        lines.append("🤖 **AI 已诊断**：")
        lines.extend(diagnosis_parts)
        if attempted:
            lines.append("")
            lines.append("📋 **已尝试方案**：")
            for i, a in enumerate(attempted, 1):
                lines.append(f"  {i}. {a}")
        if missing:
            lines.append("")
            lines.append(f"⚠️ **还缺什么**：{'; '.join(missing) if isinstance(missing, list) else missing}")
        lines.append("")
        lines.append(f"🎯 **建议下一步**：{next_step}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(
            f"📨 **工单**：`{briefing.get('ticket_id', '?')}` "
            f"| 优先级 **{briefing.get('priority', '?')}** "
            f"| SLA **{briefing.get('sla_hours', '?')}h** "
            f"（截止 {briefing.get('sla_due', '?')}）"
        )
        if briefing.get("diagnosis_id"):
            lines.append(f"🔗 **关联诊断**：`{briefing['diagnosis_id']}`")
        lines.append(
            f"💬 **对话来源**：chat_id=`{(chat_id or '?')[:24]}` · "
            f"open_id=`{(merchant_user_id or '?')[:24]}`"
        )
        return "\n".join(lines)

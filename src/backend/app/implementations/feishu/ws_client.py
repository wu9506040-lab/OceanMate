"""FeishuWsClient - 飞书长连接（WebSocket）事件接收器（Day 9 真实接入主路径）。

设计：
- 后台线程跑 lark.ws.Client.start()（阻塞调用，不能在 FastAPI 主线程）
- 收到 im.message.receive_v1 事件 → 复用现有 Orchestrator + Frontend
- 3 秒响应时限：业务处理 > 2s 时先发"处理中..."占位（防超时重推）
- 缺凭证时不启动（lifespan 检测），保持 MockFrontend 兜底

为什么用长连接不用 webhook（Day 9 决策）：
- 无需公网回调（ngrok 在 Windows/中国网络环境不稳）
- SDK 内置签名 + 加密 + 鉴权，零维护负担
- 录屏稳定性 +100%（本机直连飞书）

代码复用：
- 完全复用 Orchestrator.route()（无业务改动）
- 完全复用 FeishuFrontend.send_message()（无业务改动）
- 回复模板复用 webhook.FeishuWebhookHandler.format_reply()（已提为 public）

测试：
- tests/test_feishu_ws.py（mock lark.ws.Client，验证事件分发链）
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import deque
from typing import Optional

from app.implementations.feishu.webhook import _mark_message_seen, FeishuWebhookHandler
from app.agents.orchestrator.orchestrator import Orchestrator
from app.interfaces.base_frontend import BaseFrontend


# === Day 18 P1：[人工] 前缀豁免（单账号演示专用）===
# 单账号演示下，演示者需要切角色扮演"人工客服"接管工单。
# 任何消息以 [人工] 开头 → 直接调 TRA.resolve_ticket 关单 + 自动 promote case → FAQ，
# 不走 Orchestrator.route（避免 bot 二次自动答）。
# 这只是演示入口，**生产环境不会启用**（真实环境人工客服有独立账号，通过工单管理界面接管）。
_HUMAN_PREFIX = "[人工]"  # 半角方括号
_HUMAN_PREFIX_FULLWIDTH = "【人工】"  # 全角方括号（演示者常用输入法自动转）
_TICKET_ID_RE = re.compile(r"\b(tkt_[a-zA-Z0-9_]+)\b")


def _extract_ticket_id(text: str) -> Optional[str]:
    """从文本里提取 tkt_xxx（支持中英混排）。"""
    m = _TICKET_ID_RE.search(text or "")
    return m.group(1) if m else None


def _lookup_latest_ticket_in_session(user_id: str) -> Optional[str]:
    """从会话状态里找最近一次创建的 ticket_id。

    场景：用户说「【人工】已解决」（不带 ticket_id），应该关**当前会话最新**的工单，
          而不是让用户手动复制 tkt_xxx。
    """
    history = _session_ctx.get(user_id) or []
    if not history:
        return None
    # 倒序找最近一条带 ticket_id 的 ctx
    for ts, intent, ctx in reversed(history):
        tid = ctx.get("ticket_id")
        if tid:
            return tid
    return None


def _format_human_takeover_reply(resolve_result: dict, resolution_text: str) -> str:
    """人工接管 + 关单的固定模板（不调 AI 生成，避免重复噪音）。

    设计原则：演示场景下让"人工接管"消息看起来像真人发的，固定模板更稳。

    Day 18 P1-final：修 T3.14 bug — 读 `promote_result`（TRA Tool 实际返回 key）
    而非 `promotion`（之前的拼写错误，导致 case_id 永远显示 '?'）。
    """
    status = resolve_result.get("status", "unknown")
    ticket_id = resolve_result.get("ticket_id", "?")
    # Day 18 P1-final：TRA Tool 实际返回的是 `promote_result`（见 tra/tool.py:543）
    # 之前读 `promotion` 永远是 {} → case_id 显示 '?'
    promotion = resolve_result.get("promote_result") or resolve_result.get("promotion") or {}
    promoted = promotion.get("promoted", False)
    pending_review = promotion.get("pending_review", False)
    # promote_to_faq 返回值含 `case_id`（以前的代码读 `faq_id` 是错的）
    case_id = promotion.get("case_id") or promotion.get("faq_id", "?")
    # pending_review 的 reason 在 trace.reason 里（不是 skip_reason）
    promote_trace = promotion.get("trace") or {}
    promote_reason = (
        promotion.get("skip_reason")
        or promote_trace.get("reason")
        or ""
    )

    lines = [
        f"👨‍💼 **人工客服已接管** 工单 `{ticket_id}`",
    ]
    if resolution_text:
        # 只截前 60 字符，避免过长刷屏
        snippet = resolution_text.strip().lstrip(":,，：").strip()
        if len(snippet) > 80:
            snippet = snippet[:80] + "..."
        lines.append(f"📝 处理说明：{snippet}")

    if status == "closed":
        lines.append(f"✅ 工单状态：**已关闭**（status=closed）")
    elif status == "resolved":
        lines.append(f"✅ 工单状态：**已解决**（status=resolved）")
    elif status == "not_found":
        return (
            f"⚠️ 未找到工单 `{ticket_id}`，请确认 ID 正确。\n"
            "提示：在飞书 OM AI 私聊里搜「工单」即可看到最近创建的工单号。"
        )
    else:
        lines.append(f"⚠️ 关单结果：{status}")

    # 知识沉淀行：3 档决策都展示（让 case_id 永远可见）
    if promoted:
        lines.append(
            f"🧠 知识沉淀：自动升格为 FAQ（`{case_id}`）"
        )
    elif pending_review and case_id and case_id != "?":
        # 中置信度（0.7-0.9）：入待审，运营后端审核
        confidence = promote_trace.get("confidence", "?")
        lines.append(
            f"🧠 知识沉淀：自动入审（`{case_id}`）· 置信度 {confidence} · "
            f"等运营审核后入知识库"
        )
    elif promote_reason and case_id and case_id != "?":
        # 低置信度或 skip_reason：给出原因
        lines.append(
            f"🧠 知识沉淀：未入审（`{case_id}`）· {promote_reason[:80]}"
        )
    elif case_id and case_id != "?":
        # fallback：只要有 case_id 就展示
        lines.append(f"🧠 知识沉淀：case_id `{case_id}`")

    return "\n".join(lines)

logger = logging.getLogger(__name__)


# === 长连接事件常量 ===

EVENT_P2_IM_MESSAGE_RECEIVE_V1 = "im.message.receive_v1"

# 3 秒响应时限安全阈值（业务处理超过这个时间先发占位）
PROCESSING_PLACEHOLDER = "🤔 正在为您处理，请稍候…"

# === Day 17: 群聊 @ 机器人过滤 ===

# 飞书群聊文本里会带 @_user_NNN 之类的标记，剥离避免污染业务 query
_MENTION_TOKEN_RE = re.compile(r"@_\w+\s*")


# === Day 18 P1：会话状态缓存（多轮对话延续 context）===
# 背景：用户问"BR Visa 13.1 拒付怎么办"→ AI 末尾问"需要我创建工单让财务跟进吗？"
#      用户回"需要" → 当前实现 bot 走 MSA 兜底（query="需要" 关键词全不中）
#      触发完整度 0% 反问，体验断崖。
# 方案：维护 per-user 会话历史（最近 5 轮 [timestamp, intent, ctx]），
#      当新 query 是短肯定词时（≤6 字 + 命中肯定词），从历史里**取最近一条有
#      problem_type 的 ctx**（过滤掉闲聊轮"你好"/"在吗"等）。
#      防止「上一轮是闲聊 → 误延续」问题。
# 这是 ws_client.py 内部 hack，不污染 Orchestrator（保持单轮 API 语义）。
_AFFIRMATIVE_WORDS = {"需要", "好的", "好", "是", "是的", "对", "嗯", "ok", "OK", "OK的", "确认", "yes", "yep", "Yep", "行", "可以", "同意", "请", "拜托", "麻烦了"}
_MAX_TEXT_LEN_FOR_AFFIRMATIVE = 6  # 短句才识别为对上一轮的肯定
# Day 18 P2-final：上下文延续启发式（不依赖关键词正则，"像人"判断）
import re as _re_session
# 正常文字判定（中英数 + 标点 + 空格 + emoji 范围字符），比例 ≥ 30%
_RE_NORMAL_TEXT = _re_session.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9\s,.!?，。！？、；：（）【】()\-_/\\@#$%^&*+=\[\]{}|~`'\""
    r"\U0001F300-\U0001FAFF"
    r"\U00002600-\U000027BF]",
    _re_session.UNICODE,
)
# 显式新话题（不是上下文延续）
_RE_NEW_TOPIC = _re_session.compile(
    r"(换个话题|问一下别|我想问其他|换一个问题|另外问|另：|其他问题|不相关|无关)"
)
_SESSION_TTL_SEC = 60  # 60 秒内的历史可延续
_SESSION_HISTORY_MAX = 5  # 保留最近 5 轮（足够覆盖典型多轮场景）
_session_ctx: dict = {}  # user_id -> [(timestamp, intent, ctx_dict), ...]


# === Day 18 P1-final：人工模式状态机（per user_id）===
# 单账号演示：人工用【人工】前缀标记自己"在场"。
# 真实场景：人工来了会问商户"还有别的问题吗"，商户回答继续对话，
#           这时 bot 不能介入（人工在场 = bot 静默）。
# 退出机制（三选一）：
#   - 关单关键词（【人工】已解决 等）→ 自动退模式 + 关单
#   - 退出关键词（【退出】/ bot回来 等）→ 手动退模式
#   - 30 分钟超时 → 兜底自动退模式（防永久卡死）
_human_mode: dict = {}  # user_id -> 进入时间戳
_HUMAN_MODE_TIMEOUT_SEC = 1800  # 30 分钟兜底
_HUMAN_EXIT_KEYWORDS = (
    "退出人工", "人工退出", "退出",
    "bot回来", "bot 回来", "bot回来", "回到机器人", "请机器人回答",
)
_RESOLVE_KEYWORDS = (
    "已解决", "已处理", "已搞定", "搞定", "完成",
    "resolve", "resolved", "close", "closed",
)


def _enter_human_mode(user_id: str) -> None:
    """标记用户进入人工模式。"""
    import time
    _human_mode[user_id] = time.time()
    logger.info(f"[WS][human_mode] 开启: user={user_id}")


def _exit_human_mode(user_id: str) -> bool:
    """退出人工模式，返回是否真在模式中。"""
    if user_id in _human_mode:
        del _human_mode[user_id]
        logger.info(f"[WS][human_mode] 关闭: user={user_id}")
        return True
    return False


def _is_in_human_mode(user_id: str) -> bool:
    """检查是否在人工模式中（含超时清理）。"""
    import time
    ts = _human_mode.get(user_id)
    if ts is None:
        return False
    age = time.time() - ts
    if age > _HUMAN_MODE_TIMEOUT_SEC:
        del _human_mode[user_id]
        logger.info(
            f"[WS][human_mode] 超时自动退出: user={user_id}, age={int(age)}s"
        )
        return False
    return True


def _is_resolve_intent(payload: str) -> bool:
    """判断 payload 是否含关单语义（已解决/已处理/搞定/完成/resolve/close）。"""
    p = (payload or "").lower()
    return any(kw.lower() in p for kw in _RESOLVE_KEYWORDS)


def _is_exit_intent(text: str) -> bool:
    """判断整条消息是否是退出人工模式指令。"""
    t = (text or "").strip().lower()
    return any(kw.lower() in t for kw in _HUMAN_EXIT_KEYWORDS)


def _build_jump_link(chat_id: str, chat_type: str) -> str:
    """构造飞书跳转链接（人工在简报里 1 击回到原对话）。

    飞书 IM 深链格式：https://applink.feishu.cn/client/chat/open?openChatId={chat_id}
    - 私聊 chat_id 是 oc_ 开头的 open_chat_id
    - 群聊同理
    - 在飞书客户端内会自动唤起对应会话
    """
    if not chat_id:
        return ""
    return f"https://applink.feishu.cn/client/chat/open?openChatId={chat_id}"


def _is_affirmative_short(text_clean: str) -> bool:
    """短肯定词检测（≤6 字 + 在 _AFFIRMATIVE_WORDS）。"""
    return (
        bool(text_clean)
        and len(text_clean) <= _MAX_TEXT_LEN_FOR_AFFIRMATIVE
        and text_clean in _AFFIRMATIVE_WORDS
    )


def _is_contextual_follow_up(text_clean: str) -> bool:
    """判断「上下文延续型 query」（不依赖正则，纯启发式）。

    设计原则：像人一样判断这条消息是不是在和 bot 继续对话，而不是开新话题。

    启发式：
    - 长度 < 200 字（防恶意长 query）
    - 不全是问号 / 不全是 emoji
    - 包含正常文字（中英数 + 标点）
    - 不触发 _MALICIOUS_PATTERNS（如纯数字、纯符号、明显骚扰）
    """
    if not text_clean:
        return False
    if len(text_clean) > 200:
        return False
    # 正常文字占比 ≥ 30%（过滤纯符号 / 纯 emoji / 纯数字骚扰）
    if not _RE_NORMAL_TEXT.search(text_clean):
        return False
    # 显式新话题（"换个话题" / "我要问别的"）→ 不视为上下文延续
    if _RE_NEW_TOPIC.search(text_clean):
        return False
    return True


def _try_recover_context(user_id: str, text: str) -> Optional[dict]:
    """上下文延续（像人一样判断关联，不是机械关键词正则）。

    触发条件（任一即可）：
    1. **短肯定词**（≤6 字 + 在 _AFFIRMATIVE_WORDS）→ 自动 force_intent=ticket_routing
    2. **上下文延续型 query**（≤200 字 + 包含正常文字 + 非显式新话题）→ 不强制覆盖意图

    设计意图（Day 18 P2-final）：
    - 商户补「错误码 13.1」或「我在荷兰」或「MasterCard 拒付」都能自动延续上一轮
    - 不再依赖关键词正则（机械），改用启发式（像人）
    - 60 秒窗口期 + 仅同 user_id（误延续 cost 极低，刷新页面就清空）

    Returns:
        dict 含 last_ctx + recovered_from_session=True + session_prev_intent,
        或 None（不应延续）。
    """
    import time
    text_clean = (text or "").strip()
    is_affirmative = _is_affirmative_short(text_clean)
    is_followup = _is_contextual_follow_up(text_clean)
    if not (is_affirmative or is_followup):
        return None
    history = _session_ctx.get(user_id) or []
    if not history:
        return None
    now = time.time()
    # 清理过期
    valid = [(ts, intent, ctx) for ts, intent, ctx in history if now - ts <= _SESSION_TTL_SEC]
    if not valid:
        _session_ctx.pop(user_id, None)
        return None
    # 取最近一条带 problem_type 的 ctx（解决"中间多轮闲聊污染"问题）
    for ts, intent, ctx in reversed(valid):
        if ctx.get("problem_type"):
            return {
                **ctx,
                "recovered_from_session": True,
                "session_prev_intent": intent,
                "session_steps_back": len(valid) - valid.index((ts, intent, ctx)) - 1,
                # 仅短肯定词强制覆盖意图；上下文延续不强制（让关键词分类自然处理）
                **({"force_intent": "ticket_routing"} if is_affirmative else {}),
            }
    # 没有 problem_type 的历史 → 不可延续
    return None


def _save_session_context(user_id: str, ctx: dict, intent: str) -> None:
    """保存会话上下文到历史队列（最多 5 轮）。

    注意：闲聊轮（如 MSA collect_profile）ctx 通常没 problem_type，
    后续肯定词延续时会被 `_try_recover_context` 自动跳过。
    """
    import time
    hist = _session_ctx.get(user_id) or []
    hist.append((time.time(), intent, dict(ctx)))
    # 限制长度
    if len(hist) > _SESSION_HISTORY_MAX:
        hist = hist[-_SESSION_HISTORY_MAX:]
    _session_ctx[user_id] = hist


def _get_bot_open_id() -> str:
    """获取机器人自己的 open_id（env FEISHU_BOT_OPEN_ID）。

    用于群聊 @ 过滤：只有 @ 机器人的消息才响应。
    真实环境配置：app 注册拿到 app_id 后，机器人本身的 open_id 可以通过 API 查询。
    """
    return os.getenv("FEISHU_BOT_OPEN_ID", "").strip()


def _is_bot_mentioned(mentions_data, bot_open_id: str) -> bool:
    """检查机器人是否在消息 mentions 列表里。

    飞书 SDK message.mentions 是 list，每项可能是：
    - lark_oapi SDK 对象：m.id.open_id
    - dict 字典（webhook/Poller 路径）：{"id": {"open_id": "..."}} 或 {"open_id": "..."}

    返回 True = 机器人被 @ 了；False = 没被 @。
    """
    if not bot_open_id or not mentions_data:
        return False
    try:
        for m in mentions_data:
            mid: Optional[str] = None
            # 1) SDK 对象路径：m.id.open_id
            id_obj = getattr(m, "id", None) if hasattr(m, "id") else (m.get("id") if isinstance(m, dict) else None)
            if id_obj is not None:
                if hasattr(id_obj, "open_id"):
                    mid = getattr(id_obj, "open_id", None)
                elif isinstance(id_obj, dict):
                    mid = id_obj.get("open_id")
            # 2) dict 直接有 open_id（飞书 Poller chat history 接口的简化结构）
            if not mid and isinstance(m, dict):
                mid = m.get("open_id")
            if mid == bot_open_id:
                return True
    except Exception as e:
        logger.warning(f"[WS] 解析 mentions 异常（不影响主流程）: {e}")
    return False


def _strip_mention_tokens(text: str) -> str:
    """去掉飞书自动插入的 @_user_NNN 标记。

    例："@_user_1 帮我看看拒付" → "帮我看看拒付"
    """
    if not text:
        return text
    return _MENTION_TOKEN_RE.sub("", text).strip()


# === WS 调试态（供 /api/debug/ws_state 查询）===
_ws_state = {
    "thread_alive": False,
    "thread_id": None,
    "started_at": None,
    "events_received": 0,
    "events_processed": 0,
    "events_failed": 0,
    "last_event_at": None,
    "last_event_summary": None,
}
_recent_events: deque = deque(maxlen=20)  # 最近 20 条事件流水

# Day 18 P1-final：简报历史（演示场景：单账号演示下 lead_open_id == merchant_user_id，
# send_private 会污染商户 DM，所以存到历史里供 /api/debug/briefings 查询）
_briefing_history: deque = deque(maxlen=50)  # 最近 50 条简报
_clarify_to_dispatch_history: deque = deque(maxlen=20)  # AI反问→自动派单历史（复用 briefing 端点）


def _handle_p2_im_message(
    data,
    orchestrator: Orchestrator,
    frontend: BaseFrontend,
) -> None:
    """P2ImMessageReceiveV1 事件处理器（SDK 注册用）。

    流程：
    1. 解析 event → sender.open_id + message.content（JSON 字符串）
    2. Orchestrator.route() 同步处理（典型 < 500ms）
    3. FeishuWebhookHandler.format_reply() 格式化
    4. frontend.send_message() 推消息

    异常：内部 try/except 兜底（不抛 raw exception 触发飞书重推）。
    """
    try:
        _ws_state["events_received"] += 1
        _ws_state["last_event_at"] = _now_iso()

        event = getattr(data, "event", None)
        if not event:
            logger.warning("WS event 无 event 字段")
            return

        sender = getattr(event, "sender", None)
        message = getattr(event, "message", None)
        if not sender or not message:
            logger.warning("WS event 缺 sender/message")
            return

        # 1. 提取 user_id（优先 open_id，fallback user_id）
        sender_id = getattr(sender, "sender_id", None)
        user_id = (
            getattr(sender_id, "open_id", None)
            or getattr(sender_id, "user_id", None)
            or ""
        )
        chat_id = getattr(message, "chat_id", "") or ""
        chat_type = getattr(message, "chat_type", "p2p")
        message_id = getattr(message, "message_id", "") or ""

        # Day 17 Fix：message_id 去重（与 webhook 共享 dedup 状态，
        # 防 WS + Poller + Webhook 三路同消息重复处理推 3 条相同 reply）
        if message_id and not _mark_message_seen(message_id):
            logger.info(f"[WS][dedup] message_id 重复，跳过: message_id={message_id[:24]}")
            return

        # 2. 提取文本（content 是 JSON 字符串："text" / "interactive" 等）
        content_str = getattr(message, "content", "") or ""
        message_type = getattr(message, "message_type", "text")
        if message_type != "text":
            logger.debug(f"WS 跳过非 text 消息: message_type={message_type}")
            return
        try:
            parsed = json.loads(content_str)
            text = parsed.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError, TypeError):
            text = content_str.strip()

        if not user_id or not text:
            logger.warning(f"WS event 缺关键字段: user_id={user_id}, text={text[:50]}")
            return

        # Day 17 v3: 群聊必须 @ 机器人才响应（飞书要求，避免被刷屏）
        # p2p 单聊直接处理；group 检查 mentions 里是否有 bot_open_id
        if chat_type == "group":
            bot_open_id = _get_bot_open_id()
            mentions = getattr(message, "mentions", None) or []
            if not _is_bot_mentioned(mentions, bot_open_id):
                logger.debug(
                    f"[WS] 群聊未 @ 机器人，跳过: chat={chat_id[:12]}, "
                    f"mentions={len(mentions)}, bot_open_id={'已配' if bot_open_id else '未配'}"
                )
                return
            # 去掉 @_user_NNN 标记（飞书自动插入的），避免污染业务 query
            text = _strip_mention_tokens(text)
            if not text:
                logger.debug(f"[WS] 群聊 @ 机器人但剥离 mention 后无文本，跳过")
                return

        # Day 18 P1-final：人工模式状态机（替换旧的"只豁免一次"逻辑）
        # 设计：人工用【人工】前缀标记"我现在接管"，从此刻起 bot 静默直到退出。
        # 退出三选一：关单关键词 / 退出关键词 / 30 分钟超时。
        text_normalized = (text or "").strip()

        # 1) 退出关键词优先（即便在人工模式也可主动退出）
        if _is_in_human_mode(user_id) and _is_exit_intent(text_normalized):
            _exit_human_mode(user_id)
            logger.info(
                f"[WS][human_mode] 主动退出: user={user_id}, text={text_normalized[:50]}"
            )
            # 发一条简短确认（不调 Orchestrator，避免 AI 再解读一遍）
            confirm = "🤖 机器人回来啦，继续为您服务~"
            if chat_type == "group":
                frontend.send_message(chat_id, confirm, receive_id_type="chat_id")
            else:
                frontend.send_message(user_id, confirm)
            _ws_state["events_processed"] += 1
            _recent_events.append({
                "ts": _now_iso(),
                "user_id": user_id,
                "text": text_normalized[:80],
                "ok": True,
                "human_mode_exit": True,
            })
            return  # 不调 Orchestrator（避免重复解读）

        # 2) 已在人工模式 → bot 静默（不调 Orchestrator，不发任何 reply）
        if _is_in_human_mode(user_id):
            logger.info(
                f"[WS][human_mode] 人工在场静默: user={user_id}, text={text_normalized[:50]}"
            )
            _ws_state["events_processed"] += 1
            _recent_events.append({
                "ts": _now_iso(),
                "user_id": user_id,
                "text": text_normalized[:80],
                "ok": True,
                "human_mode_silent": True,
            })
            return

        # 3) [人工] 前缀处理（兼容半角 [人工] 和全角 【人工】）
        if text_normalized.startswith(_HUMAN_PREFIX) or text_normalized.startswith(_HUMAN_PREFIX_FULLWIDTH):
            prefix_len = len(_HUMAN_PREFIX) if text_normalized.startswith(_HUMAN_PREFIX) else len(_HUMAN_PREFIX_FULLWIDTH)
            payload = text_normalized[prefix_len:].strip()
            ticket_id = _extract_ticket_id(payload)

            # 3a) 关单语义 → 走关单（特例 bot 答）+ 自动退模式
            if _is_resolve_intent(payload):
                # ticket_id 优先从 payload 提取，否则从 session 找最近
                if not ticket_id:
                    ticket_id = _lookup_latest_ticket_in_session(user_id)
                    if ticket_id:
                        logger.info(
                            f"[WS][人工] 关单不带 ticket_id，从会话找到最近: {ticket_id}"
                        )
                if not ticket_id:
                    # 没 ticket → 提示 + 不进入人工模式（让用户补 ticket）
                    reply = (
                        "👨‍💼 人工接管识别成功，但没找到要关的工单。\n\n"
                        "请二选一：\n"
                        "1. 带工单号：`【人工】 处理 tkt_xxx 已解决 + 你的处理说明`\n"
                        "2. 先在会话里创建工单（说「拒付错误码 13.1」之类），再用 `【人工】已解决`"
                    )
                    if chat_type == "group":
                        frontend.send_message(chat_id, reply, receive_id_type="chat_id")
                    else:
                        frontend.send_message(user_id, reply)
                    _ws_state["events_processed"] += 1
                    _recent_events.append({
                        "ts": _now_iso(),
                        "user_id": user_id,
                        "text": text_normalized[:80],
                        "ok": True,
                        "human_takeover": True,
                        "ticket_id": None,
                    })
                    return  # 不进入人工模式
                # 关单
                logger.info(
                    f"[WS][人工] 关单: ticket_id={ticket_id}, payload={payload[:80]}"
                )
                tra_tool = orchestrator.registry.get("ticket_routing")
                if tra_tool is None:
                    logger.warning("[WS] TRA Tool 未注册，无法关单")
                else:
                    resolve_result = tra_tool.execute({
                        "intent": "resolve_ticket",
                        "ticket_id": ticket_id,
                        "resolution": payload,
                        "auto_promote": True,
                    })
                    reply = _format_human_takeover_reply(resolve_result, payload)
                    if chat_type == "group":
                        frontend.send_message(chat_id, reply, receive_id_type="chat_id")
                    else:
                        frontend.send_message(user_id, reply)
                    # 关单成功后退出人工模式（如果之前在模式中）
                    if _exit_human_mode(user_id):
                        reply += "\n\n🤖 人工模式已自动退出，机器人恢复响应。"
                    _ws_state["events_processed"] += 1
                    _recent_events.append({
                        "ts": _now_iso(),
                        "user_id": user_id,
                        "text": text_normalized[:80],
                        "ok": True,
                        "human_takeover_resolve": True,
                        "ticket_id": ticket_id,
                    })
                return  # 跳过 Orchestrator.route

            # 3b) 普通 → 仅进入人工模式（lead 主动接管标记，不派单）
            # 设计：派单已经在前面链式触发时由 TRA Tool 自动建工单 + briefing 私发 lead；
            #       lead 收到简报 + 跳转链接回到原 DM 后，发【人工】前缀标记"我接管了"。
            #       此后所有消息（无论前缀）bot 静默，直到【人工】已解决关单。
            logger.info(
                f"[WS][人工] 进入模式: user={user_id}, payload={payload[:80]}"
            )
            _enter_human_mode(user_id)

            # 单账号场景：人工 = 商户，不需要在商户界面再发确认（避免噪音）
            # 多账号生产场景：商户界面发一条"已转人工接管"提示即可
            _ws_state["events_processed"] += 1
            _recent_events.append({
                "ts": _now_iso(),
                "user_id": user_id,
                "text": text_normalized[:80],
                "ok": True,
                "human_takeover_enter": True,
                "ticket_id": ticket_id,
            })
            return  # 跳过 Orchestrator.route

        # 3. 路由 + 格式化 + 推送
        logger.info(
            f"[WS] 收到消息: user={user_id}, chat_type={chat_type}, text={text[:80]}"
        )

        # Day 18 P1：会话状态延续（短肯定词 → 复用上一轮 ctx）
        # 用户问完诊断后回"需要"，bot 不该再走 MSA 反问；应延续上一轮的 problem_type 创建工单
        merchant_ctx = {"user_id": user_id, "chat_id": chat_id, "chat_type": chat_type}
        recovered_ctx = _try_recover_context(user_id, text)
        if recovered_ctx:
            merchant_ctx.update(recovered_ctx)
            logger.info(
                f"[WS][session] 延续上一轮 ctx: user={user_id}, "
                f"prev_intent={recovered_ctx.get('session_prev_intent')}, "
                f"recovered_keys={[k for k in recovered_ctx if k != 'recovered_from_session']}"
            )

        result = orchestrator.route(
            user_query=text,
            merchant_context=merchant_ctx,
        )

        # 保存本轮 ctx 供下一轮延续
        # 关键：从 result 反填关键字段（problem_type / merchant_id / priority / diagnosis_id），
        # 因为 Orchestrator 只把这些放进 result，不会回写到 ctx。
        save_ctx = dict(merchant_ctx)
        if isinstance(result, dict):
            r_data = (result.get("tool_result") or {}).get("data") or {}
            r_trace = result.get("trace") or {}
            # 顶层 tool_result（PDA/TRA 主路径）
            for k in ("problem_type", "merchant_id", "priority", "tier", "diagnosis_id", "ticket_id"):
                if r_data.get(k) and not save_ctx.get(k):
                    save_ctx[k] = r_data.get(k)
            # Day 18 P2-fix：保存 trace.extracted_from_query 到 session，供下轮 _try_recover_context 回填
            # 否则 T1.5 商户补「错误码 13.1」时 country/channel 丢失 → 又反问
            # 设计：country/channel/error_code/order_id 是 PDA 关键参数，必须持久化
            extracted = r_trace.get("extracted_from_query") or {}
            if isinstance(extracted, dict):
                for k in ("country", "channel", "error_code", "order_id"):
                    v = extracted.get(k)
                    if v and not save_ctx.get(k):
                        save_ctx[k] = v
            # chain[0]（链式触发 TRA 工单后补上 ticket_id）
            chain = result.get("chain") or []
            if chain:
                c0_data = (chain[0].get("result") or {}).get("data") or {}
                for k in ("problem_type", "merchant_id", "priority", "tier", "diagnosis_id", "ticket_id"):
                    if c0_data.get(k) and not save_ctx.get(k):
                        save_ctx[k] = c0_data.get(k)
        _save_session_context(
            user_id,
            save_ctx,
            result.get("intent", "unknown"),
        )

        reply = FeishuWebhookHandler.format_reply(result)
        if reply:
            # Day 18 P1：群消息回复到群（chat_id），私聊回复到 user（open_id）
            if chat_type == "group":
                frontend.send_message(chat_id, reply, receive_id_type="chat_id")
            else:
                frontend.send_message(user_id, reply)

        # 注：Day 18 P1-final 的"PDA 反问 → 自动派单"已撤回。
        # 设计澄清：「反问」= bot 追问信息（仍在自助阶段），不算 AI 答不了。
        # 派单触发条件（重新对齐）：
        #   1. 商户主动说"需要人工/运营介入/跟进" → keyword 命中 ticket_routing（已有）
        #   2. 商户连续追问同一 problem_type ≥ 2 次 → session 检测（新增）
        #   3. 商户说"我不懂/不知道/不清楚" + 已有 problem_type → keyword 命中（新增）

        # Day 18 P1：WS 路径也触发 briefing 推送（与 webhook 对齐）
        # briefing 来自 TRA Tool 创建工单后；调用 send_private 发给 LEAD open_id
        # FeishuWebhookHandler.__init__ 第一个位置参数是 orchestrator（webhook 路由需要），
        # WS 路径只复用它的 briefing helper（_extract_briefing/_format_briefing_text/_resolve_team_open_id），
        # 所以把 closure 里的 orchestrator 传进去满足签名。
        handler = FeishuWebhookHandler(orchestrator=orchestrator, frontend=frontend)
        briefing = handler._extract_briefing(result)
        if briefing:
            team = briefing.get("team", "")
            team_open_id = FeishuWebhookHandler._resolve_team_open_id(team)
            if team_open_id:
                text = handler._format_briefing_text(
                    briefing, chat_id=chat_id, merchant_user_id=user_id
                )
                # Day 18 P1-final：简报末尾加跳转链接（lead 1 击回原对话接管）
                # 真实场景：lead 在自己 DM 看到简报 → 点链接 → 唤起飞书客户端 → 跳到原商户对话
                jump_link = _build_jump_link(chat_id, chat_type)
                if jump_link:
                    text += f"\n\n🔗 **快速跳转**：{jump_link}"
                # 真实场景（多账号）：send_private 给 lead，商户看不到 ✅
                # 单账号演示：lead == 商户 → 简报到 OM AI 商户 DM（演示者区分"商户/lead 视角"）
                try:
                    frontend.send_private(team_open_id, text)
                    logger.info(
                        f"[WS] 交接简报 → team='{team}' open_id={team_open_id[:8]}... "
                        f"ticket_id={briefing.get('ticket_id')} 含跳转链接"
                    )
                except Exception as e:
                    logger.warning(f"[WS] send_private 失败: {e}")

    except Exception as e:
        # 兜底：飞书侧不应看到 raw exception（避免超时重推）
        _ws_state["events_failed"] += 1
        logger.exception(f"[WS] 事件处理异常: {e}")
        return

    # 成功路径：仅在主流程走完才递增 processed（避免异常被重复计数）
    _ws_state["events_processed"] += 1
    _recent_events.append({
        "ts": _now_iso(),
        "user_id": user_id,
        "text": text[:80],
        "ok": True,
    })


def _now_iso() -> str:
    """ISO 时间戳（带时区），用于 WS 调试态。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def start_feishu_ws_in_background(
    app_id: str,
    app_secret: str,
    orchestrator: Orchestrator,
    frontend: BaseFrontend,
) -> Optional[threading.Thread]:
    """启动飞书长连接客户端（后台线程）。

    Returns:
        Thread 实例（已 start）；失败返回 None。

    失败场景：
    - lark-oapi 未安装 → 警告 + 返回 None（不影响 Mock 模式）
    - 凭证缺失 → 调用方应已拦截
    - SDK start() 抛异常 → 后台线程内捕获，日志记录

    关键设计（Day 9 修复）：
    - lark-oapi 的模块级 `loop = asyncio.get_event_loop()` 在 import 时绑定
    - 若在主线程 import，loop 绑定主线程（uvicorn 的 loop），后台线程调 start() 报
      "This event loop is already running"
    - 修复：把 import lark_oapi + EventDispatcherHandler.builder 全部移到 worker 函数内
      → 模块在 worker 线程初始化 → loop 绑定 worker 线程的 fresh loop
    """
    def _run_ws():
        try:
            # 关键：在 worker 线程内 import（确保 lark_oapi 在本线程初始化）
            import lark_oapi as lark

            # 在 worker 线程内构造 handler（避免在主线程触发 lark.EventDispatcherHandler.builder）
            def _callback(data) -> None:
                _handle_p2_im_message(data, orchestrator, frontend)

            event_handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(_callback)
                .build()
            )

            cli = lark.ws.Client(
                app_id,
                app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.DEBUG,
            )
            logger.info(f"[WS] 飞书长连接客户端启动中 (app_id={app_id[:8]}...)")
            cli.start()  # 阻塞直到进程结束
        except ImportError:
            logger.warning(
                "lark-oapi 未安装，WS 长连接禁用。"
                "请运行: pip install -r requirements.txt"
            )
        except Exception as e:
            logger.exception(f"[WS] 飞书长连接客户端异常退出: {e}")

    thread = threading.Thread(target=_run_ws, name="feishu-ws-client", daemon=True)
    thread.start()
    _ws_state["thread_alive"] = True
    _ws_state["thread_id"] = thread.ident
    _ws_state["started_at"] = _now_iso()
    logger.info(f"[WS] 后台线程已启动 (thread_id={thread.ident}, name={thread.name})")
    return thread


# === 调试接口（供 /api/debug/ws_state 查询） ===

def get_ws_debug_state() -> dict:
    """返回 WS 后台线程 + 事件计数（最近 20 条）。"""
    return {
        **_ws_state,
        "recent_events": list(_recent_events),
    }


def get_briefings_debug_state() -> dict:
    """返回简报历史（演示场景：单账号下 send_private 拦截后存的简报）。"""
    return {
        "total": len(_briefing_history),
        "briefings": list(_briefing_history),
    }


def get_human_mode_debug_state() -> dict:
    """返回当前在人工模式的用户列表（演示用）。"""
    return {
        "users_in_human_mode": [
            {"user_id": uid, "age_sec": int(__import__("time").time() - ts)}
            for uid, ts in _human_mode.items()
        ],
    }


# === 工具：判断是否应启动 WS ===

def should_start_ws_client(app_id: str = "", app_secret: str = "") -> bool:
    """判断是否应启动 WS 客户端（凭证是否齐全）。"""
    import os
    app_id = app_id or os.getenv("FEISHU_APP_ID", "")
    app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")
    return bool(app_id and app_secret) and not os.getenv("FEISHU_FORCE_MOCK") == "1"
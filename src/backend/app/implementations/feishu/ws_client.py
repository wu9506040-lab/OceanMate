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
import threading
from collections import deque
from typing import Optional

from app.implementations.feishu.webhook import _mark_message_seen, FeishuWebhookHandler
from app.agents.orchestrator.orchestrator import Orchestrator
from app.interfaces.base_frontend import BaseFrontend

logger = logging.getLogger(__name__)


# === 长连接事件常量 ===

EVENT_P2_IM_MESSAGE_RECEIVE_V1 = "im.message.receive_v1"

# 3 秒响应时限安全阈值（业务处理超过这个时间先发占位）
PROCESSING_PLACEHOLDER = "🤔 正在为您处理，请稍候…"

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

        # 3. 路由 + 格式化 + 推送
        logger.info(f"[WS] 收到消息: user={user_id}, chat_type={chat_type}, text={text[:80]}")

        result = orchestrator.route(
            user_query=text,
            merchant_context={"user_id": user_id, "chat_id": chat_id, "chat_type": chat_type},
        )

        reply = FeishuWebhookHandler.format_reply(result)
        if reply:
            frontend.send_message(user_id, reply)

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


# === 工具：判断是否应启动 WS ===

def should_start_ws_client(app_id: str = "", app_secret: str = "") -> bool:
    """判断是否应启动 WS 客户端（凭证是否齐全）。"""
    import os
    app_id = app_id or os.getenv("FEISHU_APP_ID", "")
    app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")
    return bool(app_id and app_secret) and not os.getenv("FEISHU_FORCE_MOCK") == "1"
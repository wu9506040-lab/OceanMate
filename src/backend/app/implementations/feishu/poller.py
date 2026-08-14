"""Feishu Chat Poller - 轮询 chat 历史消息作为 WS 收不到事件的 fallback（Day 9）。

为什么需要：
- WS 长连接需要事件订阅生效，但有些租户/测试环境事件不投递
- 轮询是 fallback，2 秒一次，UX 接近实时
- 完全不依赖事件订阅

实现：
- 后台线程每 N 秒拉一次 chat 消息（list_messages API）
- 按 message_id 去重（每条只处理一次）
- 跳过 bot 自己发的消息（sender_type != "user"）
- 处理逻辑：orchestrator.route() → FeishuWebhookHandler.format_reply() → frontend.send_message()
- 与 ws_client 共用 format_reply 和 Orchestrator

复用：
- 完全复用 Orchestrator.route()（无业务改动）
- 完全复用 FeishuFrontend.send_message()（无业务改动）
- 完全复用 FeishuWebhookHandler.format_reply()（无业务改动）

测试：
- tests/test_feishu_poller.py（mock FeishuOpenAPI + Orchestrator + Frontend）
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Optional

from app.agents.orchestrator.orchestrator import Orchestrator
from app.implementations.feishu.api import FeishuOpenAPI
from app.implementations.feishu.webhook import FeishuWebhookHandler

logger = logging.getLogger(__name__)


# === Poller 调试态（供 /api/debug/poller_state 查询）===

_poller_state = {
    "thread_alive": False,
    "thread_id": None,
    "started_at": None,
    "chat_id": None,
    "poll_interval_sec": 0.0,
    "polls_total": 0,
    "messages_seen": 0,
    "messages_processed": 0,
    "messages_failed": 0,
    "last_poll_at": None,
    "last_message_at": None,
}
_recent_processed: deque = deque(maxlen=20)


def _now_iso() -> str:
    """ISO 时间戳（带时区）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _extract_text_from_message(msg: dict) -> str:
    """从飞书 API 返回的 message dict 里提取纯文本。

    body.content 是 JSON 字符串，形如 '{"text": "..."}'
    """
    body = msg.get("body", {}) or {}
    content_str = body.get("content", "") or ""
    try:
        parsed = json.loads(content_str)
        return (parsed.get("text", "") or "").strip()
    except (json.JSONDecodeError, TypeError):
        return content_str.strip()


def _is_user_message(msg: dict) -> bool:
    """过滤掉 bot 自己的消息（sender_type != 'user'）。"""
    sender = msg.get("sender", {}) or {}
    return sender.get("sender_type") == "user"


def start_feishu_poller_in_background(
    api: FeishuOpenAPI,
    chat_id: str,
    orchestrator: Orchestrator,
    frontend,  # BaseFrontend（仅用 send_message）
    poll_interval_sec: float = 2.0,
) -> Optional[threading.Thread]:
    """启动飞书 chat 轮询客户端（后台线程）。

    Args:
        api: FeishuOpenAPI 实例（用于 list_messages）
        chat_id: 目标 chat（p2p 或 group 都行）
        orchestrator: Orchestrator 实例
        frontend: BaseFrontend（用于 send_message）
        poll_interval_sec: 轮询间隔（秒），默认 2

    Returns:
        Thread 实例（已 start）；失败返回 None。
    """
    if not chat_id:
        logger.warning("[Poller] chat_id 缺失，不启动")
        return None

    def _run():
        # 跟踪已处理消息 ID（去重）；按 message_id set
        seen_ids: set[str] = set()
        # 跟踪上次轮询时间戳（毫秒），下次只拉新消息
        last_time_ms = int(time.time() * 1000) - 5000  # 初始看最近 5s（接续旧消息）

        logger.info(f"[Poller] 启动 (chat_id={chat_id}, interval={poll_interval_sec}s)")
        while True:
            try:
                _poller_state["polls_total"] += 1
                _poller_state["last_poll_at"] = _now_iso()

                # 飞书 API start_time/end_time 单位是**秒**（不是毫秒）
                messages = api.list_messages(
                    chat_id=chat_id,
                    start_time_sec=last_time_ms // 1000 if last_time_ms > 10**12 else int(last_time_ms),
                    page_size=20,
                )

                for msg in messages:
                    msg_id = msg.get("message_id", "")
                    if not msg_id or msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                    # 跳过 bot 自己发的消息
                    if not _is_user_message(msg):
                        continue

                    _poller_state["messages_seen"] += 1
                    text = _extract_text_from_message(msg)
                    if not text:
                        continue

                    sender = msg.get("sender", {}) or {}
                    # 飞书 list_messages 返回的 sender 结构是扁平：
                    # {"id": "ou_xxx", "id_type": "open_id", "sender_type": "user", ...}
                    # 注意：sender.id 就是 open_id（不是 sender.sender_id.open_id）
                    user_id = (
                        sender.get("id")
                        or sender.get("open_id")
                        or ""
                    )

                    if not user_id:
                        logger.warning(f"[Poller] 跳过缺 user_id 的消息: {msg_id}")
                        continue

                    logger.info(
                        f"[Poller] 收到消息: user={user_id[:12]}..., text={text[:60]}"
                    )

                    try:
                        result = orchestrator.route(
                            user_query=text,
                            merchant_context={"user_id": user_id, "chat_id": chat_id},
                        )
                        reply = FeishuWebhookHandler.format_reply(result)
                        if reply:
                            frontend.send_message(user_id, reply)
                        _poller_state["messages_processed"] += 1
                        _poller_state["last_message_at"] = _now_iso()
                        _recent_processed.append({
                            "ts": _now_iso(),
                            "user_id": user_id[:12] + "...",
                            "text": text[:60],
                            "ok": True,
                        })
                    except Exception as e:
                        _poller_state["messages_failed"] += 1
                        _recent_processed.append({
                            "ts": _now_iso(),
                            "user_id": user_id[:12] + "...",
                            "text": text[:60],
                            "ok": False,
                            "error": str(e)[:80],
                        })
                        logger.exception(f"[Poller] 处理消息失败: {e}")

                # 推进时间窗
                if messages:
                    last_time_ms = max(
                        last_time_ms,
                        max(int(m.get("create_time", 0)) for m in messages) + 1,
                    )

                # 清理 seen_ids（保留最近 200 条）
                if len(seen_ids) > 500:
                    seen_ids = set(list(seen_ids)[-200:])

            except Exception as e:
                logger.exception(f"[Poller] 轮询异常: {e}")

            time.sleep(poll_interval_sec)

    thread = threading.Thread(target=_run, name="feishu-poller", daemon=True)
    thread.start()
    _poller_state.update({
        "thread_alive": True,
        "thread_id": thread.ident,
        "started_at": _now_iso(),
        "chat_id": chat_id,
        "poll_interval_sec": poll_interval_sec,
    })
    logger.info(f"[Poller] 后台线程已启动 (thread_id={thread.ident})")
    return thread


def should_start_poller(chat_id: str = "") -> bool:
    """判断是否应启动 Poller（chat_id 是否配置）。"""
    import os

    chat_id = chat_id or os.getenv("FEISHU_POLL_CHAT_ID", "")
    return bool(chat_id)


def get_poller_debug_state() -> dict:
    """返回 Poller 调试态。"""
    return {
        **_poller_state,
        "recent_processed": list(_recent_processed),
    }
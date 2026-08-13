"""飞书前端实现层（工厂 + 降级策略）。

工厂函数（自动选择 Mock vs Feishu）：
- FEISHU_APP_ID + FEISHU_APP_SECRET 都有 → FeishuFrontend（真实 httpx 调用）
- 缺失任一 → MockFrontend（写本地日志，Demo 不卡死）

评审要点：
- 真实环境切凭证即可启用（无需改业务代码）
- 4 Tool 和 Orchestrator 都不感知载体（仅依赖 BaseFrontend 协议）
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from app.interfaces.base_frontend import BaseFrontend
from app.implementations.feishu.mock_frontend import MockFrontend

logger = logging.getLogger(__name__)


def get_feishu_frontend(
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    btable_app_token: Optional[str] = None,
    btable_table_id: Optional[str] = None,
    verification_token: Optional[str] = None,
    force_mock: bool = False,
) -> BaseFrontend:
    """工厂函数：返回 BaseFrontend 实例（Mock 或 真实）。

    优先级：
    1. force_mock=True → 强制 Mock
    2. env FEISHU_FORCE_MOCK=1 → Mock
    3. None or 缺凭证 → Mock（自动降级，log 提示）
    4. 凭证齐全 → FeishuFrontend

    Returns:
        BaseFrontend 实例
    """
    # 显式强制 Mock
    if force_mock or os.getenv("FEISHU_FORCE_MOCK") == "1":
        logger.info("FeishuFrontend 强制启用 MockFrontend（force_mock=True）")
        return MockFrontend()

    # 读 env（未传参时）
    app_id = app_id or os.getenv("FEISHU_APP_ID", "")
    app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")
    btable_app_token = btable_app_token or os.getenv("FEISHU_BTABLE_APP_TOKEN", "")
    btable_table_id = btable_table_id or os.getenv("FEISHU_BTABLE_TABLE_ID", "")
    verification_token = verification_token or os.getenv("FEISHU_VERIFICATION_TOKEN")

    # 凭证缺失 → 自动 Mock
    if not (app_id and app_secret):
        logger.warning(
            "⚠️ Feishu 凭证缺失（FEISHU_APP_ID / FEISHU_APP_SECRET），自动启用 MockFrontend。"
            "Demo 模式：消息会写到 .feishu_mock_log.json。"
        )
        return MockFrontend()

    # 凭证齐全 → 真实实现
    from app.implementations.feishu.frontend import FeishuFrontend
    logger.info(f"FeishuFrontend 启用真实集成（app_id={app_id[:8]}...）")
    return FeishuFrontend(
        app_id=app_id,
        app_secret=app_secret,
        btable_app_token=btable_app_token,
        btable_table_id=btable_table_id,
        verification_token=verification_token,
    )


__all__ = [
    "MockFrontend",
    "FeishuFrontend",
    "FeishuOpenAPI",
    "FeishuAPIError",
    "FeishuWebhookHandler",
    "get_feishu_frontend",
    "start_feishu_ws_in_background",
    "should_start_ws_client",
]


def __getattr__(name):
    """懒加载（避免循环 import）。"""
    if name == "FeishuFrontend":
        from app.implementations.feishu.frontend import FeishuFrontend
        return FeishuFrontend
    if name == "FeishuOpenAPI":
        from app.implementations.feishu.api import FeishuOpenAPI
        return FeishuOpenAPI
    if name == "FeishuAPIError":
        from app.implementations.feishu.api import FeishuAPIError
        return FeishuAPIError
    if name == "FeishuWebhookHandler":
        from app.implementations.feishu.webhook import FeishuWebhookHandler
        return FeishuWebhookHandler
    if name == "start_feishu_ws_in_background":
        from app.implementations.feishu.ws_client import start_feishu_ws_in_background
        return start_feishu_ws_in_background
    if name == "should_start_ws_client":
        from app.implementations.feishu.ws_client import should_start_ws_client
        return should_start_ws_client
    if name == "get_ws_debug_state":
        from app.implementations.feishu.ws_client import get_ws_debug_state
        return get_ws_debug_state
    if name == "start_feishu_poller_in_background":
        from app.implementations.feishu.poller import start_feishu_poller_in_background
        return start_feishu_poller_in_background
    if name == "should_start_poller":
        from app.implementations.feishu.poller import should_start_poller
        return should_start_poller
    if name == "get_poller_debug_state":
        from app.implementations.feishu.poller import get_poller_debug_state
        return get_poller_debug_state
    raise AttributeError(f"module 'app.implementations.feishu' has no attribute '{name}'")

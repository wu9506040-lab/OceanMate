"""FeishuFrontend - 飞书前端实现（真实集成 BaseFrontend）。

设计：
- 5 方法全部走 FeishuOpenAPI（httpx 调飞书真实 API）
- 异常 → 返回 False / 空串，**不抛 raw exception**（友好降级）
- 用于：FEISHU_APP_ID + FEISHU_APP_SECRET 环境变量齐全时启用

参见 docs/sop/SOP-FEISHU.md §4 逆向场景。
"""

from __future__ import annotations

import logging
from typing import Optional

from app.interfaces.base_frontend import BaseFrontend
from app.implementations.feishu.api import FeishuOpenAPI, FeishuAPIError

logger = logging.getLogger(__name__)


# === 多维表格配置（占位 · 真实环境从 env 读）===

DEFAULT_BTABLE_APP_TOKEN = ""  # 飞书多维表格 app_token
DEFAULT_BTABLE_TABLE_ID = ""  # 表格 ID


class FeishuFrontend(BaseFrontend):
    """飞书前端实现（BaseFrontend 协议）。

    使用：
        frontend = FeishuFrontend(
            app_id="cli_xxx",
            app_secret="xxx",
            btable_app_token="bascnxxx",     # 可选：多维表格 app_token
            btable_table_id="tblxxx",         # 可选：表格 ID
        )
        ok = frontend.send_message("ou_xxx", "BR Visa 拒付诊断完成")
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        btable_app_token: str = DEFAULT_BTABLE_APP_TOKEN,
        btable_table_id: str = DEFAULT_BTABLE_TABLE_ID,
        verification_token: Optional[str] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.api = FeishuOpenAPI(app_id=app_id, app_secret=app_secret)
        self.btable_app_token = btable_app_token
        self.btable_table_id = btable_table_id

    def close(self) -> None:
        """关闭 HTTP 客户端（测试 / 进程退出时）。"""
        self.api.close()

    # === 5 方法实现 ===

    def send_message(self, user_id: str, message: str, receive_id_type: str = "open_id") -> bool:
        """发消息给商户（im/v1/messages）。

        Args:
            user_id: open_id（私聊） | chat_id（群）
            receive_id_type: "open_id" | "chat_id"（Day 18 P1：群消息回复）

        异常处理：网络/Auth/JSON 错 → 返回 False + log（不抛 raw exception）。
        """
        try:
            self.api.send_message(user_id=user_id, text=message, receive_id_type=receive_id_type)
            return True
        except FeishuAPIError as e:
            logger.warning(f"Feishu send_message failed: {e}")
            return False

    def send_image(self, user_id: str, image_path: str) -> bool:
        """发图片（先 upload_image 拿 key，再 send_message with image msg_type）。

        异常处理：上传/发送失败 → 返回 False + log。
        适合：错误码配图、商户 dashboard 截图等场景。
        """
        import os
        if not os.path.exists(image_path):
            logger.warning(f"Feishu send_image: file not found {image_path}")
            return False
        try:
            image_key = self.api.upload_image(image_path)
            if not image_key:
                logger.warning(f"Feishu send_image: upload returned empty image_key")
                return False
            self.api.send_image(user_id=user_id, image_key=image_key)
            return True
        except FeishuAPIError as e:
            logger.warning(f"Feishu send_image failed: {e}")
            return False

    def send_private(self, user_id: str, message: str) -> bool:
        """发私有消息（人工交接简报）。"""
        try:
            self.api.send_message(user_id=user_id, text=message)
            return True
        except FeishuAPIError as e:
            logger.warning(f"Feishu send_private failed: {e}")
            return False

    def create_group(self, members: list[str], name: Optional[str] = None) -> str:
        """创建群聊（im/v1/chats）。

        异常处理：失败返回空串 + log（不抛 raw exception）。
        """
        try:
            data = self.api.create_group(
                user_id_list=members,
                name=name or "OceanMate 工单群",
            )
            return data.get("chat_id", "")
        except FeishuAPIError as e:
            logger.warning(f"Feishu create_group failed: {e}")
            return ""

    def add_group_member(self, group_id: str, user_id: str) -> bool:
        """拉人进群。"""
        try:
            self.api.add_group_member(chat_id=group_id, user_id_list=[user_id])
            return True
        except FeishuAPIError as e:
            logger.warning(f"Feishu add_group_member failed: {e}")
            return False

    def sync_dashboard_data(self, data: dict) -> bool:
        """同步运营数据到多维表格。

        异常处理：凭证缺失 / API 失败 → 返回 False + log。
        """
        if not (self.btable_app_token and self.btable_table_id):
            logger.warning("Feishu 多维表格未配置（btable_app_token / btable_table_id 缺失）")
            return False
        try:
            self.api.sync_dashboard_data(
                app_token=self.btable_app_token,
                table_id=self.btable_table_id,
                fields=_data_to_btable_fields(data),
            )
            return True
        except FeishuAPIError as e:
            logger.warning(f"Feishu sync_dashboard_data failed: {e}")
            return False


def _data_to_btable_fields(data: dict) -> dict:
    """运营数据 → 多维表格 fields 格式（PoC 简化）。"""
    # 飞书多维表格 fields 是 dict，value 类型按列 schema 自动
    return {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))}

"""FeishuOpenAPI - 飞书 Open API 客户端（httpx 实现，不依赖 lark-oapi）。

设计要点：
- 仅 PoC 必要端点（5 个），不实现完整飞书 SDK
- tenant_access_token 内存缓存（2 小时有效）
- 超时 5s（飞书平均 1-2s）+ 失败重试 1 次
- 错误响应统一抛 FeishuAPIError（带 code + msg）

参考：https://open.feishu.cn/document/server-docs/api-call-guide/server-api-list
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

# === 飞书 API 基础配置 ===

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"
DEFAULT_TIMEOUT = 5.0  # 秒


class FeishuAPIError(Exception):
    """飞书 API 错误（统一封装）。"""

    def __init__(self, code: int, msg: str, endpoint: str):
        self.code = code
        self.msg = msg
        self.endpoint = endpoint
        super().__init__(f"Feishu API error [{endpoint}]: code={code}, msg={msg}")


class FeishuOpenAPI:
    """飞书 Open API 客户端（httpx 同步版）。

    使用：
        api = FeishuOpenAPI(app_id="...", app_secret="...")
        ok = api.send_message(user_id="ou_xxx", text="BR Visa 拒付诊断完成")
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        timeout: float = DEFAULT_TIMEOUT,
        base_url: str = FEISHU_BASE_URL,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.timeout = timeout
        self.base_url = base_url
        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        """关闭 HTTP 客户端（测试 / 进程退出时）。"""
        try:
            self._http.close()
        except Exception:
            pass

    # === Tenant Token 管理（2 小时缓存）===

    def _get_tenant_token(self) -> str:
        """获取 tenant_access_token（缓存到过期）。"""
        if self._token and time.time() < self._token_expire_at - 60:
            return self._token

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        body = {"app_id": self.app_id, "app_secret": self.app_secret}
        try:
            resp = self._http.post(url, json=body)
            data = self._parse(resp, "auth.tenant_access_token")
            self._token = data["tenant_access_token"]
            self._token_expire_at = time.time() + data.get("expire", 7200)
            return self._token
        except Exception as e:
            raise FeishuAPIError(
                code=-1, msg=f"获取 tenant_access_token 失败: {e}", endpoint="auth.tenant_access_token"
            ) from e

    # === 核心 5 端点 ===

    def send_message(self, user_id: str, text: str, msg_type: str = "text") -> dict:
        """发消息（im/v1/messages）。

        Args:
            user_id: 接收者 ID（open_id）
            text: 消息内容
            msg_type: "text" | "interactive"（卡片）

        Returns:
            {"message_id": "..."}
        """
        url = f"{self.base_url}/im/v1/messages?receive_id_type=open_id"
        body = {
            "receive_id": user_id,
            "msg_type": msg_type,
            "content": _pack_content(msg_type, text),
        }
        return self._post_authed(url, body, "im.send_message").get("data", {})

    def upload_image(self, image_path: str, image_type: str = "message") -> str:
        """上传图片到飞书（im/v1/images），返回 image_key。

        用于后续在消息中引用 image_key 发图片。
        需要权限 im:resource。
        image_type: "message"（消息图片）或 "avatar"（头像），默认 "message"。
        """
        import os
        url = f"{self.base_url}/im/v1/images"
        with open(image_path, "rb") as f:
            files = {"image": (os.path.basename(image_path), f, "image/png")}
            data_payload = {"image_type": image_type}
            headers = {"Authorization": f"Bearer {self._get_tenant_token()}"}
            resp = self._http.post(url, files=files, data=data_payload, headers=headers)
            data = self._parse(resp, "im.upload_image")
            return data.get("data", {}).get("image_key", "")

    def send_image(self, user_id: str, image_key: str) -> dict:
        """发图片消息（im/v1/messages · msg_type=image）。

        Args:
            user_id: 接收者 ID（open_id）
            image_key: 上传后获得的 image_key
        """
        import json
        url = f"{self.base_url}/im/v1/messages?receive_id_type=open_id"
        body = {
            "receive_id": user_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}),
        }
        return self._post_authed(url, body, "im.send_image").get("data", {})

    def create_group(self, user_id_list: list[str], name: str = "OceanMate 工单群") -> dict:
        """创建群聊（im/v1/chats）。

        Returns:
            {"chat_id": "oc_xxx", ...}
        """
        url = f"{self.base_url}/im/v1/chats"
        body = {"name": name, "user_id_list": user_id_list}
        return self._post_authed(url, body, "im.create_group").get("data", {})

    def add_group_member(self, chat_id: str, user_id_list: list[str]) -> dict:
        """拉人进群（im/v1/chats/{chat_id}/members）。

        Returns:
            {"invalid_id_list": [...], ...}
        """
        url = f"{self.base_url}/im/v1/chats/{chat_id}/members"
        body = {"id_list": user_id_list}
        return self._post_authed(url, body, "im.add_group_member").get("data", {})

    def list_chats(self, page_size: int = 20) -> list[dict]:
        """列出 bot 所在的所有 chat（im/v1/chats）。

        需要权限 im:chat:readonly（或 im:chat / im:chat:read）。
        Returns:
            [{"chat_id": "oc_xxx", "name": "...", "chat_type": "p2p|group", ...}, ...]
        """
        url = f"{self.base_url}/im/v1/chats?page_size={page_size}"
        return self._get_authed(url, "im.list_chats").get("data", {}).get("items", [])

    def list_messages(
        self,
        chat_id: str,
        start_time_ms: Optional[int] = None,
        page_size: int = 20,
    ) -> list[dict]:
        """拉取 chat 最近消息（im/v1/messages）。

        Args:
            chat_id: 目标 chat
            start_time_ms: 仅返回此时间戳之后的消息（毫秒）
            page_size: 最多拉取条数（最大 50）

        需要权限 im:message:readonly。

        Returns:
            [{"message_id": "...", "sender": {...}, "msg_type": "text", "body": {"content": "..."},
              "create_time": 1700000000000}, ...]
        """
        params = f"container_id_type=chat&container_id={chat_id}&page_size={page_size}&sort_type=ByCreateTimeAsc"
        if start_time_ms is not None:
            params += f"&start_time={start_time_ms}"
        url = f"{self.base_url}/im/v1/messages?{params}"
        return self._get_authed(url, "im.list_messages").get("data", {}).get("items", [])

    def sync_dashboard_data(
        self, app_token: str, table_id: str, fields: dict
    ) -> dict:
        """同步数据到多维表格（bitable/v1/apps/.../tables/.../records）。

        Returns:
            {"record": {"record_id": "..."}}
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        body = {"fields": fields}
        return self._post_authed(url, body, "bitable.add_record").get("data", {})

    # === 内部辅助 ===

    def _post_authed(self, url: str, body: dict, endpoint: str) -> dict:
        """POST 带租户 Token + 失败重试 1 次。"""
        headers = {"Authorization": f"Bearer {self._get_tenant_token()}"}
        for attempt in range(2):
            try:
                resp = self._http.post(url, json=body, headers=headers)
                return self._parse(resp, endpoint)
            except FeishuAPIError as e:
                # token 过期（code 99991663 / 99991664）→ 重试一次
                if attempt == 0 and e.code in (99991663, 99991664):
                    self._token = None
                    continue
                raise

    def _get_authed(self, url: str, endpoint: str) -> dict:
        """GET 带租户 Token + 失败重试 1 次。"""
        headers = {"Authorization": f"Bearer {self._get_tenant_token()}"}
        for attempt in range(2):
            try:
                resp = self._http.get(url, headers=headers)
                return self._parse(resp, endpoint)
            except FeishuAPIError as e:
                if attempt == 0 and e.code in (99991663, 99991664):
                    self._token = None
                    continue
                raise

    def _parse(self, resp: httpx.Response, endpoint: str) -> dict:
        """解析响应：HTTP 200 + code=0 视为成功，否则抛 FeishuAPIError。"""
        if resp.status_code != 200:
            raise FeishuAPIError(
                code=resp.status_code,
                msg=f"HTTP {resp.status_code}: {resp.text[:200]}",
                endpoint=endpoint,
            )
        try:
            data = resp.json()
        except Exception as e:
            raise FeishuAPIError(
                code=-2, msg=f"JSON 解析失败: {e}", endpoint=endpoint
            ) from e

        if data.get("code", 0) != 0:
            raise FeishuAPIError(
                code=data.get("code", -1),
                msg=data.get("msg", "未知错误"),
                endpoint=endpoint,
            )
        return data


def _pack_content(msg_type: str, text: str) -> str:
    """按 msg_type 打包 content（飞书 API 要求 content 是 JSON 字符串）。"""
    import json
    if msg_type == "text":
        return json.dumps({"text": text})
    if msg_type == "interactive":
        # 卡片消息：text 已是 JSON 字符串
        return text
    return json.dumps({"text": text})

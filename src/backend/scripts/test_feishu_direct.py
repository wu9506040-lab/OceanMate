"""绕过 WS，直接用飞书 OpenAPI 测试消息收发链路。

为什么：WS 长连接在某些情况下收不到事件（订阅生效延迟、租户配置等）。
此脚本证明：
1. 凭证有效（能拿到 tenant_access_token）
2. Bot 能列出自己的 chat
3. Bot 能向 chat 发消息
4. Bot 能读 chat 历史消息

用法：
    cd src/backend
    python -m scripts.test_feishu_direct [chat_id_or_open_id]

不带参数 → 自动列出 bot 所在 chat 让你选第一个发测试消息
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Windows console GBK 兼容
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# 把 src/backend 加入 import 路径
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# 加载 .env
try:
    from dotenv import load_dotenv

    root_env = BACKEND_ROOT.parent.parent / ".env"
    local_env = BACKEND_ROOT / ".env"
    if root_env.exists():
        load_dotenv(root_env)
    elif local_env.exists():
        load_dotenv(local_env)
except ImportError:
    pass

import httpx  # noqa: E402

FEISHU_BASE = "https://open.feishu.cn/open-apis"


def get_token() -> str:
    """获取 tenant_access_token。"""
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("❌ 凭证缺失（FEISHU_APP_ID / FEISHU_APP_SECRET）")
        sys.exit(1)

    r = httpx.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10.0,
    )
    data = r.json()
    if data.get("code", -1) != 0:
        print(f"❌ 获取 token 失败: {data}")
        sys.exit(1)
    print(f"✅ token: {data['tenant_access_token'][:16]}...")
    print(f"   有效期: {data.get('expire', 0)} 秒")
    return data["tenant_access_token"]


def list_chats(token: str) -> list:
    """列出 bot 所在的所有 chat（含单聊/群聊）。"""
    r = httpx.get(
        f"{FEISHU_BASE}/im/v1/chats?page_size=20",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    data = r.json()
    if data.get("code", -1) != 0:
        print(f"❌ 列出 chat 失败: {data}")
        sys.exit(1)
    items = data.get("data", {}).get("items", [])
    print(f"✅ bot 所在 chat 共 {len(items)} 个：")
    for i, c in enumerate(items):
        chat_id = c.get("chat_id", "?")
        name = c.get("name", "(无名)")
        chat_type = c.get("chat_type", "?")  # p2p / group
        print(f"   [{i}] {name} (type={chat_type}, chat_id={chat_id})")
    return items


def send_text(token: str, receive_id: str, receive_id_type: str, text: str) -> dict:
    """向指定 receive_id 发文本消息。"""
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    r = httpx.post(
        f"{FEISHU_BASE}/im/v1/messages?receive_id_type={receive_id_type}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=body,
        timeout=10.0,
    )
    data = r.json()
    if data.get("code", -1) != 0:
        print(f"❌ 发消息失败: {data}")
        return data
    msg_id = data.get("data", {}).get("message_id", "?")
    print(f"✅ 已发送: message_id={msg_id}")
    return data


def list_recent_messages(token: str, chat_id: str) -> list:
    """读 chat 最近 10 条消息（验证 Bot 收到的入站）。"""
    r = httpx.get(
        f"{FEISHU_BASE}/im/v1/messages?container_id_type=chat&container_id={chat_id}&page_size=10&sort_type=ByCreateTimeDesc",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    data = r.json()
    if data.get("code", -1) != 0:
        print(f"❌ 读消息失败: {data}")
        return []
    items = data.get("data", {}).get("items", [])
    print(f"✅ chat {chat_id} 最近 {len(items)} 条消息：")
    for m in items:
        sender = m.get("sender", {}).get("sender_id", {}).get("open_id", "?")
        msg_type = m.get("msg_type", "?")
        content_str = m.get("body", {}).get("content", "{}")
        try:
            content = json.loads(content_str).get("text", content_str)[:80]
        except (json.JSONDecodeError, TypeError):
            content = content_str[:80]
        create_time = m.get("create_time", 0)
        print(f"   [{create_time}] sender={sender[:12]}... type={msg_type} text={content}")
    return items


def main() -> int:
    token = get_token()
    print()

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if not arg:
        chats = list_chats(token)
        if not chats:
            print("⚠️ bot 暂未加入任何 chat")
            return 1
        # 默认选第一个（通常是最近的私聊/群）
        target = chats[0]
        chat_id = target["chat_id"]
        chat_name = target.get("name", "(无名)")
        chat_type = target.get("chat_type", "?")
        print()
        print(f"👉 默认选第一个 chat: {chat_name} ({chat_type})")
    else:
        chat_id = arg

    print()
    print(f"📤 测试向 chat_id={chat_id} 发消息：")
    send_text(token, chat_id, "chat_id", "🤖 [OceanMate 直连测试] 你好，我是 OM AI。如果收到这条，说明 Bot → User 链路通了。")

    print()
    print(f"📥 读 chat_id={chat_id} 最近消息：")
    list_recent_messages(token, chat_id)

    print()
    print("✅ 测试完成。如果 Bot 能发能读 → 凭证 + 权限 + 链路全 OK，问题只在 WS 事件订阅。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""诊断脚本：检查飞书 bot 当前所在 chat + 最近消息。

用法：
    cd src/backend
    python scripts/diag_feishu.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Windows console UTF-8（CLAUDE.md 已知约束）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

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


def main() -> int:
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("❌ FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
        return 1
    if app_secret.startswith("<PLACEHOLDER"):
        print("❌ APP_SECRET 是占位符")
        return 1

    from app.implementations.feishu.api import FeishuOpenAPI

    api = FeishuOpenAPI(app_id=app_id, app_secret=app_secret)
    print("=" * 60)
    print("Step 1: 列出 bot 所在 chat（判断 bot 在哪些会话里）")
    print("=" * 60)
    try:
        chats = api.list_chats(page_size=50)
        print(f"✅ bot 在 {len(chats)} 个 chat 里：")
        for c in chats:
            print(f"   - chat_id={c.get('chat_id')}  name={c.get('name')}  type={c.get('chat_type')}")
    except Exception as e:
        print(f"❌ list_chats 失败: {e}")
        return 1

    print()
    print("=" * 60)
    print("Step 2: 拉每个 chat 最近 5 条消息（验证是否能看到你发的「你好」）")
    print("=" * 60)
    for c in chats[:5]:
        chat_id = c.get("chat_id", "")
        if not chat_id:
            continue
        try:
            msgs = api.list_messages(chat_id=chat_id, page_size=5)
            print(f"\n📨 {c.get('name', chat_id)} ({chat_id}) 最近 {len(msgs)} 条：")
            for m in msgs[:5]:
                sender = m.get("sender", {})
                sender_id = sender.get("sender_id", {})
                sender_open = sender_id.get("open_id", "?")[:16]
                msg_type = m.get("msg_type", "?")
                body = m.get("body", {})
                content = body.get("content", "")[:60]
                ts = m.get("create_time", 0)
                print(f"   [{ts}] sender={sender_open}.. type={msg_type} content={content}")
        except Exception as e:
            print(f"❌ list_messages({chat_id}) 失败: {e}")

    api.close()
    print()
    print("=" * 60)
    print("诊断结论")
    print("=" * 60)
    if not chats:
        print("⚠️ bot 没在任何 chat 里 — 用户没法发消息给 bot")
        print("   → 需要用户在飞书后台确认 bot 发布到当前企业 + 启用机器人能力")
    else:
        print(f"✅ bot 在 {len(chats)} 个 chat")
        print("   → 请确认「你好」消息所在 chat 在上表里")
    return 0


if __name__ == "__main__":
    sys.exit(main())
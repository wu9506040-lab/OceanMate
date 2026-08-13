"""发现 + 测试飞书 chat_id，为 Poller 配置做准备（Day 9 路线 A）。

用法：
    cd src/backend
    python -m scripts.test_feishu_poller_setup

功能：
1. 用 token 列出 bot 所在的所有 chat（需要 im:chat:readonly）
2. 让你选一个 chat_id 输出（直接 copy 到 .env）
3. 给用户的 open_id 发一条测试消息（验证 outbound 链路）

输出：
- 列出 chat（含 chat_id / 名称 / 类型）
- 推荐 p2p chat 给 OM AI 单聊
- 发送一条 outbound 测试消息
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

from app.implementations.feishu.api import FeishuOpenAPI, FeishuAPIError  # noqa: E402

# 用户 open_id（从 cc-connect config.toml 已知）
USER_OPEN_ID = os.getenv("USER_OPEN_ID", "ou_4a2da87d3b67eae1c7a0860d85f43776")


def main() -> int:
    api = FeishuOpenAPI(
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
    )

    print("=" * 60)
    print("Step 1: 列出 bot 所在 chat（找 user↔OM AI 的 p2p chat_id）")
    print("=" * 60)
    try:
        chats = api.list_chats(page_size=20)
        if not chats:
            print("⚠️ bot 暂未加入任何 chat（先在飞书客户端跟 OM AI 聊一句再回来）")
        else:
            print(f"✅ 共 {len(chats)} 个 chat：\n")
            for i, c in enumerate(chats):
                chat_id = c.get("chat_id", "?")
                name = c.get("name", "(无名)")
                chat_type = c.get("chat_type", "?")
                external = c.get("external", False)
                tag = "[P2P]" if chat_type == "p2p" else "[GROUP]"
                print(f"  [{i}] {tag} {name}")
                print(f"      chat_id = {chat_id}")
                print(f"      external = {external}\n")
    except FeishuAPIError as e:
        if e.code == 99991672:
            print(f"❌ 缺权限 im:chat:readonly（飞书后台 → OM AI → 权限管理 → 加这个权限）")
            print(f"   错误: {e.msg[:200]}")
        else:
            print(f"❌ API 错误: code={e.code}, msg={e.msg[:200]}")
        chats = []

    print("=" * 60)
    print("Step 2: outbound 测试 — 给你的 open_id 发消息")
    print("=" * 60)
    try:
        result = api.send_message(
            user_id=USER_OPEN_ID,
            text="🤖 [OceanMate Poller 预热] 如果你收到这条 → outbound 链路通。\n接下来 Poller 会监听这个 chat，自动回复你的咨询。",
        )
        msg_id = result.get("message_id", "?")
        print(f"✅ 已发送 → message_id={msg_id}")
        print(f"   接收者: {USER_OPEN_ID}")
    except FeishuAPIError as e:
        print(f"❌ 发消息失败: code={e.code}, msg={e.msg[:200]}")

    print()
    print("=" * 60)
    print("下一步")
    print("=" * 60)
    if chats:
        # 推荐 P2P chat（用户↔OM AI 单聊）
        p2p = [c for c in chats if c.get("chat_type") == "p2p"]
        if p2p:
            target = p2p[0]
            print(f"👉 推荐 chat_id = {target.get('chat_id')}")
            print()
            print("把它加到 .env（项目根或 src/backend/.env）：")
            print(f"   FEISHU_POLL_CHAT_ID={target.get('chat_id')}")
            print()
            print("然后重启服务（PID 17140 那条 nohup 进程）：")
            print("   cmd //c \"taskkill /F /PID 17140\"")
            print("   cd src/backend && nohup python -m uvicorn app.main:app --port 8000 > /tmp/uvicorn.log 2>&1 &")
            print()
            print("重启后：发消息给 OM AI，curl 看 /api/debug/poller_state 验证")
        else:
            print("⚠️ 没找到 P2P chat（用户可能没主动开过 OM AI 单聊窗口）")
            print("   在飞书客户端主动跟 OM AI 聊一句，再回来跑这个脚本")
    else:
        print("⚠️ 没法列 chat（缺权限或 bot 未加入 chat）")
        print("   方案 A: 飞书后台 → OM AI → 权限管理 → 添加 im:chat:readonly")
        print("   方案 B: 在飞书客户端主动跟 OM AI 私聊几句，再回来跑这个脚本")
        print("   方案 C: 自己从飞书客户端 chat URL 复制 chat_id（形如 oc_xxx）")

    api.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
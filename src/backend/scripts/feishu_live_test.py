"""飞书真实端到端实时测试（人在飞书客户端发消息 → 脚本实时检测）。

流程：
1. 后端启动 WS + Poller（前台跑 FastAPI）
2. 用户在飞书客户端找到机器人，发任意消息（如 "ping"）
3. 本脚本每 2 秒轮询 list_chats，发现新 chat 立即通知
4. 列出当前 chat + 历史消息，确认 bot 是否回过

用法：
    cd src/backend
    unset FEISHU_FORCE_MOCK
    python scripts/feishu_live_test.py

    同时另开终端：
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

    然后你在飞书客户端找到机器人发消息。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT.parent / ".env", override=False)

from app.implementations.feishu.api import FeishuOpenAPI, FeishuAPIError


def main():
    print("=" * 70)
    print("飞书真实端到端实时测试 · 等你在飞书客户端发消息")
    print("=" * 70)

    api = FeishuOpenAPI(
        app_id=os.environ["FEISHU_APP_ID"],
        app_secret=os.environ["FEISHU_APP_SECRET"],
    )

    # 1. 基线：当前 chat 数
    initial_chats = api.list_chats(page_size=50)
    initial_ids = {c.get("chat_id") for c in initial_chats}
    print(f"\n[基线] bot 当前在 {len(initial_chats)} 个 chat:")
    for c in initial_chats:
        print(f"  - {c.get('chat_id')} ({c.get('name', '?')})")
    print()

    print("[轮询] 每 2 秒检查一次 list_chats，按 Ctrl+C 停止")
    print("👉 现在请在飞书客户端搜索机器人（按 App ID cli_aaf8...）→ 发任意消息")
    print()

    start = time.time()
    seen = set(initial_ids)
    try:
        while True:
            elapsed = int(time.time() - start)
            try:
                chats = api.list_chats(page_size=50)
            except FeishuAPIError as e:
                print(f"[{elapsed}s] ❌ list_chats 失败: {e}")
                time.sleep(2)
                continue

            new_chats = [c for c in chats if c.get("chat_id") not in seen]
            if new_chats:
                print(f"\n🎉 [{elapsed}s] 检测到 {len(new_chats)} 个新 chat！")
                for c in new_chats:
                    cid = c.get("chat_id")
                    name = c.get("name", "?")
                    ctype = c.get("chat_type", "?")
                    print(f"   ✅ chat_id={cid}  name={name}  type={ctype}")
                    seen.add(cid)

                    # 立即拉这个 chat 的最近消息
                    print(f"   → 拉取最近消息...")
                    try:
                        msgs = api.list_messages(chat_id=cid, page_size=5)
                        for m in msgs:
                            sender = m.get("sender", {}).get("sender_id", {}).get("open_id", "?")
                            mtype = m.get("msg_type", "?")
                            content = m.get("body", {}).get("content", "")
                            print(f"      [{m.get('create_time')}] {sender[:20]} ({mtype}): {content[:80]}")
                    except FeishuAPIError as e:
                        print(f"      ⚠️ list_messages 失败: {e}")

                print()
                print("✅ 端到端链路验证：你已在飞书客户端发消息成功触达 bot")
                print("👉 下一步：在 uvicorn 那个终端看 log，应该看到 '收到消息 from xxx'")
                print("   如果 bot 自动回复了，说明 WS 链路完全通")
                print()
                print("[继续监控] 5 秒后退出（或 Ctrl+C）")
                time.sleep(5)
                break

            # 静默轮询
            if elapsed % 10 == 0 and elapsed > 0:
                print(f"[{elapsed}s] 还在等（chat 数={len(chats)}）...")

            time.sleep(2)
    except KeyboardInterrupt:
        print(f"\n[退出] 共监控 {int(time.time() - start)} 秒")


if __name__ == "__main__":
    main()

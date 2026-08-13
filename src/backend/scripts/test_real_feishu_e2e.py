"""真实飞书接入端到端测试（通道层 · 不依赖 WS 收到事件）。

测试 4 项通道：
1. list_chats       — 验证 bot 当前在哪些 chat
2. upload_image     — 验证 im:resource 权限
3. sync_dashboard   — 验证多维表格写入
4. send_message     — 验证消息发送（需要 user open_id）

用法：
    cd src/backend
    python scripts/test_real_feishu_e2e.py                       # 跑测试 1+2+3
    python scripts/test_real_feishu_e2e.py --open-id ou_xxx      # 加测试 4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

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


# === 测试用 fixture：1x1 PNG（最小有效图片） ===

_1X1_PNG_PATH = BACKEND_ROOT / "data" / "test_1x1.png"


def _ensure_test_image() -> Path:
    """生成 1x1 PNG 文件用于 upload_image 测试。"""
    import base64
    _1X1_PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _1X1_PNG_PATH.exists():
        # 最小有效 1x1 红色 PNG（base64 解码）
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        _1X1_PNG_PATH.write_bytes(png_bytes)
    return _1X1_PNG_PATH


# === 4 项通道测试 ===

def test_list_chats(api) -> dict:
    """测试 1：bot 当前所在 chat 列表。"""
    try:
        chats = api.list_chats(page_size=50)
        return {
            "ok": True,
            "chat_count": len(chats),
            "chats": [
                {"chat_id": c.get("chat_id"), "name": c.get("name"), "type": c.get("chat_type")}
                for c in chats[:5]
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_upload_image(api, image_path: Path) -> dict:
    """测试 2：上传图片到飞书（验证 im:resource 权限）。"""
    try:
        image_key = api.upload_image(str(image_path))
        if not image_key:
            return {"ok": False, "error": "upload returned empty image_key"}
        return {"ok": True, "image_key": image_key[:16] + "..."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_sync_dashboard(api, app_token: str, table_id: str) -> dict:
    """测试 3：写入 demo 状态到多维表格（验证 bitable 写入权限）。"""
    try:
        fields = {
            "problem_type": "通道测试",
            "priority": "low",
            "tier": "standard",
            "assignee": "通用支持团队",
            "sla_hours": 24,
            "notification_channel": "飞书通用群",
            "rule_id": "rule_demo_e2e_test",
        }
        result = api.sync_dashboard_data(app_token=app_token, table_id=table_id, fields=fields)
        return {"ok": True, "record_id": (result.get("record") or {}).get("record_id", "?")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_send_message(api, user_id: str) -> dict:
    """测试 4：发文本消息（验证 im:message 权限 + send_message 通道）。"""
    try:
        result = api.send_message(
            user_id=user_id,
            text="🤖 来自 OceanMate AI 的测试消息（test_real_feishu_e2e）",
        )
        return {"ok": True, "message_id": result.get("message_id", "?")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === 主流程 ===

def main() -> int:
    parser = argparse.ArgumentParser(description="真实飞书端到端测试")
    parser.add_argument(
        "--open-id",
        default=None,
        help="测试 send_message 的目标 open_id（从 WS 日志拿到）",
    )
    args = parser.parse_args()

    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    app_token = os.getenv("FEISHU_BITABLE_APP_TOKEN") or os.getenv("FEISHU_BTABLE_APP_TOKEN", "")
    routing_table_id = os.getenv("FEISHU_BTABLE_ROUTING_RULES_TABLE_ID", "")

    if not app_id or not app_secret:
        print("❌ FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
        return 1
    if not app_token:
        print("❌ FEISHU_BITABLE_APP_TOKEN 未配置")
        return 1

    from app.implementations.feishu.api import FeishuOpenAPI
    api = FeishuOpenAPI(app_id=app_id, app_secret=app_secret)

    print("=" * 60)
    print(f"真实飞书端到端测试（app_id={app_id[:8]}...）")
    print("=" * 60)

    # Test 1: list_chats
    print("\n[Test 1] list_chats — bot 当前所在 chat")
    r1 = test_list_chats(api)
    print(f"   结果: {json.dumps(r1, ensure_ascii=False, indent=2)}")
    if r1["ok"]:
        print(f"   ✅ 通道正常（{r1['chat_count']} 个 chat）")
        if r1["chat_count"] == 0:
            print("   ⚠️  0 个 chat — 用户还没点进去发消息")
    else:
        print(f"   ❌ 失败: {r1['error']}")

    # Test 2: upload_image
    print("\n[Test 2] upload_image — 上传 1x1 PNG")
    img_path = _ensure_test_image()
    r2 = test_upload_image(api, img_path)
    print(f"   结果: {json.dumps(r2, ensure_ascii=False, indent=2)}")
    if r2["ok"]:
        print(f"   ✅ 通道正常（image_key={r2['image_key']}）")
    else:
        print(f"   ❌ 失败: {r2['error']}")

    # Test 3: sync_dashboard
    if routing_table_id:
        print("\n[Test 3] sync_dashboard — 写 demo 状态到多维表格")
        r3 = test_sync_dashboard(api, app_token, routing_table_id)
        print(f"   结果: {json.dumps(r3, ensure_ascii=False, indent=2)}")
        if r3["ok"]:
            print(f"   ✅ 通道正常（record_id={r3['record_id']}）")
        else:
            print(f"   ❌ 失败: {r3['error']}")
    else:
        print("\n[Test 3] sync_dashboard — 跳过（缺 FEISHU_BTABLE_ROUTING_RULES_TABLE_ID）")

    # Test 4: send_message（需要 open_id）
    print("\n[Test 4] send_message — 发文本消息")
    if args.open_id:
        r4 = test_send_message(api, args.open_id)
        print(f"   结果: {json.dumps(r4, ensure_ascii=False, indent=2)}")
        if r4["ok"]:
            print(f"   ✅ 通道正常（message_id={r4['message_id']}）")
        else:
            print(f"   ❌ 失败: {r4['error']}")
    else:
        print("   跳过（缺 --open-id · 等 WS 拿到 open_id 再跑）")

    api.close()

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    results = [r1, r2]
    if routing_table_id:
        results.append(r3)
    if args.open_id:
        results.append(r4)
    passed = sum(1 for r in results if r.get("ok"))
    print(f"通过 {passed}/{len(results)} 项")
    if passed == len(results):
        print("✅ 所有通道正常")
        return 0
    print("⚠️  存在失败通道 — 见上方详情")
    return 1


if __name__ == "__main__":
    sys.exit(main())
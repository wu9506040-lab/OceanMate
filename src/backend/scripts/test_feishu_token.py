"""测试飞书 tenant_access_token 能否成功获取（真实接入前必跑）。

用法：
    cd src/backend
    python -m scripts.test_feishu_token

期望输出：
    ✅ token 获取成功
    token: t-xxx（前 8 位）...
    有效期: 7190 秒（约 120 分钟）

失败排查：
    ❌ 凭证缺失 → 检查 .env 是否在 src/backend/.env 或项目根目录 .env
    ❌ 99991663 / 99991664 → App ID 或 App Secret 错
    ❌ 网络超时 → 检查能否访问 open.feishu.cn
    ❌ 99991672 → 应用未启用机器人能力
"""

from __future__ import annotations

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

# 尝试加载 .env（优先项目根目录 → 再 src/backend/.env）
try:
    from dotenv import load_dotenv

    root_env = BACKEND_ROOT.parent.parent / ".env"  # 项目根目录
    local_env = BACKEND_ROOT / ".env"  # src/backend/.env
    if root_env.exists():
        load_dotenv(root_env)
        print(f"[OK] 加载项目根 .env: {root_env}")
    elif local_env.exists():
        load_dotenv(local_env)
        print(f"[OK] 加载本地 .env: {local_env}")
    else:
        print("[WARN] 未找到 .env 文件，将依赖系统环境变量")
except ImportError:
    print("[WARN] python-dotenv 未安装，跳过 .env 加载")


def main() -> int:
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")

    if not app_id or app_id.startswith("<PLACEHOLDER"):
        print("❌ FEISHU_APP_ID 未配置或为占位符")
        print("   请先 cp .env.example .env 并填入真实值")
        return 1
    if not app_secret or app_secret.startswith("<PLACEHOLDER"):
        print("❌ FEISHU_APP_SECRET 未配置或为占位符")
        return 1

    print(f"App ID: {app_id[:8]}...")
    print(f"App Secret: {app_secret[:4]}***")
    print(f"目标: https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal")
    print()

    try:
        import httpx
    except ImportError:
        print("❌ httpx 未安装（pip install httpx）")
        return 1

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    body = {"app_id": app_id, "app_secret": app_secret}

    try:
        resp = httpx.post(url, json=body, timeout=10.0)
    except httpx.ConnectError as e:
        print(f"❌ 网络连接失败: {e}")
        print("   排查：能否 ping 通 open.feishu.cn")
        return 1
    except httpx.TimeoutException:
        print("❌ 请求超时（>10s）")
        return 1

    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code}: {resp.text[:200]}")
        return 1

    data = resp.json()
    if data.get("code", -1) != 0:
        code = data.get("code", -1)
        msg = data.get("msg", "未知错误")
        print(f"❌ 飞书返回错误: code={code}, msg={msg}")
        print()
        print("常见错误码：")
        print("  99991663 → App Secret 错误")
        print("  99991664 → App ID 不存在")
        print("  99991672 → 应用未启用机器人能力")
        print("  99991668 → 应用未上架/未发布")
        return 1

    token = data.get("tenant_access_token", "")
    expire = data.get("expire", 0)
    print("✅ token 获取成功")
    print(f"   token: {token[:16]}...")
    print(f"   有效期: {expire} 秒（约 {expire // 60} 分钟）")
    print()
    print()
    print("下一步（Day 9 长连接模式，无需 ngrok）：")
    print("  1. 启动 FastAPI（后台线程会启长连接）")
    print("     python -m uvicorn app.main:app --port 8000")
    print("  2. 飞书后台 → 应用 → 事件与回调 → 事件配置")
    print("     订阅方式选「使用长连接接收事件」（需服务在线才能保存）")
    print("     添加事件：im.message.receive_v1")
    print("  3. 飞书客户端发消息测试")
    return 0


if __name__ == "__main__":
    sys.exit(main())
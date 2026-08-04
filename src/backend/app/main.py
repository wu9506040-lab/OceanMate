"""OceanMate AI Backend - FastAPI v2 入口（4 Tool + 飞书 webhook 集成）。

Path:
- 飞书智能伙伴事件入口：POST /feishu/webhook
- URL 验证：POST /feishu/url_verification
- 调试 chat：POST /api/chat
- 健康检查：GET /api/health
- Mock 日志：GET /api/feishu_mock_log
- Tool 列表：GET /api/tools

设计（Day 6-7）：
- 工厂函数 create_default_orchestrator() 装配 4 Tool
- 工厂函数 get_feishu_frontend() 自动选 Mock / 真实
- 4 Tool 通过 Orchestrator 路由，零业务改动
- 缺凭证时 Mock 兜底，Demo 不卡死

注意：
- /feishu/webhook 走完整链路（Orchestrator → 回复 → MockFrontend.send_message → 写日志）
- /api/chat 仅调 Orchestrator 返回结果，**不推消息**（调试用，区别于 webhook）
- 真实环境切 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量即可启用真 FeishuFrontend
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Windows 中文/emoji 输出兼容（CLAUDE.md 已知约束）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agents.orchestrator import create_default_orchestrator
from app.implementations.feishu import get_feishu_frontend, FeishuWebhookHandler


# === 全局单例（PoC 简化）===

_orchestrator = None
_frontend = None
_webhook_handler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：启动时建单例，关闭时释放。"""
    global _orchestrator, _frontend, _webhook_handler

    db_path = os.getenv("OCEANMATE_DB", "data/oceanmate.db")
    chroma_path = os.getenv("OCEANMATE_CHROMA", "data/chroma")

    _orchestrator = create_default_orchestrator(
        db_path=db_path,
        chroma_path=chroma_path,
        auto_init_db=True,
    )
    _frontend = get_feishu_frontend()
    _webhook_handler = FeishuWebhookHandler(
        orchestrator=_orchestrator,
        frontend=_frontend,
        verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
        enable_signature_check=False,  # PoC 简化
    )
    print(f"[OK] OceanMate AI 启动完成")
    tool_names = [t['name'] for t in _orchestrator.list_tools()]
    print(f"  - 4 Tool: {', '.join(tool_names)}")
    print(f"  - Frontend: {type(_frontend).__name__}")

    yield

    # 关闭
    if hasattr(_frontend, "close"):
        _frontend.close()
    print("[BYE] OceanMate AI shutdown")


app = FastAPI(
    title="OceanMate AI",
    version="2.2",
    description="跨境支付商户成功 AI 助手（4 Tool + 飞书 webhook 集成）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Pydantic Schemas ===

class ChatRequest(BaseModel):
    query: str
    user_id: Optional[str] = "demo_user"
    merchant_context: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    tools: list[str]
    frontend: str
    db_path: str


# === 路由 ===

@app.get("/")
def root():
    return {
        "project": "OceanMate AI",
        "version": "2.2",
        "endpoints": [
            "/api/health",
            "/api/chat",
            "/api/tools",
            "/api/feishu_mock_log",
            "/feishu/webhook",
        ],
    }


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        tools=[t["name"] for t in _orchestrator.list_tools()],
        frontend=type(_frontend).__name__,
        db_path=os.getenv("OCEANMATE_DB", "data/oceanmate.db"),
    )


@app.post("/api/chat")
def chat(req: ChatRequest):
    """调试接口：模拟商户提问（curl 即可演示）。"""
    ctx = req.merchant_context or {}
    ctx["user_id"] = req.user_id
    result = _orchestrator.route(user_query=req.query, merchant_context=ctx)
    return result


@app.get("/api/tools")
def list_tools():
    """列出所有 Tool 的 MCP tool_spec（评审展示）。"""
    return _orchestrator.list_tools()


@app.get("/api/feishu_mock_log")
def feishu_mock_log():
    """查看 Mock 事件日志（仅 MockFrontend 有日志）。"""
    from app.implementations.feishu.mock_frontend import MockFrontend
    if isinstance(_frontend, MockFrontend):
        return {"events": _frontend.read_log()}
    return {"events": [], "note": "当前 Frontend 非 Mock，日志仅 MockFrontend 支持"}


@app.post("/feishu/webhook")
def feishu_webhook(payload: dict):
    """飞书智能伙伴事件回调入口（兼容 URL 验证 + 业务事件）。"""
    return _webhook_handler.handle_event(payload)


@app.post("/feishu/url_verification")
def feishu_url_verification(payload: dict):
    """飞书 URL 验证（独立端点，便于配 WEBHOOK_URL 时单测）。"""
    return _webhook_handler._handle_url_verification(payload)


# === 启动入口（uvicorn）===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

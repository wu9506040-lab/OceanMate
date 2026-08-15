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

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# 自动加载 .env（项目根优先，回退到 src/backend/.env）
# 无 python-dotenv 时优雅降级（依赖环境变量）
# Path(__file__) = src/backend/app/main.py，parents[3] = 项目根 (ai-pioneer)
try:
    from dotenv import load_dotenv
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    _root_env = _PROJECT_ROOT / ".env"
    _local_env = Path(__file__).resolve().parent.parent / ".env"  # src/backend/.env
    if _root_env.exists():
        load_dotenv(_root_env)
        print(f"[OK] 加载 .env: {_root_env}")
    elif _local_env.exists():
        load_dotenv(_local_env)
        print(f"[OK] 加载 .env: {_local_env}")
    else:
        print(f"[WARN] 未找到 .env（项目根: {_root_env}, 本地: {_local_env}）")
except ImportError:
    pass  # 没装 python-dotenv 时依赖系统 env

# Windows 中文/emoji 输出兼容（CLAUDE.md 已知约束）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agents.orchestrator import create_default_orchestrator
from app.implementations.feishu import (
    get_feishu_frontend,
    FeishuWebhookHandler,
    start_feishu_ws_in_background,
    should_start_ws_client,
    get_ws_debug_state,
    start_feishu_poller_in_background,
    should_start_poller,
    get_poller_debug_state,
    get_briefings_debug_state,
    get_human_mode_debug_state,
)
from app.implementations.feishu.api import FeishuOpenAPI
from app.implementations.demo_scenarios import DEMO_SCENARIOS


# === 全局单例（PoC 简化）===

_orchestrator = None
_frontend = None
_webhook_handler = None
_ws_thread = None  # Day 9 长连接后台线程
_poller_thread = None  # Day 9 轮询 fallback 后台线程
_feishu_api = None  # Day 9 直接 API 调用（poller 用）


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：启动时建单例 + 启 WS / Poller 后台线程，关闭时释放。"""
    global _orchestrator, _frontend, _webhook_handler, _ws_thread, _poller_thread, _feishu_api

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
        # Day 15 P0-4：签名校验（默认关闭，env 设为 1 才开启；生产模式必开）
        enable_signature_check=os.getenv("FEISHU_ENABLE_SIGNATURE_CHECK", "0") == "1",
        encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY"),
    )

    # 直接 API 客户端（poller 用 list_messages）
    if not os.getenv("FEISHU_FORCE_MOCK") == "1":
        _feishu_api = FeishuOpenAPI(
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        )

    print(f"[OK] OceanMate AI 启动完成")
    tool_names = [t['name'] for t in _orchestrator.list_tools()]
    print(f"  - 4 Tool: {', '.join(tool_names)}")
    print(f"  - Frontend: {type(_frontend).__name__}")

    # === Day 9 长连接（WebSocket）后台线程 ===
    # 有凭证 + 非 Mock → 启 WS（生产主路径）
    if should_start_ws_client():
        _ws_thread = start_feishu_ws_in_background(
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            orchestrator=_orchestrator,
            frontend=_frontend,
        )
        if _ws_thread:
            print(f"  - 长连接: 已启动（thread={_ws_thread.name}）")
        else:
            print(f"  - 长连接: 启动失败（lark-oapi 未装？）")
    else:
        print(f"  - 长连接: 未启用（缺凭证或 FEISHU_FORCE_MOCK=1）")

    # === Day 9 Poller fallback（WS 收不到事件时用）===
    poll_chat_id = os.getenv("FEISHU_POLL_CHAT_ID", "")
    if poll_chat_id and _feishu_api and not os.getenv("FEISHU_FORCE_MOCK") == "1":
        _poller_thread = start_feishu_poller_in_background(
            api=_feishu_api,
            chat_id=poll_chat_id,
            orchestrator=_orchestrator,
            frontend=_frontend,
            poll_interval_sec=float(os.getenv("FEISHU_POLL_INTERVAL", "2.0")),
        )
        if _poller_thread:
            print(f"  - Poller: 已启动（chat_id={poll_chat_id}, interval={_poller_thread.name}）")
    else:
        print(f"  - Poller: 未启用（缺 FEISHU_POLL_CHAT_ID 或 FEISHU_FORCE_MOCK=1）")

    yield

    # 关闭
    if _feishu_api:
        _feishu_api.close()
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


# === 全局异常处理（Day 14 P1 修复：防止 500 泄漏 stack trace） ===

import logging
import traceback
from fastapi.responses import JSONResponse

# Day 18 P1 修复：显式设置 root logger level，否则 uvicorn 默认 WARNING
# 会把 ws_client.py / webhook.py 里的 logger.info / logger.debug 全过滤掉，
# 业务处理成功但日志看不到，调试 root cause 极其困难。
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底所有未捕获异常，返回结构化 500 而非 HTML 错误页。

    安全考虑：线上环境不应把 traceback 暴露给客户端。生产部署时把 include_trace=False。
    评审 Demo 默认 include_trace=True，方便快速排查。
    """
    tb = traceback.format_exc()
    logger.error(f"[UnhandledException] {request.method} {request.url.path}: {exc}\n{tb}")
    include_trace = os.getenv("DEBUG", "1") == "1"  # 默认暴露便于评审；生产置 0
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": f"服务器内部错误: {type(exc).__name__}",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],  # 截断防止日志泄漏
            "trace": tb if include_trace else None,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """参数校验异常 → 400 而非 500。"""
    return JSONResponse(
        status_code=400,
        content={
            "code": 400,
            "message": str(exc),
            "error_type": "ValueError",
            "path": str(request.url.path),
        },
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


@app.get("/api/debug/ws_state")
def debug_ws_state():
    """WS 长连接调试态：线程存活 + 事件计数 + 最近 20 条流水。

    用法：
    - 飞书客户端发消息后立即 curl 此端点
    - 看 events_received 是否递增 → 知道 WS 有没有收到事件
    - 看 recent_events 看具体消息内容
    """
    return get_ws_debug_state()


@app.get("/api/debug/poller_state")
def debug_poller_state():
    """Poller 轮询调试态：轮询次数 + 已处理消息 + 最近 20 条流水。"""
    return get_poller_debug_state()


@app.get("/api/debug/briefings")
def debug_briefings():
    """简报历史（单账号演示：send_private 拦截后存的简报）。

    单账号演示下 lead_open_id == merchant_user_id，send_private 会污染商户 DM，
    所以改为存到 _briefing_history。演示者从此端点看完整简报（含跳转链接）。
    """
    return get_briefings_debug_state()


@app.get("/api/debug/human_mode")
def debug_human_mode():
    """当前在人工模式的用户列表（演示用：实时看 lead 是否在「人工接管」状态）。"""
    return get_human_mode_debug_state()


# === Day 10 黄金用例（评审 / 录屏用）===

@app.get("/api/demo/scenarios")
def list_demo_scenarios():
    """列出所有 Demo 黄金用例（不执行，只看元数据）。"""
    return {
        "count": len(DEMO_SCENARIOS),
        "scenarios": [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "tool": s["tool"],
                "demo_query": s["demo_query"],
            }
            for s in DEMO_SCENARIOS
        ],
    }


def _check_expected(result: dict, expected: dict) -> tuple[bool, list[str]]:
    """校验 Tool 返回是否符合预期。返回 (passed, missing_list)。"""
    missing = []
    if "problem_type" in expected:
        if result.get("problem_type") != expected["problem_type"]:
            missing.append(f"problem_type={result.get('problem_type')}, expected {expected['problem_type']}")
    if expected.get("has_root_causes") and not result.get("root_causes"):
        missing.append("root_causes empty")
    if expected.get("has_evidence_chain") and not result.get("evidence_chain"):
        missing.append("evidence_chain empty")
    if expected.get("has_recommended_actions") and not result.get("recommended_actions"):
        missing.append("recommended_actions empty")
    if expected.get("has_image") and not result.get("error_image_path"):
        missing.append("error_image_path missing")
    if "response_contains" in expected:
        if expected["response_contains"] not in (result.get("response") or ""):
            missing.append(f"response missing '{expected['response_contains']}'")
    if "recommendations_min" in expected:
        if len(result.get("recommendations", [])) < expected["recommendations_min"]:
            missing.append(f"recommendations count < {expected['recommendations_min']}")
    if "sla_hours_max" in expected:
        sla = result.get("sla_hours", 999)
        if sla > expected["sla_hours_max"]:
            missing.append(f"sla_hours={sla} > {expected['sla_hours_max']}")
    if "notification_channel_contains" in expected:
        nc = result.get("notification_channel", "")
        if expected["notification_channel_contains"] not in nc:
            missing.append(f"notification_channel '{nc}' missing '{expected['notification_channel_contains']}'")
    if "match_level" in expected:
        if result.get("match_level") != expected["match_level"]:
            missing.append(f"match_level={result.get('match_level')}, expected {expected['match_level']}")
    if "assignee_contains" in expected:
        if expected["assignee_contains"] not in (result.get("assignee") or ""):
            missing.append(f"assignee missing '{expected['assignee_contains']}'")
    if "faqs_min" in expected:
        if len(result.get("faqs", [])) < expected["faqs_min"]:
            missing.append(f"faqs count < {expected['faqs_min']}")
    return (len(missing) == 0, missing)


def _run_scenario(s: dict) -> dict:
    """执行单个 Demo 场景（直调 Tool，不走 Orchestrator 路由）。"""
    if s["tool"] == "payment_diagnosis":
        result = _orchestrator.registry.safe_execute("payment_diagnosis", s["params"])
    elif s["tool"] == "merchant_success":
        result = _orchestrator.registry.safe_execute("merchant_success", s["params"])
    elif s["tool"] == "ticket_routing":
        result = _orchestrator.registry.safe_execute("ticket_routing", s["params"])
    elif s["tool"] == "knowledge_evolution":
        result = _orchestrator.registry.safe_execute("knowledge_evolution", s["params"])
    else:
        return {"id": s["id"], "status": "error", "error": f"Unknown tool: {s['tool']}"}

    if not result.get("success"):
        return {
            "id": s["id"],
            "name": s["name"],
            "status": "failed",
            "error_code": result.get("error_code"),
            "error_message": result.get("error_message"),
        }

    data = result.get("data", {})
    passed, missing = _check_expected(data, s["expected"])
    return {
        "id": s["id"],
        "name": s["name"],
        "tool": s["tool"],
        "status": "passed" if passed else "partial",
        "expected_check": {"passed": passed, "missing": missing},
        "demo_query": s["demo_query"],
        "result_summary": {
            "problem_type": data.get("problem_type"),
            "confidence": data.get("confidence"),
            "error_image_path": data.get("error_image_path") or None,
            "sla_hours": data.get("sla_hours"),
            "assignee": data.get("assignee"),
            "response_excerpt": (data.get("response") or "")[:120],
            "recommendations_count": len(data.get("recommendations", [])),
            "faqs_count": len(data.get("faqs", [])),
        },
        "full_result": data,
    }


@app.get("/api/demo/run/{scenario_id}")
def run_demo_scenario(scenario_id: str):
    """执行单个 Demo 黄金用例。

    用法：
        curl http://localhost:8000/api/demo/run/demo_01_visa_chargeback
    """
    for s in DEMO_SCENARIOS:
        if s["id"] == scenario_id:
            return _run_scenario(s)
    raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


@app.get("/api/demo/run_all")
def run_all_demo_scenarios():
    """一键跑完全部 6 个 Demo 黄金用例（录屏前必跑）。

    Returns:
        {"total": 6, "passed": N, "partial": M, "failed": K, "scenarios": [...]}
    """
    results = [_run_scenario(s) for s in DEMO_SCENARIOS]
    counts = {"passed": 0, "partial": 0, "failed": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "total": len(results),
        **counts,
        "scenarios": results,
    }


@app.post("/feishu/webhook")
async def feishu_webhook(request: Request):
    """飞书智能伙伴事件回调入口（兼容 URL 验证 + 业务事件 + 签名校验）。

    真实接入时，飞书会带 3 个 header：
    - X-Lark-Request-Timestamp
    - X-Lark-Request-Nonce
    - X-Lark-Signature

    签名校验需原始 body 字节（HMAC 必须与飞书侧计算的完全一致），
    因此走 Request.body() 取 raw bytes，再解析 JSON。
    """
    raw_body = await request.body()
    # Day 10: 编码容错（Windows curl 中文 GBK 字节流兼容）— 优先 UTF-8，失败 fallback GBK
    body_str = ""
    if raw_body:
        for enc in ("utf-8", "gbk", "utf-16"):
            try:
                body_str = raw_body.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not body_str:
            body_str = raw_body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(body_str) if body_str else {}
    except json.JSONDecodeError:
        logger = __import__("logging").getLogger(__name__)
        logger.warning(f"Feishu webhook 收到非 JSON body: {body_str[:100]}")
        payload = {}

    return _webhook_handler.handle_event(
        payload,
        body_str=body_str,
        timestamp=request.headers.get("X-Lark-Request-Timestamp", ""),
        nonce=request.headers.get("X-Lark-Request-Nonce", ""),
        signature=request.headers.get("X-Lark-Signature", ""),
    )


@app.post("/feishu/url_verification")
def feishu_url_verification(payload: dict):
    """飞书 URL 验证（独立端点，便于配 WEBHOOK_URL 时单测）。"""
    return _webhook_handler._handle_url_verification(payload)


# === 启动入口（uvicorn）===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

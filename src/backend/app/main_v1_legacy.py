"""OceanMate AI Backend - v1 LEGACY（已弃用 · 禁止 import）。

历史：
- 2026-07-17 老版 PoC 入口（仅 PDA Tool）
- 2026-08-04 重写为 v2 入口（4 Tool + 飞书 webhook），原 main.py 改名为本文件
- 保留目的：参考历史实现；禁止新代码 import

新版入口：app/main.py（v2）
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.payment_diagnosis.schemas import DiagnoseRequest, DiagnoseResponse
from app.agents.payment_diagnosis.service import PaymentDiagnosisService

app = FastAPI(
    title="OceanMate AI",
    version="0.1.0-demo",
    description="跨境支付商户成功运营助手 · PoC (Payment Diagnosis Agent)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局单例（PoC 简化）
_service = PaymentDiagnosisService()


@app.get("/")
def root():
    return {
        "project": "OceanMate AI",
        "stage": "PoC Demo",
        "agents": ["MSA", "PDA", "TRA", "KEA"],
        "endpoints": ["/api/diagnose"],
    }


@app.post("/api/diagnose", response_model=DiagnoseResponse)
def diagnose(req: DiagnoseRequest):
    """Payment Diagnosis Agent 主入口。

    对应 docs/agents/payment_diagnosis_agent.md §3 输入 §5 输出。
    """
    return _service.diagnose(req)
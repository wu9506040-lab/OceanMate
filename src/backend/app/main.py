"""OceanMate AI Backend - FastAPI 入口 (PoC)."""

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
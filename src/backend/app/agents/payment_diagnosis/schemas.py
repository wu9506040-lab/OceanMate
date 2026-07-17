"""Pydantic schemas for Payment Diagnosis Agent.

对应 docs/agents/payment_diagnosis_agent.md §3 (输入) 和 §5 (输出)。
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ===== 输入 =====

class ProblemRecord(BaseModel):
    """商户问题档案（来自 Merchant Success Agent 或飞书智能伙伴）。"""

    merchant_id: str = Field(..., description="商户 ID（Demo 占位：<DEMO_MERCHANT_ID>）")
    country: str = Field(..., description="ISO 国家码，如 BR/US/CN")
    channel: str = Field(..., description="支付渠道，如 Visa/Mastercard/PayPal")
    error_code: str = Field(..., description="错误码（Demo 占位：<DEMO_ERROR_CODE>）")
    affected_orders: List[str] = Field(default_factory=list, description="受影响的订单号列表")


class DiagnoseRequest(BaseModel):
    """POST /api/diagnose 请求体。"""

    problem_record: ProblemRecord


# ===== 输出 =====

class EvidenceItem(BaseModel):
    """证据链单条。"""

    type: Literal["risk_rule", "channel_status", "config_snapshot"]
    id: str = Field(..., description="证据 ID（Demo 阶段以 <xxx_demo_xxx> 占位符呈现）")
    source: str = Field(..., description="证据来源系统（Demo 后缀 _demo）")
    description: Optional[str] = Field(None, description="证据说明")


class Diagnosis(BaseModel):
    """诊断输出（含证据链 - 核心创新点）。"""

    problem_type: str = Field(..., description="问题类型：支付失败/拒付/退款异常/Webhook 回调失败")
    root_causes: List[str] = Field(..., description="根因列表（人话描述）")
    evidence_chain: List[EvidenceItem] = Field(..., description="证据链（每条可追溯到具体规则/日志/快照）")
    recommended_actions: List[str] = Field(..., description="建议处理步骤")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")
    next_agent: str = Field(default="Ticket Routing Agent", description="下一跳 Agent")


class DiagnoseResponse(BaseModel):
    """POST /api/diagnose 响应体。"""

    diagnosis: Diagnosis
    trace: dict = Field(default_factory=dict, description="执行轨迹（便于演示）")
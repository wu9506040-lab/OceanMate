"""Pydantic v2 数据模型 — 7 个核心实体。

设计要点：
- Pydantic v2 风格（model_validate, model_dump, field_validator）
- 所有时间字段用 datetime（SQLite 存 ISO 字符串）
- 可选字段用 Optional[...] = None
- 主键都用 str（UUID 或外部 ID，不自增）

实体：
- Merchant        商户
- ErrorCode       错误码知识库
- Case            诊断案例
- Ticket          工单
- Conversation    对话会话
- Message         对话消息
- Handoff         人工交接记录
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# === 1. Merchant ===

class Merchant(BaseModel):
    """商户表 - 跨境支付商户档案。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="商户 ID（Demo: <DEMO_MERCHANT_ID>）")
    country: str = Field(..., description="ISO 国家码，如 BR/US/CN")
    industry: Optional[str] = Field(None, description="行业：fashion/electronics/digital...")
    avg_amount: Optional[float] = Field(None, description="客单价（USD）")
    tier: str = Field(default="standard", description="等级：standard/premium/vip")
    feishu_record_id: Optional[str] = Field(None, description="飞书多维表格记录 ID")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# === 2. ErrorCode ===

class ErrorCode(BaseModel):
    """错误码知识库 - 飞书同步源，本地缓存。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="错误码记录 ID")
    code: str = Field(..., description="错误码，如 ERR_DEMO_RISK_BLOCK_BR_VISA_001")
    country: Optional[str] = Field(None, description="适用国家")
    channel: Optional[str] = Field(None, description="适用渠道")
    root_cause: Optional[str] = Field(None, description="根因描述")
    solution: Optional[str] = Field(None, description="解决方案")
    feishu_record_id: Optional[str] = Field(None, description="飞书源 ID")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# === 3. Case ===

class Case(BaseModel):
    """诊断案例 - 飞书同步源，本地缓存。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="案例 ID")
    problem_desc: str = Field(..., description="问题描述")
    diagnosis: Optional[str] = Field(None, description="诊断结果")
    resolution: Optional[str] = Field(None, description="解决方案")
    country: Optional[str] = None
    channel: Optional[str] = None
    error_code: Optional[str] = None
    problem_type: Optional[str] = Field(None, description="问题类型：支付失败/拒付/退款异常")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    merchant_id: Optional[str] = None
    feishu_record_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# === 4. Ticket ===

class Ticket(BaseModel):
    """工单 - 飞书同步源，本地缓存。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="工单 ID")
    problem_type: str = Field(..., description="问题类型")
    priority: str = Field(default="medium", description="优先级：high/medium/low")
    status: str = Field(default="pending", description="状态：pending/processing/resolved/closed")
    merchant_id: Optional[str] = None
    assignee: Optional[str] = Field(None, description="处理人/团队")
    source: Optional[str] = Field(None, description="工单来源：merchant_diagnosis/...")
    diagnosis_id: Optional[str] = Field(None, description="关联的诊断 ID")
    feishu_record_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[str] = None
    resolved_at: Optional[datetime] = None


# === 5. Conversation ===

class Conversation(BaseModel):
    """对话会话 - 本地存储。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="会话 ID（UUID）")
    user_id: str = Field(..., description="用户 ID（飞书 open_id）")
    started_at: Optional[datetime] = None
    last_msg_at: Optional[datetime] = None
    status: str = Field(default="active", description="active/closed/timeout")
    merchant_id: Optional[str] = None
    tool_name: Optional[str] = Field(None, description="当前激活的 Tool")


# === 6. Message ===

class Message(BaseModel):
    """对话消息 - 本地存储。"""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = Field(None, description="自增主键")
    conversation_id: str = Field(..., description="所属会话 ID")
    role: str = Field(..., description="user/assistant/system/tool")
    content: str = Field(..., description="消息内容")
    tool_calls: Optional[str] = Field(None, description="Tool 调用 JSON 字符串")
    created_at: Optional[datetime] = None


# === 7. Handoff ===

class Handoff(BaseModel):
    """人工交接记录 - 本地存储。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="交接 ID")
    conversation_id: str = Field(..., description="所属会话 ID")
    agent_id: Optional[str] = Field(None, description="人工客服 ID")
    reason: Optional[str] = Field(None, description="交接原因")
    briefing: Optional[str] = Field(None, description="AI 给人工的交接简报")
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


# === 统一导出 ===

__all__ = [
    "Merchant", "ErrorCode", "Case", "Ticket",
    "Conversation", "Message", "Handoff",
]
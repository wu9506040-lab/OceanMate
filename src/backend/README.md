# OceanMate AI · Backend (PoC)

> **阶段**：报名阶段 PoC（仅实现 Payment Diagnosis Agent 主路径）
>
> **目的**：消除"代码仓库全空目录"的质疑，向 OP 命题企业展示方案可落地。

---

## 文件结构

```
src/backend/
├── README.md                     # 本文件
├── requirements.txt              # 依赖
├── run_demo.py                   # 终端 Demo（推荐先用这个录屏）
└── app/
    ├── main.py                   # FastAPI 入口
    └── agents/
        └── payment_diagnosis/    # Payment Diagnosis Agent (Demo 核心)
            ├── schemas.py        # Pydantic 输入/输出
            ├── evidence_store.py # 3 证据源 mock (替换为 OP API 即可对接)
            ├── llm_provider.py   # Qwen + Mock（无 key 自动降级）
            └── service.py        # 核心诊断逻辑
```

## 快速开始（无需任何 API Key）

```bash
cd src/backend
pip install -r requirements.txt
python run_demo.py
```

预期输出（终端彩色 JSON + 证据链）：

```
================================================================
  OceanMate AI · Payment Diagnosis Agent (LLM = MockLLMProvider)
================================================================

📋 问题档案
────────────────────────────────────────────────────────────────
  商户 ID    : <DEMO_MERCHANT_ID>
  国家/渠道  : BR / Visa
  错误码     : ERR_DEMO_RISK_BLOCK_BR_VISA_001

🔍 诊断结果 (置信度 85%)
────────────────────────────────────────────────────────────────
  问题类型   : 支付失败

  根因分析:
    1. BR Visa 渠道 3DS 认证配置问题...
    2. ...

  证据链 (共 3 条 · 可追溯):
    ● risk_rule          <risk_rule_demo_001>          ← payment_error_database_demo
    ● channel_status     <channel_status_demo_001>     ← channel_logs_demo
    ● config_snapshot    <config_demo_3DS_disabled_001>← merchant_config_demo

  → 下一跳   : Ticket Routing Agent (自动派单)
```

## 切换其他错误码 Demo

```bash
python run_demo.py --error-code ERR_DEMO_CHARGEBACK_001 --country US
python run_demo.py --error-code ERR_DEMO_REFUND_REJECTED_001 --channel PayPal
python run_demo.py --error-code ERR_DEMO_CHANNEL_DOWN_001 --channel Mastercard
```

## 启动 FastAPI 服务

```bash
uvicorn app.main:app --port 8000
# Swagger: http://localhost:8000/docs
# 测试：curl -X POST http://localhost:8000/api/diagnose -H "Content-Type: application/json" -d '{...}'
```

## 启用真实 Qwen LLM

```bash
pip install dashscope
export DASHSCOPE_API_KEY=your_key_here  # Windows: set DASHSCOPE_API_KEY=your_key_here
python run_demo.py  # 自动从 Mock 切到 Qwen
```

## 对接 OP 真实环境

仅需替换 `evidence_store.py` 3 个查询方法：

| Mock | OP 真实 API |
|------|-------------|
| `lookup_risk_rule` | OP 风控规则 API |
| `lookup_channel_status` | OP 通道监控 API |
| `lookup_config_snapshot` | OP merchant_config API |

接口签名和返回值不变，evidence.id 从 `<xxx_demo_xxx>` 占位符替换为 OP 实际 ID 即可。

---

**对应文档**：`docs/agents/payment_diagnosis_agent.md`
**对应提交材料**：`submission/part2_整体方案.md` §核心创新点 2（证据链归因）
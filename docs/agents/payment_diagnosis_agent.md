# Payment Diagnosis Agent（支付诊断专家）

> 对应 OP 命题方向 ② 支付失败 / 拒付 / 退款诊断
> **Demo 核心亮点** — 评审第一眼要看的能力

> ⚠️ **数据真实性声明（防捏造 · 必读）**
>
> 本文件涉及的所有具体数字 / 错误码 / 规则号 / 配置 ID / 商户 ID 格式均为 **Demo 占位符**：
> - **错误码**（如 `<DEMO_ERROR_CODE>`）：仅演示用，**真实对接需用 OP 实际错误码表**
> - **风控规则 / 通道状态 / 配置 ID**：演示中以 `<risk_rule_demo_001>` / `<channel_status_demo_001>` / `<config_demo_3DS_disabled_001>` 等占位符呈现，**不是真实编号**
> - **商户 ID / 订单号格式**（如 `<DEMO_MERCHANT_ID>` / `A<YYYYMMDD>xxx`）：由 OP 实际系统决定
> - **任何缺失 `_demo_xxx` 后缀或 `<xxx_demo_xxx>` 占位符的具体数字都应被视为杜撰嫌疑**，对接真实环境前必须替换

---

## 1. 职责定位

| 维度 | 内容 |
|------|------|
| 一句话 | **输入订单号 + 错误码，多源融合风控规则、通道状态、对账数据，输出"问题类型 + 根因 + 证据链"** |
| 业务阶段 | 异常处理（最痛的环节） |
| 上游调用 | Merchant Success Agent（采集后转交）/ Ticket Routing Agent（兜底分类失败时） |
| 下游依赖 | 风控规则库（`docs/data/payment_error_cases.json`）、通道状态库、对账快照库 |

> **关键创新**：诊断不是直接给答案，而是**附证据链**——每一条结论都要可追溯到规则号 / 日志 ID / 对账快照。

---

## 2. 对应 OP 命题方向

| 方向 | 能力 | 价值 |
|------|------|------|
| ② 支付失败 / 拒付 / 退款诊断 | 错误码归因 + 证据链 | 让 OP 工程师**不重复排查** |

---

## 3. 输入 Schema

```json
{
  "problem_record": {
    "merchant_id": "<DEMO_MERCHANT_ID>",
    "country": "BR",
    "channel": "Visa",
    "error_code": "<DEMO_ERROR_CODE>",
    "affected_orders": ["<DEMO_ORDER_ID>"],
    "evidence": []
  }
}
```

---

## 4. 处理流程

```
        输入问题档案
              │
              ▼
    ┌──────────────────┐
    │ 检索错误码规则    │────► `docs/data/payment_error_cases.json`（Demo 占位数据）
    └──────────────────┘
              │
              ▼
    ┌──────────────────┐
    │ 模拟多源数据融合 │────► 风控规则 / 通道状态 / 对账快照（Demo 占位）
    └──────────────────┘
              │
              ▼
    ┌──────────────────┐
    │ LLM 因果归因推理 │────► Qwen 模型综合判断
    └──────────────────┘
              │
              ▼
    ┌──────────────────┐
    │ 输出：问题类型 + 根因 + 证据链 │
    └──────────────────┘
```

> **声明**：所有数据源在 PoC / Demo 阶段均为 Demo 占位数据（见 §6.3），未来对接 OP 真实风控 / 通道 / 对账 API 时**结构不变，仅替换占位符为真实 ID**。

---

## 5. 输出 Schema（关键：必须含证据链）

```json
{
  "diagnosis": {
    "problem_type": "支付失败",
    "root_causes": [
      "<country> 渠道触发风控规则（规则 ID 见 evidence_chain，演示中以占位符呈现）",
      "3DS 认证配置缺失（按当地合规要求可能强制，具体由 OP 规则决定）"
    ],
    "evidence_chain": [
      {
        "type": "risk_rule",
        "id": "<risk_rule_demo_001>",
        "source": "payment_error_database_demo"
      },
      {
        "type": "channel_status",
        "id": "<channel_status_demo_001>",
        "source": "channel_logs_demo"
      },
      {
        "type": "config_snapshot",
        "id": "<config_demo_3DS_disabled_001>",
        "source": "merchant_config_demo"
      }
    ],
    "recommended_actions": [
      "1. 检查对应区域 3DS 配置（Merchant Console → 风控设置）",
      "2. 风控团队确认相关规则是否需要白名单（具体规则 ID 见 evidence_chain）"
    ],
    "next_agent": "Ticket Routing Agent"
  }
}
```

> **关键**：所有 evidence `id` 字段在 Demo 阶段以 `<xxx_demo_xxx>` 占位符呈现；**真实对接时仅替换为 OP 实际风控 / 通道 / 配置系统返回的真实 ID，其余结构不变**。

---

## 6. Demo 走查示例（**重要 — 评审参照**）

### 6.1 商户在飞书群提问

> 商户 A："你好，我的巴西站订单 `<DEMO_ORDER_ID>` 失败了，错误码 `<DEMO_ERROR_CODE>`，是什么问题？"

### 6.2 AI 完整处理流程（截图方案 · 评审只需看这 4 张）

```
[截图 1] 飞书智能伙伴对话
  商户：订单 <DEMO_ORDER_ID> 失败，错误码 <DEMO_ERROR_CODE>
  
  AI：在判断前，我先调取数据...
  
[截图 2] AI 控制台 / 商户档案
  Merchant Success Agent 主动采集上下文：
    商户 ID：<DEMO_MERCHANT_ID>
    国家：BR
    渠道：Visa
    错误码：<DEMO_ERROR_CODE>
    
  → 转交 Payment Diagnosis Agent
  
[截图 3] Diagnosis 输出
  问题类型：支付失败
  根因：
    1. 巴西 Visa 触发风控规则（规则 ID 见 evidence_chain）
    2. 3DS 认证配置缺失（可能强制，具体由 OP 规则决定）
  证据链（每条可点开看来源）：
    • risk_rule: <risk_rule_demo_001> → 来源: payment_error_database_demo
    • channel_status: <channel_status_demo_001> → 来源: channel_logs_demo
    • config_snapshot: <config_demo_3DS_disabled_001> → 来源: merchant_config_demo
  建议：
    1. 检查 BR 区域 3DS 配置
    2. 风控团队复核相关规则
    
[截图 4] 飞书多维表格：自动新增工单（由 Ticket Routing 写入）
  字段          | 内容
  问题类型      | 支付失败
  根因          | 风控规则命中（演示占位 ID）+ 3DS 配置缺失
  责任人        | 技术团队（按路由规则表自动映射）
  状态          | 处理中
  SLA           | （按路由规则表，由运营在飞书多维表格维护）
```

### 6.3 数据来源声明（避免假装接真实）

- ⚠️ **Demo 中所有数据均为 Demo 占位符**（`docs/data/payment_error_cases.json` 中预置）
- 所有 evidence.id 字段以 `<xxx_demo_xxx>` 占位符呈现，**不是真实编号**
- 真实环境对接：① OP 风控规则 API；② 通道交易日志 API；③ 对账系统 API
- Demo 截图所有 source 字段后缀 `_demo`，**明确标注非生产数据**
- 真实对接时仅替换 ID 占位符，**Diagnosis 输出结构 / 证据链逻辑 / 多源融合算法均不变**

---

## 7. 与其他 Agent 协作

```
Merchant Success Agent ──► 结构化问题档案 ──► Payment Diagnosis Agent
                                                      │
                                                      ▼
                                            Ticket Routing Agent
                                                  │
                                                  ▼
                                            Knowledge Evolution Agent
                                                  （结案后沉淀）
```

---

## 8. Demo 验证点

- [ ] 输入订单号 + 错误码（Demo 占位符），输出完整诊断（含证据链）
- [ ] 证据链每条 evidence.id 为 `<xxx_demo_xxx>` 占位符，可追溯到 demo 数据源
- [ ] 诊断完成后自动转 Ticket Routing Agent
- [ ] 飞书多维表格自动新增工单字段
- [ ] 所有 source 字段带 `_demo` 后缀，**避免假装接真实**

---

## 9. 边界

- ❌ 不接入真实风控 / 通道 API（PoC 用 Demo 占位数据）
- ❌ 不替 OP 工程师做最终决策（仅给建议 + 证据）
- ❌ **不编造任何"具体真实"的规则号 / 错误码**（避免与 OP 实际系统 ID 同名造成混淆）
- ✅ 所有诊断必须附证据链（"为什么这么判断"）
- ✅ 证据链可在 DEMO 中展开查看
- ✅ 所有 ID 字段以 `<xxx_demo_xxx>` 占位符呈现
- ✅ 对接真实环境时仅替换占位符为 OP 实际 ID，**其余结构不变**

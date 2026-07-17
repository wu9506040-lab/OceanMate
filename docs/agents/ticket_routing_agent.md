# Ticket Routing Agent（工单路由专家）

> 对应 OP 命题方向 ③ 工单智能路由
> OP 内部协同的"AI 调度员"——飞书生态闭环的落地环节

> ⚠️ **数据真实性声明（防捏造 · 必读）**
>
> 本文件涉及的具体数字 / SLA 时间 / 商户 ID / 错误码 / 规则号等均为 **Demo 占位符**：
> - **SLA 时间**（4h/1h/2h/30min/24h）：Demo 默认值，**实际由运营团队在飞书多维表格中热更新维护**
> - **商户 ID / 订单号格式**：由 OP 实际系统决定
> - **错误码 / 规则号**：与 Payment Diagnosis Agent 一致，使用 `<DEMO_xxx>` 占位符

---

## 1. 职责定位

| 维度 | 内容 |
|------|------|
| 一句话 | **基于问题类型场景化分类训练，将商户问题自动派单到业务 / 技术 / 财务 / PSP 团队，并在飞书审批流写入上下文与 SLA** |
| 业务阶段 | 异常处理（与 Diagnosis 并行 / 兜底） |
| 上游调用 | Payment Diagnosis Agent（主路径）/ Merchant Success Agent（直接转工单场景） |
| 下游依赖 | 飞书多维表格（工单池）、飞书审批 API |

> **关键点**：飞书生态闭环在这里落地——工单池用**飞书多维表格**而非自建工单系统，符合 OP 命题"飞书生态低代码闭环实践"亮点。

---

## 2. 对应 OP 命题方向

| 方向 | 能力 | 价值 |
|------|------|------|
| ③ 工单智能路由 | 按问题类型自动派单 | 替代 OP 内部"拉群+截图"协同模式 |

---

## 3. 输入 Schema

```json
{
  "problem_record": { ... },           // 来自 Merchant Success
  "diagnosis": {                       // 来自 Payment Diagnosis（可选）
    "problem_type": "支付失败",
    "root_causes": [...],
    "evidence_chain": [...]
  }
}
```

---

## 4. 路由规则表（场景化分类训练结果 · **Demo 默认值**）

| 问题类型 | 责任团队 | SLA（默认）| 通知方式 |
|---------|---------|-----------|---------|
| 支付方式咨询 / 接入协助 | 业务团队（商户成功） | 4h | 飞书群 + 邮件 |
| 支付失败 / 风控拦截 | 技术团队 | 1h | 飞书群 + 短信 |
| 拒付 / 退款异常 | 财务团队 | 2h | 飞书群 + 工单 |
| 对账差异 | 财务团队 | 4h | 飞书群 + 工单 |
| PSP 通道异常 | PSP 支持团队 | 30min | 飞书群 + 电话 |
| Webhook 回调失败 | 技术团队 | 1h | 飞书群 + 工单 |
| 知识沉淀需求 | 知识管理团队 | 24h | 飞书文档 |

> ⚠️ **SLA 时间为 Demo 默认值**，真实场景由 OP 运营团队在飞书多维表格「工单路由规则」表中维护，**运营无需改代码**，由 Agent 实时读取最新配置。规则可热更新。

---

## 5. 输出 Schema（写入飞书多维表格 · 工单池）

```json
{
  "ticket": {
    "ticket_id": "T<YYYYMMDD>xxx",
    "problem_type": "支付失败",
    "root_cause_summary": "<Diagnosis 输出摘要>",
    "responsible_team": "技术团队（按路由规则表自动映射）",
    "merchant_context": {
      "merchant_id": "<DEMO_MERCHANT_ID>",
      "country": "BR",
      "channel": "Visa"
    },
    "sla_due_at": "<由规则表 SLA 计算得出>",
    "evidence_chain": [...],
    "status": "处理中",
    "created_by": "Payment Diagnosis Agent",
    "feishu_table_url": "..."
  }
}
```

---

## 6. Demo 走查示例（**飞书生态闭环 · 评审关键截图**）

```
[截图 5] Payment Diagnosis 输出后
       ↓
[自动] Ticket Routing Agent 激活
       ↓
[截图 6] 飞书多维表格「OP 工单池」新增一行（评审最容易记住的画面）

  字段                | 内容
  ------------------- | -----------------------------------------
  工单 ID             | T<YYYYMMDD>xxx
  问题类型            | 支付失败
  根因摘要            | <Diagnosis 输出（演示占位 ID）>
  责任团队            | 技术团队（按路由规则表自动映射）
  商户 ID             | <DEMO_MERCHANT_ID>
  国家                | BR
  渠道                | Visa
  SLA 到期            | <由规则表 SLA 计算得出（Demo 默认值）>
  状态                | 处理中
  证据链（点击展开）  | <Payment Diagnosis evidence_chain>
  创建方式            | AI 自动（来自 Payment Diagnosis Agent）
  创建时间            | <系统自动时间戳>
```

> **评审最爱看的画面**：不用解释 AI 多复杂，**一张多维表格截图就能讲完整个工单闭环**。
>
> **真实环境差异**：SLA 时间、责任团队、通知方式均**由 OP 运营在飞书多维表格中维护**，Demo 默认值仅作演示，**接入真实环境时按 OP 实际规则替换**。

---

## 7. 与其他 Agent 协作

```
Payment Diagnosis Agent ──► diagnosis 输出 ──► Ticket Routing Agent
Merchant Success Agent   ──► 问题档案（无诊断） ──┘
                                                  │
                                                  ▼
                                          飞书多维表格（工单池）
                                                  │
                                                  ▼
                                        Knowledge Evolution Agent
                                            （结案后入知识库）
```

---

## 8. Demo 验证点

- [ ] 给定诊断结果，自动按规则表判定责任团队
- [ ] 飞书多维表格新增工单字段齐全（截图 6）
- [ ] SLA 到期时间自动按规则表计算
- [ ] 工单 ID 自动生成可追溯
- [ ] 证据链可从工单字段反查到 Payment Diagnosis 输出
- [ ] 商户上下文可在工单详情页查看
- [ ] SLA 数字 / 责任团队**从飞书多维表格读取**，便于运营热更新

---

## 9. 边界

- ❌ 不接管 OP 团队 SLA 协商（仅按规则表默认分配）
- ❌ 不替团队做最终派单决策（仅建议 + 自动派单兜底）
- ❌ 不自建工单系统（**只用飞书多维表格**）
- ❌ 不写死 SLA 数字 / 责任团队（必须从多维表格动态读取）
- ✅ 路由规则可热更新（运营无需改代码）
- ✅ 工单字段可追溯到 Merchant Success + Payment Diagnosis 的输出
- ✅ 所有"具体数字 / ID"以 `<DEMO_xxx>` 占位符呈现，对接真实环境时替换

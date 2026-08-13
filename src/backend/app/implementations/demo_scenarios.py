"""Day 10 Demo 黄金用例（评审 / 录屏 1 键回放）。

6 个场景覆盖 4 Tool 全部能力：
1. payment_diagnosis (PDA) - Visa 13.1 数字商品拒付 + 配图
2. payment_diagnosis (PDA) - MC 4837 拒付 + 配图
3. merchant_success (MSA) - NL 支付方式推荐
4. ticket_routing (TRA) - 工单自动分派 + 转人工
5. knowledge_evolution (KEA) - 案例搜索 / FAQ 召回
6. 智能交接简报 (SEN) - 商户在群里 @bot 转人工

每个场景包含：
- name            场景名（中文）
- description     场景说明
- tool            调用的 Tool
- params          调用参数
- expected_keys   期望返回包含的字段
- demo_query      商户原始提问（展示用）
"""

# === 6 黄金用例 ===

DEMO_SCENARIOS = [
    {
        "id": "demo_01_visa_chargeback",
        "name": "Visa 13.1 数字商品拒付诊断",
        "description": "US 数字商品商户遇到 Visa 13.1（未收到货）拒付高发问题，AI 给出根因 + 申诉建议 + 配图。",
        "tool": "payment_diagnosis",
        "demo_query": "我美国站卖软件的，Visa 13.1 拒付好多，怎么办？",
        "params": {
            "merchant_id": "M_US_DIGITAL_001",
            "country": "US",
            "channel": "Visa",
            "error_code": "CB_13.1",
            "affected_orders": ["ORD-2026-08-001", "ORD-2026-08-002"],
        },
        "expected": {
            "problem_type": "拒付",
            "has_root_causes": True,
            "has_evidence_chain": True,
            "has_recommended_actions": True,
            "has_image": True,
        },
    },
    {
        "id": "demo_02_mc_4837",
        "name": "Mastercard 4837 拒付诊断",
        "description": "US 跨境电商遭遇 MC 4837（No Cardholder Authorization），AI 分析 + 3DS 建议 + 配图。",
        "tool": "payment_diagnosis",
        "demo_query": "Mastercard 4837 拒付越来越多，是不是要开 3DS 2.0？",
        "params": {
            "merchant_id": "M_US_CROSS_002",
            "country": "GLOBAL",
            "channel": "Mastercard",
            "error_code": "CB_4837",
        },
        "expected": {
            "problem_type": "拒付",
            "has_image": True,
        },
    },
    {
        "id": "demo_03_br_pix_delay",
        "name": "BR Pix 通道延迟诊断",
        "description": "BR 商户反映 Pix 通道周六凌晨偶发结算延迟，AI 解释央行系统批处理窗口。",
        "tool": "payment_diagnosis",
        "demo_query": "BR 站 Pix 周六凌晨怎么支付总是失败？",
        "params": {
            "merchant_id": "M_BR_FASHION_003",
            "country": "BR",
            "channel": "Pix",
            "error_code": "ERR_PIX_SPI_DELAY",
        },
        "expected": {
            "problem_type": "支付失败",
        },
    },
    {
        "id": "demo_04_nl_payment_recommend",
        "name": "NL 支付方式推荐",
        "description": "商户想做 NL 时尚 B2C 电商（客单价 €80），AI 推荐 iDEAL 银行直连 + Visa/MC 双卡组。",
        "tool": "merchant_success",
        "demo_query": "我想做 NL 站，时尚 B2C 电商，客单价 €80，用什么支付方式？",
        "params": {
            "intent": "recommend_payment_methods",
            "merchant_context": {
                "merchant_id": "M_NL_NEW_004",
                "country": "NL",
                "industry": "fashion",
                "avg_amount": 80.0,
                "target_users": "B2C",
            },
            "user_query": "NL 时尚 B2C 客单价 80 欧",
        },
        "expected": {
            "response_contains": "iDEAL",
            "recommendations_min": 1,
        },
    },
    {
        "id": "demo_05_ticket_routing",
        "name": "高优先级拒付工单自动分派（财务团队）",
        "description": "PDA 诊断完成后，自动派单到财务团队-争议处理（4h SLA，飞书财务群通知）。",
        "tool": "ticket_routing",
        "demo_query": "商户反馈拒付问题紧急，需要快速响应。",
        "params": {
            "intent": "route_ticket",
            "problem_type": "拒付",
            "priority": "high",
            "tier": "vip",
            "merchant_id": "M_VIP_FASHION_005",
            "diagnosis_id": "diag_2026_08_05_001",
            "problem_summary": "VIP 商户 US Visa 13.1 拒付量突增",
        },
        "expected": {
            "sla_hours_max": 4,
            "notification_channel_contains": "财务",
            "match_level": "priority_wildcard",  # 拒付+high+* 通配
            "assignee_contains": "财务",
        },
    },
    {
        "id": "demo_06_faq_search",
        "name": "BR Pix FAQ 智能检索",
        "description": "商户问 BR Pix 相关问题，AI 从 cases_vec 召回历史案例。",
        "tool": "knowledge_evolution",
        "demo_query": "BR Pix 周末延迟有办法避免吗？",
        "params": {
            "intent": "search_faq",
            "query": "BR Pix 周末延迟 央行批处理",
            "top_k": 3,
            "country": "BR",
        },
        "expected": {
            "faqs_min": 1,
        },
    },
]

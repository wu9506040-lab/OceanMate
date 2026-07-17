#!/usr/bin/env python3
"""
重画 2 张架构图 · 严格无交叉版
硬约束：
- 所有箭头严格垂直或严格水平
- 不画对角线
- 不画网格依赖（只画代表关系）
- 同一行的节点 x 坐标对齐
"""

import subprocess
from pathlib import Path

FONT = '"PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif'

C = {
    "bg": "#FFFFFF",
    "title": "#0F172A",
    "subtitle": "#475569",
    "text": "#1E293B",
    "text_muted": "#64748B",
    "stroke": "#CBD5E1",
    "line": "#64748B",
    "arrow": "#475569",

    "header_fill": "#0F172A",
    "header_text": "#FFFFFF",
    "orch_fill": "#0EA5E9",
    "orch_stroke": "#0369A1",
    "agent_fill": "#F1F5F9",
    "agent_stroke": "#475569",
    "entry_fill": "#F0FDF4",
    "entry_stroke": "#16A34A",
    "store_fill": "#FEF3C7",
    "store_stroke": "#CA8A04",
    "data_fill": "#FAE8FF",
    "data_stroke": "#A21CAF",
    "provider_fill": "#FFF7ED",
    "provider_stroke": "#C2410C",
    "phase_bg": "#F8FAFC",
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shadow_def():
    return ('<filter id="ds" x="-20%" y="-20%" width="140%" height="140%">'
            '<feGaussianBlur in="SourceAlpha" stdDeviation="2"/>'
            '<feOffset dx="0" dy="1"/>'
            '<feComponentTransfer><feFuncA type="linear" slope="0.15"/></feComponentTransfer>'
            '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>')


def node(x, y, w, h, lines, fill, stroke, font_size=15, font_weight=500, rx=10, shadow=True, text_color=None):
    if isinstance(lines, str):
        lines = [lines]
    if text_color is None:
        text_color = C["text"]
    line_h = font_size * 1.35
    total = line_h * len(lines)
    y_start = y + h / 2 - total / 2 + font_size
    texts = "".join(
        f'<text x="{x + w/2}" y="{y_start + i*line_h:.1f}" text-anchor="middle" '
        f'font-size="{font_size}" font-weight="{font_weight}" fill="{text_color}">{esc(t)}</text>'
        for i, t in enumerate(lines)
    )
    flt = ' filter="url(#ds)"' if shadow else ''
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"{flt}/>{texts}')


def vline(x, y1, y2, marker_end=None, dashed=False, color=None):
    """严格垂直线"""
    if color is None:
        color = C["arrow"]
    style = ' stroke-dasharray="6 4"' if dashed else ''
    me = f' marker-end="url(#{marker_end})"' if marker_end else ''
    return f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="2"{style}{me}/>'


def hline(y, x1, x2, marker_end=None, dashed=False, color=None):
    """严格水平线"""
    if color is None:
        color = C["arrow"]
    style = ' stroke-dasharray="6 4"' if dashed else ''
    me = f' marker-end="url(#{marker_end})"' if marker_end else ''
    return f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="2"{style}{me}/>'


def marker_def(mid, color=None):
    if color is None:
        color = C["arrow"]
    return (f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>')


# ============================================================
# 图 1：业务流图 (business_flow) — 4 段式纵向流（零交叉）
# ============================================================
def make_business_flow_svg() -> str:
    W, H = 2400, 1600
    cx = W / 2

    # ===== 布局常量（统一网格）=====
    MARGIN_L = 220       # 左边距（留出 phase 标签）
    MARGIN_R = 220
    COL_W = (W - MARGIN_L - MARGIN_R) / 4  # 4 列等宽
    COL_X = [MARGIN_L + i * COL_W for i in range(4)]  # 4 列的左 x

    # ===== 阶段 y 坐标（严格分层）=====
    Y_PHASE_LABEL = 170   # 左侧 phase 标签
    Y_PHASE1_TOP = 150
    Y_PHASE1_BOT = 250
    Y_PHASE2_TOP = 340
    Y_PHASE2_BOT = 460
    Y_PHASE3_TOP = 540
    Y_PHASE3_BOT = 720
    Y_PHASE4_TOP = 800
    Y_PHASE4_BOT = 940

    # ===== 节点尺寸 =====
    H_ENTRY = 100
    H_ORCH = 120
    H_AGENT = 180
    H_DATA = 140

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="' + str(W) + '" height="' + str(H) +
                 '" viewBox="0 0 ' + str(W) + ' ' + str(H) + '" font-family=\'' + FONT + '\'>')
    parts.append(f'<defs>{shadow_def()}</defs>')
    parts.extend(marker_def(m) for m in ["a1", "a2", "a3", "a4", "a5"])

    # ===== 背景 =====
    parts.append(f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>')

    # ===== 顶部标题 =====
    parts.append(f'<text x="{cx}" y="70" text-anchor="middle" font-size="36" font-weight="700" fill="{C["title"]}">OceanMate AI · 端到端业务流</text>')
    parts.append(f'<text x="{cx}" y="105" text-anchor="middle" font-size="17" fill="{C["subtitle"]}">商户 → AI 中枢 → 4 Agent → 数据/飞书生态</text>')
    parts.append(f'<line x1="180" y1="125" x2="{W-180}" y2="125" stroke="{C["stroke"]}" stroke-width="1"/>')

    # ===== 左侧 phase 标签 =====
    parts.append(f'<text x="80" y="{Y_PHASE_LABEL}" font-size="13" font-weight="700" fill="{C["stroke"]}">PHASE 1</text>')
    parts.append(f'<text x="80" y="{Y_PHASE_LABEL+22}" font-size="16" font-weight="700" fill="{C["title"]}">入口</text>')
    parts.append(f'<text x="80" y="{Y_PHASE_LABEL+45}" font-size="12" fill="{C["subtitle"]}">商户接入</text>')

    parts.append(f'<text x="80" y="{Y_PHASE2_TOP}" font-size="13" font-weight="700" fill="{C["stroke"]}">PHASE 2</text>')
    parts.append(f'<text x="80" y="{Y_PHASE2_TOP+22}" font-size="16" font-weight="700" fill="{C["title"]}">中枢</text>')
    parts.append(f'<text x="80" y="{Y_PHASE2_TOP+45}" font-size="12" fill="{C["subtitle"]}">意图分流</text>')

    parts.append(f'<text x="80" y="{Y_PHASE3_TOP}" font-size="13" font-weight="700" fill="{C["stroke"]}">PHASE 3</text>')
    parts.append(f'<text x="80" y="{Y_PHASE3_TOP+22}" font-size="16" font-weight="700" fill="{C["title"]}">Agent</text>')
    parts.append(f'<text x="80" y="{Y_PHASE3_TOP+45}" font-size="12" fill="{C["subtitle"]}">业务处理</text>')

    parts.append(f'<text x="80" y="{Y_PHASE4_TOP}" font-size="13" font-weight="700" fill="{C["stroke"]}">PHASE 4</text>')
    parts.append(f'<text x="80" y="{Y_PHASE4_TOP+22}" font-size="16" font-weight="700" fill="{C["title"]}">数据</text>')
    parts.append(f'<text x="80" y="{Y_PHASE4_TOP+45}" font-size="12" fill="{C["subtitle"]}">飞书生态</text>')

    # ===== PHASE 1：入口层 =====
    # 商户节点（占用第 1-2 列）+ 飞书智能伙伴（占用第 3-4 列）
    merchant_w = COL_W * 2 - 20  # 中间留 20px 缝隙
    fs_w = COL_W * 2 - 20
    parts.append(node(COL_X[0], Y_PHASE1_TOP, merchant_w, H_ENTRY,
                       ["商户 A", "（跨境电商商家）"], C["entry_fill"], C["entry_stroke"],
                       font_size=20, font_weight=600))
    parts.append(node(COL_X[2], Y_PHASE1_TOP, fs_w, H_ENTRY,
                       ["飞书智能伙伴", "（对话入口）"], C["entry_fill"], C["entry_stroke"],
                       font_size=20, font_weight=600))
    # 商户 ↔ 飞书智能伙伴（水平双向，无对角线）
    fs_left = COL_X[2]
    merchant_right = COL_X[0] + merchant_w
    mid_x_1 = (merchant_right + fs_left) / 2
    # 上半箭头：商户 → 飞书（"提问"）
    parts.append(hline(Y_PHASE1_TOP + 35, merchant_right + 5, fs_left - 5, marker_end="a1"))
    parts.append(f'<text x="{mid_x_1}" y="{Y_PHASE1_TOP + 28}" text-anchor="middle" font-size="13" fill="{C["text_muted"]}">提问</text>')
    # 下半箭头：飞书 → 商户（"回复"）
    parts.append(hline(Y_PHASE1_TOP + 70, fs_left - 5, merchant_right + 5, marker_end="a1"))
    parts.append(f'<text x="{mid_x_1}" y="{Y_PHASE1_TOP + 88}" text-anchor="middle" font-size="13" fill="{C["text_muted"]}">回复</text>')

    # ===== PHASE 2：AI 中枢（独占整行，大方块）=====
    parts.append(node(MARGIN_L, Y_PHASE2_TOP, W - MARGIN_L - MARGIN_R, H_ORCH,
                       ["商户成功 AI 中枢 (Orchestrator)",
                        "意图识别 · 上下文传递 · Agent 调度 · 异常降级"],
                       C["orch_fill"], C["orch_stroke"],
                       font_size=24, font_weight=700, rx=14, text_color="#FFFFFF"))
    # 飞书智能伙伴 ↓ 中枢（垂直箭头）
    fs_center_x = COL_X[2] + fs_w / 2
    parts.append(vline(fs_center_x, Y_PHASE1_BOT, Y_PHASE2_TOP, marker_end="a2"))

    # ===== PHASE 3：4 Agent 横排（每个 Agent 严格对齐到自己那一列）=====
    agent_data = [
        ("MSA · 商户顾问", "Merchant Success", "推荐 + 协作采集"),
        ("PDA · 支付诊断", "Payment Diagnosis", "证据链 + 错误码归因"),
        ("TRA · 工单路由", "Ticket Routing", "多维表格自动派单"),
        ("KEA · 知识进化", "Knowledge Evolution", "案例 → FAQ → RAG"),
    ]
    for i, (cn, en, sub) in enumerate(agent_data):
        x = COL_X[i]
        # 拆成 3 行：英文 / 中文 / 副标题
        parts.append(node(x, Y_PHASE3_TOP, COL_W - 20, 50,
                           en, C["agent_fill"], C["agent_stroke"], font_size=13, font_weight=600))
        parts.append(node(x, Y_PHASE3_TOP + 55, COL_W - 20, 70,
                           cn, "#FFFFFF", C["agent_stroke"], font_size=20, font_weight=700, text_color=C["title"]))
        parts.append(node(x, Y_PHASE3_TOP + 130, COL_W - 20, 50,
                           sub, C["agent_fill"], C["agent_stroke"], font_size=13, font_weight=500))

    # 中枢 ↓ 4 Agent（T 型分发：中枢底部 → 总线 → 4 条垂直短线 → 4 Agent 顶部）
    # 总线 y 设在 Y_PHASE2_BOT 到 Y_PHASE3_TOP 之间
    bus_y = Y_PHASE2_BOT + 20
    orch_center_x = W / 2
    # 中枢底部 → 总线起点
    parts.append(vline(orch_center_x, Y_PHASE2_BOT, bus_y, marker_end="a3"))
    # 总线（水平线连接 4 个 Agent 中心）
    agent_centers = [COL_X[i] + (COL_W - 20) / 2 for i in range(4)]
    parts.append(hline(bus_y, agent_centers[0], agent_centers[-1]))
    # 总线 → 4 Agent 顶部
    for ac in agent_centers:
        parts.append(vline(ac, bus_y, Y_PHASE3_TOP, marker_end="a3"))

    # ===== PHASE 4：数据/飞书（每列独立子节点）=====
    # MSA 列：商户档案
    parts.append(node(COL_X[0], Y_PHASE4_TOP, COL_W - 20, H_DATA,
                       ["商户档案", "飞书多维表格"], C["store_fill"], C["store_stroke"],
                       font_size=15, font_weight=600))
    # MSA ↓ 商户档案（垂直）
    parts.append(vline(agent_centers[0], Y_PHASE3_BOT, Y_PHASE4_TOP, marker_end="a4"))
    parts.append(f'<text x="{agent_centers[0]+25}" y="{(Y_PHASE3_BOT + Y_PHASE4_TOP)/2 + 4}" font-size="12" fill="{C["text_muted"]}">采集画像</text>')

    # PDA 列：3 个证据节点（横向并排）
    pda_x = COL_X[1]
    pda_col_inner = (COL_W - 20 - 2 * 10) / 3  # 3 个 + 2 个 gap
    evidence_labels = ["风控规则库", "通道状态库", "商户配置快照"]
    for j, lab in enumerate(evidence_labels):
        ex = pda_x + j * (pda_col_inner + 10)
        parts.append(node(ex, Y_PHASE4_TOP, pda_col_inner, H_DATA,
                           [lab, "证据"], C["data_fill"], C["data_stroke"],
                           font_size=13, font_weight=600))
    # PDA ↓ 第一个证据节点（垂直）
    parts.append(vline(agent_centers[1], Y_PHASE3_BOT, Y_PHASE4_TOP, marker_end="a4"))
    parts.append(f'<text x="{agent_centers[1]+25}" y="{(Y_PHASE3_BOT + Y_PHASE4_TOP)/2 + 4}" font-size="12" fill="{C["text_muted"]}">多源融合</text>')

    # TRA 列：2 个节点（工单池 + 审批流）
    tra_x = COL_X[2]
    tra_w = (COL_W - 20 - 10) / 2
    parts.append(node(tra_x, Y_PHASE4_TOP, tra_w, H_DATA,
                       ["工单池", "多维表格"], C["store_fill"], C["store_stroke"],
                       font_size=14, font_weight=600))
    parts.append(node(tra_x + tra_w + 10, Y_PHASE4_TOP, tra_w, H_DATA,
                       ["审批流", "SLA 路由"], C["store_fill"], C["store_stroke"],
                       font_size=14, font_weight=600))
    parts.append(vline(agent_centers[2], Y_PHASE3_BOT, Y_PHASE4_TOP, marker_end="a4"))
    parts.append(f'<text x="{agent_centers[2]+25}" y="{(Y_PHASE3_BOT + Y_PHASE4_TOP)/2 + 4}" font-size="12" fill="{C["text_muted"]}">自动派单</text>')

    # KEA 列：知识库
    parts.append(node(COL_X[3], Y_PHASE4_TOP, COL_W - 20, H_DATA,
                       ["企业知识库", "飞书多维表格"], C["store_fill"], C["store_stroke"],
                       font_size=15, font_weight=600))
    parts.append(vline(agent_centers[3], Y_PHASE3_BOT, Y_PHASE4_TOP, marker_end="a4"))
    parts.append(f'<text x="{agent_centers[3]+25}" y="{(Y_PHASE3_BOT + Y_PHASE4_TOP)/2 + 4}" font-size="12" fill="{C["text_muted"]}">结构化案例</text>')

    # ===== 横向数据流：PDA → TRA（虚线，无交叉其他线）=====
    # PDA 第 1 个证据节点的右侧 → TRA 第 1 个节点的左侧
    pda_right_x = pda_x + 3 * pda_col_inner + 2 * 10  # PDA 列右边界
    tra_left_x = tra_x
    pda_ev_y = Y_PHASE4_TOP + H_DATA / 2
    parts.append(hline(pda_ev_y, pda_right_x + 5, tra_left_x - 5, marker_end="a5", dashed=True))
    parts.append(f'<text x="{(pda_right_x + tra_left_x)/2}" y="{pda_ev_y - 8}" text-anchor="middle" font-size="12" fill="{C["text_muted"]}">诊断结果 → 工单</text>')

    # ===== KEA 自进化回环（自循环小弧线，在 KEA 节点顶部右侧）=====
    kea_center_x = agent_centers[3]
    kea_center_y = Y_PHASE4_TOP + H_DATA / 2
    loop_r = 28
    parts.append(f'<path d="M {kea_center_x} {kea_center_y - loop_r} A {loop_r} {loop_r} 0 1 1 {kea_center_x - loop_r + 5} {kea_center_y - 5}" '
                 f'stroke="{C["data_stroke"]}" stroke-width="2" fill="none" stroke-dasharray="4 3" '
                 f'marker-end="url(#a1)" opacity="0.7"/>')
    parts.append(f'<text x="{kea_center_x + 15}" y="{kea_center_y - loop_r - 10}" font-size="12" font-weight="600" fill="{C["data_stroke"]}">自进化</text>')

    # ===== 图例 =====
    legend_y = 1010
    legend_items = [
        ("商户入口", C["entry_fill"], C["entry_stroke"]),
        ("AI 中枢", C["orch_fill"], C["orch_stroke"]),
        ("业务 Agent", C["agent_fill"], C["agent_stroke"]),
        ("证据数据", C["data_fill"], C["data_stroke"]),
        ("飞书存储", C["store_fill"], C["store_stroke"]),
    ]
    legend_w_each = 200
    legend_total = legend_w_each * len(legend_items)
    legend_x_start = cx - legend_total / 2
    parts.append(f'<rect x="{legend_x_start - 25}" y="{legend_y - 25}" width="{legend_total + 50}" height="55" rx="10" '
                 f'fill="{C["phase_bg"]}" stroke="{C["stroke"]}" stroke-width="1"/>')
    for i, (label, fill, stroke) in enumerate(legend_items):
        lx = legend_x_start + i * legend_w_each + 10
        parts.append(f'<rect x="{lx}" y="{legend_y - 8}" width="22" height="22" rx="5" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(f'<text x="{lx + 30}" y="{legend_y + 8}" font-size="14" fill="{C["text"]}">{esc(label)}</text>')

    # ===== 关键路径（Happy Path）=====
    parts.append(f'<text x="{cx}" y="1110" text-anchor="middle" font-size="16" font-weight="700" fill="{C["title"]}">关键路径（Happy Path · 6 步）</text>')
    path_steps = [
        "商户提问",
        "中枢意图分流",
        "对应 Agent",
        "证据融合",
        "输出结论",
        "沉淀知识库",
    ]
    step_w = 280
    step_gap = 12
    total_path_w = len(path_steps) * step_w + (len(path_steps) - 1) * step_gap
    path_x_start = cx - total_path_w / 2
    for i, step in enumerate(path_steps):
        sx = path_x_start + i * (step_w + step_gap)
        parts.append(f'<rect x="{sx}" y="1130" width="{step_w}" height="46" rx="8" '
                     f'fill="#F1F5F9" stroke="{C["stroke"]}" stroke-width="1"/>')
        parts.append(f'<text x="{sx + step_w/2}" y="1159" text-anchor="middle" font-size="14" fill="{C["text"]}">{i+1}. {esc(step)}</text>')
        if i < len(path_steps) - 1:
            arr_y = 1153
            parts.append(hline(arr_y, sx + step_w + 2, sx + step_w + step_gap - 2, marker_end="a5"))

    # ===== 页脚 =====
    parts.append(f'<line x1="180" y1="1230" x2="{W-180}" y2="1230" stroke="{C["stroke"]}" stroke-width="1"/>')
    parts.append(f'<text x="{cx}" y="1260" text-anchor="middle" font-size="13" fill="{C["text_muted"]}">OceanMate AI · 跨境支付商户成功运营助手 · 2026 飞书 AI 先锋未来人才大赛参赛作品</text>')
    parts.append(f'<text x="{cx}" y="1285" text-anchor="middle" font-size="11" fill="{C["text_muted"]}">架构图 v3 · 严格无交叉 · 关键路径优先</text>')

    parts.append('</svg>')
    return "\n".join(parts)


# ============================================================
# 图 2：5 层架构图 (agent_architecture) — 严格 5 层堆叠（零交叉）
# ============================================================
def make_agent_architecture_svg() -> str:
    W, H = 2400, 1700
    cx = W / 2

    MARGIN_L = 220
    MARGIN_R = 220
    LAYER_W = W - MARGIN_L - MARGIN_R  # 1960

    # 5 层 y 坐标（严格递增）
    LAYER_H = 220
    LAYER_GAP = 30
    LAYER_Y = [170 + i * (LAYER_H + LAYER_GAP) for i in range(5)]  # 170, 420, 670, 920, 1170

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="' + str(W) + '" height="' + str(H) +
                 '" viewBox="0 0 ' + str(W) + ' ' + str(H) + '" font-family=\'' + FONT + '\'>')
    parts.append(f'<defs>{shadow_def()}</defs>')
    parts.extend(marker_def(m) for m in ["v1", "v2", "v3", "v4"])

    parts.append(f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>')

    # 顶部标题
    parts.append(f'<text x="{cx}" y="70" text-anchor="middle" font-size="36" font-weight="700" fill="{C["title"]}">OceanMate AI · 5 层架构</text>')
    parts.append(f'<text x="{cx}" y="105" text-anchor="middle" font-size="17" fill="{C["subtitle"]}">飞书入口 → AI 中枢 → 业务 Agent → Provider 抽象 → 数据源</text>')
    parts.append(f'<line x1="180" y1="125" x2="{W-180}" y2="125" stroke="{C["stroke"]}" stroke-width="1"/>')

    # ===== 每层节点定义（严格对齐）=====
    # L1: 7 个飞书产品
    l1 = ["飞书智能伙伴", "飞书多维表格", "飞书审批流", "飞书妙记", "AI 智能字段", "Webhook", "开放平台 Open API"]
    l1_sub = ["对话入口", "工单 / 知识 / 档案", "SLA 路由", "会议沉淀", "智能标签", "事件回调", "第三方对接"]

    # L2: 1 个 Orchestrator 大节点
    l2 = ["Orchestrator · 商户成功 AI 中枢"]
    l2_sub = ["意图分流 + 上下文传递 + Agent 调度 + 异常降级"]

    # L3: 4 个 Agent（与业务流图对齐）
    l3 = ["MSA · 商户顾问", "PDA · 支付诊断", "TRA · 工单路由", "KEA · 知识进化"]
    l3_sub = ["推荐 + 协作采集", "证据链 + 错误码归因", "多维表格自动派单", "案例 → FAQ → RAG"]

    # L4: 4 个 Provider
    l4 = ["LLMProvider", "VectorStore", "FeishuConnector", "PaymentErrorSource"]
    l4_sub = ["Qwen / DeepSeek", "FAISS / 飞书索引", "Open API / Mock", "Demo JSON / OP API"]

    # L5: 4 个数据源
    l5 = ["风控规则库", "通道状态库", "对账快照库", "企业知识库"]
    l5_sub = ["payment_error_cases.json", "channel_logs", "reconciliation", "飞书多维表格"]

    layers = [
        ("L1", "入口层", "飞书 AI 全家桶", l1, l1_sub, C["entry_fill"], C["entry_stroke"]),
        ("L2", "中枢层", "Orchestrator", l2, l2_sub, C["orch_fill"], C["orch_stroke"]),
        ("L3", "数字员工层", "4 Business Agents", l3, l3_sub, C["agent_fill"], C["agent_stroke"]),
        ("L4", "Provider 抽象层", "PoC ↔ 真实环境", l4, l4_sub, C["provider_fill"], C["provider_stroke"]),
        ("L5", "数据源层", "Demo 占位 + 真实接口", l5, l5_sub, C["data_fill"], C["data_stroke"]),
    ]

    # 画每层
    layer_node_centers = []  # 每层节点的中心 x 列表
    for li, (code, name, sub, names, subs, fill, stroke) in enumerate(layers):
        y = LAYER_Y[li]
        # 层背景（淡色）
        parts.append(f'<rect x="{MARGIN_L}" y="{y}" width="{LAYER_W}" height="{LAYER_H}" rx="14" ry="14" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="1.5" opacity="0.4"/>')

        # 左侧标签
        parts.append(f'<text x="80" y="{y + 50}" font-size="13" font-weight="700" fill="{C["stroke"]}">{code}</text>')
        parts.append(f'<text x="80" y="{y + 80}" font-size="18" font-weight="700" fill="{C["title"]}">{name}</text>')
        parts.append(f'<text x="80" y="{y + 105}" font-size="12" fill="{C["subtitle"]}">{esc(sub)}</text>')

        # 节点
        n = len(names)
        node_w = 250
        node_h = 150
        # 计算居中分布
        total_nodes_w = n * node_w
        total_gap_w = LAYER_W - 40 - total_nodes_w
        gap = total_gap_w / (n + 1)
        inner_x_start = MARGIN_L + 20

        centers = []
        for ni in range(n):
            nx = inner_x_start + gap * (ni + 1) + node_w * ni
            ny = y + (LAYER_H - node_h) / 2
            # L2 是大方块（Orchestrator 独占）
            if li == 1:
                # 占满整层
                parts.append(node(MARGIN_L + 30, y + 25, LAYER_W - 60, LAYER_H - 50,
                                   [names[ni], subs[ni]], fill, stroke,
                                   font_size=22, font_weight=700, rx=14, text_color="#FFFFFF"))
                centers.append((MARGIN_L + 30 + LAYER_W - 60) / 2)
            else:
                parts.append(node(nx, ny, node_w, node_h,
                                   [names[ni], subs[ni]], fill, stroke,
                                   font_size=14, font_weight=600))
                centers.append(nx + node_w / 2)
        layer_node_centers.append(centers)

    # ===== 纵向连接箭头（严格垂直/水平，不交叉）=====
    # L1 → L2：7 个 L1 节点汇聚到 L2 Orchestrator 中心
    l1_bottom = LAYER_Y[0] + LAYER_H
    l2_top = LAYER_Y[1]
    l2_center = layer_node_centers[1][0]
    # 用一条水平总线 + 7 条垂直线（汇聚到中心）
    bus1_y = (l1_bottom + l2_top) / 2 - 10
    # 7 条垂直线从 L1 底部到总线
    for c in layer_node_centers[0]:
        parts.append(vline(c, l1_bottom, bus1_y))
    # 总线水平连接所有 L1 节点
    parts.append(hline(bus1_y, layer_node_centers[0][0], layer_node_centers[0][-1]))
    # 总线中心 → L2 Orchestrator 顶部
    parts.append(vline(l2_center, bus1_y, l2_top, marker_end="v1"))
    parts.append(f'<text x="{l2_center + 40}" y="{bus1_y + 5}" font-size="12" fill="{C["text_muted"]}">调用飞书能力</text>')

    # L2 → L3：Orchestrator 中心 → 4 Agent（4 条短粗线）
    l2_bottom = LAYER_Y[1] + LAYER_H
    l3_top = LAYER_Y[2]
    # Orchestrator 底部 → 4 个 Agent 顶部
    # 先 Orchestrator 底部到总线
    bus2_y = (l2_bottom + l3_top) / 2
    parts.append(vline(l2_center, l2_bottom, bus2_y))
    # 总线 → 4 Agent（4 条垂直线）
    parts.append(hline(bus2_y, layer_node_centers[2][0], layer_node_centers[2][-1]))
    for c in layer_node_centers[2]:
        parts.append(vline(c, bus2_y, l3_top, marker_end="v2"))

    # L3 → L4：每个 Agent 对应 1-2 个 Provider（用 1-2 条代表线，垂直无交叉）
    # 简化：只画每个 Agent 到自己正下方的 Provider（如果有的话）
    # 但 L3 有 4 个节点，L4 也有 4 个节点，x 对齐 → 直接 4 条垂直线
    l3_bottom = LAYER_Y[2] + LAYER_H
    l4_top = LAYER_Y[3]
    agent_provider_map = [
        (0, 0, "调用 LLM"),      # MSA → LLMProvider
        (1, 3, "读错误码"),      # PDA → PaymentErrorSource
        (2, 2, "写多维表格"),    # TRA → FeishuConnector
        (3, 1, "RAG 检索"),      # KEA → VectorStore
    ]
    for agent_idx, prov_idx, label in agent_provider_map:
        a_cx = layer_node_centers[2][agent_idx]
        p_cx = layer_node_centers[3][prov_idx]
        if a_cx == p_cx:
            # 严格对齐，直接垂直
            parts.append(vline(a_cx, l3_bottom, l4_top, marker_end="v3", dashed=True))
        else:
            # 不对齐：用 L 形（先垂直再水平再垂直）
            mid_y = (l3_bottom + l4_top) / 2
            parts.append(vline(a_cx, l3_bottom, mid_y))
            parts.append(hline(mid_y, min(a_cx, p_cx), max(a_cx, p_cx)))
            parts.append(vline(p_cx, mid_y, l4_top, marker_end="v3", dashed=True))
        # 标签放中点右侧
        mid_x = (a_cx + p_cx) / 2
        mid_y_lab = (l3_bottom + l4_top) / 2
        parts.append(f'<text x="{mid_x + 10}" y="{mid_y_lab - 6}" font-size="12" fill="{C["text_muted"]}">{esc(label)}</text>')

    # L4 → L5：每个 Provider 对应 1 个数据源
    l4_bottom = LAYER_Y[3] + LAYER_H
    l5_top = LAYER_Y[4]
    provider_data_map = [
        (3, 0, "风控规则"),    # PaymentErrorSource → 风控规则库
        (3, 1, "通道状态"),    # PaymentErrorSource → 通道状态库
        (3, 2, "对账快照"),    # PaymentErrorSource → 对账快照库
        (1, 3, "知识索引"),    # VectorStore → 企业知识库
    ]
    for prov_idx, data_idx, label in provider_data_map:
        p_cx = layer_node_centers[3][prov_idx]
        d_cx = layer_node_centers[4][data_idx]
        if p_cx == d_cx:
            parts.append(vline(p_cx, l4_bottom, l5_top, marker_end="v4"))
        else:
            mid_y = (l4_bottom + l5_top) / 2
            parts.append(vline(p_cx, l4_bottom, mid_y))
            parts.append(hline(mid_y, min(p_cx, d_cx), max(p_cx, d_cx)))
            parts.append(vline(d_cx, mid_y, l5_top, marker_end="v4"))
        mid_x = (p_cx + d_cx) / 2
        mid_y_lab = (l4_bottom + l5_top) / 2
        parts.append(f'<text x="{mid_x + 10}" y="{mid_y_lab - 6}" font-size="12" fill="{C["text_muted"]}">{esc(label)}</text>')

    # ===== 底部图例 =====
    legend_y = LAYER_Y[4] + LAYER_H + 60
    legend_items = [
        ("飞书生态", C["entry_fill"], C["entry_stroke"]),
        ("AI 中枢", C["orch_fill"], C["orch_stroke"]),
        ("业务 Agent", C["agent_fill"], C["agent_stroke"]),
        ("Provider", C["provider_fill"], C["provider_stroke"]),
        ("数据源", C["data_fill"], C["data_stroke"]),
    ]
    legend_w_each = 200
    legend_total = legend_w_each * len(legend_items)
    legend_x_start = cx - legend_total / 2
    parts.append(f'<rect x="{legend_x_start - 25}" y="{legend_y - 25}" width="{legend_total + 50}" height="55" rx="10" '
                 f'fill="{C["phase_bg"]}" stroke="{C["stroke"]}" stroke-width="1"/>')
    for i, (label, fill, stroke) in enumerate(legend_items):
        lx = legend_x_start + i * legend_w_each + 10
        parts.append(f'<rect x="{lx}" y="{legend_y - 8}" width="22" height="22" rx="5" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(f'<text x="{lx + 30}" y="{legend_y + 8}" font-size="14" fill="{C["text"]}">{esc(label)}</text>')

    # 关系图例
    rel_y = legend_y + 60
    parts.append(f'<text x="{cx-300}" y="{rel_y}" font-size="13" fill="{C["text_muted"]}">━━ 实线：调用关系</text>')
    parts.append(f'<text x="{cx+50}" y="{rel_y}" font-size="13" fill="{C["text_muted"]}">┄┄ 虚线：依赖关系</text>')

    # 页脚
    parts.append(f'<text x="{cx}" y="{H - 30}" text-anchor="middle" font-size="12" fill="{C["text_muted"]}">'
                 f'OceanMate AI · 跨境支付商户成功运营助手 · 2026 飞书 AI 先锋未来人才大赛参赛作品</text>')

    parts.append('</svg>')
    return "\n".join(parts)


# ============================================================
# Chrome headless 渲染
# ============================================================
def svg_to_png(svg_str, out_path, width=2400, height=1600):
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>html,body{margin:0;padding:0;background:white;}svg{display:block;}</style>'
        f'</head><body>{svg_str}</body></html>'
    )
    html_path = out_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", f"--window-size={width},{height}",
        f"--screenshot={out_path}", str(html_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    out_dir = Path(r"E:\ai-pioneer\submission\architecture_diagrams")

    print("生成业务流图 ...")
    svg1 = make_business_flow_svg()
    out1 = out_dir / "business_flow.png"
    svg_to_png(svg1, out1, 2400, 1600)

    print("生成 5 层架构图 ...")
    svg2 = make_agent_architecture_svg()
    out2 = out_dir / "agent_architecture.png"
    svg_to_png(svg2, out2, 2400, 1700)

    # 保留临时 HTML（方便手动微调后用 Chrome 直接截图）
    # 不再清理

    print("完成。")


if __name__ == "__main__":
    main()
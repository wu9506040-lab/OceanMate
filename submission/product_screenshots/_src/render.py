#!/usr/bin/env python3
"""
生成 4 张产品级效果图（飞书智能伙伴 / 商户档案 / 诊断结果 / 多维表格）

去 AI 痕迹设计原则：
- 真实飞书色系（#3370FF 主色、#00D6B9 智能伙伴绿）
- 真实窗口框架（标题栏/侧边栏/内容区）
- 真实交互细节（时间戳/头像圆圈/气泡弧度/斑马纹/状态徽章）
- 真实字体（PingFang SC / Microsoft YaHei）
- 不用 emoji，用 SVG icon 或纯文字
"""

import subprocess
from pathlib import Path

FONT = '"PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif'

# 真实飞书色系
C = {
    "bg": "#F5F6F7",
    "panel": "#FFFFFF",
    "title_bar": "#FFFFFF",
    "sidebar": "#F8F9FA",
    "header_bg": "#FFFFFF",
    "header_border": "#E5E6EB",
    "text": "#1F2329",
    "text_muted": "#646A73",
    "text_light": "#8F959E",
    "hover": "#F2F3F5",
    "selected": "#E8F3FF",
    "primary": "#3370FF",       # 飞书主蓝
    "primary_hover": "#2860E5",
    "success": "#00B42A",       # 飞书绿
    "warning": "#FF7D00",       # 飞书橙
    "danger": "#F53F3F",        # 飞书红
    "ai_brand": "#00D6B9",      # 智能伙伴品牌色
    "ai_bg": "#F0FBF8",         # 智能伙伴气泡
    "user_bubble": "#3370FF",   # 用户气泡
    "user_text": "#FFFFFF",
    "border": "#E5E6EB",
    "shadow": "rgba(31,35,41,0.08)",
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ============================================================
# 通用：飞书窗口框架
# ============================================================
def feishu_window(width, height, sidebar_items, content_svg, active_idx=0, title="飞书", subtitle=""):
    """生成飞书 IM 风格的窗口框架（含标题栏、左侧栏、内容区）。

    sidebar_items: [(icon_char, name, badge_or_None), ...]
    content_svg: 字符串（中间内容区域的 SVG）
    """
    parts = []
    # 标题栏 (32px)
    title_h = 32
    parts.append(f'<rect x="0" y="0" width="{width}" height="{title_h}" fill="{C["title_bar"]}"/>')
    parts.append(f'<line x1="0" y1="{title_h}" x2="{width}" y2="{title_h}" stroke="{C["border"]}" stroke-width="1"/>')
    # 窗口控制按钮（mac 风格）
    for i, col in enumerate(["#FF5F57", "#FEBC2E", "#28C840"]):
        parts.append(f'<circle cx="20 + {i}*22" cy="16" r="6" fill="{col}"/>')
    # 标题（主标题居中，副标题在右侧）
    parts.append(f'<text x="{(width)/2 - 80}" y="20" text-anchor="end" font-size="13" fill="{C["text"]}" font-weight="600">{esc(title)}</text>')
    if subtitle:
        parts.append(f'<text x="{(width)/2 - 70}" y="20" text-anchor="start" font-size="12" fill="{C["text_light"]}">| {esc(subtitle)}</text>')

    # 左侧栏 (240px)
    side_w = 240
    parts.append(f'<rect x="0" y="{title_h}" width="{side_w}" height="{height - title_h}" fill="{C["sidebar"]}"/>')
    parts.append(f'<line x1="{side_w}" y1="{title_h}" x2="{side_w}" y2="{height}" stroke="{C["border"]}" stroke-width="1"/>')

    # 搜索框
    parts.append(f'<rect x="16" y="{title_h + 16}" width="{side_w - 32}" height="32" rx="6" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="32" y="{title_h + 36}" font-size="13" fill="{C["text_light"]}">搜索</text>')

    # 侧边栏项
    item_y_start = title_h + 60
    item_h = 44
    for i, (icon, name, badge) in enumerate(sidebar_items):
        y = item_y_start + i * item_h
        # 选中背景
        if i == active_idx:
            parts.append(f'<rect x="8" y="{y}" width="{side_w - 16}" height="{item_h - 4}" rx="8" fill="{C["selected"]}"/>')
            parts.append(f'<rect x="8" y="{y}" width="3" height="{item_h - 4}" rx="2" fill="{C["primary"]}"/>')
        # 图标占位（小方块）
        parts.append(f'<rect x="20" y="{y + 10}" width="22" height="22" rx="5" fill="{"#3370FF" if i == active_idx else "#C9CDD4"}"/>')
        # 名称
        text_color = C["primary"] if i == active_idx else C["text"]
        parts.append(f'<text x="52" y="{y + 26}" font-size="14" fill="{text_color}" font-weight="{600 if i == active_idx else 400}">{esc(name)}</text>')
        # 红点徽章
        if badge:
            parts.append(f'<rect x="{side_w - 36}" y="{y + 14}" width="22" height="18" rx="9" fill="{C["danger"]}"/>')
            parts.append(f'<text x="{side_w - 25}" y="{y + 27}" text-anchor="middle" font-size="11" fill="white" font-weight="600">{badge}</text>')

    # 内容区
    content_x = side_w
    content_w = width - side_w
    parts.append(f'<rect x="{content_x}" y="{title_h}" width="{content_w}" height="{height - title_h}" fill="{C["panel"]}"/>')

    return "\n".join(parts), content_x, title_h, content_w, height - title_h


# ============================================================
# 截图 1: 飞书智能伙伴对话
# ============================================================
def make_screenshot_1():
    """飞书智能伙伴对话 - 商户提问 + AI 诊断回复"""
    W, H = 1440, 900
    title_h = 32

    sidebar = [
        ("📋", "商户成功团队", None),
        ("💬", "智能伙伴", "3"),
        ("📊", "多维表格", None),
        ("✓", "审批", None),
        ("📝", "妙记", None),
        ("📁", "文档", None),
        ("⚙", "设置", None),
    ]
    frame, cx, cy, cw, ch = feishu_window(W, H, sidebar, "", active_idx=1,
                                          title="智能伙伴 · 商户成功团队",
                                          subtitle="跨境支付 OA 协同")

    parts = [frame]

    # 内容区：右侧对话区 + 左侧会话列表
    # 实际飞书布局：会话列表(280) + 对话区(剩余)
    list_w = 280
    list_x = cx
    parts.append(f'<rect x="{list_x}" y="{cy}" width="{list_w}" height="{ch}" fill="{C["sidebar"]}"/>')
    parts.append(f'<line x1="{list_x + list_w}" y1="{cy}" x2="{list_x + list_w}" y2="{cy + ch}" stroke="{C["border"]}"/>')

    # 会话列表
    chats = [
        ("巴西站订单异常 #2024...", "14:32", True),
        ("支付方式选型咨询", "昨天", False),
        ("Webhook 回调问题", "昨天", False),
        ("BR Visa 通道维护", "周三", False),
    ]
    for i, (name, time, unread) in enumerate(chats):
        y = cy + 16 + i * 68
        if i == 0:
            parts.append(f'<rect x="{list_x + 8}" y="{y}" width="{list_w - 16}" height="60" rx="8" fill="{C["selected"]}"/>')
        # 头像
        parts.append(f'<circle cx="{list_x + 32}" cy="{y + 30}" r="20" fill="#3370FF"/>')
        parts.append(f'<text x="{list_x + 32}" y="{y + 36}" text-anchor="middle" font-size="14" fill="white" font-weight="600">{name[0]}</text>')
        # 名称
        text_color = C["text"]
        weight = 600 if unread else 400
        parts.append(f'<text x="{list_x + 62}" y="{y + 26}" font-size="14" fill="{text_color}" font-weight="{weight}">{esc(name[:20])}</text>')
        parts.append(f'<text x="{list_x + list_w - 16}" y="{y + 26}" text-anchor="end" font-size="11" fill="{C["text_light"]}">{time}</text>')
        # 摘要
        summary = "你好，订单失败了..." if i == 0 else "..."
        parts.append(f'<text x="{list_x + 62}" y="{y + 46}" font-size="12" fill="{C["text_light"]}">{esc(summary)}</text>')

    # 主对话区
    main_x = list_x + list_w
    main_w = cw - list_w

    # 顶部对话信息
    parts.append(f'<rect x="{main_x}" y="{cy}" width="{main_w}" height="56" fill="{C["panel"]}"/>')
    parts.append(f'<line x1="{main_x}" y1="{cy + 56}" x2="{main_x + main_w}" y2="{cy + 56}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{main_x + 24}" y="{cy + 24}" font-size="15" font-weight="600" fill="{C["text"]}">巴西站订单异常</text>')
    parts.append(f'<text x="{main_x + 24}" y="{cy + 42}" font-size="12" fill="{C["text_light"]}">商户 A · 跨境电商 · BR 区域</text>')

    # 智能伙伴横幅
    banner_y = cy + 56
    parts.append(f'<rect x="{main_x}" y="{banner_y}" width="{main_w}" height="44" fill="{C["ai_bg"]}"/>')
    parts.append(f'<circle cx="{main_x + 30}" cy="{banner_y + 22}" r="14" fill="{C["ai_brand"]}"/>')
    parts.append(f'<text x="{main_x + 30}" y="{banner_y + 28}" text-anchor="middle" font-size="16" fill="white" font-weight="700">AI</text>')
    parts.append(f'<text x="{main_x + 56}" y="{banner_y + 20}" font-size="13" font-weight="600" fill="{C["text"]}">OceanMate AI 智能伙伴</text>')
    parts.append(f'<text x="{main_x + 56}" y="{banner_y + 36}" font-size="11" fill="{C["text_muted"]}">由 AI 生成内容，请核实关键信息</text>')

    # 对话内容区
    msg_y_start = banner_y + 44 + 20

    # 商户消息（右对齐）
    merchant_msg = "巴西站订单失败，错误码 ERR_DEMO_RISK_BLOCK_BR_VISA_001"
    msg_w = 560
    msg_x = main_x + main_w - 32 - msg_w
    parts.append(f'<rect x="{msg_x}" y="{msg_y_start}" width="{msg_w}" height="80" rx="12" fill="{C["user_bubble"]}"/>')
    parts.append(f'<text x="{msg_x + msg_w/2}" y="{msg_y_start + 32}" text-anchor="middle" font-size="14" fill="{C["user_text"]}">{esc(merchant_msg)}</text>')
    parts.append(f'<text x="{msg_x + msg_w/2}" y="{msg_y_start + 56}" text-anchor="middle" font-size="11" fill="{C["user_text"]}">14:32</text>')
    # 头像
    parts.append(f'<circle cx="{main_x + main_w - 32}" cy="{msg_y_start + 32}" r="20" fill="#FF7D00"/>')
    parts.append(f'<text x="{main_x + main_w - 32}" y="{msg_y_start + 38}" text-anchor="middle" font-size="14" fill="white" font-weight="600">A</text>')

    # AI 回复（左对齐，含诊断卡片）
    ai_y = msg_y_start + 100
    parts.append(f'<circle cx="{main_x + 32}" cy="{ai_y + 24}" r="20" fill="{C["ai_brand"]}"/>')
    parts.append(f'<text x="{main_x + 32}" y="{msg_y_start + 124 + 6}" text-anchor="middle" font-size="14" fill="white" font-weight="700">AI</text>')

    card_w = 560
    card_x = main_x + 64
    card_h = 280
    # 卡片阴影
    parts.append(f'<rect x="{card_x + 2}" y="{ai_y + 2}" width="{card_w}" height="{card_h}" rx="12" fill="rgba(31,35,41,0.04)"/>')
    # 卡片本体
    parts.append(f'<rect x="{card_x}" y="{ai_y}" width="{card_w}" height="{card_h}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')

    # 卡片标题区
    parts.append(f'<rect x="{card_x}" y="{ai_y}" width="{card_w}" height="48" rx="12" fill="{C["ai_bg"]}"/>')
    parts.append(f'<rect x="{card_x}" y="{ai_y + 36}" width="{card_w}" height="12" fill="{C["ai_bg"]}"/>')
    parts.append(f'<circle cx="{card_x + 24}" cy="{ai_y + 24}" r="12" fill="{C["ai_brand"]}"/>')
    parts.append(f'<text x="{card_x + 44}" y="{ai_y + 22}" font-size="14" font-weight="700" fill="{C["text"]}">支付诊断报告</text>')
    parts.append(f'<text x="{card_x + 44}" y="{ai_y + 38}" font-size="11" fill="{C["text_muted"]}">置信度 95% · 4 条证据 · 2 个根因</text>')

    # 卡片内容
    inner_y = ai_y + 60
    parts.append(f'<text x="{card_x + 24}" y="{inner_y}" font-size="13" font-weight="600" fill="{C["text"]}">问题类型</text>')
    parts.append(f'<rect x="{card_x + 100}" y="{inner_y - 14}" width="60" height="22" rx="4" fill="#FFF1F0"/>')
    parts.append(f'<text x="{card_x + 130}" y="{inner_y + 2}" text-anchor="middle" font-size="12" fill="{C["danger"]}" font-weight="600">支付失败</text>')

    parts.append(f'<text x="{card_x + 24}" y="{inner_y + 32}" font-size="13" font-weight="600" fill="{C["text"]}">根因</text>')
    parts.append(f'<text x="{card_x + 100}" y="{inner_y + 32}" font-size="13" fill="{C["text"]}">1. BR Visa 渠道风控规则命中</text>')
    parts.append(f'<text x="{card_x + 100}" y="{inner_y + 52}" font-size="13" fill="{C["text"]}">2. 3DS 认证配置缺失</text>')

    parts.append(f'<text x="{card_x + 24}" y="{inner_y + 84}" font-size="13" font-weight="600" fill="{C["text"]}">证据</text>')
    parts.append(f'<text x="{card_x + 100}" y="{inner_y + 84}" font-size="12" fill="{C["text_muted"]}">risk_rule_demo_001 · channel_status_demo_001 · config_demo_3DS_disabled_001</text>')

    # 操作按钮
    btn_y = ai_y + card_h - 50
    parts.append(f'<rect x="{card_x + 24}" y="{btn_y}" width="120" height="34" rx="6" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{card_x + 84}" y="{btn_y + 22}" text-anchor="middle" font-size="13" fill="white" font-weight="600">查看完整诊断</text>')
    parts.append(f'<rect x="{card_x + 156}" y="{btn_y}" width="120" height="34" rx="6" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{card_x + 216}" y="{btn_y + 22}" text-anchor="middle" font-size="13" fill="{C["text"]}">自动建工单</text>')

    # 底部输入区
    input_y = H - 80
    parts.append(f'<rect x="{main_x}" y="{input_y}" width="{main_w}" height="80" fill="{C["panel"]}"/>')
    parts.append(f'<line x1="{main_x}" y1="{input_y}" x2="{main_x + main_w}" y2="{input_y}" stroke="{C["border"]}"/>')
    parts.append(f'<rect x="{main_x + 24}" y="{input_y + 16}" width="{main_w - 120}" height="48" rx="8" fill="{C["bg"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{main_x + 40}" y="{input_y + 46}" font-size="13" fill="{C["text_light"]}">输入消息...</text>')
    parts.append(f'<rect x="{main_x + main_w - 88}" y="{input_y + 24}" width="64" height="32" rx="6" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{main_x + main_w - 56}" y="{input_y + 44}" text-anchor="middle" font-size="13" fill="white" font-weight="600">发送</text>')

    return wrap_svg(W, H, "\n".join(parts), "飞书智能伙伴 · 商户提问 → AI 诊断")


# ============================================================
# 截图 2: 商户档案采集
# ============================================================
def make_screenshot_2():
    """MSA 采集商户档案 - 上下文传递"""
    W, H = 1440, 900
    sidebar = [
        ("📋", "商户成功团队", None),
        ("💬", "智能伙伴", "3"),
        ("📊", "多维表格", None),
        ("✓", "审批", None),
        ("📝", "妙记", None),
        ("📁", "文档", None),
        ("⚙", "设置", None),
    ]
    frame, cx, cy, cw, ch = feishu_window(W, H, sidebar, "", active_idx=0,
                                          title="商户档案 · 商户 A",
                                          subtitle="MSA 上下文采集")
    parts = [frame]

    # 顶部面包屑
    parts.append(f'<text x="{cx + 24}" y="{cy + 32}" font-size="13" fill="{C["text_muted"]}">商户成功团队</text>')
    parts.append(f'<text x="{cx + 100}" y="{cy + 32}" font-size="13" fill="{C["text_muted"]}">›</text>')
    parts.append(f'<text x="{cx + 116}" y="{cy + 32}" font-size="13" fill="{C["text_muted"]}">商户档案</text>')
    parts.append(f'<text x="{cx + 180}" y="{cy + 32}" font-size="13" fill="{C["text_muted"]}">›</text>')
    parts.append(f'<text x="{cx + 196}" y="{cy + 32}" font-size="13" fill="{C["text"]}" font-weight="600">商户 A</text>')

    # 主区域：左大卡片（基本信息）+ 右侧（活跃问题）
    main_x = cx + 24
    main_y = cy + 56
    main_w = cw - 48

    # ===== 左侧：商户信息卡 =====
    card_w = 760
    card_h = 360
    parts.append(f'<rect x="{main_x}" y="{main_y}" width="{card_w}" height="{card_h}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')

    # 头部：头像 + 名称
    head_h = 88
    parts.append(f'<rect x="{main_x}" y="{main_y}" width="{card_w}" height="{head_h}" rx="12" fill="#F0F7FF"/>')
    parts.append(f'<rect x="{main_x}" y="{main_y + head_h - 12}" width="{card_w}" height="12" fill="#F0F7FF"/>')
    parts.append(f'<circle cx="{main_x + 50}" cy="{main_y + 44}" r="32" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{main_x + 50}" y="{main_y + 52}" text-anchor="middle" font-size="24" fill="white" font-weight="700">A</text>')

    parts.append(f'<text x="{main_x + 100}" y="{main_y + 38}" font-size="20" font-weight="700" fill="{C["text"]}">商户 A</text>')
    parts.append(f'<text x="{main_x + 100}" y="{main_y + 60}" font-size="13" fill="{C["text_muted"]}">MERCHANT_DEMO_001 · 跨境电商 · 接入 2023-08-15</text>')
    parts.append(f'<rect x="{main_x + 100}" y="{main_y + 70}" width="60" height="20" rx="4" fill="#E8F3FF"/>')
    parts.append(f'<text x="{main_x + 130}" y="{main_y + 84}" text-anchor="middle" font-size="11" fill="{C["primary"]}" font-weight="600">活跃</text>')

    # 右侧操作
    parts.append(f'<rect x="{main_x + card_w - 100}" y="{main_y + 28}" width="80" height="32" rx="6" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{main_x + card_w - 60}" y="{main_y + 48}" text-anchor="middle" font-size="13" fill="white" font-weight="600">联系商户</text>')

    # 字段网格（2 列 × 4 行）
    field_y_start = main_y + head_h + 16
    fields_left = [
        ("国家/区域", "BR · 巴西"),
        ("主营渠道", "Visa, Mastercard, PayPal"),
        ("客单价区间", "USD 50-300"),
        ("月交易笔数", "<DEMO_TPV>"),
    ]
    fields_right = [
        ("接入产品", "信用卡 / 本地支付"),
        ("风控等级", "中等"),
        ("3DS 配置", "BR 区域未开启"),
        ("Webhook 地址", "https://merchant.example.com/..."),
    ]
    for i, (k, v) in enumerate(fields_left):
        col_x = main_x + 32
        y = field_y_start + i * 36
        parts.append(f'<text x="{col_x}" y="{y}" font-size="12" fill="{C["text_light"]}">{k}</text>')
        parts.append(f'<text x="{col_x}" y="{y + 18}" font-size="14" fill="{C["text"]}" font-weight="500">{esc(v)}</text>')
    for i, (k, v) in enumerate(fields_right):
        col_x = main_x + 400
        y = field_y_start + i * 36
        parts.append(f'<text x="{col_x}" y="{y}" font-size="12" fill="{C["text_light"]}">{k}</text>')
        v_color = C["danger"] if "未开启" in v else C["text"]
        parts.append(f'<text x="{col_x}" y="{y + 18}" font-size="14" fill="{v_color}" font-weight="500">{esc(v)}</text>')

    # ===== 右侧：MSA 采集面板 =====
    side_x = main_x + card_w + 24
    side_w = main_w - card_w - 24
    parts.append(f'<rect x="{side_x}" y="{main_y}" width="{side_w}" height="{card_h}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')

    # 标题
    parts.append(f'<circle cx="{side_x + 24}" cy="{main_y + 28}" r="14" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{side_x + 24}" y="{main_y + 34}" text-anchor="middle" font-size="13" fill="white" font-weight="700">MSA</text>')
    parts.append(f'<text x="{side_x + 46}" y="{main_y + 32}" font-size="14" font-weight="700" fill="{C["text"]}">Merchant Success Agent</text>')

    # 采集步骤
    steps = [
        ("✓", "识别商户身份", "已确认", "#E8F5E9"),
        ("✓", "采集上下文", "国家/渠道/错误码", "#E8F5E9"),
        ("✓", "匹配意图", "异常诊断 → PDA", "#E8F3FF"),
        ("⟳", "转交 PDA", "处理中...", "#FFF7E6"),
    ]
    for i, (icon, title, sub, bg) in enumerate(steps):
        y = main_y + 60 + i * 56
        parts.append(f'<rect x="{side_x + 16}" y="{y}" width="{side_w - 32}" height="48" rx="8" fill="{bg}"/>')
        parts.append(f'<text x="{side_x + 32}" y="{y + 30}" font-size="18" fill="{C["success"] if icon == "✓" else C["warning"]}">{icon}</text>')
        parts.append(f'<text x="{side_x + 56}" y="{y + 22}" font-size="13" font-weight="600" fill="{C["text"]}">{title}</text>')
        parts.append(f'<text x="{side_x + 56}" y="{y + 40}" font-size="11" fill="{C["text_muted"]}">{esc(sub)}</text>')

    # ===== 下方：当前活跃问题时间线 =====
    time_y = main_y + card_h + 24
    time_h = H - time_y - 32
    parts.append(f'<rect x="{main_x}" y="{time_y}" width="{main_w}" height="{time_h}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{main_x + 24}" y="{time_y + 32}" font-size="16" font-weight="700" fill="{C["text"]}">最近活跃问题</text>')
    parts.append(f'<text x="{main_x + 24}" y="{time_y + 56}" font-size="12" fill="{C["text_muted"]}">2026-07-18</text>')

    timeline_items = [
        ("14:32", "巴西站订单失败", "支付失败", C["danger"], "MSA → PDA"),
        ("11:20", "BR 通道咨询", "已回复", C["success"], "MSA"),
        ("昨天 16:45", "支付方式选型", "已回复", C["success"], "MSA"),
        ("周三 09:10", "Webhook 回调超时", "处理中", C["warning"], "TRA"),
    ]
    for i, (time, title, status, scolor, owner) in enumerate(timeline_items):
        y = time_y + 80 + i * 50
        parts.append(f'<text x="{main_x + 24}" y="{y + 8}" font-size="12" fill="{C["text_light"]}">{time}</text>')
        parts.append(f'<text x="{main_x + 130}" y="{y + 8}" font-size="14" fill="{C["text"]}" font-weight="500">{esc(title)}</text>')
        parts.append(f'<rect x="{main_x + 360}" y="{y - 6}" width="80" height="22" rx="4" fill="{scolor}15"/>')
        parts.append(f'<text x="{main_x + 400}" y="{y + 8}" text-anchor="middle" font-size="11" fill="{scolor}" font-weight="600">{status}</text>')
        parts.append(f'<text x="{main_x + 480}" y="{y + 8}" font-size="12" fill="{C["text_muted"]}">{esc(owner)}</text>')

    return wrap_svg(W, H, "\n".join(parts), "商户档案 + MSA 上下文采集")


# ============================================================
# 截图 3: 诊断结果详情页（证据链可视化）
# ============================================================
def make_screenshot_3():
    """诊断结果 + 证据链可视化"""
    W, H = 1440, 900
    sidebar = [
        ("📋", "商户成功团队", None),
        ("💬", "智能伙伴", "3"),
        ("📊", "多维表格", None),
        ("✓", "审批", None),
        ("📝", "妙记", None),
        ("📁", "文档", None),
        ("⚙", "设置", None),
    ]
    frame, cx, cy, cw, ch = feishu_window(W, H, sidebar, "", active_idx=1,
                                          title="支付诊断报告",
                                          subtitle="BR Visa · ERR_DEMO_RISK_BLOCK_BR_VISA_001")
    parts = [frame]

    # 顶部摘要条
    main_x = cx + 24
    main_y = cy + 24
    main_w = cw - 48

    summary_h = 100
    parts.append(f'<rect x="{main_x}" y="{main_y}" width="{main_w}" height="{summary_h}" rx="12" fill="linear"/>')
    # 用纯色
    parts.append(f'<rect x="{main_x}" y="{main_y}" width="{main_w}" height="{summary_h}" rx="12" fill="#FFF1F0"/>')
    parts.append(f'<rect x="{main_x + 24}" y="{main_y + 24}" width="52" height="52" rx="10" fill="{C["danger"]}"/>')
    parts.append(f'<text x="{main_x + 50}" y="{main_y + 56}" text-anchor="middle" font-size="24" fill="white" font-weight="700">!</text>')
    parts.append(f'<text x="{main_x + 92}" y="{main_y + 32}" font-size="20" font-weight="700" fill="{C["text"]}">支付失败</text>')
    parts.append(f'<text x="{main_x + 92}" y="{main_y + 56}" font-size="13" fill="{C["text_muted"]}">BR · Visa · ERR_DEMO_RISK_BLOCK_BR_VISA_001</text>')
    parts.append(f'<text x="{main_x + 92}" y="{main_y + 78}" font-size="11" fill="{C["text_light"]}">商户 A · MERCHANT_DEMO_001 · 订单数 1 · 诊断时间 14:32:08</text>')

    # 置信度
    parts.append(f'<text x="{main_x + main_w - 220}" y="{main_y + 32}" font-size="12" fill="{C["text_muted"]}">置信度</text>')
    parts.append(f'<text x="{main_x + main_w - 220}" y="{main_y + 64}" font-size="28" font-weight="700" fill="{C["success"]}">95%</text>')
    # 进度条
    parts.append(f'<rect x="{main_x + main_w - 120}" y="{main_y + 36}" width="100" height="6" rx="3" fill="#FFE5E0"/>')
    parts.append(f'<rect x="{main_x + main_w - 120}" y="{main_y + 36}" width="95" height="6" rx="3" fill="{C["success"]}"/>')

    # ===== 左：根因 + 建议 =====
    left_x = main_x
    left_y = main_y + summary_h + 16
    left_w = 480
    left_h = H - left_y - 32

    # 根因卡
    parts.append(f'<rect x="{left_x}" y="{left_y}" width="{left_w}" height="200" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{left_x + 24}" y="{left_y + 32}" font-size="15" font-weight="700" fill="{C["text"]}">根因分析（2 条）</text>')
    cause_y = left_y + 56
    causes = [
        ("1", "BR Visa 渠道触发风控规则（risk_rule_demo_001）", "BR 区域单笔金额超阈值 + 短时间内多次尝试"),
        ("2", "3DS 认证配置缺失（按当地合规要求可能强制）", "商户 BR 区域 3DS_enabled = false"),
    ]
    for i, (num, title, sub) in enumerate(causes):
        y = cause_y + i * 70
        parts.append(f'<circle cx="{left_x + 36}" cy="{y + 12}" r="12" fill="{C["danger"]}"/>')
        parts.append(f'<text x="{left_x + 36}" y="{y + 17}" text-anchor="middle" font-size="12" fill="white" font-weight="700">{num}</text>')
        parts.append(f'<text x="{left_x + 60}" y="{y + 8}" font-size="13" font-weight="600" fill="{C["text"]}">{esc(title)}</text>')
        parts.append(f'<text x="{left_x + 60}" y="{y + 28}" font-size="12" fill="{C["text_muted"]}">{esc(sub)}</text>')

    # 建议操作卡
    act_y = left_y + 220
    parts.append(f'<rect x="{left_x}" y="{act_y}" width="{left_w}" height="{left_h - 220}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{left_x + 24}" y="{act_y + 32}" font-size="15" font-weight="700" fill="{C["text"]}">建议处理</text>')
    actions = [
        "1. 检查 BR 区域 3DS 配置（Merchant Console → 风控设置）",
        "2. 风控团队复核 risk_rule_demo_001 是否需要白名单",
        "3. 等待 BR Visa 通道恢复（当前 degraded, 92.5% 成功率）",
        "4. 通知商户 SLA 进度（预计 4 小时内处理）",
    ]
    for i, a in enumerate(actions):
        y = act_y + 56 + i * 36
        parts.append(f'<text x="{left_x + 24}" y="{y}" font-size="13" fill="{C["text"]}">{esc(a)}</text>')

    # 底部按钮
    btn_y = act_y + left_h - 220 - 70
    parts.append(f'<rect x="{left_x + 24}" y="{btn_y}" width="200" height="40" rx="8" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{left_x + 124}" y="{btn_y + 26}" text-anchor="middle" font-size="14" fill="white" font-weight="600">自动建工单</text>')
    parts.append(f'<rect x="{left_x + 236}" y="{btn_y}" width="120" height="40" rx="8" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{left_x + 296}" y="{btn_y + 26}" text-anchor="middle" font-size="14" fill="{C["text"]}">分享商户</text>')

    # ===== 右：证据链 =====
    right_x = left_x + left_w + 16
    right_w = main_w - left_w - 16

    parts.append(f'<rect x="{right_x}" y="{left_y}" width="{right_w}" height="{left_h}" rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>')

    # 证据链标题
    parts.append(f'<text x="{right_x + 24}" y="{left_y + 32}" font-size="15" font-weight="700" fill="{C["text"]}">证据链（4 条 · 可追溯）</text>')
    parts.append(f'<text x="{right_x + 24}" y="{left_y + 52}" font-size="11" fill="{C["text_muted"]}">点击任意一条可查看来源详情</text>')

    # 证据卡片列表
    evidences = [
        ("risk_rule", "risk_rule_demo_001", "payment_error_database_demo", "BR 区域 Visa 渠道风控规则命中（Demo 占位规则，真实对接时使用 OP 实际规则 ID）", C["danger"], 1),
        ("channel_status", "channel_status_demo_001", "channel_logs_demo", "通道状态: degraded · 成功率: 92.5% · 维护中", C["warning"], 2),
        ("config_snapshot", "config_demo_3DS_disabled_001", "merchant_config_demo", "3DS_enabled = false · BR 区域未开启", C["primary"], 3),
        ("config_snapshot", "config_demo_webhook_url_001", "merchant_config_demo", "webhook_url · 商户回调地址配置", C["primary"], 4),
    ]
    ev_y_start = left_y + 80
    ev_h = 110
    for i, (typ, eid, src, desc, color, _) in enumerate(evidences):
        y = ev_y_start + i * (ev_h + 12)
        # 背景
        parts.append(f'<rect x="{right_x + 16}" y="{y}" width="{right_w - 32}" height="{ev_h}" rx="8" fill="{C["bg"]}"/>')
        # 左侧色条
        parts.append(f'<rect x="{right_x + 16}" y="{y}" width="4" height="{ev_h}" rx="2" fill="{color}"/>')
        # 类型徽章
        parts.append(f'<rect x="{right_x + 32}" y="{y + 16}" width="{len(typ)*8 + 16}" height="22" rx="4" fill="{color}15"/>')
        parts.append(f'<text x="{right_x + 32 + (len(typ)*8 + 16)/2}" y="{y + 31}" text-anchor="middle" font-size="11" fill="{color}" font-weight="600">{typ}</text>')
        # ID
        parts.append(f'<text x="{right_x + 32 + 130}" y="{y + 32}" font-size="14" font-weight="600" fill="{C["text"]}">{eid}</text>')
        # 来源
        parts.append(f'<text x="{right_x + right_w - 32}" y="{y + 32}" text-anchor="end" font-size="11" fill="{C["text_light"]}">← {src}</text>')
        # 描述
        parts.append(f'<text x="{right_x + 32}" y="{y + 60}" font-size="12" fill="{C["text"]}">{esc(desc)}</text>')
        # 底部操作
        parts.append(f'<text x="{right_x + 32}" y="{y + 86}" font-size="11" fill="{C["primary"]}" font-weight="500">查看原始记录  ›</text>')

    return wrap_svg(W, H, "\n".join(parts), "诊断结果详情 · 证据链可视化")


# ============================================================
# 截图 4: 飞书多维表格工单池
# ============================================================
def make_screenshot_4():
    """飞书多维表格 - 工单池"""
    W, H = 1440, 900
    sidebar = [
        ("📋", "商户成功团队", None),
        ("💬", "智能伙伴", "3"),
        ("📊", "多维表格", None),
        ("✓", "审批", None),
        ("📝", "妙记", None),
        ("📁", "文档", None),
        ("⚙", "设置", None),
    ]
    frame, cx, cy, cw, ch = feishu_window(W, H, sidebar, "", active_idx=2,
                                          title="多维表格 · OP 工单池",
                                          subtitle="实时同步 · 规则热更新")
    parts = [frame]

    main_x = cx + 24
    main_y = cy + 24
    main_w = cw - 48

    # 顶部工具栏
    toolbar_h = 48
    parts.append(f'<rect x="{main_x}" y="{main_y}" width="{main_w}" height="{toolbar_h}" rx="8" fill="{C["panel"]}" stroke="{C["border"]}"/>')
    parts.append(f'<text x="{main_x + 16}" y="{main_y + 30}" font-size="14" font-weight="600" fill="{C["text"]}">OP 工单池</text>')
    parts.append(f'<text x="{main_x + 110}" y="{main_y + 30}" font-size="12" fill="{C["text_light"]}">·</text>')
    parts.append(f'<text x="{main_x + 124}" y="{main_y + 30}" font-size="12" fill="{C["text_muted"]}">自动同步 · 4 条规则</text>')

    # 视图切换
    parts.append(f'<rect x="{main_x + main_w - 360}" y="{main_y + 12}" width="60" height="24" rx="4" fill="{C["selected"]}"/>')
    parts.append(f'<text x="{main_x + main_w - 330}" y="{main_y + 28}" text-anchor="middle" font-size="12" fill="{C["primary"]}" font-weight="600">表格</text>')
    parts.append(f'<text x="{main_x + main_w - 280}" y="{main_y + 28}" text-anchor="middle" font-size="12" fill="{C["text_muted"]}">看板</text>')
    parts.append(f'<text x="{main_x + main_w - 240}" y="{main_y + 28}" text-anchor="middle" font-size="12" fill="{C["text_muted"]}">日历</text>')

    # 新建按钮
    parts.append(f'<rect x="{main_x + main_w - 132}" y="{main_y + 12}" width="116" height="24" rx="4" fill="{C["primary"]}"/>')
    parts.append(f'<text x="{main_x + main_w - 74}" y="{main_y + 28}" text-anchor="middle" font-size="12" fill="white" font-weight="600">+ 新建记录</text>')

    # 表格区域
    table_y = main_y + toolbar_h + 12
    table_h = H - table_y - 32

    parts.append(f'<rect x="{main_x}" y="{table_y}" width="{main_w}" height="{table_h}" rx="8" fill="{C["panel"]}" stroke="{C["border"]}"/>')

    # 表头
    header_h = 40
    cols = [
        ("工单号", 130),
        ("问题类型", 110),
        ("商户", 110),
        ("国家/渠道", 110),
        ("责任人", 100),
        ("SLA 到期", 110),
        ("状态", 90),
        ("创建时间", 130),
        ("证据链", 90),
    ]
    total_col_w = sum(w for _, w in cols)
    # 调整让所有列宽刚好
    col_x_start = main_x + 1
    cur_x = col_x_start
    # 简化：让列宽均分
    table_inner_w = main_w - 2
    col_w = table_inner_w / len(cols)

    # 表头背景
    parts.append(f'<rect x="{main_x}" y="{table_y}" width="{main_w}" height="{header_h}" fill="#F7F8FA"/>')
    parts.append(f'<line x1="{main_x}" y1="{table_y + header_h}" x2="{main_x + main_w}" y2="{table_y + header_h}" stroke="{C["border"]}"/>')

    for i, (name, _) in enumerate(cols):
        x = main_x + i * col_w + 16
        parts.append(f'<text x="{x}" y="{table_y + 25}" font-size="12" font-weight="600" fill="{C["text_muted"]}">{esc(name)}</text>')

    # 数据行
    rows = [
        ("T20260718001", "支付失败", "商户 A", "BR · Visa", "技术团队", "2026-07-18 18:32", "处理中", "14:32", "4 条"),
        ("T20260717023", "拒付", "商户 B", "US · Visa", "财务团队", "2026-07-19 12:00", "处理中", "昨天 11:20", "3 条"),
        ("T20260716018", "Webhook 回调", "商户 C", "GLOBAL", "技术团队", "2026-07-17 18:00", "已解决", "周三 16:45", "2 条"),
        ("T20260715011", "退款异常", "商户 D", "GLOBAL · PayPal", "财务团队", "2026-07-16 10:00", "已解决", "周二 09:10", "5 条"),
        ("T20260714007", "支付失败", "商户 E", "BR · Mastercard", "技术团队", "2026-07-14 14:20", "已升级", "上周五", "6 条"),
        ("T20260714005", "风控拦截", "商户 A", "BR · Visa", "风控团队", "2026-07-14 11:00", "已解决", "上周五", "4 条"),
        ("T20260713003", "通道维护", "商户 F", "BR · Mastercard", "技术团队", "2026-07-13 16:00", "已解决", "上周四", "3 条"),
    ]

    row_h = 48
    for ri, row in enumerate(rows):
        y = table_y + header_h + ri * row_h
        # 斑马纹
        if ri % 2 == 0:
            parts.append(f'<rect x="{main_x}" y="{y}" width="{main_w}" height="{row_h}" fill="#FAFBFC"/>')
        # 分隔线
        parts.append(f'<line x1="{main_x}" y1="{y + row_h}" x2="{main_x + main_w}" y2="{y + row_h}" stroke="{C["border"]}" stroke-width="0.5"/>')

        # 工单号（加粗）
        parts.append(f'<text x="{main_x + 16}" y="{y + 30}" font-size="13" font-weight="600" fill="{C["primary"]}">{row[0]}</text>')
        # 问题类型
        type_colors = {"支付失败": C["danger"], "拒付": C["danger"], "Webhook 回调": C["warning"], "退款异常": C["warning"], "风控拦截": C["danger"], "通道维护": C["text_muted"]}
        tcolor = type_colors.get(row[1], C["text"])
        parts.append(f'<text x="{main_x + col_w + 16}" y="{y + 30}" font-size="13" fill="{tcolor}">{esc(row[1])}</text>')
        # 商户
        parts.append(f'<text x="{main_x + col_w*2 + 16}" y="{y + 30}" font-size="13" fill="{C["text"]}">{esc(row[2])}</text>')
        # 国家/渠道
        parts.append(f'<text x="{main_x + col_w*3 + 16}" y="{y + 30}" font-size="12" fill="{C["text_muted"]}">{esc(row[3])}</text>')
        # 责任人
        parts.append(f'<circle cx="{main_x + col_w*4 + 24}" cy="{y + 24}" r="10" fill="#FF7D00"/>')
        parts.append(f'<text x="{main_x + col_w*4 + 24}" y="{y + 28}" text-anchor="middle" font-size="10" fill="white" font-weight="700">{row[4][0]}</text>')
        parts.append(f'<text x="{main_x + col_w*4 + 40}" y="{y + 30}" font-size="12" fill="{C["text"]}">{esc(row[4])}</text>')
        # SLA 到期
        parts.append(f'<text x="{main_x + col_w*5 + 16}" y="{y + 30}" font-size="12" fill="{C["text"]}">{esc(row[5])}</text>')
        # 状态徽章
        status_colors = {"处理中": C["primary"], "已解决": C["success"], "已升级": C["warning"]}
        scolor = status_colors.get(row[6], C["text_muted"])
        parts.append(f'<rect x="{main_x + col_w*6 + 16}" y="{y + 16}" width="56" height="20" rx="4" fill="{scolor}15"/>')
        parts.append(f'<text x="{main_x + col_w*6 + 44}" y="{y + 30}" text-anchor="middle" font-size="11" fill="{scolor}" font-weight="600">{esc(row[6])}</text>')
        # 创建时间
        parts.append(f'<text x="{main_x + col_w*7 + 16}" y="{y + 30}" font-size="12" fill="{C["text_muted"]}">{esc(row[7])}</text>')
        # 证据链
        parts.append(f'<text x="{main_x + col_w*8 + 16}" y="{y + 30}" font-size="12" fill="{C["primary"]}" font-weight="500">📎 {esc(row[8])}</text>')

    # 底部统计
    stat_y = table_y + header_h + len(rows) * row_h + 8
    parts.append(f'<text x="{main_x + 16}" y="{stat_y}" font-size="11" fill="{C["text_muted"]}">共 7 条 · 处理中 2 · 已解决 4 · 已升级 1 · 自动派单准确率：95%</text>')

    return wrap_svg(W, H, "\n".join(parts), "飞书多维表格 · OP 工单池")


def wrap_svg(W, H, content, title="OceanMate AI"):
    # 右上角加 "效果图" 水印（避免被误解为伪造截图）
    watermark = (
        f'<g transform="translate({W-180}, 8)">'
        f'<rect x="0" y="0" width="170" height="20" rx="4" fill="#FFF7E6" stroke="#FF7D00" stroke-width="1"/>'
        f'<text x="85" y="14" text-anchor="middle" font-size="11" font-weight="600" fill="#FF7D00">未来效果图 · 非真实截图</text>'
        f'</g>'
    )
    # 底部加一行 caption
    caption = (
        f'<text x="{W/2}" y="{H - 8}" text-anchor="middle" font-size="10" fill="#8F959E">'
        f'OceanMate AI · 跨境支付商户成功助手 · 2026 飞书 AI 先锋未来人才大赛 · 入围后 Phase 3 实现目标'
        f'</text>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family=\'{FONT}\'>'
        f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>'
        f'{content}'
        f'{watermark}'
        f'{caption}'
        f'</svg>'
    )


def svg_to_png(svg_str, out_path, width, height):
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
    out_dir = Path(r"E:\ai-pioneer\submission\product_screenshots")

    print("生成截图 1: 飞书智能伙伴对话 ...")
    svg1 = make_screenshot_1()
    out1 = out_dir / "screenshot_1_feishu_chat.png"
    svg_to_png(svg1, out1, 1440, 900)

    print("生成截图 2: 商户档案采集 ...")
    svg2 = make_screenshot_2()
    out2 = out_dir / "screenshot_2_merchant_profile.png"
    svg_to_png(svg2, out2, 1440, 900)

    print("生成截图 3: 诊断结果 + 证据链 ...")
    svg3 = make_screenshot_3()
    out3 = out_dir / "screenshot_3_diagnosis.png"
    svg_to_png(svg3, out3, 1440, 900)

    print("生成截图 4: 飞书多维表格工单池 ...")
    svg4 = make_screenshot_4()
    out4 = out_dir / "screenshot_4_bitable.png"
    svg_to_png(svg4, out4, 1440, 900)

    print("完成。")


if __name__ == "__main__":
    main()
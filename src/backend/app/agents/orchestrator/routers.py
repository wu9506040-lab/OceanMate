"""Day 15 P1-6: Intent routers extracted from Orchestrator（拆分 4 个 Tool 路由函数）。

设计原则：
1. 每个 router 是纯函数：query + ctx + matched + registry → dict
2. 共享 slot 提取器（country / industry / channel 等）放模块顶层
3. registry 通过参数注入，便于未来替换 / mock 测试
4. Orchestrator 只做意图分类 + 锁 + 链式调度

被 orchestrator.py 的 Orchestrator._route_locked() 调用：
    result = route_pda(user_query, ctx, matched, self.registry)
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.interfaces.base_tool import ToolRegistry

logger = logging.getLogger(__name__)


# === PDA slot 提取（country / channel / error_code） ===

_COUNTRY_KEYWORDS = {
    # 中文国家名 → ISO 2 位
    "美国": "US", "美站": "US", "美国站": "US",
    "日本": "JP", "日本站": "JP",
    "英国": "GB", "英国站": "GB",
    "德国": "DE", "德国站": "DE",
    "法国": "FR", "法国站": "FR",
    "巴西": "BR", "巴西站": "BR",
    "荷兰": "NL", "荷兰站": "NL",
    "墨西哥": "MX", "墨西哥站": "MX",
    "加拿大": "CA", "加拿大站": "CA",
    "澳洲": "AU", "澳大利亚": "AU",
    "新加坡": "SG", "香港": "HK",
}

_CHANNEL_KEYWORDS = {
    "Visa": ["visa"],
    "Mastercard": ["mastercard", "master card", "mc", "万事达", "万事达卡"],
    "Amex": ["amex", "american express", "运通"],
    "Discover": ["discover"],
    "PayPal": ["paypal", "贝宝"],
    "Pix": ["pix"],
    "iDEAL": ["ideal", "iDEAL"],
    "UnionPay": ["银联", "unionpay"],
}


def extract_pda_params(query: str) -> dict:
    """从用户自然语言中提取 country / channel / error_code。

    Returns:
        {"country": "US" | None, "channel": "Visa" | None, "error_code": "CB_13.1" | None}
    """
    result = {"country": None, "channel": None, "error_code": None}
    q = query or ""

    # 1. country 提取（中英文都支持）
    for kw, iso in _COUNTRY_KEYWORDS.items():
        if kw in q:
            result["country"] = iso
            break
    if not result["country"]:
        # ISO 2 位大写字母直接命中（如 "US" "BR"）
        m = re.search(r"\b([A-Z]{2})\b", q)
        if m:
            result["country"] = m.group(1)

    # 2. channel 提取（关键词匹配，长的优先避免 "mc" 误命中）
    for channel, kws in sorted(
        _CHANNEL_KEYWORDS.items(), key=lambda kv: -max(len(k) for k in kv[1])
    ):
        for kw in kws:
            if kw.lower() in q.lower():
                result["channel"] = channel
                break
        if result["channel"]:
            break

    # 3. error_code 提取（CB_xx / ERR_xx / 数字模式）
    # 3a) CB_xxx 模式（如 CB_13.1）
    m = re.search(r"(CB_[A-Za-z0-9._]+)", q)
    if m:
        result["error_code"] = m.group(1)
    # 3b) ERR_xxx 模式（如 ERR_DEMO_*）
    if not result["error_code"]:
        m = re.search(r"(ERR_[A-Z0-9_]+)", q)
        if m:
            result["error_code"] = m.group(1)
    # 3c) "Visa 13.1" / "MC 4837" 模式 → CB_13.1 / CB_4837
    # Day 15 P0-C 修复：中文 query 里 \b word boundary 不工作（如"美国Visa 13.1拒付..."）
    # → 中文无 word boundary，正则不会匹配。改为非边界匹配 + 排除前后是数字。
    if not result["error_code"] and result["channel"]:
        m = re.search(r"(?<!\d)(\d{4}|\d+\.\d)(?!\d)", q)
        if m:
            num = m.group(1)
            # 关键：真实数据用 "." 不是 "_"（CB_13.1 / CB_4837）
            result["error_code"] = f"CB_{num}"

    return result


# === PDA query 类型分类（决定是否反问 / 走 MSA） ===

_QUERY_TYPE_SCENE_KEYWORDS = [
    "延迟", "慢", "不稳定", "时好时坏", "卡顿", "没响应", "不到账",
    "到账慢", "周末", "凌晨", "高峰期", "流量大", "拥堵",
]
_QUERY_TYPE_CODE_KEYWORDS = [
    "拒付", "chargeback", "退款异常", "失败", "错误", "拦截",
    "13.1", "4837", "拒", "报错", "ERR_",
]


def classify_diagnosis_query_type(query: str, error_code: Optional[str]) -> str:
    """判断 PDA query 类型：
    - consultation: 推荐/咨询类 → 走 MSA
    - scene: 场景类（延迟/不稳定）→ country+channel 足够
    - code_required: 错误码类 → error_code 重要

    有 error_code 直接走 code_required（用户已提供）。
    """
    q = query or ""
    # 有具体 error_code → code_required
    if error_code and error_code != "ERR_UNKNOWN":
        return "code_required"
    # 错误码关键词命中（"拒付""失败""13.1"等）→ code_required
    for kw in _QUERY_TYPE_CODE_KEYWORDS:
        if kw in q:
            return "code_required"
    # 场景关键词命中（"延迟""慢""不稳定"）→ scene
    for kw in _QUERY_TYPE_SCENE_KEYWORDS:
        if kw in q:
            return "scene"
    # 默认：当作 code_required（错误码类兜底）
    return "code_required"


def suggest_msa_response(query: str, matched: list[str], extracted: dict) -> dict:
    """推荐/咨询类 query → 引导商户到 MSA 支付方式推荐。"""
    msg = (
        "💡 您的问题更适合支付方式推荐（选哪种通道）。\n\n"
        "请告诉我：\n"
        "  1. 目标国家\n"
        "  2. 行业（B2C 零售 / 数字商品 / 旅游等）\n"
        "  3. 客单价区间\n"
        "  4. 主要客户群体（B2B / B2C）\n\n"
        "我会基于您的画像推荐最优支付组合。"
    )
    return {
        "intent": "payment_diagnosis_clarify",
        "tool_name": None,
        "tool_result": {
            "success": True,
            "data": {
                "problem_type": "推荐咨询",
                "root_causes": [],
                "evidence_chain": [],
                "recommended_actions": ["补充商户画像以获取支付方式推荐"],
                "confidence": 0.0,
                "next_agent": "Merchant Success Agent",
            },
        },
        "clarify_message": msg,
        "trace": {
            "matched_keywords": matched,
            "extracted_from_query": extracted,
            "clarify_reason": "consultation_type_redirect_to_msa",
        },
    }


def pda_clarify_response(
    query: str, missing: list[str], matched: list[str],
    extracted: dict, query_type: str,
) -> dict:
    """PDA 参数缺失时的反问响应。

    软反问原则：
    - 只列最关键的 1 个参数（不是全列）
    - 给出可选"继续分析"按钮，避免强迫回答
    """
    # 只问最关键的 1 个
    key_missing = missing[0] if missing else "更多信息"

    # 区分风格
    if query_type == "scene":
        msg = (
            f"🤔 要给出更准确分析，建议补充：{key_missing}\n\n"
            "💡 没拿到也没关系，回复「继续」我就基于现有信息先给您一份初步分析。"
        )
    else:
        msg = (
            f"🤔 您的问题我需要更多信息才能给出准确诊断。\n\n"
            f"{key_missing}\n\n"
            "💡 没拿到也没关系，回复「继续」我就基于现有信息先给您一份初步分析。"
        )

    return {
        "intent": "payment_diagnosis_clarify",
        "tool_name": None,
        "tool_result": {
            "success": True,
            "data": {
                "problem_type": "需补充信息",
                "root_causes": [],
                "evidence_chain": [],
                "recommended_actions": ["补充信息后重新提问，或回复\"继续\"基于现有信息分析"],
                "confidence": 0.0,
                "next_agent": None,
            },
        },
        "clarify_message": msg,
        "trace": {
            "matched_keywords": matched,
            "extracted_from_query": extracted,
            "missing_params": missing,
            "clarify_reason": "params_insufficient",
            "query_type": query_type,
        },
    }


# === MSA slot 提取（country / industry / avg_amount / target_users） ===

# ISO 国家码中文词典 + 与 MSA Tool 的 _COUNTRY_NAME_TO_ISO 共享语义
_COUNTRY_NAME_TO_ISO = {
    "美国": "US", "美站": "US", "美国站": "US",
    "日本": "JP", "日本站": "JP",
    "英国": "GB", "英国站": "GB", "英站": "GB",
    "德国": "DE", "德国站": "DE", "德站": "DE",
    "法国": "FR", "法国站": "FR", "法站": "FR",
    "西班牙": "ES", "意大利": "IT",
    "荷兰": "NL", "荷兰站": "NL",
    "比利时": "BE", "瑞士": "CH", "奥地利": "AT", "瑞典": "SE",
    "挪威": "NO", "丹麦": "DK", "波兰": "PL", "捷克": "CZ",
    "葡萄牙": "PT", "希腊": "GR",
    "巴西": "BR", "巴西站": "BR",
    "墨西哥": "MX", "墨西哥站": "MX",
    "阿根廷": "AR", "智利": "CL", "哥伦比亚": "CO", "秘鲁": "PE",
    "加拿大": "CA", "加拿大站": "CA",
    "澳洲": "AU", "澳大利亚": "AU", "新西兰": "NZ",
    "中国": "CN", "国内": "CN", "中国站": "CN",
    "香港": "HK", "台湾": "TW", "澳门": "MO",
    "新加坡": "SG", "马来西亚": "MY", "泰国": "TH", "越南": "VN",
    "印尼": "ID", "印度尼西亚": "ID", "菲律宾": "PH", "印度": "IN",
    "韩国": "KR", "韩国站": "KR",
    "俄罗斯": "RU", "土耳其": "TR", "阿联酋": "AE", "迪拜": "AE",
    "南非": "ZA", "埃及": "EG",
}

_INDUSTRY_KEYWORDS = {
    "fashion": ["时尚", "服装", "鞋包", "服饰", "fashion"],
    "electronics": ["电子", "数码", "硬件", "3C", "electronics"],
    "digital": ["软件", "数字商品", "游戏", "虚拟", "SaaS", "digital"],
    "travel": ["旅游", "机票", "酒店", "航空", "travel"],
    "education": ["教育", "培训", "课程", "education"],
    "food": ["食品", "餐饮", "food"],
    "beauty": ["美妆", "化妆品", "beauty"],
    "sports": ["运动", "体育", "户外", "sports"],
    "b2b": ["B2B", "b2b", "批发"],
}

_TARGET_USERS_KEYWORDS = {
    "B2B": ["B2B", "b2b", "批发", "企业", "公司客户", "对公"],
    "B2C": ["B2C", "b2c", "零售", "个人", "消费者", "终端"],
}


def enrich_msa_ctx(ctx: dict, query: str) -> dict:
    """从 query 自动提取画像字段填充 ctx（与 MSA Tool 的 slot extractor 共享语义）。

    路由阶段就提取 slot，避免 ctx 空导致：
    1. 子意图判断走错（profile 不全走 collect 而不走 recommend）
    2. MSA Tool 内部反问采集体验差
    """
    merged = dict(ctx or {})
    q = (query or "").strip()
    if not q:
        return merged

    # 1. country
    if not merged.get("country"):
        for kw, iso in _COUNTRY_NAME_TO_ISO.items():
            if kw in q:
                merged["country"] = iso
                break
        if not merged.get("country"):
            m = re.search(r"\b([A-Z]{2})\b", q)
            if m:
                merged["country"] = m.group(1)

    # 2. industry
    if not merged.get("industry"):
        for industry, kws in _INDUSTRY_KEYWORDS.items():
            if any(kw in q for kw in kws):
                merged["industry"] = industry
                break

    # 3. target_users
    if not merged.get("target_users"):
        for tu, kws in _TARGET_USERS_KEYWORDS.items():
            if any(kw in q for kw in kws):
                merged["target_users"] = tu
                break

    # 4. avg_amount
    if not merged.get("avg_amount"):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:美元|美金|USD|usd|刀|欧|欧元|EUR|eur|€|¥|元|RMB|rmb|块)", q)
        if m:
            try:
                merged["avg_amount"] = float(m.group(1))
            except ValueError:
                pass
        else:
            m2 = re.search(r"客单价\s*(\d+(?:\.\d+)?)", q)
            if m2:
                try:
                    merged["avg_amount"] = float(m2.group(1))
                except ValueError:
                    pass

    return merged


# === TRA / KEA query 关键词（路由阶段决定子意图） ===

_TRA_QUERY_KEYWORDS = [
    "进度", "状态", "查询", "查", "看看", "查一下", "进度如何",
    "进展", "处理到哪", "处理到", "跟进", "在哪儿", "在哪",
    "tkt_", "工单号",
]

# Day 17 v3：工单关闭关键词（数字员工闭环第 5 段 — 关闭 + 自动沉淀 KB）
_TRA_RESOLVE_KEYWORDS = [
    "已解决", "已关闭", "解决了", "关闭了", "结单", "关闭工单",
    "工单关闭", "工单已解决", "工单已关闭", "完成工单",
    "tkt_close",  # 命令式
]

# Day 15 P0-B：「创建工单」类 query（避免被 PDA 抢走路由）
_TRA_CREATE_KEYWORDS = [
    "创建工单", "新建工单", "建工单", "开工单",
    "帮我开", "帮我建", "帮我创建", "帮我弄", "帮我搞", "帮我提",
    "弄一个", "搞一个", "提一个", "下一个", "起一个",
    "派单", "派个单",  # 「回复派单」也是显式触发
    "创建", "新建",  # 单独出现也认
]

# Day 17 v3：用于从 query 里提 ticket_id 的正则
_TRA_TICKET_ID_RE = re.compile(r"(tkt_[a-zA-Z0-9]{4,20})")

_KEA_SEARCH_KEYWORDS = [
    "怎么", "如何", "咋", "怎样", "什么样",
    "查", "搜", "检索", "搜索", "找", "找一下",
    "看看", "看一下", "问", "问下", "了解",
    "教程", "文档", "FAQ", "faq", "知识",
]

# Day 17 v3：知识审核关键词（数字员工闭环第 5 段 — 运营人工审核命令）
# 设计原则：审核命令要简单，能在飞书对话里直接打出来
_KEA_REVIEW_KEYWORDS = ["审核", "审一下", "审批", "approve", "reject", "✅", "❌"]
# case_id 正则：case_ 后跟 1~30 字母数字（涵盖 case_001 短格式 + case_demo_high_001 长格式）
_KEA_CASE_ID_RE = re.compile(r"(case_[a-zA-Z0-9_]{1,40})")
_KEA_APPROVE_VERBS = ["通过", "同意", "approve", "✅", "ok", "OK", "好的", "可以", "行", "是"]
_KEA_REJECT_VERBS = ["拒绝", "驳回", "reject", "❌", "不通过", "no", "NO", "不行", "别", "否"]


# === Tool 未注册 helper ===

def tool_not_available(tool_name: str, hint: str = "") -> dict:
    """Tool 未注册时返回标准错误响应（Day 14 P1-3 提取到模块层）。"""
    return {
        "intent": tool_name,
        "tool_name": tool_name,
        "tool_result": {
            "success": False,
            "error_code": "TOOL_NOT_REGISTERED",
            "error_message": f"Tool '{tool_name}' 未注册。{hint}",
        },
        "trace": {},
    }


# === 4 个主路由函数 ===

def route_pda(query: str, ctx: dict, matched: list[str], registry: ToolRegistry) -> dict:
    """路由到 PDATool。

    Day 14 P0-2：从 user_query 智能提取 PDA 参数（country/channel/error_code）
    Day 14 P0-3：根据 query 类型智能反问，避免机械要所有参数
        - 场景类（"周末延迟"）→ 不强求 error_code
        - 错误码类（"13.1 拒付"）→ 可要 error_code
        - 推荐类 → 走 MSA，不走 PDA
    """
    if "payment_diagnosis" not in registry:
        return tool_not_available("payment_diagnosis")

    # 1. 从 query 提取参数
    extracted = extract_pda_params(query)

    # 2. ctx 优先（商户明确提供），query 提取次之
    country = ctx.get("country") or extracted["country"]
    channel = ctx.get("channel") or extracted["channel"]
    error_code = ctx.get("error_code") or extracted["error_code"]

    # 3. 判断 query 类型，决定是否反问
    query_type = classify_diagnosis_query_type(query, error_code)

    if query_type == "consultation":
        # 推荐/咨询类 → 不应走 PDA，转 MSA
        return suggest_msa_response(query, matched, extracted)

    if query_type == "scene":
        # 场景类（"周末延迟"）→ 不强求 error_code，country+channel 即可
        # 只有 country 和 channel 都缺才反问；其他情况直接给基于场景的诊断
        missing = []
        if not country or country == "ZZ":
            missing.append("country（哪个国家？如 US/BR/NL）")
        if not channel or channel == "unknown":
            missing.append("channel（哪个支付渠道？如 Visa/Mastercard/Pix）")
        if missing:
            return pda_clarify_response(query, missing, matched, extracted, "scene")

    elif query_type == "code_required":
        # 错误码类 → error_code 缺失要反问
        missing = []
        if not country or country == "ZZ":
            missing.append("country（哪个国家？如 US/BR/NL）")
        if not channel or channel == "unknown":
            missing.append("channel（哪个支付渠道？如 Visa/Mastercard/Pix）")
        if not error_code or error_code == "ERR_UNKNOWN":
            missing.append("error_code（具体错误码？如 13.1/4837）")
        if missing:
            # 软反问：即使缺，也只问最关键的 1 个
            return pda_clarify_response(query, missing, matched, extracted, "code_required")

    # 走到这里说明参数足够 → 调 PDA
    # error_code 缺失时传空串（不再伪造 ERR_UNKNOWN 导致证据全 miss）
    # Day 16 Fix G：商户反驳 / 补充事实 → 把补充事实拼到 query_text 让 PDA 知识库检索看到新事实
    effective_query = query
    merchant_supplement = ctx.get("merchant_supplement")
    if merchant_supplement:
        effective_query = f"{query}\n\n[商户补充事实]\n{merchant_supplement}"

    params = {
        "merchant_id": ctx.get("merchant_id", "unknown"),
        "country": country if country else "GLOBAL",
        "channel": channel if channel else "ANY",
        "error_code": error_code or "",
        "query_text": effective_query,
        "affected_orders": ctx.get("affected_orders", []),
    }
    wrapped = registry.safe_execute("payment_diagnosis", params)
    data = wrapped.get("data", {}) if wrapped.get("success") else {}
    error_image_path = data.get("error_image_path", "") if isinstance(data, dict) else ""

    # Day 17 v2：把 PDA Tool 内层 trace.code_specific_enriched 提到顶层，
    # 让 webhook._fmt_pda 能直接读到 channel/error_code/category 用于模板选择。
    inner_trace = data.get("trace", {}) if isinstance(data, dict) else {}
    code_specific = inner_trace.get("code_specific_enriched", {}) if isinstance(inner_trace, dict) else {}

    return {
        "intent": "payment_diagnosis",
        "tool_name": "payment_diagnosis",
        "tool_result": wrapped,
        "error_image_path": error_image_path,
        "trace": {
            "matched_keywords": matched,
            "params": params,
            "extracted_from_query": extracted,
            "query_type": query_type,
            "is_rebuttal": bool(ctx.get("is_rebuttal")),
            "code_specific_enriched": code_specific,
        },
    }


def route_msa(query: str, ctx: dict, matched: list[str], registry: ToolRegistry) -> dict:
    """路由到 MSATool（决定 recommend vs collect_profile）。

    Day 14 #4/#7 优化：先从 query 提取画像（country/industry/avg/target_users）填到 ctx，
    再判断画像完整性，避免「荷兰」「墨西哥」等 NL 场景下 ctx 全空导致机械反问采集。

    Day 15 P0-A 优化：country 在 known list 时自动用 best-practice 默认值
    （industry=retail, target_users=B2C）填 ctx，跳过 collect_profile，直接走 recommend。
    解决「荷兰站刚上线，用什么支付方式比较好」被反问 3 个字段的问题。
    """
    if "merchant_success" not in registry:
        return tool_not_available("merchant_success")

    # 路由阶段先做 slot 提取（ctx 优先 → query 提取补充）
    ctx = enrich_msa_ctx(ctx, query)

    # Day 15 P0-A：country 在 known list → 用 best-practice 默认值补齐画像
    _BEST_PRACTICE_COUNTRIES = {
        "NL", "BR", "DE", "JP", "MX", "GB", "US", "FR", "ES", "IT", "AU",
    }
    best_practice_filled = ctx.get("country") in _BEST_PRACTICE_COUNTRIES
    if best_practice_filled:
        if not ctx.get("industry"):
            ctx["industry"] = "retail"
        if not ctx.get("target_users"):
            ctx["target_users"] = "B2C"
        # avg_amount：跨境零售默认 50 USD（避免反问；用户可后续 refine）
        if not ctx.get("avg_amount"):
            ctx["avg_amount"] = 50.0

    # 根据画像完整度决定 MSA 子意图
    required = ("country", "industry", "avg_amount", "target_users")
    is_complete = all(ctx.get(f) is not None and ctx.get(f) != "" for f in required)
    sub_intent = (
        "recommend_payment_methods" if is_complete else "collect_profile"
    )

    params = {
        "intent": sub_intent,
        "merchant_context": ctx,
        "user_query": query,
    }
    result = registry.safe_execute("merchant_success", params)
    return {
        "intent": "merchant_success",
        "tool_name": "merchant_success",
        "tool_result": result,
        "trace": {
            "matched_keywords": matched,
            "sub_intent": sub_intent,
            "is_profile_complete": is_complete,
            "country": ctx.get("country"),
            "best_practice_filled": best_practice_filled,
        },
    }


def route_tra(query: str, ctx: dict, matched: list[str], registry: ToolRegistry) -> dict:
    """路由到 TRATool。

    自动选 intent（优先级从高到低）：
    1. ctx 含 ticket_id + 关闭关键词 → resolve_ticket（数字员工闭环第 5 段：关闭 + 自动沉淀 KB）
    2. query 中提到 ticket_id + 关闭关键词 → resolve_ticket（运营或客服主动关单）
    3. ctx 含 ticket_id → query_status（商户问现有工单状态）
    4. query 命中 query 关键词（"进度"/"状态"/"查询"等）→ query_status
    5. ctx 含 problem_type → route_ticket（典型 PDA → TRA 链）
    6. 都没有 → 默认 route_ticket（让 TRA 自己反问）

    Day 14 #9 修复：「工单进度怎么查」「查一下工单状态」等查询类 query 不再被错误地创建空工单。
    Day 17 v3 新增：resolve_ticket 子意图（关闭工单 + 自动沉淀 KB）。
    """
    if "ticket_routing" not in registry:
        return tool_not_available(
            "ticket_routing",
            hint="TRA Tool 未注册。如需立即处理，请联系人工客服。",
        )

    # === Day 17 v3：resolve_ticket 触发（优先级最高） ===
    resolve_matched = [k for k in _TRA_RESOLVE_KEYWORDS if k in query]
    if resolve_matched:
        # 从 query/ctx 提取 ticket_id
        ticket_id = ctx.get("ticket_id") or _extract_ticket_id_from_query(query)
        if ticket_id:
            sub_intent = "resolve_ticket"
            query_matched = resolve_matched
        else:
            # 没有 ticket_id → 降级为 query_status（让 TRA 友好提示）
            sub_intent = "query_status"
            query_matched = resolve_matched + ["no_ticket_id"]
            ticket_id = None
    elif ctx.get("ticket_id"):
        # 优先：商户明确提供 ticket_id（链式查询）
        sub_intent = "query_status"
        query_matched = []
    elif ctx.get("problem_type"):
        # 链式触发优先：PDA → TRA 这种 ctx 带 problem_type 的走 route_ticket
        sub_intent = "route_ticket"
        query_matched = []
    else:
        # 从 query 文本里查 query 关键词（不依赖 ctx）
        query_matched = [k for k in _TRA_QUERY_KEYWORDS if k in query]
        if query_matched:
            sub_intent = "query_status"
        else:
            sub_intent = "route_ticket"

    params = {
        "intent": sub_intent,
        "problem_type": ctx.get("problem_type"),
        "priority": ctx.get("priority", "medium"),
        "tier": ctx.get("tier", "standard"),
        "merchant_id": ctx.get("merchant_id"),
        "diagnosis_id": ctx.get("diagnosis_id"),
        "ticket_id": ctx.get("ticket_id") or (ticket_id if sub_intent == "resolve_ticket" else None),
    }
    # resolve_ticket 显式开 auto_promote
    if sub_intent == "resolve_ticket":
        params["auto_promote"] = True

    # 清理 None，让 Tool 自己的 schema 处理缺省
    params = {k: v for k, v in params.items() if v is not None}
    result = registry.safe_execute("ticket_routing", params)
    return {
        "intent": "ticket_routing",
        "tool_name": "ticket_routing",
        "tool_result": result,
        "trace": {
            "matched_keywords": matched,
            "sub_intent": sub_intent,
            "query_intent_matched": query_matched,  # 记录 query 命中的关键词
            "params": params,
        },
    }


def _extract_ticket_id_from_query(query: str) -> Optional[str]:
    """从 query 文本里用正则提取 tkt_xxx 形式的 ticket_id。

    Day 17 v3：「tkt_abc123 已解决」「关闭 tkt_abc123」之类的输入都能识别。
    """
    if not query:
        return None
    m = _TRA_TICKET_ID_RE.search(query)
    return m.group(1) if m else None


def route_kea(query: str, ctx: dict, matched: list[str], registry: ToolRegistry) -> dict:
    """路由到 KEATool。

    自动选 intent（优先级从高到低）：
    0. 命中审核关键词 + case_id → approve_case / reject_case（Day 17 v3 数字员工闭环第 5 段）
    1. ctx.case_id             → promote_to_faq （"这个案例能进FAQ吗"）
    2. ctx.query 显式传入      → search_faq     （商户直接搜 FAQ）
    3. query 命中 search 关键词 → search_faq    （"知识库怎么检索..."）
    4. 否则                    → list_candidates（让 KEA 列候选给商户看）
    """
    if "knowledge_evolution" not in registry:
        return tool_not_available(
            "knowledge_evolution",
            hint="KEA Tool 未注册。如需立即处理，请联系人工客服。",
        )

    # === Day 17 v3：人工审核命令识别（优先级最高，覆盖所有其他意图）===
    # 命令格式示例：
    #   "审核 case_001 通过" / "审核 case_001 拒绝"
    #   "✅ case_001"        / "❌ case_001"
    #   "approve case_001"   / "reject case_001"
    review_sub_intent, review_case_id = _detect_review_command(query)
    if review_sub_intent:
        params = {
            "intent": review_sub_intent,
            "case_id": review_case_id,
        }
        result = registry.safe_execute("knowledge_evolution", params)
        return {
            "intent": "knowledge_evolution",
            "tool_name": "knowledge_evolution",
            "tool_result": result,
            "trace": {
                "matched_keywords": matched,
                "sub_intent": review_sub_intent,
                "case_id": review_case_id,
                "review_command": True,
            },
        }

    if ctx.get("case_id"):
        sub_intent = "promote_to_faq"
        search_matched = []
    else:
        # 从 query 文本判断意图
        query_clean = (query or "").strip()
        # 去掉头部「知识库」/「FAQ」等提示词（避免误命中"知识"）
        for prefix in ("知识库", "FAQ", "faq"):
            if query_clean.startswith(prefix):
                query_clean = query_clean[len(prefix):].strip()
        search_matched = [k for k in _KEA_SEARCH_KEYWORDS if k in query_clean]
        if ctx.get("query") or search_matched:
            sub_intent = "search_faq"
        else:
            sub_intent = "list_candidates"

    # search_faq 时把原 query 写入 ctx.query（让 KEA 拿来做语义检索）
    if sub_intent == "search_faq" and not ctx.get("query"):
        ctx = {**ctx, "query": query}

    params = {
        "intent": sub_intent,
        "case_id": ctx.get("case_id"),
        "query": ctx.get("query") or query,
        "top_k": ctx.get("top_k", 5),
        "country": ctx.get("country"),
        "min_confidence": ctx.get("min_confidence", 0.85),
        "limit": ctx.get("limit", 20),
    }
    # 去掉 None，让 Tool schema 自行处理缺省
    params = {k: v for k, v in params.items() if v is not None}
    result = registry.safe_execute("knowledge_evolution", params)
    return {
        "intent": "knowledge_evolution",
        "tool_name": "knowledge_evolution",
        "tool_result": result,
        "trace": {
            "matched_keywords": matched,
            "sub_intent": sub_intent,
            "search_intent_matched": search_matched,  # 记录命中关键词
            "params": params,
        },
    }


def _detect_review_command(query: str) -> tuple[Optional[str], Optional[str]]:
    """检测人工审核命令，返回 (sub_intent, case_id)。

    支持的命令格式：
    - "审核 case_001 通过" / "审核 case_001 拒绝"
    - "审一下 case_001 通过" / "审批 case_001 不通过"
    - "✅ case_001"            / "❌ case_001"
    - "approve case_001"       / "reject case_001"

    Returns:
        ("approve_case", "case_001") / ("reject_case", "case_001") / (None, None)
    """
    if not query:
        return None, None
    q = query.strip()
    # 先看是否含 case_id
    m = _KEA_CASE_ID_RE.search(q)
    if not m:
        return None, None
    case_id = m.group(1)
    # 必须含审核关键词才算审核命令（避免 "case_001 是什么" 被误判）
    has_review_keyword = any(kw in q for kw in _KEA_REVIEW_KEYWORDS)
    if not has_review_keyword:
        return None, None
    # 判断 approve / reject
    if any(v in q for v in _KEA_APPROVE_VERBS):
        return "approve_case", case_id
    if any(v in q for v in _KEA_REJECT_VERBS):
        return "reject_case", case_id
    # 含审核关键词 + case_id 但没有明确 accept/reject 动词 → 不当作审核命令
    # 避免误操作（落到 list_candidates 而不是误审核）
    return None, None


def unknown_response(query: str, matched: list[str], registry: ToolRegistry) -> dict:
    """意图不明 → 兜底到 MSA collect_profile（让商户说出更多）。"""
    # 同时尝试 MSA 的 collect_profile（友好引导）
    if "merchant_success" in registry:
        result = registry.safe_execute("merchant_success", {
            "intent": "collect_profile",
            "merchant_context": {},
            "user_query": query,
        })
        return {
            "intent": "unknown_fallback_to_msa",
            "tool_name": "merchant_success",
            "tool_result": result,
            "trace": {
                "matched_keywords": matched,
                "fallback_reason": "no_keyword_match",
            },
        }

    # 兜底中的兜底（无 MSA 时）
    return {
        "intent": "unknown",
        "tool_name": None,
        "tool_result": {
            "success": False,
            "error_code": "INTENT_UNKNOWN",
            "error_message": (
                f"无法识别您的意图：「{query[:30]}」。"
                "请补充：支付失败（诊断）/ 选支付方式（推荐）/ 工单状态 / 知识查询。"
            ),
        },
        "trace": {"matched_keywords": matched},
    }
"""MSATool - 商户成功助手（OP 命题方向 ① + ④ · 含 PWR 子能力）。

两种 intent：
- recommend_payment_methods  推荐支付方式（PWR 子能力 · 命题方向 ①）
- collect_profile            采集商户画像（命题方向 ④ 数据协作）

设计：
- 复用 BaseRAGEngine + BaseLLMGateway（已 mock 降级）
- 画像完整性不足时主动反问（SOP-MSA-002）
- 复用 ChromaRAGEngine 已 seed 的 payment_methods_vec collection
"""

from __future__ import annotations

from typing import Optional

from app.interfaces.base_tool import BaseTool
from app.interfaces.base_rag import BaseRAGEngine
from app.interfaces.base_llm import BaseLLMGateway
from app.implementations.llm.qwen_gateway import MockLLMGateway
from app.implementations.rag.chroma_rag import COLLECTION_PAYMENT_METHODS


# === 画像完整性规则 ===

REQUIRED_PROFILE_FIELDS = ("country", "industry", "avg_amount", "target_users")
REVERSE_QUESTIONS = {
    "country":      "您想进入哪个国家的市场？（如 US / BR / CN）",
    "industry":     "您的行业是什么？（如 fashion / electronics / digital）",
    "avg_amount":   "您的客单价大约多少？（如 50 美元）",
    "target_users": "您的目标客户是 B2B 还是 B2C？",
}

# === Day 14 #4/#7 优化：ISO 国家码中文词典 ===
# 「荷兰」「墨西哥」等中文国家名 → ISO 3166-1 alpha-2 码
# Orchestrator 已能在 PDA 场景下识别（DAY 14 P0-2），MSA 之前没复用，导致
# "荷兰用什么支付方式" 进入 MSA 后 ctx.country 仍为空 → 触发反问采集，体验差。
_COUNTRY_NAME_TO_ISO = {
    # 常用国家（OP 服务覆盖范围内）
    "美国": "US", "美站": "US", "美国站": "US",
    "日本": "JP", "日本站": "JP",
    "英国": "GB", "英国站": "GB", "英站": "GB",
    "德国": "DE", "德国站": "DE", "德站": "DE",
    "法国": "FR", "法国站": "FR", "法站": "FR",
    "西班牙": "ES", "西班牙站": "ES",
    "意大利": "IT", "意大利站": "IT",
    "荷兰": "NL", "荷兰站": "NL",  # Day 14 #4
    "比利时": "BE", "比利时站": "BE",
    "瑞士": "CH", "奥地利": "AT", "瑞典": "SE", "挪威": "NO", "丹麦": "DK",
    "波兰": "PL", "捷克": "CZ", "葡萄牙": "PT", "希腊": "GR",
    "巴西": "BR", "巴西站": "BR",  # 主力市场
    "墨西哥": "MX", "墨西哥站": "MX",  # Day 14 #7
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

# 行业关键词（中文 → MSA 内部 industry 标识）
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

# 客户群体关键词
_TARGET_USERS_KEYWORDS = {
    "B2B": ["B2B", "b2b", "批发", "企业", "公司客户", "对公"],
    "B2C": ["B2C", "b2c", "零售", "个人", "消费者", "终端"],
}


class MSATool(BaseTool):
    """MSA Tool — 商户成功助手（命题方向 ① + ④ · 含 PWR 子能力）。

    复用：
    - BaseRAGEngine（默认 ChromaRAGEngine.payment_methods_vec）
    - BaseLLMGateway（默认 MockLLMGateway，Qwen 可降级）

    输入示例：
        {
            "intent": "recommend_payment_methods",
            "merchant_context": {
                "country": "US",
                "industry": "fashion",
                "avg_amount": 85.0,
                "target_users": "B2C"
            },
            "user_query": "我想做美国站"
        }

    输出示例：
        {
            "intent": "recommend_payment_methods",
            "response": "根据您做美国 B2C 时尚电商（客单价 $85）的画像...",
            "recommendations": [
                {"method": "Visa", "evidence_id": "pm_demo_visa_us_001", "rationale": "..."},
                ...
            ],
            "follow_up_questions": [],
            "profile_completeness": 1.0,
            "trace": {...}
        }
    """

    name = "merchant_success"
    description = (
        "MSA 商户成功助手：含 PWR（支付方式推荐）和画像采集两种能力。"
        "对位 OP 命题方向 ①（支付方式推荐）+ ④（数据协作采集）。"
        "输入 intent 决定行为：recommend_payment_methods 或 collect_profile。"
    )

    def __init__(
        self,
        rag: Optional[BaseRAGEngine] = None,
        llm: Optional[BaseLLMGateway] = None,
    ):
        self.rag = rag
        self.llm = llm or MockLLMGateway()
        # rag 默认懒加载（避免在 tests/conftest.py 阶段就启动 Chroma）

    def _ensure_rag(self) -> BaseRAGEngine:
        if self.rag is None:
            from app.implementations.rag.chroma_rag import ChromaRAGEngine
            self.rag = ChromaRAGEngine()
        return self.rag

    # === MCP tool_spec schemas ===

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["recommend_payment_methods", "collect_profile"],
                    "description": "意图：推荐支付方式 / 采集画像",
                },
                "merchant_context": {
                    "type": "object",
                    "description": "商户画像（recommend 时越完整越好；collect_profile 时可为部分）",
                    "properties": {
                        "merchant_id": {"type": "string"},
                        "country": {"type": "string", "minLength": 2, "maxLength": 2},
                        "industry": {"type": "string"},
                        "avg_amount": {"type": "number", "minimum": 0},
                        "target_users": {"type": "string", "enum": ["B2B", "B2C", "C2C"]},
                        "tier": {"type": "string"},
                    },
                },
                "user_query": {
                    "type": "string",
                    "description": "商户原始提问或当前轮消息",
                },
            },
            "required": ["intent", "user_query"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "response": {"type": "string", "description": "给商户的回复文本"},
                "recommendations": {
                    "type": "array",
                    "description": "推荐结果（仅 recommend_payment_methods）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string"},
                            "evidence_id": {"type": "string"},
                            "rationale": {"type": "string"},
                            "fee_rate": {"type": "string"},
                            "settlement": {"type": "string"},
                        },
                    },
                },
                "follow_up_questions": {
                    "type": "array",
                    "description": "追问列表（画像不完整时返回）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "question": {"type": "string"},
                        },
                    },
                },
                "profile_completeness": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "画像完整度 0-1",
                },
                "trace": {"type": "object"},
            },
            "required": ["intent", "response", "profile_completeness"],
        }

    @property
    def capabilities(self) -> dict:
        return {
            "async_supported": True,
            "idempotent": False,  # 商户对话有上下文
            "requires_auth": False,
        }

    # === 业务执行 ===

    def execute(self, params: dict) -> dict:
        intent = params["intent"]
        ctx = params.get("merchant_context") or {}
        query = params["user_query"]

        # Day 14 #4/#7：从 query 自动提取画像填充 ctx（不影响 ctx 已显式传入的字段）
        ctx = self._auto_fill_ctx(ctx, query)

        if intent == "recommend_payment_methods":
            return self._recommend_payment_methods(ctx, query)
        elif intent == "collect_profile":
            return self._collect_profile(ctx, query)
        else:
            raise ValueError(f"Unknown intent: {intent}")

    # === Day 14 #4/#7 优化：从 query 自动提取画像（country / industry / avg_amount / target_users）===

    def _extract_slots_from_query(self, query: str) -> dict:
        """从自然语言 query 中提取画像字段。

        提取策略（无 LLM，纯关键词 + 正则）：
        - country: 中文国家名 → ISO 2 位（"荷兰" → "NL"）
        - industry: 中文行业关键词 → MSA industry 标识
        - avg_amount: 数字 + "美元/欧/块/元" → 数值
        - target_users: B2B/B2C 关键词

        Returns:
            dict，只包含**确实提取到**的字段（缺失字段不出现在结果里）
        """
        import re

        slots: dict = {}
        q = (query or "").strip()
        if not q:
            return slots

        # 1. country：先中文词典，再 ISO 2 位直接命中
        for kw, iso in _COUNTRY_NAME_TO_ISO.items():
            if kw in q:
                slots["country"] = iso
                break
        if "country" not in slots:
            m = re.search(r"\b([A-Z]{2})\b", q)
            if m:
                slots["country"] = m.group(1)

        # 2. industry：第一个命中的行业标识
        for industry, kws in _INDUSTRY_KEYWORDS.items():
            if any(kw in q for kw in kws):
                slots["industry"] = industry
                break

        # 3. target_users：B2B vs B2C
        for tu, kws in _TARGET_USERS_KEYWORDS.items():
            if any(kw in q for kw in kws):
                slots["target_users"] = tu
                break

        # 4. avg_amount：「50 美元」「€80」「¥100」「100块」等
        if not slots.get("avg_amount"):
            m = re.search(r"(\d+(?:\.\d+)?)\s*(美元|美金|USD|usd|刀|元|RMB|rmb|欧|欧元|EUR|eur|€|¥|块)", q)
            if m:
                try:
                    slots["avg_amount"] = float(m.group(1))
                except ValueError:
                    pass
            else:
                # 纯数字 + 「客单价」
                m2 = re.search(r"客单价\s*(\d+(?:\.\d+)?)", q)
                if m2:
                    try:
                        slots["avg_amount"] = float(m2.group(1))
                    except ValueError:
                        pass
                else:
                    # 「客单价 €80」「客单价80 欧」格式
                    m3 = re.search(r"(\d+(?:\.\d+)?)\s*(?:欧|美元|元|美金)", q)
                    if m3:
                        try:
                            slots["avg_amount"] = float(m3.group(1))
                        except ValueError:
                            pass

        return slots

    def _auto_fill_ctx(self, ctx: dict, query: str) -> dict:
        """从 query 自动填充 ctx 缺失字段，返回新 ctx（不修改原对象）。

        Day 14 #4/#7：「荷兰用什么支付方式比较好」能从 query 抽出 NL 自动填 ctx.country，
        不再机械反问采集，体验好得多。
        """
        extracted = self._extract_slots_from_query(query)
        if not extracted:
            return ctx
        # ctx 已有字段优先（避免覆盖显式传入）
        merged = dict(ctx)
        for k, v in extracted.items():
            if not merged.get(k):
                merged[k] = v
        return merged

    # === 子能力 1：PWR（支付方式推荐） ===

    def _recommend_payment_methods(self, ctx: dict, query: str) -> dict:
        """PWR：检查画像完整性 → 完整则 RAG 推荐，否则主动反问。

        异常处理（SOP-MSA-002）：
        - 画像缺字段 → 返 follow_up_questions，不进入 RAG
        - RAG 检索抛异常 → 友好降级（recommendations 空，response 解释）
        """
        completeness, missing = self._profile_completeness(ctx)

        if missing:
            return {
                "intent": "recommend_payment_methods",
                "response": (
                    f"为了给您推荐最合适的支付方式，请先告诉我以下信息："
                    f"{'; '.join(REVERSE_QUESTIONS[f] for f in missing)}"
                ),
                "recommendations": [],
                "follow_up_questions": [
                    {"field": f, "question": REVERSE_QUESTIONS[f]} for f in missing
                ],
                "profile_completeness": completeness,
                "trace": {
                    "missing_fields": list(missing),
                    "rag_skipped": True,
                },
            }

        # 画像完整 → RAG 检索
        rag = self._ensure_rag()
        rag_query = f"{ctx.get('country', '')} {ctx.get('industry', '')} 支付方式"
        country_filter = {"country": ctx["country"]} if ctx.get("country") else None

        try:
            docs = rag.retrieve(
                rag_query,
                top_k=5,
                filter=country_filter,
                collection_name=COLLECTION_PAYMENT_METHODS,
            )
        except Exception as e:
            # RAG 失败 → 友好降级
            return {
                "intent": "recommend_payment_methods",
                "response": (
                    "抱歉，支付方式知识库暂时无法访问。"
                    "已记录您的问题，稍后人工回复。"
                    f"（trace: {e}）"
                ),
                "recommendations": [],
                "follow_up_questions": [],
                "profile_completeness": completeness,
                "trace": {"rag_error": str(e), "rag_degraded": True},
            }

        recommendations = []
        for doc in docs:
            recommendations.append({
                "method": doc.metadata.get("method", "Unknown"),
                "evidence_id": doc.id,
                "rationale": doc.text[:120],
                "fee_rate": doc.metadata.get("fee_rate"),
                "settlement": doc.metadata.get("settlement"),
            })

        # LLM 生成自然语言总结（Mock 降级 OK）
        summary = self._generate_summary(ctx, recommendations, query)

        return {
            "intent": "recommend_payment_methods",
            "response": summary,
            "recommendations": recommendations,
            "follow_up_questions": [],
            "profile_completeness": completeness,
            "trace": {
                "rag_results": len(docs),
                "llm_provider": type(self.llm).__name__,
            },
        }

    # === 子能力 2：采集画像 ===

    def _collect_profile(self, ctx: dict, query: str) -> dict:
        """根据当前 ctx 计算画像完整度 + 引导用户补全。"""
        completeness, missing = self._profile_completeness(ctx)

        if not missing:
            return {
                "intent": "collect_profile",
                "response": (
                    "您的画像已完整（国家 / 行业 / 客单价 / 目标用户），"
                    "可以开始诊断 / 推荐。"
                ),
                "recommendations": [],
                "follow_up_questions": [],
                "profile_completeness": 1.0,
                "trace": {"profile_complete": True},
            }

        return {
            "intent": "collect_profile",
            "response": (
                f"已记录您提供的信息（完整度 {completeness:.0%}）。"
                f"还差：{', '.join(missing)}"
            ),
            "recommendations": [],
            "follow_up_questions": [
                {"field": f, "question": REVERSE_QUESTIONS[f]} for f in missing
            ],
            "profile_completeness": completeness,
            "trace": {"missing_fields": list(missing)},
        }

    # === 工具方法 ===

    @staticmethod
    def _profile_completeness(ctx: dict) -> tuple[float, tuple[str, ...]]:
        """计算画像完整度，返回 (completeness, missing_fields)。

        评分：4 个核心字段（country / industry / avg_amount / target_users）
        每填一个 = 0.25，满分 1.0。

        Day 15 P0-A 修复：`not ctx.get(f)` 在 avg_amount=0 时误判为「缺失」
        （因为 `not 0 == True`）。改为严格 None/空串判断。
        """
        def _is_filled(v) -> bool:
            """值是否算「已填」——非 None 且非空串。
            注意：0 / 0.0 / False 都是有效值，不算缺失。"""
            return v is not None and v != ""
        filled = sum(1 for f in REQUIRED_PROFILE_FIELDS if _is_filled(ctx.get(f)))
        completeness = filled / len(REQUIRED_PROFILE_FIELDS)
        missing = tuple(f for f in REQUIRED_PROFILE_FIELDS if not _is_filled(ctx.get(f)))
        return completeness, missing

    def _generate_summary(self, ctx: dict, recommendations: list[dict], query: str) -> str:
        """LLM 生成自然语言总结。失败降级模板。"""
        prompt_messages = [{
            "role": "user",
            "content": (
                f"商户提问：{query}\n"
                f"商户画像：{ctx}\n"
                f"推荐支付方式：{recommendations}\n"
                f"请用 2-3 句话总结推荐理由。"
            ),
        }]
        try:
            return self.llm.chat(prompt_messages)
        except Exception:
            # LLM 失败 → 模板兜底
            methods = [r["method"] for r in recommendations[:3]]
            return (
                f"根据您{ctx.get('country', '?')} {ctx.get('industry', '?')} 画像，"
                f"推荐：{' / '.join(methods)}（共 {len(recommendations)} 种）。"
                "详见 recommendations 列表。"
            )
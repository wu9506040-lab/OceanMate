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

        if intent == "recommend_payment_methods":
            return self._recommend_payment_methods(ctx, query)
        elif intent == "collect_profile":
            return self._collect_profile(ctx, query)
        else:
            raise ValueError(f"Unknown intent: {intent}")

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
        """
        filled = sum(
            1 for f in REQUIRED_PROFILE_FIELDS
            if ctx.get(f) is not None and ctx.get(f) != ""
        )
        completeness = filled / len(REQUIRED_PROFILE_FIELDS)
        missing = tuple(f for f in REQUIRED_PROFILE_FIELDS if not ctx.get(f))
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
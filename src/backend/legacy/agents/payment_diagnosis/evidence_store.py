"""Evidence Store - 4 个证据源。

对接 OP 真实环境时：
- risk_rule       → OP 风控规则 API（当前：payment_error_cases.json）
- channel_status  → OP 通道监控 API（当前：JSON 模板）
- config_snapshot → OP merchant_config API（当前：JSON 模板）
- knowledge_base  → Chroma 向量库（真实：117 错误码 + 12 案例，Day 14 P0-1 接入）

仅替换查询实现，接口签名不变。
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from .schemas import EvidenceItem, ProblemRecord

logger = logging.getLogger(__name__)

# Demo 数据文件路径（指向 docs/data/，与文档一致）
# __file__ = ai-pioneer/src/backend/app/agents/payment_diagnosis/evidence_store.py
# parents[5] = ai-pioneer
_DEFAULT_DATA_PATH = Path(__file__).resolve().parents[5] / "docs" / "data" / "payment_error_cases.json"

# Day 14 P0-4：业务规则 —— 非卡组织渠道（本地支付 / 钱包）不涉及 3DS
NON_CARD_CHANNELS = {"Pix", "iDEAL", "UnionPay", "Klarna", "PayPal", "OXXO", "Boleto"}

# Day 14 P0-2：config 相关性关键词（避免把 3DS / webhook 配置塞进无关问题）
_CONFIG_3DS_KEYS = ("3ds", "sca", "secure")
_CONFIG_WEBHOOK_KEYS = ("webhook", "callback", "notify_url")


class EvidenceStore:
    """4 个证据源实现（前 3 个 JSON 占位 + 第 4 个真实向量库）。"""

    def __init__(self, data_path: Optional[Path] = None, rag_engine=None):
        self.data_path = data_path or _DEFAULT_DATA_PATH
        with open(self.data_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        # Day 14 P0-1：知识库检索引擎（懒加载，测试可注入 mock）
        self._rag = rag_engine
        self._rag_init_failed = False

    # ===== 证据源 1: 风控规则库 =====

    def lookup_risk_rule(self, error_code: str, country: str, channel: str) -> Optional[EvidenceItem]:
        """根据 error_code/country/channel 查找匹配的风控规则。

        Day 9 扩展：除 cases 外，还查 reason_codes（107 条真实 Visa/MC 拒付码）。
        优先 exact match；都 miss 则 None。
        """
        # 1) exact match in cases
        for case in self.data.get("cases", []):
            if (
                case["error_code"] == error_code
                and case["country"] == country
                and case["channel"] == channel
            ):
                return EvidenceItem(
                    type="risk_rule",
                    id=case["id"],
                    source="payment_error_database_demo",
                    description=case["rule_description"],
                )
        # 2) exact match in reason_codes (Visa/MC 真实拒付码)
        for rc in self.data.get("reason_codes", []):
            if (
                rc["error_code"] == error_code
                and (rc.get("country") == country or rc.get("country") == "GLOBAL")
                and (rc.get("channel") == channel or rc.get("channel") == "ANY")
            ):
                return EvidenceItem(
                    type="risk_rule",
                    id=rc["id"],
                    source="reason_code_public_reference",
                    description=(
                        f"{rc.get('rule_description', '')}。"
                        f"建议处理：{rc.get('recommended_action', '')}"
                    ),
                )
        # 3) 模糊匹配：仅按 error_code（cases 优先）
        for case in self.data.get("cases", []):
            if case["error_code"] == error_code:
                return EvidenceItem(
                    type="risk_rule",
                    id=case["id"],
                    source="payment_error_database_demo",
                    description=case["rule_description"] + "（模糊匹配 country/channel）",
                )
        # 4) 模糊匹配：reason_codes 仅按 error_code
        for rc in self.data.get("reason_codes", []):
            if rc["error_code"] == error_code:
                return EvidenceItem(
                    type="risk_rule",
                    id=rc["id"],
                    source="reason_code_public_reference",
                    description=(
                        f"{rc.get('rule_description', '')}。"
                        f"建议处理：{rc.get('recommended_action', '')}"
                    ),
                )
        return None

    # ===== 证据源 2: 通道状态库 =====

    def lookup_channel_status(self, country: str, channel: str) -> Optional[EvidenceItem]:
        """查找通道当前状态。"""
        for status in self.data.get("channel_status_templates", []):
            if status["country"] == country and status["channel"] == channel:
                return EvidenceItem(
                    type="channel_status",
                    id=status["id"],  # <channel_status_demo_xxx>
                    source="channel_logs_demo",
                    description=f"通道状态: {status['status']}, 成功率: {status['success_rate']}",
                )
        return None

    # ===== 证据源 3: 商户配置快照 =====

    def lookup_config_snapshot(
        self,
        country: str,
        channel: str = "",
        problem_type: str = "",
    ) -> List[EvidenceItem]:
        """查找商户配置（3DS、webhook 等）。

        Day 14 P0-2 相关性过滤（修复"巴西 Pix 延迟被推 3DS + example.com webhook"）：
        - 3DS 类配置：仅信用卡类渠道返回（Pix/iDEAL/UnionPay 等本地支付不涉及 3DS）
        - webhook 类配置：仅 Webhook / 回调类问题返回
        不传 channel / problem_type 时保持旧行为（向后兼容既有测试）。
        """
        items = []
        is_card_channel = bool(channel) and channel not in NON_CARD_CHANNELS
        is_webhook_problem = "webhook" in (problem_type or "").lower() or "回调" in (problem_type or "")

        for cfg in self.data.get("config_templates", []):
            if cfg["country"] != country and cfg["country"] != "GLOBAL":
                continue
            key = (cfg.get("config_key") or "").lower()

            # 过滤 1：3DS 配置只给卡组织渠道
            if channel and any(k in key for k in _CONFIG_3DS_KEYS) and not is_card_channel:
                logger.debug(f"[EvidenceStore] 跳过 3DS 配置（{channel} 是非卡渠道）: {cfg['id']}")
                continue
            # 过滤 2：webhook 配置只给 Webhook / 回调类问题
            if problem_type and any(k in key for k in _CONFIG_WEBHOOK_KEYS) and not is_webhook_problem:
                logger.debug(f"[EvidenceStore] 跳过 webhook 配置（问题类型={problem_type}）: {cfg['id']}")
                continue

            items.append(
                EvidenceItem(
                    type="config_snapshot",
                    id=cfg["id"],  # <config_demo_xxx>
                    source="merchant_config_demo",
                    description=f"{cfg['config_key']} = {cfg['config_value']} | {cfg['note']}",
                )
            )
        return items

    # ===== 证据源 4: 知识库向量检索（Day 14 P0-1）=====

    # 场景类关键词 → 走 cases_vec（案例库）而不是 error_codes_vec
    _SCENE_KEYWORDS = (
        "延迟", "慢", "不稳定", "时好时坏", "卡顿", "不到账", "到账慢",
        "周末", "凌晨", "高峰", "拥堵", "对账", "结算",
    )

    def _ensure_rag(self):
        """懒加载 Chroma 引擎；失败一次后不再重试（避免每次诊断都卡住）。"""
        if self._rag is not None or self._rag_init_failed:
            return self._rag
        try:
            from app.implementations.rag.chroma_rag import ChromaRAGEngine
            self._rag = ChromaRAGEngine()
        except Exception as e:
            logger.warning(f"[EvidenceStore] 知识库不可用，降级仅用 JSON 证据源: {e}")
            self._rag_init_failed = True
        return self._rag

    def pick_collections(self, problem: ProblemRecord) -> List[str]:
        """按 query 类型决定检索哪个 collection（P0-1 核心修复）。

        - 有真实 error_code            → error_codes_vec（错误码知识）
        - 场景类关键词命中             → cases_vec（案例知识）
        - 两者都有                     → 两个都查
        - 都没有但有 query_text        → cases_vec 兜底
        """
        from app.implementations.rag.chroma_rag import (
            COLLECTION_CASES, COLLECTION_ERROR_CODES, COLLECTION_FAQ,
        )
        cols = []
        has_code = bool(problem.error_code) and problem.error_code.upper() != "ERR_UNKNOWN"
        q = problem.query_text or ""
        is_scene = any(kw in q for kw in self._SCENE_KEYWORDS)

        if has_code:
            cols.append(COLLECTION_ERROR_CODES)
        if is_scene or not has_code:
            cols.append(COLLECTION_CASES)
        # FAQ（数据飞轮沉淀）永远参与召回
        cols.append(COLLECTION_FAQ)
        return cols

    @staticmethod
    def _is_relevant(meta: dict, problem: ProblemRecord) -> bool:
        """相关性门槛（P0-1）：召回文档必须与问题在国家/渠道/错误码上对得上。

        没有门槛的话，ZZ / UnknownChannel / 不存在的错误码也会召回一堆无关知识，
        LLM 拿到就开始编（Day 14 实测：ZZ 场景被编出「3DS 验证未开启」）。
        """
        meta = meta or {}
        m_country = (meta.get("country") or "").upper()
        m_channel = (meta.get("channel") or "").upper()
        m_code = (meta.get("error_code") or "").upper()
        p_country = (problem.country or "").upper()
        p_channel = (problem.channel or "").upper()
        p_code = (problem.error_code or "").upper()

        # 1) 错误码精确命中 → 强相关，直接通过
        if p_code and m_code and p_code == m_code:
            return True
        country_ok = bool(m_country) and (m_country == p_country or m_country == "GLOBAL")
        channel_ok = bool(m_channel) and (m_channel == p_channel or m_channel == "ANY")
        if not (country_ok and channel_ok):
            return False
        # 2) 文档本身是「GLOBAL + ANY」全通配（如 MC 4-digit 拒付码）→ 对谁都命中，
        #    此时若错误码又对不上，说明只是向量相似度巧合，不能当证据（否则 LLM 会编）
        if m_country == "GLOBAL" and m_channel == "ANY":
            return False
        return True

    def lookup_knowledge_base(
        self, problem: ProblemRecord, top_k: int = 3
    ) -> List[EvidenceItem]:
        """从 Chroma 检索真实知识作为证据（P0-1）。

        检索文本优先用商户原话（query_text），没有则用 country/channel/error_code 拼。
        召回后走 _is_relevant 过滤，防止无关知识被 LLM 拿去编造。
        """
        rag = self._ensure_rag()
        if rag is None:
            return []

        query = problem.query_text or " ".join(
            x for x in (problem.country, problem.channel, problem.error_code) if x
        )
        if not query.strip():
            return []

        items: List[EvidenceItem] = []
        seen_ids = set()
        for col in self.pick_collections(problem):
            try:
                docs = rag.retrieve(query, top_k=top_k, collection_name=col)
            except Exception as e:
                logger.warning(f"[EvidenceStore] 检索 {col} 失败: {e}")
                continue
            for doc in docs:
                if doc.id in seen_ids:
                    continue
                if not self._is_relevant(doc.metadata, problem):
                    logger.debug(f"[EvidenceStore] 丢弃不相关召回 {doc.id}（{doc.metadata}）")
                    continue
                seen_ids.add(doc.id)
                items.append(
                    EvidenceItem(
                        type="knowledge_base",
                        id=doc.id,
                        source=f"chroma:{col}",
                        description=(doc.text or "")[:400],
                    )
                )
        return items[:4]

    # ===== 一站式融合 =====

    def collect_evidence(
        self, problem: ProblemRecord, problem_type: str = ""
    ) -> List[EvidenceItem]:
        """收集所有证据（risk_rule → channel_status → knowledge_base → config_snapshot）。

        Day 14 P0-1：新增 knowledge_base（Chroma 真实检索）。
        Day 14 P0-2：config_snapshot 传 channel / problem_type 做相关性过滤。
        """
        evidence = []
        risk = self.lookup_risk_rule(problem.error_code, problem.country, problem.channel)
        if risk:
            evidence.append(risk)
        channel = self.lookup_channel_status(problem.country, problem.channel)
        if channel:
            evidence.append(channel)
        evidence.extend(self.lookup_knowledge_base(problem))
        evidence.extend(
            self.lookup_config_snapshot(problem.country, problem.channel, problem_type)
        )
        return evidence
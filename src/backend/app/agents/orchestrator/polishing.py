"""Day 16「像真人客服」对话打磨层（polishing）。

设计：4 个对话质量修复 ——
- Fix E: 告别语识别（不调 Tool，直接返短文本）
- Fix F: 去重派单（5 分钟内同 query 不重复 TRA）
- Fix G: 商户反驳识别（识别"不是的"+ 提取补充事实注入 ctx）
- Fix H: 同理心开头（紧急词触发诊断前加同理心短句）

调用方：FeishuWebhookHandler.handle_event（before orchestrator.route）

模块化：纯函数 + 模块级 SQLite 连接，便于单测。
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================
# Fix E: 告别语识别
# ============================================================

_FAREWELL_KEYWORDS = [
    # 中文
    "好的", "好的谢谢", "谢谢", "感谢", "辛苦了", "再见", "拜拜",
    "好的辛苦", "好的收到", "收到谢谢", "了解", "明白了", "知道了",
    # emoji
    "👌", "🙏", "👍", "😊", "😄", "🙂",
    # 英文
    "thanks", "thank you", "thx", "ok thanks", "ok thank you",
    "got it", "sounds good", "perfect", "great", "cool", "bye",
    "no problem", "np",
]


def is_farewell(query: str) -> bool:
    """检测是否是告别语。

    规则：query.strip() 长度 ≤ 15 且（所有词匹配关键词 / query 在关键词集合里）。
    例：'好的' → True；'好的我也觉得是13.1' → False（太长）
    """
    q = (query or "").strip()
    if not q or len(q) > 15:
        return False
    q_lower = q.lower()
    if q_lower in _FAREWELL_KEYWORDS:
        return True
    return any(kw in q_lower for kw in _FAREWELL_KEYWORDS if len(kw) >= 3)


# ============================================================
# Fix F: 去重派单（同 user_id+query hash 5 分钟内不重复）
# ============================================================

_DB_PATH = Path(__file__).resolve().parents[4] / "data" / "polishing.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_db_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    """懒加载 SQLite 连接（线程局部）。"""
    conn = sqlite3.connect(str(_DB_PATH), timeout=5)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS recent_tickets (
            user_id TEXT,
            query_hash TEXT,
            ticket_id TEXT,
            created_at REAL,
            PRIMARY KEY (user_id, query_hash)
        )"""
    )
    conn.commit()
    return conn


def _query_hash(query: str) -> str:
    """query 的归一化 hash（去空格 + 小写 + md5 前 8 位）。"""
    norm = "".join((query or "").lower().split())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


_DEDUP_WINDOW_SEC = 300  # 5 分钟


def lookup_recent_ticket(user_id: str, query: str) -> Optional[str]:
    """查 5 分钟内该 user 是否对该 query 已派过工单。

    Returns:
        ticket_id 或 None
    """
    if not user_id or not query:
        return None
    qhash = _query_hash(query)
    with _db_lock:
        try:
            conn = _get_db()
            cur = conn.execute(
                "SELECT ticket_id, created_at FROM recent_tickets WHERE user_id=? AND query_hash=?",
                (user_id, qhash),
            )
            row = cur.fetchone()
            if row:
                ticket_id, created_at = row
                if time.time() - created_at < _DEDUP_WINDOW_SEC:
                    logger.info(
                        f"[polishing] 去重命中: user={user_id[:12]} query_hash={qhash} "
                        f"ticket={ticket_id} (距今 {int(time.time()-created_at)}s)"
                    )
                    return ticket_id
            return None
        except Exception as e:
            logger.warning(f"[polishing] dedup lookup 失败: {e}")
            return None


def record_recent_ticket(user_id: str, query: str, ticket_id: str) -> None:
    """记录 user_id + query_hash → ticket_id（用于下次去重）。"""
    if not user_id or not query or not ticket_id:
        return
    qhash = _query_hash(query)
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "INSERT OR REPLACE INTO recent_tickets (user_id, query_hash, ticket_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, qhash, ticket_id, time.time()),
            )
            conn.commit()
            # 顺手清理过期记录（>1 小时）
            conn.execute(
                "DELETE FROM recent_tickets WHERE created_at < ?",
                (time.time() - 3600,),
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"[polishing] dedup record 失败: {e}")


# ============================================================
# Fix G: 商户反驳识别 + 补充事实注入
# ============================================================

_REBUTTAL_KEYWORDS = [
    # 反驳
    "不是的", "不是", "错的", "错了", "不对",
    "但是", "可是", "然而", "其实",
    "已经", "早就", "之前就",
    "我",  # 「我已经...」「我方...」弱信号
]

_FACT_INDICATORS = [
    # 商户在补充新事实的信号词
    "物流", "发货", "单号", "运单", "已签收", "签收",
    "凭证", "记录", "已发", "发了",
    "3DS", "认证", "已开", "开启了",
    "配置", "已配", "已设置",
    "沟通", "已联系", "联系过",
    "退款", "已退", "退了",
    "重新", "又",
]


def detect_rebuttal(query: str) -> bool:
    """检测商户是否在反驳/补充事实（区别于新问题）。

    规则：
    - 含反驳关键词（不是的/但是/其实/已经）
    - 且含事实信号词（物流/发货/凭证/已开...）
    - OR 长度 > 30 且含「已经/之前就」等已发生事实词
    """
    q = (query or "").strip()
    if not q:
        return False
    # 强反驳关键词：不是的/不是/错的/错了/不对/但是/可是/然而/其实
    strong_rebuttal = _REBUTTAL_KEYWORDS[:9]  # 强反驳前 9 个
    has_rebuttal = any(kw in q for kw in strong_rebuttal)
    has_fact = any(kw in q for kw in _FACT_INDICATORS)
    if has_rebuttal and has_fact:
        return True
    # 弱反驳 + 长 query（含「已经/之前就」等已发生事实词 + 长度 > 30）
    if len(q) > 30 and any(kw in q for kw in _REBUTTAL_KEYWORDS):
        return True
    return False


# ============================================================
# Fix H: 同理心开头
# ============================================================

_URGENT_KEYWORDS = [
    "紧急", "急", "急需", "赶紧", "马上", "尽快",
    "爆了", "好多", "很多", "太多", "爆炸", "严重",
    "影响", "影响很大", "快撑不住", "撑不住",
    "崩了", "挂了",
]


def has_urgent_signal(query: str) -> bool:
    """检测商户语气是否紧急。"""
    q = (query or "").strip()
    return any(kw in q for kw in _URGENT_KEYWORDS)


# ============================================================
# 主入口：polish_result（webhook 调用）
# ============================================================


@dataclass
class PolishResult:
    """Polishing 处理结果。"""

    # True 表示 query 是告别语，无需走 Orchestrator
    is_farewell: bool = False
    farewell_reply: Optional[str] = None

    # 5 分钟内同 user+query 已派过工单 → 跳链式 TRA
    recent_ticket_id: Optional[str] = None

    # 商户反驳 / 补充事实
    is_rebuttal: bool = False

    # 同理心信号 → 在 PDA 文字前加这段
    urgent_prepend: Optional[str] = None

    # 注入 ctx 的补充事实
    merchant_supplement: Optional[str] = None


def polish_query(query: str, *, user_id: Optional[str] = None) -> PolishResult:
    """对用户 query 做"像真人客服"的预处理。

    调用方：
        result = polish_query(query, user_id=user_id)
        if result.is_farewell:
            return farewell_reply
        if result.recent_ticket_id:
            # 5 分钟内同 query 已派过 → 不再重复派
            ...
        ctx["merchant_supplement"] = result.merchant_supplement
        ctx["urgent_prepend"] = result.urgent_prepend
    """
    p = PolishResult()

    # 1. Fix E: 告别语
    if is_farewell(query):
        p.is_farewell = True
        p.farewell_reply = (
            "🙌 不客气！您的工单我们正在跟进，"
            "有进展会第一时间通知您。如有新问题随时找我。"
        )
        return p

    # 2. Fix F: 去重派单
    if user_id:
        p.recent_ticket_id = lookup_recent_ticket(user_id, query)

    # 3. Fix G: 商户反驳
    if detect_rebuttal(query):
        p.is_rebuttal = True
        p.merchant_supplement = (
            "⚠️ 商户补充：商户对诊断结论有补充意见（'不是的/但是'类）"
            f"，请基于以下 query 重新审视根因：\n{query}\n"
            "（建议：保留核心 evidence，但 root_causes/actions 可调整方向）"
        )

    # 4. Fix H: 同理心信号
    if has_urgent_signal(query):
        p.urgent_prepend = (
            "🤝 我理解您很着急——这类情况对商户现金流影响很大。"
            "我立刻为您深度分析 + 派单到对应团队：\n\n"
        )

    return p
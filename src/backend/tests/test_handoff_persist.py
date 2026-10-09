"""Day 19 M15：人工交接落 handoffs 表测试（webhook._persist_handoff）。

背景：审计发现 handoffs 表与 HandoffRepository 存在但零调用方——交接只发私信无台账。
本测试锁定三件事：
- HP-1 交接成功后 conversations（父会话补建）与 handoffs 各 1 行，字段正确
- HP-2 同 chat 重复交接：conversation 不重复、handoff 各自成行（多人交接是常态）
- HP-3 FK 顺序正确不因外键约束整条失败（先父会话后工单）
"""
import sqlite3
from unittest.mock import MagicMock

import pytest

from app.implementations.feishu.webhook import FeishuWebhookHandler
from app.implementations import opa_metrics

DDL = [
    """CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_msg_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'active', merchant_id TEXT, tool_name TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS handoffs (
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
        agent_id TEXT, reason TEXT, briefing TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved_at DATETIME,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    )""",
]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    p = tmp_path / "oceanmate.db"
    conn = sqlite3.connect(p)
    for d in DDL:
        conn.execute(d)
    conn.commit()
    conn.close()
    # _persist_handoff 在调用期读取模块属性 → monkeypatch 生效
    monkeypatch.setattr(opa_metrics, "DEFAULT_DB_PATH", p)
    return p


def _handler():
    return FeishuWebhookHandler(orchestrator=MagicMock(), frontend=MagicMock())


def _rows(p, sql):
    conn = sqlite3.connect(p)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class TestPersistHandoff:

    def test_hp1_persists_conversation_and_handoff(self, tmp_db):
        h = _handler()
        h._persist_handoff(
            {"problem_type": "拒付", "merchant_id": "M001"},
            chat_id="oc_test_1", team="争议处理组", briefing_text="简报正文",
        )
        convs = _rows(tmp_db, "SELECT id, user_id FROM conversations")
        hfts = _rows(tmp_db, "SELECT conversation_id, agent_id, reason FROM handoffs")
        assert convs == [("oc_test_1", "M001")]
        assert hfts == [("oc_test_1", "争议处理组", "拒付")]

    def test_hp2_repeat_same_chat_adds_handoff_only(self, tmp_db):
        h = _handler()
        b = {"problem_type": "支付失败"}
        h._persist_handoff(b, chat_id="oc_dup", team="技术组", briefing_text="t1")
        h._persist_handoff(b, chat_id="oc_dup", team="技术组", briefing_text="t2")
        assert len(_rows(tmp_db, "SELECT * FROM conversations")) == 1
        assert len(_rows(tmp_db, "SELECT * FROM handoffs")) == 2

    def test_hp3_fk_violation_none_swallowed(self, tmp_db):
        # briefing 缺 merchant_id → user_id 回退 chat_id；不应抛（best-effort）
        h = _handler()
        h._persist_handoff({}, chat_id="oc_min", team="通用", briefing_text="")
        assert len(_rows(tmp_db, "SELECT * FROM handoffs WHERE conversation_id='oc_min'")) == 1

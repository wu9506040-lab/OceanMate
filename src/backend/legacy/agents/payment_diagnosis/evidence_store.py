"""Evidence Store - 3 个证据源（Demo 占位实现）。

对接 OP 真实环境时：
- risk_rule → OP 风控规则 API
- channel_status → OP 通道监控 API
- config_snapshot → OP merchant_config API

仅替换查询实现，接口签名不变。
"""

import json
from pathlib import Path
from typing import List, Optional

from .schemas import EvidenceItem, ProblemRecord

# Demo 数据文件路径（指向 docs/data/，与文档一致）
# __file__ = ai-pioneer/src/backend/app/agents/payment_diagnosis/evidence_store.py
# parents[5] = ai-pioneer
_DEFAULT_DATA_PATH = Path(__file__).resolve().parents[5] / "docs" / "data" / "payment_error_cases.json"


class EvidenceStore:
    """3 个证据源 mock 实现。"""

    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = data_path or _DEFAULT_DATA_PATH
        with open(self.data_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    # ===== 证据源 1: 风控规则库 =====

    def lookup_risk_rule(self, error_code: str, country: str, channel: str) -> Optional[EvidenceItem]:
        """根据 error_code/country/channel 查找匹配的风控规则。"""
        for case in self.data["cases"]:
            if (
                case["error_code"] == error_code
                and case["country"] == country
                and case["channel"] == channel
            ):
                return EvidenceItem(
                    type="risk_rule",
                    id=case["id"],  # <risk_rule_demo_xxx> 占位符
                    source="payment_error_database_demo",
                    description=case["rule_description"],
                )
        # 模糊匹配：仅按 error_code
        for case in self.data["cases"]:
            if case["error_code"] == error_code:
                return EvidenceItem(
                    type="risk_rule",
                    id=case["id"],
                    source="payment_error_database_demo",
                    description=case["rule_description"] + "（模糊匹配 country/channel）",
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

    def lookup_config_snapshot(self, country: str) -> List[EvidenceItem]:
        """查找商户配置（3DS、webhook 等）。"""
        items = []
        for cfg in self.data.get("config_templates", []):
            if cfg["country"] == country or cfg["country"] == "GLOBAL":
                items.append(
                    EvidenceItem(
                        type="config_snapshot",
                        id=cfg["id"],  # <config_demo_xxx>
                        source="merchant_config_demo",
                        description=f"{cfg['config_key']} = {cfg['config_value']} | {cfg['note']}",
                    )
                )
        return items

    # ===== 一站式融合 =====

    def collect_evidence(self, problem: ProblemRecord) -> List[EvidenceItem]:
        """收集所有证据（按 risk_rule → channel_status → config_snapshot 顺序）。"""
        evidence = []
        risk = self.lookup_risk_rule(problem.error_code, problem.country, problem.channel)
        if risk:
            evidence.append(risk)
        channel = self.lookup_channel_status(problem.country, problem.channel)
        if channel:
            evidence.append(channel)
        evidence.extend(self.lookup_config_snapshot(problem.country))
        return evidence
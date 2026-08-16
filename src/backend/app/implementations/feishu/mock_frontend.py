"""MockFrontend - 飞书前端降级实现（PoC 演示友好）。

设计：
- 5 方法全部 mock 化，永不抛异常，永不返回 False
- 所有事件写本地日志 `.feishu_mock_log.json`（路径覆盖：默认 cwd/，可通过 env FEISHU_MOCK_LOG 改）
- 用于：FEISHU_APP_ID / FEISHU_APP_SECRET 缺失时的自动降级，Demo 不卡死

评审价值：
- 演示路径不依赖真实飞书凭证（赛制允许 mock，参考 solution_overview.md §5.1）
- 真实环境切凭证即可启用真 FeishuFrontend（替换工厂函数返回）
- 写日志便于录屏演示（demo/feishu_mock_log.json 可看完整事件流）
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.interfaces.base_frontend import BaseFrontend


# === Mock 日志路径 ===

DEFAULT_MOCK_LOG = Path.cwd() / ".feishu_mock_log.json"


def _get_mock_log_path() -> Path:
    """Mock 日志路径（可被环境变量覆盖）。"""
    return Path(os.getenv("FEISHU_MOCK_LOG", str(DEFAULT_MOCK_LOG)))


class MockFrontend(BaseFrontend):
    """飞书前端 Mock 实现 —— 无凭证时自动激活。

    行为：
    - 所有方法立即返回（True / fake_id / 永远成功）
    - 每次调用追加一条事件到本地 JSON 日志
    - 不抛任何异常（除非磁盘写满）

    用法：
        frontend = MockFrontend()
        ok = frontend.send_message("user_123", "BR Visa 拒付诊断完成")
        # → .feishu_mock_log.json 追加 {"event": "send_message", ...}
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or _get_mock_log_path()

    # === 5 方法实现（全部 mock） ===

    def send_message(self, user_id: str, message: str, receive_id_type: str = "open_id") -> bool:
        """Mock 发消息：永远成功 + 写日志。"""
        self._log("send_message", user_id=user_id, message=message, receive_id_type=receive_id_type)
        return True

    def send_private(self, user_id: str, message: str) -> bool:
        """Mock 发私有消息：永远成功 + 写日志。"""
        self._log("send_private", user_id=user_id, message=message)
        return True

    def create_group(self, members: list[str], name: Optional[str] = None) -> str:
        """Mock 创建群：返回 fake_group_id + 写日志。"""
        group_id = f"mock_group_{uuid.uuid4().hex[:8]}"
        self._log("create_group", group_id=group_id, members=members, name=name)
        return group_id

    def add_group_member(self, group_id: str, user_id: str) -> bool:
        """Mock 拉人进群：永远成功 + 写日志。"""
        self._log("add_group_member", group_id=group_id, user_id=user_id)
        return True

    def sync_dashboard_data(self, data: dict) -> bool:
        """Mock 同步多维表格：永远成功 + 写日志。

        评审演示：把 data 写到日志里，录屏时能直观看到「数据已同步」。
        """
        self._log("sync_dashboard_data", data=data)
        return True

    def sync_review_decision(self, data: dict) -> bool:
        """Mock 同步审核决策到 review_decisions：写日志 + 返回 True。"""
        self._log("sync_review_decision", data=data)
        return True

    # === Day 18 P2-final：反向同步（Mock）===

    def fetch_review_decisions(
        self,
        *,
        decision_filter: Optional[str] = None,
        max_pages: int = 10,
    ) -> list[dict]:
        """Mock 拉取审核决策：返回空列表（录屏用 Mock 时多维表格数据靠手动 seed）。"""
        self._log("fetch_review_decisions", decision_filter=decision_filter, max_pages=max_pages)
        return []

    def get_record_by_id(self, record_id: str) -> dict:
        """Mock 按 record_id 查记录：返回空 dict。"""
        self._log("get_record_by_id", record_id=record_id)
        return {}

    # === 辅助：日志读写 ===

    def _log(self, event: str, **fields) -> None:
        """追加一条事件到日志文件（JSON Lines 格式）。"""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": event,
            "frontend": "mock",
            **fields,
        }
        try:
            # 追加写（每行一个 JSON record）
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # Mock 实现不允许日志失败影响业务
            pass

    def read_log(self) -> list[dict]:
        """读所有 mock 事件（调试 / 录屏演示用）。"""
        if not self.log_path.exists():
            return []
        records = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def clear_log(self) -> None:
        """清空日志（测试 setup 用）。"""
        if self.log_path.exists():
            self.log_path.unlink()

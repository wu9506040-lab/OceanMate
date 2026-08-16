"""BaseFrontend - 飞书前端抽象接口。

6 个核心方法（商户交互 + 客服协同 + 运营看板 + 错误码配图）：
- send_message()        发消息给商户
- send_private()        发私有消息（仅指定用户可见，如交接简报）
- send_image()          发图片（错误码配图、dashboard 截图等）—— Day 9 新增
- create_group()        创建群聊
- add_group_member()    拉人进群
- sync_dashboard_data() 同步运营数据到多维表格

实现层：app/implementations/feishu/api.py（Day 6-7 写 + Day 9 加 send_image）
SOP：SOP-FEISHU-001（4 个逆向场景：API 超时/JSON 错/唯一键冲突/Chroma 失败）
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseFrontend(ABC):
    """飞书前端基类。

    评审意义：未来切换前端（飞书 → 微信/企业微信/Slack）只需换实现。
    """

    @abstractmethod
    def send_message(self, user_id: str, message: str) -> bool:
        """给用户发消息（公开消息，群聊可见）。

        Args:
            user_id: 用户 ID（飞书 open_id）
            message: 消息内容

        Returns:
            True 成功 / False 失败
        """

    def send_image(self, user_id: str, image_path: str) -> bool:
        """发图片（错误码配图 / dashboard 截图等）。

        Args:
            user_id: 接收者 ID
            image_path: 本地图片路径（PNG/JPG）

        Returns:
            True 成功 / False 失败

        默认实现：Mock/无图片时不发，返回 True（PoC 兜底）。真实 FeishuFrontend 覆盖。
        """
        # 默认 no-op：子类可覆盖
        return True

    @abstractmethod
    def send_private(self, user_id: str, message: str) -> bool:
        """发私有消息（仅指定用户可见）。

        用途：人工交接简报发给客服，商户看不到。

        Args:
            user_id: 接收者 ID
            message: 消息内容

        Returns:
            True 成功 / False 失败
        """

    @abstractmethod
    def create_group(self, members: list[str], name: Optional[str] = None) -> str:
        """创建群聊。

        Args:
            members: 成员 ID 列表
            name: 群名（可选）

        Returns:
            群 ID

        Raises:
            RuntimeError: 创建失败
        """

    @abstractmethod
    def add_group_member(self, group_id: str, user_id: str) -> bool:
        """拉人进群（人工介入时用）。

        Args:
            group_id: 群 ID
            user_id: 用户 ID

        Returns:
            True 成功 / False 失败
        """

    @abstractmethod
    def sync_dashboard_data(self, data: dict) -> bool:
        """同步运营数据到多维表格。

        Args:
            data: {"metric": "ticket_count", "value": 123, "timestamp": "..."}

        Returns:
            True 成功 / False 失败
        """

    def sync_review_decision(self, data: dict) -> bool:
        """同步审核决策到多维表格（Day 18 P1-final · 知识沉淀可视化）。

        用途：T6.1 运营审核通过 / 自动入审时，把决策记录写入多维表格
        `review_decisions` 表，让录屏可以现场展示真实数据飞轮。

        Args:
            data: {
                "case_id": "case_xxx",
                "decision": "approved" | "rejected" | "auto_promoted",
                "reviewer": "lead" | "auto",
                "decided_at": "2026-08-16T02:30:00",
                "problem_type": "拒付",
                "confidence": 0.85,
                "ticket_id": "tkt_xxx" (optional),
            }

        Returns:
            True 成功 / False 失败

        默认实现：NoOp（Mock/单元测试不写多维表格）。真实 FeishuFrontend 覆盖。
        """
        # 默认 no-op：子类可覆盖
        return True

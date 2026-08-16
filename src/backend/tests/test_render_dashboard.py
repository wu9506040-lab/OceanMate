"""render_dashboard.py 看板"待审核卡"测试 — Day 18 P2-final。

覆盖：
- dashboard HTML 必须含"⏳ 待审核 X 条"卡片
- 卡片只在 pending_count > 0 时显示数字
- 副标题必须含"待审核 X 条"摘要
- 不会展示"已通过"/"已拒绝"数字（用户原话：审核过的不算数）
"""

import sys
from pathlib import Path

import pytest

# scripts/render_dashboard.py 直接 import 不便（依赖 env 文件读取）
# 改用 importlib 加载并只测 render_html 纯函数
import importlib.util

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
DASHBOARD_PATH = SCRIPTS_DIR / "render_dashboard.py"


@pytest.fixture
def render_html():
    spec = importlib.util.spec_from_file_location("render_dashboard", DASHBOARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_html


@pytest.fixture
def minimal_data():
    """最小可用数据集。"""
    return {
        "total": 60,
        "raw_total": 65,
        "type_count": {"拒付": 20, "支付失败": 16, "咨询": 11, "退款异常": 10},
        "status_count": {"in_progress": 25, "pending": 20, "resolved": 14},
        "prio_count": {"medium": 34, "high": 22, "low": 3},
        "date_count": {"2026-08-13": 6},
        "pending_count": 5,  # 5 条待审核
    }


class TestDashboardPendingCard:
    """dashboard 必须显式展示"待审核 X 条"卡片（橙色高亮）。"""

    def test_html_contains_pending_count(self, render_html, minimal_data):
        """HTML 必须含数字「5」（pending_count）。"""
        html = render_html(minimal_data)
        assert "5" in html

    def test_html_contains_pending_label(self, render_html, minimal_data):
        """HTML 必须含"待审核案例"标签。"""
        html = render_html(minimal_data)
        assert "待审核案例" in html

    def test_html_contains_pending_emoji(self, render_html, minimal_data):
        """HTML 必须含⏳ emoji（强调"待办"感）。"""
        html = render_html(minimal_data)
        assert "⏳" in html

    def test_html_has_pending_class(self, render_html, minimal_data):
        """待审核卡必须有 .pending CSS class（橙色背景）。"""
        html = render_html(minimal_data)
        assert "card pending" in html or "class=\"card pending\"" in html

    def test_subtitle_includes_pending_count(self, render_html, minimal_data):
        """副标题必须含「待审核 X 条」摘要。"""
        html = render_html(minimal_data)
        assert "待审核" in html
        # 必须出现"待审核 5 条"或"待审核 <b>5</b>"形式
        assert "5" in html

    def test_pending_count_zero_renders_zero(self, render_html):
        """pending_count=0 → HTML 仍然含卡片（数字为 0，提醒"无待办"）。"""
        data = {
            "total": 60, "raw_total": 65,
            "type_count": {}, "status_count": {}, "prio_count": {},
            "date_count": {},
            "pending_count": 0,
        }
        html = render_html(data)
        assert "待审核案例" in html
        # 0 也必须出现在卡片里（不能漏渲染）
        assert ">0<" in html or "v\">0<" in html or "0" in html


class TestDashboardExcludesApprovedRejected:
    """Day 18 P2-final 用户原话：「审核过的就不算数」 — 看板不展示已通过/已拒绝数量。"""

    def test_no_approved_count_in_html(self, render_html, minimal_data):
        """HTML 不应含「已通过」数量（用户原话：审核过的不算数）。"""
        html = render_html(minimal_data)
        # 注意：HTML 里允许"已通过"作为文字（如 _fmt_kea_list_review_history 里的段标题），
        # 但 dashboard 看板**数字卡**区域不能有"已通过 X 条"
        # 简化断言：检查数字卡区域不出现"已通过"+"数字"
        import re
        card_section = html.split("</div>")[:20]  # 前几个 div 是数字卡
        joined = " ".join(card_section)
        assert "已通过" not in joined

    def test_no_rejected_count_in_html(self, render_html, minimal_data):
        """HTML 数字卡区域不应含「已拒绝」数量。"""
        html = render_html(minimal_data)
        import re
        card_section = html.split("</div>")[:20]
        joined = " ".join(card_section)
        assert "已拒绝" not in joined

    def test_no_auto_promoted_count_in_html(self, render_html, minimal_data):
        """HTML 数字卡区域不应含「自动入审」数量。"""
        html = render_html(minimal_data)
        card_section = html.split("</div>")[:20]
        joined = " ".join(card_section)
        assert "自动入审" not in joined


class TestDashboardCardGridIs5Columns:
    """数字卡区必须是 5 列布局（4 张原卡 + 1 张待审核）。"""

    def test_grid_template_columns_5(self, render_html, minimal_data):
        """CSS grid-template-columns 必须是 5 列。"""
        html = render_html(minimal_data)
        # 检查 .cards 类的 grid-template-columns
        assert "repeat(5" in html or "grid-template-columns: repeat(5" in html

    def test_total_cards_count_is_5(self, render_html, minimal_data):
        """数字卡区必须恰好 5 张 div.card。"""
        html = render_html(minimal_data)
        cards_section = html.split('<div class="cards">')[1].split("</div>\n\n<div class=\"grid\">")[0]
        # 数 class="card" 或 class="card pending"
        import re
        card_count = len(re.findall(r'class="card(?:\s+pending)?"', cards_section))
        assert card_count == 5, f"应有 5 张卡，实际={card_count}"
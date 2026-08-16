# docs/runbook/ 目录说明

> **目的**：runbook 是 OceanMate 运营 / 交付 / 演示材料汇集点（含 dashboard 配置、真实终端输出、截图）。

## 📷 截图真伪清单（第一性原则 · 必读）

| 文件 | 真/假 | 用途 | 说明 |
|------|------|------|------|
| `dashboard_screenshot.png` | ✅ **真截图** | 提交材料 · 体现数据飞轮 | 由 `dashboard_preview.html` Playwright 渲染，**数据来自真实飞书多维表格**（有效工单/覆盖天数/活跃团队等是真实查询结果） |
| `feishu_chat_screenshot.png` | ⚠️ **程序化 mock** | 文档配图 · 演示形态 | 由 `src/backend/scripts/render_demo_screenshots.py` 生成（HTML mock，非真实飞书对话截图） |
| `diagnosis_screenshot.png` | ⚠️ **程序化 mock** | 文档配图 · 演示形态 | 同上（展示 PDA 诊断结果结构，但内容是 mock） |

**评审要点**：
- dashboard 是**真数据截图**（Playwright 渲染 live bitable API）
- 其余 2 张是**产品形态示意图**（用于静态文档 / 演示，非真实飞书界面）
- 真实对话与诊断：**请看 demo 视频**（录屏脚本 `demo/recordings/main_demo_script.md`），视频为真实飞书 + 真实多维表格

## 📁 文件清单

| 文件 | 内容 |
|------|------|
| `dashboard_config_guide.md` | 运营如何在飞书多维表格里配 dashboard |
| `dashboard_preview.html` | 渲染 dashboard_screenshot.png 的源 HTML（实时数据） |
| `dashboard_screenshot.png` | 真实 dashboard 截图 |
| `feishu_chat_screenshot.png` | mock — 飞书智能伙伴对话示意图 |
| `diagnosis_screenshot.png` | mock — 诊断结果示意图 |
| `day15_*.txt` / `day15_real_terminal_outputs.md` | Day 15 真实 11 个 case 终端输出 |
| `feishu_ai_field_setup.md` | 飞书 AI 字段配置说明 |
| `rebuild_bitable_in_feishu.md` | 多维表格重建步骤 |
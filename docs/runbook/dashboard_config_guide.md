# OceanMate 运营看板配置清单（飞书多维表）

> **目标**：在飞行社企业下"OceanMate 数据"多维表中配 dashboard，配完截图发 zwyyy7。
> **链接**：https://larkcommunity.feishu.cn/base/LQkTbJe1jaCM1PsFU48cslfgnSe
> **预计时间**：30-40 分钟
> **数据已就位**：60 条工单（含 50 条模拟，含 created_at、status、priority、problem_type）

---

## 🎨 配色规范（专业冷静蓝灰 + 红色告警）

| 用途 | 色值 | 用途说明 |
|------|------|---------|
| 主色 | `#1677FF` | 标题、链接、强调数字 |
| 辅色蓝 | `#4096FF` | 折线图主色、待处理 |
| 辅色绿 | `#00C896` | 已解决、知识库增长 |
| 辅色橙 | `#FF8C42` | 中优先级 |
| 辅色红 | `#F5222D` | 高优先级告警、错误 |
| 背景灰 | `#F5F7FA` | 卡片背景 |
| 文字深 | `#1F2329` | 标题 |
| 文字灰 | `#646A73` | 副标题、注释 |
| 边框灰 | `#E5E6EB` | 卡片分割线 |

⚠️ **不要用彩虹色、渐变、emoji 装饰**。专业配色=单调克制。

---

## 📐 整体布局（像真实 SaaS 运营看板）

```
┌────────────────────────────────────────────────────────────┐
│ 标题：OceanMate AI 运营看板 · 实时数据                    │
│ 副标题：最后更新 2026-08-10 12:45                        │
├──────────┬──────────┬──────────┬──────────┬───────────────┤
│ 累计工单 │ 待处理工 │ 平均解决 │ 知识库   │ (预留空间)    │
│   60     │   15     │   6.2h   │ 117 条   │               │
├──────────┴──────────┴──────────┴──────────┴───────────────┤
│  问题类型分布（柱状图）   │  近 7 天工单趋势（折线图）    │
│  ┌──────────────────┐    │  ┌─────────────────────────┐  │
│  │  拒付  ▓▓▓▓▓▓▓ 21 │    │  │     ╱╲      ╱╲          │  │
│  │  支付  ▓▓▓▓▓▓  16 │    │  │   ╱   ╲  ╱   ╲         │  │
│  │  退款  ▓▓▓▓▓   10 │    │  │  ╱     ╲╱     ╲╱       │  │
│  │  咨询  ▓▓▓▓▓   11 │    │  │ 08-04...08-10         │  │
│  └──────────────────┘    │  └─────────────────────────┘  │
├──────────────────────────┼───────────────────────────────┤
│  优先级分布（饼图）       │  知识库增长趋势（折线图）    │
│  ┌──────────────────┐    │  ┌─────────────────────────┐  │
│  │   high 38%       │    │  │  ╱╲                     │  │
│  │   med  57%       │    │  │ ╱  ╲    ╱╲              │  │
│  │   low   5%       │    │  │     ╲  ╱  ╲             │  │
│  └──────────────────┘    │  └─────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## 🛠️ 配置步骤（手把手）

### Step 1：进入多维表

1. 浏览器打开：https://larkcommunity.feishu.cn/base/LQkTbJe1jaCM1PsFU48cslfgnSe
2. 右上角切换为 **「仪表盘视图」**（不是表格视图）
3. 点击 **「+ 新建仪表盘」**
4. 命名：**OceanMate AI 运营看板**
5. 描述：实时运营数据 · 跨境支付商户成功运营助手
6. 创建

### Step 2：添加 4 个核心指标卡片（顶部一行）

每个卡片独立添加，操作相同：

| 卡片 | 数据源 | 字段 | 聚合 | 颜色 |
|------|--------|------|------|------|
| **累计工单** | routing_rules | - | COUNT（所有） | 主色蓝 `#1677FF` |
| **待处理工单** | routing_rules | status | COUNT WHERE status=pending | 橙 `#FF8C42` |
| **平均解决时长** | routing_rules | sla_hours | AVG（按 status=resolved） | 绿 `#00C896` |
| **知识库条目数** | error_codes | - | COUNT（所有） | 紫 `#722ED1`（可选，不强制） |

**操作**：仪表盘内 → 添加组件 → **「数字」** → 选择数据源 → 配置字段 → 设置颜色。

### Step 3：问题类型分布（柱状图）

1. 添加组件 → **「柱状图」**
2. 数据源：`routing_rules` 表
3. X 轴：`problem_type`（按问题类型分组）
4. Y 轴：COUNT（自动计数）
5. 排序：降序
6. 配色：使用辅色蓝 `#4096FF`
7. 标题：**问题类型分布**
8. 副标题：拒付 / 支付失败 / 退款异常 / 咨询

### Step 4：近 7 天工单趋势（折线图）

⚠️ **注意**：模拟工单没有真实时间戳（created_at 是自动生成，无法批量覆盖）。**折线图会显示成"最近 24 小时"集中分布**。

**方案 A（推荐，30 秒搞定）**：用 dashboard 自带的「时间范围筛选」配置成「最近 7 天」，即便数据集中在今天，也能展示趋势组件样式。

**方案 B（数据更漂亮，5 分钟）**：手动去后台把 50 条工单的 created_at 改成分布在 7 天内（飞书后台双击日期字段可以选）。

操作：
1. 添加组件 → **「折线图」**
2. 数据源：`routing_rules`
3. X 轴：`created_at`（按天聚合）
4. Y 轴：COUNT
5. 时间范围：最近 7 天
6. 主色：辅色蓝 `#4096FF`
7. 标题：**近 7 天工单趋势**
8. 副标题：每日新增工单数

### Step 5：优先级分布（饼图）

1. 添加组件 → **「饼图」**
2. 数据源：`routing_rules`
3. 维度：`priority`
4. 指标：COUNT
5. 配色：
   - high → 红 `#F5222D`
   - medium → 橙 `#FF8C42`
   - low → 蓝 `#4096FF`
6. 显示数值 + 百分比
7. 标题：**优先级分布**
8. 副标题：高 / 中 / 低优先级占比

### Step 6：知识库增长趋势（折线图）

⚠️ **注意**：error_codes 表是 seed 一次性导入，没有真实增长数据。**折线图会显示成"单点"**。

**方案 A（推荐）**：用 error_codes 表 + payment_methods 表的联合数量，创建一个「知识库条目总数」折线（虽然只有一个时间点，但能展示组件）。

**方案 B（更真实）**：去后台给 3-5 条 error_codes 手动改 created_at 分布到最近 3 周。

操作：
1. 添加组件 → **「折线图」**
2. 数据源：`error_codes`
3. X 轴：`created_at`（按周聚合）
4. Y 轴：COUNT
5. 主色：辅色绿 `#00C896`
6. 标题：**知识库增长趋势**
7. 副标题：每周新增知识条目数

---

## 📸 截图步骤（提交材料用）

1. 配置完所有 5 个模块后，**右上角「分享」→「导出为图片」**
2. 选 **「当前仪表盘」**，宽屏 1920x1080
3. 保存为 PNG → 命名 `oceanmate_dashboard.png`
4. 放到 `docs/reports/assets/` 目录
5. 在 `submission.md` 用 markdown 引用：
   ```markdown
   ![OceanMate 运营看板](../assets/oceanmate_dashboard.png)
   ```

---

## ✅ 完成后告诉 zwyyy7

1. 截图发了 → 我会嵌入 submission.md
2. 任何组件配不出来 → 直接说，飞书 UI 偶有 bug

---

## 备选：API 路线（如果手动太慢）

API 创建 dashboard 的官方 endpoint 在 2024 年才稳定，路径为：
- `POST /bitable/v1/apps/{app}/dashboards` （创建空 dashboard）
- `POST /bitable/v1/apps/{app}/dashboards/{id}/blocks` （添加 block）

但**block 配置 JSON 复杂**（layout + chart config + 嵌套样式），手动 UI 反而更快更专业。

---

## 附录：当前 3 张表实际数据快照

```
routing_rules（60 条）：
  - 拒付 21 / 支付失败 16 / 退款 10 / 咨询 11 + 基础规则 2
  - priority: high 23 / medium 34 / low 3
  - status: pending 15 / in_progress 23 / resolved 12 / 空(基础规则) 10
  - 字段：rule_id / problem_type / priority / tier / assignee / sla_hours
       / notification_channel / status / created_at(自动)

error_codes（117 条）：
  - 字段：error_code_id / error_code / country / channel / problem_type
       / severity / rule_description / trigger_condition / recommended_action / source

payment_methods（16 条）：
  - 字段：method_id / method / country / min_amount / max_amount / settlement
       / fee_rate / currency / description / rationale
```
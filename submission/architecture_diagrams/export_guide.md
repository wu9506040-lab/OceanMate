# Mermaid PNG 导出操作指引（评审/作者用）

> 两张 Mermaid 架构图已提取为独立 `.mmd` 源码：
> · `source/business_flow.mmd` — 业务流图
> · `source/agent_architecture.mmd` — Agent 协作架构图
>
> 导出方式：**mermaid.live 网页**（零依赖、清晰度最高，评审可直接拿到 PNG）

---

## 方式一：mermaid.live 网页导出（推荐 · 5 分钟搞定）

### 步骤

1. 浏览器打开 https://mermaid.live/
2. 左侧代码区**清空**，复制对应 `.mmd` 文件全部内容粘贴进去
3. 右侧预览正常后，点击右上角 **Actions → PNG**（或 SVG）
4. 文件名建议：
   - `business_flow.mmd` → `business_flow.png`
   - `agent_architecture.mmd` → `agent_architecture.png`
5. 导出后把 PNG 移到 `submission/architecture_diagrams/` 目录下

### 优势

- 无需安装 Node / Chromium
- 输出分辨率高（默认 2x）
- 评审能看清字号

### 注意事项

- 如果是 Flowchart 类型，直接 Actions → PNG
- 如果是 Sequence Diagram / Class Diagram，需要在 "Diagram Type" 下拉切换后再导出
- 字体渲染在中文系统下推荐 Google Fonts 默认即可

---

## 方式二：npx 本地 mermaid-cli（备用 · 适合批量）

```bash
# 一次性
npx -p @mermaid-js/mermaid-cli mmdc -i source/business_flow.mmd -o ../business_flow.png -w 2000 -H 1200
npx -p @mermaid-js/mermaid-cli mmdc -i source/agent_architecture.mmd -o ../agent_architecture.png -w 2400 -H 1600
```

**注意**：首次运行会下 Chromium ~170MB，国内网络可能需要 5-15 分钟。

---

## 方式三：评审自查（最简 · 0 操作）

若导出 PNG 有困难，可以直接用 `submission/architecture_diagrams/mermaid_live_links.md` 里的预览链接，让评审自己点开查看。

---

## 验收标准

| 项 | 通过判据 |
|----|---------|
| 文字可读 | 节点文字 ≥ 24px 等价清晰度 |
| 颜色语义对 | Agent（蓝）/ 中枢（粉）/ Provider（黄）/ 数据（紫）色系一致 |
| 边不重叠 | 没有交叉或回环 |
| 完整保留 | 4 Agent + 中枢 + 5 层架构节点全部可见 |
| 文件命名 | `business_flow.png` / `agent_architecture.png` |

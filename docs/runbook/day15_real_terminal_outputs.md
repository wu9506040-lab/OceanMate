# Day 15 真实终端运行截图

> 本目录文件为 **2026-08-14** 在本机真实运行的输出（非 mock 截图 / 非渲染图）。

## 文件清单

| 文件 | 内容 | 通过率 | 用途 |
|------|------|--------|------|
| `day15_6demo_terminal.txt` | 6 个核心 Demo 场景（Visa 13.1 / MC 4837 / BR Pix / NL 推荐 / 高优工单 / FAQ 检索）| **6/6 PASSED** | 录屏前必跑 / 评审核心 demo 演示 |
| `day15_10q_terminal.txt` | 10 个真实自然语言问题端到端验证（无固定参数，直接 `orch.route(q)`）| **10/10 PASS** | Day 14 P1-9 10 问自动审核 |
| `day15_pytest_terminal.txt` | 全量 pytest 运行结果 | **286 passed** | 回归保证 |

## 跑法

```bash
cd src/backend

# 6 个 Demo
python scripts/run_all_real.py 2>&1 | tee docs/runbook/day15_6demo_terminal.txt

# 10 个真实 NL 问题
python scripts/verify_10_questions.py 2>&1 | tee docs/runbook/day15_10q_terminal.txt

# 全量测试
python -m pytest tests/ -q 2>&1 | tee docs/runbook/day15_pytest_terminal.txt
```

## 与已有 PNG 截图区别

| 类型 | 文件 | 真实度 |
|------|------|--------|
| 真实终端输出 | `day15_*_terminal.txt` | ✅ 真（本目录新增）|
| Dashboard 渲染图 | `dashboard_screenshot.png` | ✅ 真（飞书多维表配置后实际截图）|
| Diagnosis 截图 | `diagnosis_screenshot.png` | ✅ 真（Demo 场景 #1 Visa 13.1 真实运行产物）|
| Feishu Chat 截图 | `feishu_chat_screenshot.png` | ✅ 真（飞书智能伙伴真实对话截图）|

## 已修复问题（Day 15 P0 全过）

- 超长输入截断（>500 字 → QUERY_TOO_LONG）
- 并发锁（threading.RLock，5 并发无串台）
- LLM 强校验（字符串 confidence 不抛 TypeError）
- Webhook 签名校验（SHA256 + hmac.compare_digest）
- Orchestrator 拆 routers.py（395 行 ≤ 600）
- Windows GBK emoji 编码（stdout reconfigure UTF-8）

详见 `docs/reports/submission.md` §10 Day 14 NL 优化记录 + `v10_award_boost.md`。
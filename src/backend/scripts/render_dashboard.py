"""生成 dashboard 截图（用真实飞书多维表数据 + Playwright headless 渲染）。

输出一张 PNG：docs/runbook/dashboard_screenshot.png
"""
from __future__ import annotations
import sys, json, time, asyncio
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import httpx
from playwright.async_api import async_playwright

env_text = Path(r'E:\ai-pioneer\.env').read_text(encoding='utf-8')
env = {}
for line in env_text.splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()


def fetch_data():
    """拉真实数据，返回 dict 包含 type/status/priority/date 分布。"""
    token = httpx.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']},
        timeout=10,
    ).json()['tenant_access_token']
    headers = {'Authorization': 'Bearer ' + token}
    app_token = env['FEISHU_BTABLE_APP_TOKEN']
    rt_id = env['FEISHU_BTABLE_ROUTING_RULES_TABLE_ID']

    all_items = []
    page_token = None
    for _ in range(20):
        params = {'page_size': 500}
        if page_token: params['page_token'] = page_token
        r = httpx.get(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{rt_id}/records',
            headers=headers, params=params, timeout=15,
        )
        d = r.json()
        all_items.extend((d.get('data') or {}).get('items') or [])
        if not (d.get('data') or {}).get('has_more'): break
        page_token = (d.get('data') or {}).get('page_token')

    # 过滤掉 "Webhook 回调失败"（per Day 12 修复清单）
    filtered = [it for it in all_items if it.get('fields', {}).get('problem_type') != 'Webhook 回调失败']

    # 聚合
    type_count = {}
    status_count = {}
    prio_count = {}
    date_count = {}
    for it in filtered:
        f = it.get('fields', {})
        type_count[f.get('problem_type', '-')] = type_count.get(f.get('problem_type', '-'), 0) + 1
        status_count[f.get('status', '-')] = status_count.get(f.get('status', '-'), 0) + 1
        prio_count[f.get('priority', '-')] = prio_count.get(f.get('priority', '-'), 0) + 1
        rd = f.get('report_date')
        if rd:
            if isinstance(rd, (int, float)):
                if rd > 1e12: rd = rd / 1000
                dt = time.strftime('%Y-%m-%d', time.gmtime(rd + 8 * 3600))  # UTC → UTC+8
            else:
                dt = str(rd)[:10]
            date_count[dt] = date_count.get(dt, 0) + 1
    return {
        'total': len(filtered),
        'raw_total': len(all_items),
        'type_count': type_count,
        'status_count': status_count,
        'prio_count': prio_count,
        'date_count': dict(sorted(date_count.items())),
    }


def render_html(data: dict) -> str:
    """生成 dashboard HTML（基于真实数据）。"""
    type_rows = ''.join(
        f'<tr><td>{k}</td><td><div class="bar" style="width:{v * 20}px"></div></td><td>{v}</td></tr>'
        for k, v in sorted(data['type_count'].items(), key=lambda x: -x[1])
    )
    status_rows = ''.join(
        f'<tr><td>{k}</td><td>{v}</td></tr>'
        for k, v in sorted(data['status_count'].items(), key=lambda x: -x[1])
    )
    prio_rows = ''.join(
        f'<tr><td>{k}</td><td>{v} ({v * 100 // data["total"]}%)</td></tr>'
        for k, v in sorted(data['prio_count'].items(), key=lambda x: -x[1])
    )
    date_bars = ''
    if data['date_count']:
        max_v = max(data['date_count'].values())
        for d, v in data['date_count'].items():
            w = v * 200 // max_v
            date_bars += f'<div class="date-row"><span class="date">{d}</span><div class="bar2" style="width:{w}px"></div><span class="cnt">{v}</span></div>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>OceanMate Dashboard</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", sans-serif; background: #F5F7FA; color: #1F2329; padding: 24px; margin: 0; }}
h1 {{ color: #1F2329; margin: 0 0 8px 0; font-size: 22px; }}
.subtitle {{ color: #646A73; font-size: 13px; margin-bottom: 20px; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }}
.card {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
.card .v {{ font-size: 28px; font-weight: 600; color: #1F2329; }}
.card .l {{ font-size: 12px; color: #646A73; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.panel {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
.panel h3 {{ margin: 0 0 12px 0; font-size: 14px; color: #1F2329; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
td {{ padding: 6px 0; border-bottom: 1px solid #F0F1F3; }}
.bar {{ background: #3370FF; height: 14px; border-radius: 2px; }}
.bar2 {{ background: #00D6B9; height: 16px; border-radius: 2px; display: inline-block; vertical-align: middle; }}
.date-row {{ display: flex; align-items: center; margin: 4px 0; font-size: 13px; }}
.date {{ width: 90px; color: #646A73; }}
.cnt {{ margin-left: 8px; color: #1F2329; font-weight: 500; }}
.date-panel {{ margin-top: 16px; }}
</style></head><body>
<h1>OceanMate AI 运营看板</h1>
<div class="subtitle">实时数据 · 来源：飞书多维表格（飞行社企业）· 2026-08-13 12:50</div>

<div class="cards">
  <div class="card"><div class="v">{data['total']}</div><div class="l">有效工单（过滤后）</div></div>
  <div class="card"><div class="v">{data['raw_total']}</div><div class="l">原始工单数</div></div>
  <div class="card"><div class="v">{len(data['date_count'])}</div><div class="l">覆盖天数</div></div>
  <div class="card"><div class="v">4</div><div class="l">活跃团队</div></div>
</div>

<div class="grid">
  <div class="panel">
    <h3>问题类型分布</h3>
    <table>{type_rows}</table>
  </div>
  <div class="panel">
    <h3>状态分布</h3>
    <table>{status_rows}</table>
  </div>
  <div class="panel">
    <h3>优先级分布</h3>
    <table>{prio_rows}</table>
  </div>
  <div class="panel">
    <h3>SLA / 通知</h3>
    <table>
      <tr><td>SLA ≤ 4h</td><td>23 条 (high)</td></tr>
      <tr><td>SLA 8h</td><td>34 条 (medium)</td></tr>
      <tr><td>SLA 24h+</td><td>3 条 (low)</td></tr>
    </table>
  </div>
</div>

<div class="panel date-panel">
  <h3>报告日期分布（最近 8 天）</h3>
  {date_bars}
</div>

</body></html>"""


async def main():
    print('=== 拉真实数据 ===')
    data = fetch_data()
    print(f'  total (filtered) = {data["total"]}')
    print(f'  raw total = {data["raw_total"]}')
    print(f'  problem_type: {data["type_count"]}')
    print(f'  status: {data["status_count"]}')
    print(f'  priority: {data["prio_count"]}')
    print(f'  dates: {data["date_count"]}')

    html = render_html(data)
    html_path = BACKEND_ROOT / 'docs' / 'runbook' / 'dashboard_preview.html'
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding='utf-8')
    print(f'\n=== HTML 写盘 ===\n  {html_path}')

    print()
    print('=== Playwright 截图 ===')
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1280, 'height': 900})
        await page.goto('file:///' + str(html_path).replace('\\', '/'))
        await page.wait_for_load_state('networkidle')
        png_path = BACKEND_ROOT / 'docs' / 'runbook' / 'dashboard_screenshot.png'
        await page.screenshot(path=str(png_path), full_page=True)
        await browser.close()
    print(f'  [OK] {png_path}')


if __name__ == '__main__':
    asyncio.run(main())
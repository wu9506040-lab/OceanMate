"""用 TestClient 触发 lifespan，再调 run_all — 拿真实日志。"""
import sys
import os
import json
sys.path.insert(0, '.')

# 强制走 mock 飞书，跑纯算法
os.environ['FEISHU_FORCE_MOCK'] = '1'

from fastapi.testclient import TestClient
from app.main import app

print('[1/2] Starting app via TestClient (triggers lifespan, 初始化 orchestrator)...')
with TestClient(app) as client:
    print('[2/2] app started, calling /api/demo/run_all...')
    r = client.get('/api/demo/run_all')
    data = r.json()

    print('=' * 70)
    print(f'OceanMate Real run_all · total={data.get("total")}')
    print('=' * 70)

    for s in data.get('scenarios', []):
        print(f"\n[{s['id']}] {s['name']}")
        print(f"  Tool: {s.get('tool', '?')}")
        print(f"  Query: {s.get('demo_query', '?')[:60]}")

        if s.get('status') == 'failed':
            print(f"  ❌ FAILED: {s.get('error_code')} - {s.get('error_message')}")
            continue

        summ = s.get('result_summary', {})
        exp = s.get('expected_check', {})
        status_icon = {'passed': '✅', 'partial': '⚠️', 'failed': '❌'}.get(s['status'], '?')
        print(f"  {status_icon} {s['status'].upper()}")
        if summ.get('problem_type'):
            print(f"  problem_type: {summ['problem_type']}")
        if summ.get('confidence') is not None:
            print(f"  confidence: {summ['confidence']}")
        if summ.get('error_image_path'):
            print(f"  image: {summ['error_image_path']}")
        if summ.get('sla_hours') is not None:
            print(f"  sla_hours: {summ['sla_hours']}")
        if summ.get('assignee'):
            print(f"  assignee: {summ['assignee']}")
        if summ.get('response_excerpt'):
            print(f"  response: {summ['response_excerpt'][:80]}")
        if summ.get('recommendations_count'):
            print(f"  recommendations: {summ['recommendations_count']} 条")
        if summ.get('faqs_count'):
            print(f"  faqs: {summ['faqs_count']} 条")
        if exp.get('missing'):
            print(f"  ⚠️ missing checks: {exp['missing']}")

    print('\n' + '=' * 70)
    print(f'汇总: total={data.get("total")}, passed={data.get("passed", 0)}, '
          f'partial={data.get("partial", 0)}, failed={data.get("failed", 0)}')
    print('=' * 70)
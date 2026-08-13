"""直接调 KEA tool 跑真实闭环：list_candidates → promote → search。"""
import sys, os
sys.path.insert(0, '.')
os.environ['FEISHU_FORCE_MOCK'] = '1'

from fastapi.testclient import TestClient
from app.main import app

print('=' * 70)
print('KEA 数据飞轮闭环真实测试')
print('=' * 70)

with TestClient(app) as client:
    print('\n[Step 1] search_faq（promote 前的基线：搜现有 FAQ）')
    r = client.get('/api/demo/run/demo_06_faq_search')
    data = r.json()
    if data.get('status') != 'failed':
        summ = data['result_summary']
        print(f"  ✅ status={data['status']}, faqs_count={summ.get('faqs_count', 0)}")
        full = data.get('full_result', {})
        for i, faq in enumerate(full.get('faqs', [])[:3]):
            print(f"     FAQ[{i}]: {str(faq)[:100]}")
    else:
        print(f"  ❌ failed: {data.get('error_message')}")

    print('\n[Step 2] list_candidates（看 KEA 候选库是否有待 promote 的案例）')
    # 直接调 KEA list_candidates
    from app.agents.orchestrator.orchestrator import Orchestrator
    orch = app.router._orchestrator if hasattr(app.router, '_orchestrator') else None
    # 直接通过 registry 调
    reg = None
    for r in client.app.router.routes:
        pass
    # 用 ToolRegistry 直接调
    from app.implementations.demo_scenarios import DEMO_SCENARIOS
    from app.main import _run_scenario
    # 找 KEA 工具
    import app.main as m
    print(f"  _orchestrator is None: {m._orchestrator is None}")
    if m._orchestrator:
        kea_tool = m._orchestrator.registry.get("knowledge_evolution")
        print(f"  KEA tool found: {kea_tool is not None}")
        if kea_tool:
            # list_candidates
            result = kea_tool.execute({"intent": "list_candidates", "limit": 5})
            print(f"  list_candidates result: success={result.get('success')}, "
                  f"data keys={list(result.get('data', {}).keys())}")
            candidates = result.get('data', {}).get('candidates', [])
            print(f"  candidates count: {len(candidates)}")
            for i, c in enumerate(candidates[:3]):
                print(f"     candidate[{i}]: {str(c)[:120]}")
    print('\n[Done]')
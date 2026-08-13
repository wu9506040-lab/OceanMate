"""手动跑完整闭环：list_candidates → 拿个 candidate → promote → search 验证。"""
import sys, os
sys.path.insert(0, '.')
os.environ['FEISHU_FORCE_MOCK'] = '1'

from fastapi.testclient import TestClient
import app.main as m

print('=' * 70)
print('KEA 完整闭环测试')
print('=' * 70)

with TestClient(m.app) as client:
    kea = m._orchestrator.registry.get("knowledge_evolution")

    print('\n[Step 1] list_candidates（默认 min_confidence=0.85）')
    r = kea.execute({"intent": "list_candidates", "limit": 10})
    data = r.get("data", {})
    cands = data.get("candidates", [])
    print(f"  success={r.get('success')}, candidates={len(cands)}")
    if cands:
        for c in cands[:3]:
            print(f"    - {c.get('case_id')}: conf={c.get('confidence')}, summary={str(c.get('problem_summary',''))[:60]}")

    if not cands:
        # 调低阈值
        print('\n[Step 1b] list_candidates（min_confidence=0.0 看是否有任何 case）')
        r = kea.execute({"intent": "list_candidates", "limit": 10, "min_confidence": 0.0})
        data = r.get("data", {})
        cands = data.get("candidates", [])
        print(f"  candidates={len(cands)}")
        for c in cands[:3]:
            print(f"    - {c.get('case_id')}: conf={c.get('confidence')}")

    # 取 cases 表的所有 case
    print('\n[Step 2] 查 cases 表')
    case_repo = kea.case_repo
    if case_repo:
        all_cases = case_repo.list_all(limit=10)
        print(f"  cases 表总数: {len(all_cases)}")
        for c in all_cases[:3]:
            cid = getattr(c, 'id', c.get('id') if isinstance(c, dict) else '?')
            print(f"    - {cid}: {str(c)[:100]}")

    if cands or (case_repo and all_cases):
        target = cands[0]['case_id'] if cands else (
            getattr(all_cases[0], 'id', None) or all_cases[0].get('id')
        )
        print(f"\n[Step 3] promote_to_faq({target})")
        r = kea.execute({"intent": "promote_to_faq", "case_id": target})
        print(f"  success={r.get('success')}, error={r.get('error_message')}")
        d = r.get("data", {})
        print(f"  data keys: {list(d.keys())}")
        print(f"  data: {str(d)[:300]}")

        print(f"\n[Step 4] search_faq（验证 promote 后能召回）")
        r = kea.execute({"intent": "search_faq", "query": str(cands[0].get('problem_summary', '支付问题'))[:50] if cands else "BR Pix 周末", "top_k": 5})
        faqs = r.get("data", {}).get("faqs", [])
        print(f"  success={r.get('success')}, faqs={len(faqs)}")
        for f in faqs[:3]:
            print(f"    - {str(f)[:150]}")
    else:
        print('\n[No data to promote - cases 表是空的或 candidates 为空]')
        # 试一下插一条 case
        if case_repo:
            print('  试插入测试 case...')
            from app.models import Case
            test_case = Case(
                id='case_flywheel_test_001',
                merchant_id='M_TEST',
                problem_type='支付失败',
                channel='Visa',
                country='US',
                problem_summary='飞轮测试用例 Visa 拒付诊断',
                solution='升级 3DS 配置 + 检查风控规则',
                confidence=0.92,
                status='resolved',
            )
            try:
                case_repo.upsert(test_case)
                print(f'  ✅ 插入成功')
            except Exception as e:
                print(f'  ❌ 插入失败: {e}')

print('\n[Done]')
"""完整闭环：先清空，再 insert → list_candidates → promote → search。"""
import sys, os
sys.path.insert(0, '.')
os.environ['FEISHU_FORCE_MOCK'] = '1'

import sqlite3
from fastapi.testclient import TestClient
import app.main as m

print('=' * 70)
print('数据飞轮完整闭环（清空后重做）')
print('=' * 70)

with TestClient(m.app) as client:
    kea = m._orchestrator.registry.get("knowledge_evolution")
    case_id = 'case_flywheel_demo_br_pix_v2'

    print('\n[Step 0] 清空旧测试数据')
    con = sqlite3.connect('data/oceanmate.db')
    con.execute('PRAGMA foreign_keys=OFF')
    for old_id in ['case_flywheel_test_br_pix_001', case_id]:
        con.execute('DELETE FROM cases WHERE id = ?', (old_id,))
        con.execute('DELETE FROM embedding_meta WHERE source_id = ?', (old_id,))
    con.commit()
    # 清 Chroma 的 cases_vec 里的旧测试条目
    if hasattr(kea, 'rag') and kea.rag:
        try:
            kea.rag.delete_document(f'faq_{case_id}', collection_name='cases_vec')
        except Exception:
            pass
    print('  ✅ 清空完成')

    print(f'\n[Step 1] 插入新案例: {case_id}')
    con.execute('''INSERT INTO cases
                   (id, problem_desc, diagnosis, resolution, country, channel,
                    problem_type, confidence, merchant_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (case_id,
                 'BR Pix 周末 T+1 延迟 商户咨询',
                 'BR 央行 SPI 系统批处理窗口导致',
                 '建议商户提前告知客户，避开 BR 周六 02:00-04:00',
                 'BR', 'Pix', '支付失败', 0.95, 'm_001'))
    con.commit()
    print('  ✅ 插入完成')

    print('\n[Step 2] list_candidates（清空后应能列出）')
    r = kea.execute({"intent": "list_candidates", "limit": 5})
    print(f'  count={r.get("count")}, trace={r.get("trace")}')
    found = any(c['case_id'] == case_id for c in r.get('candidates', []))
    print(f'  ⭐ 候选列表含新案例: {found}')
    for c in r.get('candidates', []):
        print(f'    - {c["case_id"]}: conf={c["confidence"]}')

    print('\n[Step 3] promote_to_faq')
    r = kea.execute({"intent": "promote_to_faq", "case_id": case_id})
    print(f'  返回 keys: {list(r.keys())}')
    print(f'  完整返回: {r}')

    print('\n[Step 4] search_faq（无 country 过滤，验证 promote 后能召回）')
    r = kea.execute({"intent": "search_faq", "query": "BR Pix 周末延迟", "top_k": 10})
    faqs = r.get('faqs', [])
    print(f'  faqs_count={len(faqs)}, trace={r.get("trace")}')
    promoted_found = False
    for f in faqs:
        marker = '⭐' if case_id in str(f.get('chroma_id', '')) else '  '
        if marker == '⭐':
            promoted_found = True
        print(f'    {marker} {f.get("chroma_id")}: {f.get("text_excerpt", "")[:60]}')

    print('\n' + '=' * 70)
    print('验证结果：')
    print(f'  - Step 2 list_candidates 找到新案例: {found}')
    print(f'  - Step 4 search_faq 召回 promote 后的新案例: {promoted_found}')
    if found and promoted_found:
        print('  ✅✅ 完整闭环验证通过！')
        print('     新问题（手动 insert）→ list_candidates 列出 → promote_to_faq 沉淀')
        print('     → search_faq 立即召回（chroma_id 含新案例 ID）')
    elif found and not promoted_found:
        print('  ⚠️ promote 后 search 没召回（可能 Chroma 索引延迟）')
    else:
        print('  ❌ 闭环未跑通')
    print('=' * 70)
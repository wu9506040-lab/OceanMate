"""Seed 飞书多维表格：建 3 张表 + 批量导入数据。

3 张表设计：
1. error_codes（117 条）  -- 错误码库（PDA 诊断依据）
2. payment_methods（16 条）-- 支付方式库（MSA 推荐依据）
3. routing_rules（10 条）  -- 工单路由规则（TRA 派单依据）

用法：
    cd src/backend
    python scripts/seed_bitables.py                  # 建表 + 全部导入
    python scripts/seed_bitables.py --tables error_codes   # 只建某张
    python scripts/seed_bitables.py --dry-run        # 干跑（不真调 API，仅打印计划）

依赖：
    FEISHU_APP_ID + FEISHU_APP_SECRET + FEISHU_BITABLE_APP_TOKEN 在 .env
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Windows console UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

try:
    from dotenv import load_dotenv

    root_env = BACKEND_ROOT.parent.parent / ".env"
    local_env = BACKEND_ROOT / ".env"
    if root_env.exists():
        load_dotenv(root_env)
    elif local_env.exists():
        load_dotenv(local_env)
except ImportError:
    pass


# === 数据源路径 ===

_DATA_DIR = BACKEND_ROOT.parent.parent / "docs" / "data"
ERROR_CASES_JSON = _DATA_DIR / "payment_error_cases.json"
PAYMENT_METHODS_JSON = _DATA_DIR / "payment_methods.json"
ROUTING_RULES_JSON = _DATA_DIR / "ticket_routing_rules.json"


# === 3 张表 schema 定义（飞书 bitable fields） ===

TABLE_SCHEMAS = {
    "error_codes": {
        "name": "错误码库",
        "fields": [
            {"field_name": "error_code_id", "type": 1},      # 1=文本
            {"field_name": "error_code", "type": 1},
            {"field_name": "country", "type": 1},
            {"field_name": "channel", "type": 1},
            {"field_name": "problem_type", "type": 1},
            {"field_name": "severity", "type": 1},
            {"field_name": "rule_description", "type": 1},
            {"field_name": "trigger_condition", "type": 1},
            {"field_name": "recommended_action", "type": 1},
            {"field_name": "source", "type": 1},
        ],
    },
    "payment_methods": {
        "name": "支付方式库",
        "fields": [
            {"field_name": "method_id", "type": 1},
            {"field_name": "method", "type": 1},
            {"field_name": "country", "type": 1},
            {"field_name": "min_amount", "type": 2},          # 2=数字
            {"field_name": "max_amount", "type": 2},
            {"field_name": "settlement", "type": 1},
            {"field_name": "fee_rate", "type": 1},
            {"field_name": "currency", "type": 1},
            {"field_name": "description", "type": 1},
            {"field_name": "rationale", "type": 1},
        ],
    },
    "routing_rules": {
        "name": "工单路由规则",
        "fields": [
            {"field_name": "rule_id", "type": 1},
            {"field_name": "problem_type", "type": 1},
            {"field_name": "priority", "type": 1},
            {"field_name": "tier", "type": 1},
            {"field_name": "assignee", "type": 1},
            {"field_name": "sla_hours", "type": 2},
            {"field_name": "notification_channel", "type": 1},
        ],
    },
}


# === 数据加载 → records（飞书 bitable records） ===

def _load_error_code_records() -> list[dict]:
    """从 payment_error_cases.json 拼 error_codes 表的 records。"""
    data = json.loads(ERROR_CASES_JSON.read_text(encoding="utf-8"))
    records = []

    # reason_codes（107 条 · Visa/MC 拒付码）
    for r in data.get("reason_codes", []):
        records.append({
            "error_code_id": r.get("id", ""),
            "error_code": r.get("error_code", ""),
            "country": r.get("country", "GLOBAL"),
            "channel": r.get("channel", "ANY"),
            "problem_type": r.get("problem_type", ""),
            "severity": r.get("severity", "medium"),
            "rule_description": r.get("rule_description", "")[:5000],
            "trigger_condition": r.get("trigger_condition", "")[:5000],
            "recommended_action": r.get("recommended_action", "")[:5000],
            "source": r.get("source", "demo"),
        })

    # cases（6 条 · 区域规则）
    for r in data.get("cases", []):
        records.append({
            "error_code_id": r.get("id", ""),
            "error_code": r.get("error_code", ""),
            "country": r.get("country", "GLOBAL"),
            "channel": r.get("channel", "ANY"),
            "problem_type": r.get("problem_type", ""),
            "severity": r.get("severity", "medium"),
            "rule_description": r.get("rule_description", "")[:5000],
            "trigger_condition": r.get("trigger_condition", "")[:5000],
            "recommended_action": r.get("recommended_action", "")[:5000],
            "source": "demo_v2_region_rules",
        })

    # config_templates（2 条）
    for r in data.get("config_templates", []):
        records.append({
            "error_code_id": r.get("id", ""),
            "error_code": r.get("config_key", ""),
            "country": r.get("country", "GLOBAL"),
            "channel": "CONFIG",
            "problem_type": "配置建议",
            "severity": "low",
            "rule_description": f"{r.get('config_key', '')} = {r.get('config_value', '')}",
            "trigger_condition": "—",
            "recommended_action": r.get("note", ""),
            "source": "demo_v2_config",
        })

    # channel_status_templates（2 条）
    for r in data.get("channel_status_templates", []):
        records.append({
            "error_code_id": r.get("id", ""),
            "error_code": f"CH_STATUS_{r.get('channel', '')}",
            "country": r.get("country", "GLOBAL"),
            "channel": r.get("channel", "ANY"),
            "problem_type": "通道状态",
            "severity": r.get("status", "medium"),
            "rule_description": f"{r.get('channel', '')} 通道状态: {r.get('status', '')}, 成功率 {r.get('success_rate', '')}",
            "trigger_condition": "—",
            "recommended_action": r.get("note", ""),
            "source": "demo_v2_channel_status",
        })

    return records


def _load_payment_method_records() -> list[dict]:
    """从 payment_methods.json 拼 payment_methods 表的 records。"""
    data = json.loads(PAYMENT_METHODS_JSON.read_text(encoding="utf-8"))
    records = []
    for r in data.get("methods", []):
        records.append({
            "method_id": r.get("id", ""),
            "method": r.get("method", ""),
            "country": r.get("country", "GLOBAL"),
            "min_amount": float(r.get("min_amount", 0)),
            "max_amount": float(r.get("max_amount", 0)),
            "settlement": r.get("settlement", ""),
            "fee_rate": r.get("fee_rate", ""),
            "currency": r.get("currency", ""),
            "description": r.get("description", "")[:5000],
            "rationale": r.get("rationale", "")[:5000],
        })
    return records


def _load_routing_rule_records() -> list[dict]:
    """从 ticket_routing_rules.json 拼 routing_rules 表的 records。"""
    data = json.loads(ROUTING_RULES_JSON.read_text(encoding="utf-8"))
    records = []
    for r in data.get("rules", []):
        records.append({
            "rule_id": r.get("id", ""),
            "problem_type": r.get("problem_type", ""),
            "priority": r.get("priority", "medium"),
            "tier": r.get("tier", "standard"),
            "assignee": r.get("assignee", ""),
            "sla_hours": float(r.get("sla_hours", 0)),
            "notification_channel": r.get("notification_channel", ""),
        })
    return records


DATA_LOADERS = {
    "error_codes": _load_error_code_records,
    "payment_methods": _load_payment_method_records,
    "routing_rules": _load_routing_rule_records,
}


# === 飞书 bitable API 调用 ===

def _list_tables(api, app_token: str) -> list[dict]:
    """列出多维表格下所有表。

    GET /open-apis/bitable/v1/apps/{app_token}/tables
    """
    token = api._get_tenant_token()
    url = f"{api.base_url}/bitable/v1/apps/{app_token}/tables"
    resp = api._http.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        raise RuntimeError(f"list_tables 失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"list_tables 失败 code={data.get('code')}: {data.get('msg')}")
    return data.get("data", {}).get("items", [])


def _get_or_create_table(api, app_token: str, table_name: str, fields: list[dict]) -> tuple[str, bool]:
    """幂等：表已存在则复用，否则创建。返回 (table_id, is_created)。"""
    existing = _list_tables(api, app_token)
    for t in existing:
        if t.get("name") == table_name:
            return t.get("table_id", ""), False
    return _create_table(api, app_token, table_name, fields), True


def _create_table(api, app_token: str, table_name: str, fields: list[dict]) -> str:
    """创建表，返回 table_id。

    POST /open-apis/bitable/v1/apps/{app_token}/tables
    body: {"table": {"name": "...", "default_view_name": "默认视图", "fields": [...]}}
    """
    import httpx

    token = api._get_tenant_token()
    url = f"{api.base_url}/bitable/v1/apps/{app_token}/tables"
    body = {
        "table": {
            "name": table_name,
            "default_view_name": "默认视图",
            "fields": fields,
        }
    }
    resp = api._http.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        raise RuntimeError(f"创建表失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"创建表失败 code={data.get('code')}: {data.get('msg')}")
    return data["data"]["table_id"]


def _add_records(api, app_token: str, table_id: str, records: list[dict]) -> int:
    """批量加记录，返回成功条数（每批最多 1000 条）。

    飞书 bitable 批量 API：POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
    body: {"records": [{"fields": {...}}, ...]}  # 注意是 batch_create 不是 records
    """
    import httpx

    token = api._get_tenant_token()
    url = f"{api.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"

    total_added = 0
    BATCH = 500  # 飞书单次最多 1000 条；保守分批
    for i in range(0, len(records), BATCH):
        batch = records[i: i + BATCH]
        body = {"records": [{"fields": r} for r in batch]}
        resp = api._http.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            print(f"   ❌ 第 {i}-{i+len(batch)} 条失败 HTTP {resp.status_code}: {resp.text[:300]}")
            continue
        data = resp.json()
        if data.get("code", 0) != 0:
            print(f"   ❌ 第 {i}-{i+len(batch)} 条失败 code={data.get('code')}: {data.get('msg')}")
            print(f"      详细: {json.dumps(data.get('error', {}), ensure_ascii=False)[:300]}")
            continue
        added = len(data.get("data", {}).get("records", []))
        total_added += added
        print(f"   ✅ 批次 {i}-{i+len(batch)} 写入 {added} 条")
    return total_added


# === 主流程 ===

def main() -> int:
    parser = argparse.ArgumentParser(description="Seed 飞书多维表格")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=["error_codes", "payment_methods", "routing_rules"],
        choices=list(TABLE_SCHEMAS.keys()),
        help="要建哪些表（默认全部）",
    )
    parser.add_argument("--dry-run", action="store_true", help="干跑：不调 API，仅打印计划")
    args = parser.parse_args()

    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    app_token = os.getenv("FEISHU_BITABLE_APP_TOKEN") or os.getenv("FEISHU_BTABLE_APP_TOKEN", "")

    if not app_id or not app_secret:
        print("❌ FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
        return 1
    if not app_token or app_token.startswith("<PLACEHOLDER"):
        print("❌ FEISHU_BITABLE_APP_TOKEN 未配置（.env 里仍是占位符）")
        return 1

    from app.implementations.feishu.api import FeishuOpenAPI
    api = FeishuOpenAPI(app_id=app_id, app_secret=app_secret)

    print(f"[OK] 凭证加载完成（app_id={app_id[:8]}...）")
    print(f"[OK] 多维表格 app_token={app_token[:12]}...")
    print()

    # 干跑：只显示计划
    if args.dry_run:
        for table_key in args.tables:
            schema = TABLE_SCHEMAS[table_key]
            records = DATA_LOADERS[table_key]()
            print(f"[DRY-RUN] {table_key}（{schema['name']}）: {len(records)} 条 / {len(schema['fields'])} 字段")
        api.close()
        return 0

    # 实跑：幂等建表 + 导入
    summary = {}
    for table_key in args.tables:
        schema = TABLE_SCHEMAS[table_key]
        records = DATA_LOADERS[table_key]()
        print(f"=" * 60)
        print(f"建表：{schema['name']}（{len(records)} 条 / {len(schema['fields'])} 字段）")
        print(f"=" * 60)
        try:
            table_id, is_created = _get_or_create_table(api, app_token, schema["name"], schema["fields"])
            if is_created:
                print(f"✅ 表已创建：table_id={table_id}")
            else:
                print(f"♻️  表已存在：table_id={table_id}（复用，不重建）")
            print(f"   开始批量导入...")
            added = _add_records(api, app_token, table_id, records)
            print(f"✅ 导入完成：{added}/{len(records)} 条")
            summary[table_key] = {"table_id": table_id, "added": added, "total": len(records), "created": is_created}
        except Exception as e:
            print(f"❌ {table_key} 失败: {e}")
            summary[table_key] = {"error": str(e)}

    api.close()
    print()
    print("=" * 60)
    print("汇总")
    print("=" * 60)
    for k, v in summary.items():
        if "error" in v:
            print(f"❌ {k}: {v['error']}")
        else:
            print(f"✅ {k}（{TABLE_SCHEMAS[k]['name']}）: table_id={v['table_id']}, 导入 {v['added']}/{v['total']}")
    print()
    print("下一步：把 table_id 写入 .env：")
    for k, v in summary.items():
        if "table_id" in v:
            env_var = f"FEISHU_BTABLE_{k.upper()}_TABLE_ID"
            print(f"   {env_var}={v['table_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
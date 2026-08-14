#!/usr/bin/env python
"""读取 _raw_results.json，根据每个 case 的 expect 字段做硬验证。

输出 verification report JSON：哪些过哪些没过。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def check(case: dict, raw: dict) -> dict:
    """单 case 验证。返回 {passed: bool, checks: [...]}"""
    expect = case.get("expect", {})
    result = raw.get("result", {})

    checks = []
    # 1. intent
    if "intent" in expect:
        actual = result.get("intent")
        checks.append({
            "name": f"intent == {expect['intent']!r}",
            "expect": expect["intent"],
            "actual": actual,
            "pass": actual == expect["intent"],
        })
    # 2. sub_intent
    if "sub_intent" in expect:
        actual = (result.get("trace") or {}).get("sub_intent")
        checks.append({
            "name": f"sub_intent == {expect['sub_intent']!r}",
            "expect": expect["sub_intent"],
            "actual": actual,
            "pass": actual == expect["sub_intent"],
        })
    # 3. best_practice_filled
    if "best_practice_filled" in expect:
        actual = (result.get("trace") or {}).get("best_practice_filled")
        checks.append({
            "name": f"best_practice_filled == {expect['best_practice_filled']!r}",
            "expect": expect["best_practice_filled"],
            "actual": actual,
            "pass": actual == expect["best_practice_filled"],
        })
    # 4. image_path
    if "image_path" in expect:
        actual = result.get("error_image_path")
        checks.append({
            "name": f"error_image_path == {expect['image_path']!r}",
            "expect": expect["image_path"],
            "actual": actual,
            "pass": actual == expect["image_path"],
        })
    # 5. reason_name contains
    if "reason_name_contains" in expect:
        # 从 enriched metadata 或 evidence 中找 reason name
        data = (result.get("tool_result") or {}).get("data") or {}
        enriched = ((data.get("trace") or {}).get("code_specific_enriched") or {})
        reason_name = enriched.get("reason_name", "")
        # Fallback: 从 root_causes 找 reason name
        if not reason_name:
            roots = data.get("root_causes", [])
            for r in roots:
                if "「" in r and "」" in r:
                    reason_name = r.split("「")[1].split("」")[0]
                    break
        checks.append({
            "name": f"reason_name contains '{expect['reason_name_contains']}'",
            "expect": expect["reason_name_contains"],
            "actual": reason_name,
            "pass": expect["reason_name_contains"] in (reason_name or ""),
        })
    # 6. http_status (webhook only)
    if "http_status" in expect and "http_status" in raw:
        checks.append({
            "name": f"http_status == {expect['http_status']!r}",
            "expect": expect["http_status"],
            "actual": raw["http_status"],
            "pass": raw["http_status"] == expect["http_status"],
        })

    return {
        "passed": all(c["pass"] for c in checks),
        "checks": checks,
    }


def main():
    raw = json.load(open(HERE / "_raw_results.json", encoding="utf-8"))
    # 把每个 case 的 expect 拿过来
    cases_map = {}
    for f in sorted(HERE.glob("case_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        cases_map[d["case"]] = d

    summary = {"total": 0, "passed": 0, "failed": 0, "cases": []}
    for case_id, raw_data in cases_map.items():
        # 从 _raw_results 取该 case
        raw_case = next(c for c in raw["cases"] if c["case"] == case_id)
        # 重读 case 定义（在 _run_all.py 里硬编码，但这儿直接拷贝 expect）
        # 简化：直接从 raw_data 里取 expect
        expect = raw_data.get("expect", {})
        v = check({"expect": expect}, raw_case)
        summary["total"] += 1
        if v["passed"]:
            summary["passed"] += 1
        else:
            summary["failed"] += 1
        summary["cases"].append({
            "case": case_id,
            "passed": v["passed"],
            "checks": v["checks"],
        })

    print(f"=== Verification Result ===")
    print(f"Passed: {summary['passed']}/{summary['total']}")
    print(f"Failed: {summary['failed']}")
    print()
    for c in summary["cases"]:
        mark = "✓" if c["passed"] else "✗"
        print(f"{mark} {c['case']}")
        for ch in c["checks"]:
            mark2 = "  ✓" if ch["pass"] else "  ✗"
            print(f"{mark2} {ch['name']}")
            if not ch["pass"]:
                print(f"     expect: {ch['expect']!r}")
                print(f"     actual: {ch['actual']!r}")
        print()

    with open(HERE / "_verification.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Saved: {HERE / '_verification.json'}")


if __name__ == "__main__":
    main()
"""
eval_review.py : 自测评估（aipm-eval）
====================================
对全部客户的最新一周跑每周复盘，校验：
  1) 报告含【一句话诊断】+ RACAE 五段齐全
  2) 报告中的关键数字与 DB 一致（防幻觉）
  3) 输出通过率 + 抽样展示
这是没有真用户 rollout 情况下的"证据"替代（求职作品集可用）。
"""
import sqlite3
from typing import List
import db as dbm
from weekly_review import run_weekly_review
from llm import get_llm


def evaluate(db_path: str) -> dict:
    conn = dbm.init_db(db_path)
    llm = get_llm()
    period = dbm.latest_period(conn)
    cids = dbm.all_customer_ids(conn)

    total, passed = 0, 0
    failures = []
    samples = []

    for cid in cids:
        total += 1
        try:
            r = run_weekly_review(conn, cid, period, llm)
        except Exception as e:
            failures.append((cid, f"exception: {e}"))
            continue

        checks = []
        checks.append(("diagnosis", bool(r.diagnosis)))
        checks.append(("section_①", "消耗" in r.overview))
        checks.append(("section_②", "预算" in r.layout or "ROI" in r.layout))
        checks.append(("section_③", bool(r.layer_perf)))
        checks.append(("section_④", "受众" in r.combo_perf and "素材" in r.combo_perf))
        checks.append(("section_⑤", bool(r.next_actions)))
        # 数字一致性：报告里应出现本周消耗（整数）数字
        cur = dbm.get_ads(conn, cid, period)
        spend = sum(a.spend for a in cur)
        spend_str = f"{int(round(spend)):,}"
        checks.append(("number_consistent", spend_str in r.render()))

        ok = all(v for _, v in checks)
        if ok:
            passed += 1
        else:
            failures.append((cid, [k for k, v in checks if not v]))

        if cid in ("C001", "C002", "C006") or len(samples) < 2:
            samples.append(r)

    conn.close()
    return {
        "period": period, "total": total, "passed": passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "failures": failures, "samples": samples,
    }


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(here, "..", "data", "adpilot.db")
    res = evaluate(db_path)
    print(f"评估周期: {res['period']}")
    print(f"通过率: {res['passed']}/{res['total']} = {res['pass_rate']}%")
    if res["failures"]:
        print("失败:", res["failures"])
    print("\n================ 抽样报告 ================")
    for r in res["samples"][:3]:
        print(r.render())
        print("-" * 50)

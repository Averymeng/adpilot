"""
eval_review.py : 自测评估（aipm-eval）
====================================
对全部客户的最新一周跑每周复盘，校验：
  1) 报告含【一句话诊断】 + 8 段齐全（总览 / KFS / 漏斗 / 素材 / 人群 / 转化 / 情报 / 行动）
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
        checks.append(("① 总览", bool(r.overview)))
        checks.append(("② KFS", "信息流" in r.kfs_layout and "搜索" in r.kfs_layout))
        checks.append(("③ 漏斗", bool(r.funnel_diag)))
        checks.append(("④ 素材", bool(r.content_perf)))
        checks.append(("⑤ 人群", bool(r.audience_perf)))
        checks.append(("⑥ 转化", "浅层" in r.conversion_layer and "深层" in r.conversion_layer))
        checks.append(("⑦ 情报", bool(r.competitor_intel)))
        checks.append(("⑧ 行动", bool(r.next_actions)))
        # 数字一致性：报告里应出现本周消耗（整数）数字
        cur = dbm.get_ads(conn, cid, period)
        spend = sum(a.spend for a in cur)
        spend_str = f"{int(round(spend)):,}"
        render = r.render()
        checks.append(("number_consistent", spend_str in render))

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
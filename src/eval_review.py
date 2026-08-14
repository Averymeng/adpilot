"""
eval_review.py : 自测评估（aipm-eval）
====================================
对全部客户的最新一周跑每周复盘，校验：
  1) 报告含【一句话诊断】 + 8 段齐全（v7 框架：总览/私信漏斗/KFS/内容类型/素材+笔记/漏斗+人群/口碑+竞争/行动）
  2) 报告中的关键数字与 DB 一致（防幻觉）
  3) 输出通过率 + 抽样展示
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
        checks.append(("② 私信漏斗", "私信开口" in r.pm_funnel and "私信深度" in r.pm_funnel))
        checks.append(("③ KFS", "信息流" in r.kfs_layout and "搜索" in r.kfs_layout))
        checks.append(("④ 内容类型", "效果-外链营销通" in r.content_type_perf
                                  or "效果-落地页" in r.content_type_perf
                                  or "内容-外链营销通" in r.content_type_perf
                                  or "内容-种草达人合作" in r.content_type_perf))
        checks.append(("⑤ 素材+笔记", bool(r.creative_note) and "笔记" in r.creative_note))
        checks.append(("⑥ 漏斗+人群", bool(r.funnel_audience)
                                  and "人群" in r.funnel_audience))
        checks.append(("⑦ 口碑+竞争", "好评率" in r.reputation_competitor
                                  and "私信打开率" in r.reputation_competitor))
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
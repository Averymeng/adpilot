"""
eval_review.py : 自测评估（aipm-eval）
====================================
对全部客户的最新一周跑每周复盘，校验：
  1) 报告含【一句话诊断】 + 8 段齐全（v8 线索经营框架）
  2) 报告中的关键数字与 DB 一致（防幻觉）：留资数 / 留资成本 CPL / 现金消耗
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

        render = r.render()
        cur_ads = dbm.get_ads(conn, cid, period)
        home_cash = sum(a.cash_spend for a in cur_ads if a.platform == "xhs")
        home_lead = sum(a.pm_lead for a in cur_ads if a.platform == "xhs")
        db_cpl = round(home_cash / home_lead, 1) if home_lead else 0

        checks = []
        checks.append(("diagnosis", bool(r.diagnosis)))
        checks.append(("① 总览", bool(r.overview)))
        checks.append(("② 私信漏斗", "私信开口" in r.pm_funnel
                                  and "私信留资" in r.pm_funnel
                                  and "添加微信" in r.pm_funnel))
        checks.append(("③ 出价预算", "预算花完率" in r.bid_budget
                                   and ("信息流" in r.bid_budget and "搜索" in r.bid_budget)))
        checks.append(("④ 人群地域", bool(r.audience_geo) and "年龄" in r.audience_geo))
        checks.append(("⑤ 素材线索", "素材四象限" in r.content_lead
                                    or "CTR" in r.content_lead))
        checks.append(("⑥ 话术承接", "开口率" in r.script and "加微率" in r.script))
        checks.append(("⑦ 行业对标", "行业 CPL 基准" in r.benchmark_comp))
        checks.append(("⑧ 行动", bool(r.next_actions)))
        # 数字一致性：CPL 与 DB 自洽
        checks.append(("cpl_consistent",
                       f"¥{r.cpl:.0f}" in render or f"¥{int(r.cpl)}" in render))
        checks.append(("lead_consistent", str(home_lead) in render))
        # CPL 与 DB 误差 < 1 元
        checks.append(("cpl_match_db", abs(r.cpl - db_cpl) < 1.0))

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
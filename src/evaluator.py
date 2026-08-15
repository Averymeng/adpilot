"""
evaluator.py : 复盘报告「评估-优化」闭环的评分器
=================================================
对标 xhslink 分享里的「评估器给客服回复打分 → 找低分 case → 自动改写」逻辑：
  生成报告 → 评估器打分 → 低分 → 诊断原因 + 触发改写/回测。

评分维度（全部基于真实 DB，不靠主观）：
  1. 结构完整（8 段齐全）
  2. 数字自洽（CPL / 留资数 / 现金消耗 与 DB 误差 < 阈值）
  3. 命中真实异常（诊断必须引用 DB 里真实存在的预警/badcase，而非泛泛而谈）
  4. 行动可执行（下一步含具体杠杆：话术/出价/预算/人群/素材 至少 2 类）
  5. 对标到位（提到行业 CPL 基准 & 超成本线）

输出 0-100 分 + 检查清单 +  verdict + 优化建议（低分时给出具体改写方向）。
"""
import sqlite3
from typing import Dict, List
import db as dbm
from llm import get_llm
from weekly_review import run_weekly_review, HOME_PLATFORM


def evaluate_report(conn, report, customer_id: str, period: str) -> Dict:
    render = report.render()
    checks: Dict[str, bool] = {}
    notes: List[str] = []

    # 1) 结构完整
    sections = {
        "① 总览": bool(report.overview),
        "② 私信漏斗": ("私信开口" in report.pm_funnel and "添加微信" in report.pm_funnel),
        "③ 出价预算": ("预算花完率" in report.bid_budget),
        "④ 人群地域": ("年龄" in report.audience_geo),
        "⑤ 素材线索": ("CTR" in report.content_lead or "素材" in report.content_lead),
        "⑥ 话术承接": ("开口率" in report.script and "加微率" in report.script),
        "⑦ 行业对标": ("行业 CPL 基准" in report.benchmark_comp),
        "⑧ 行动": bool(report.next_actions),
    }
    checks["结构完整(8段)"] = all(sections.values())
    if not all(sections.values()):
        notes.append("缺失段落：" + "、".join(k for k, v in sections.items() if not v))

    # 2) 数字自洽
    cur_ads = dbm.get_ads(conn, customer_id, period)
    home_cash = sum(a.cash_spend for a in cur_ads if a.platform == HOME_PLATFORM)
    home_lead = sum(a.pm_lead for a in cur_ads if a.platform == HOME_PLATFORM)
    db_cpl = round(home_cash / home_lead, 1) if home_lead else 0
    cpl_ok = (f"¥{report.cpl:.0f}" in render or f"¥{int(report.cpl)}" in render) and abs(report.cpl - db_cpl) < 1.0
    lead_ok = str(home_lead) in render
    checks["数字自洽(CPL/留资)"] = cpl_ok and lead_ok
    if not cpl_ok:
        notes.append(f"CPL 与 DB 不一致：报告 ¥{report.cpl:.0f} vs DB ¥{db_cpl:.0f}")
    if not lead_ok:
        notes.append(f"留资数未出现在报告中（DB={home_lead}）")

    # 3) 命中真实异常（必须引用 DB 中真实存在的预警/badcase/阶段信号）
    cust = dbm.get_customer(conn, customer_id)
    alerts = dbm.get_alerts(conn, customer_id=customer_id)
    badcases = dbm.get_badcases(conn, customer_id=customer_id)
    hit_real = False
    hit_detail = ""
    # 真实信号来源：① 生命周期阶段 ② 注入的「异常预警/badcase」标记 ③ alert/badcase 标题片段
    if cust and cust.lifecycle_stage == "at_risk" and "流失风险" in report.diagnosis:
        hit_real = True; hit_detail = "命中真实生命周期阶段(流失风险)"
    if (alerts or badcases) and ("异常预警" in render or "badcase" in render or "预警" in report.diagnosis):
        hit_real = True; hit_detail = hit_detail or "引用了真实预警/badcase"
    if alerts and any(a.title and (a.title[:5] in render or a.alert_type in render) for a in alerts):
        hit_real = True; hit_detail = "引用了真实预警"
    if badcases and any(b.object_name[:5] in render or b.case_type in render for b in badcases):
        hit_real = True; hit_detail = "关联了真实 badcase"
    # 至少命中一条真实信号，且诊断非空
    checks["命中真实异常"] = hit_real and bool(report.diagnosis)
    if not hit_real:
        notes.append("诊断未引用 DB 中真实存在的预警/阶段/badcase 信号（空泛）")

    # 4) 行动可执行（具体杠杆>=2 类）
    levers = ["话术", "出价", "预算", "人群", "素材", "定向", "私信", "加微"]
    used = [l for l in levers if l in report.next_actions]
    checks["行动可执行(>=2杠杆)"] = len(used) >= 2
    if len(used) < 2:
        notes.append(f"行动项杠杆过少（仅 {len(used)} 类），建议覆盖 话术/出价/预算/人群/素材")

    # 5) 对标到位（明确给出行业 CPL 基准 & 本客户相对基准的高低）
    checks["对标行业基准"] = ("行业 CPL 基准" in report.benchmark_comp
                             and ("高于行业" in report.benchmark_comp or "低于行业" in report.benchmark_comp))
    if not checks["对标行业基准"]:
        notes.append("未明确对标行业 CPL 基准/超成本线")

    # 加权计分
    weights = {
        "结构完整(8段)": 20, "数字自洽(CPL/留资)": 25, "命中真实异常": 30,
        "行动可执行(>=2杠杆)": 15, "对标行业基准": 10,
    }
    score = sum(weights[k] for k, v in checks.items() if v)
    passed = [k for k, v in checks.items() if v]
    failed = [k for k, v in checks.items() if not v]

    if score >= 85:
        verdict = "优 · 可直接发送"
    elif score >= 70:
        verdict = "良 · 可发送，建议小幅补充"
    else:
        verdict = "待优化 · 需改写后重测"

    suggestion = ""
    if failed:
        fix_map = {
            "命中真实异常": "在诊断中显式引用该客户的真实预警/阶段/badcase（例：本周 2 条负面反馈 + CPL 超基准×1.2）。",
            "数字自洽(CPL/留资)": "核对 CPL=现金消耗/留资数，确保与 DB 一致并显式写出。",
            "行动可执行(>=2杠杆)": "下一步行动补充到 2 类以上具体杠杆（话术/出价/预算/人群/素材）。",
            "对标行业基准": "补充行业 CPL 基准值与超成本线（基准×1.2）。",
            "结构完整(8段)": "补齐缺失段落。",
        }
        suggestion = "；".join(fix_map.get(f, f"优化【{f}】") for f in failed)

    return {
        "score": score, "checks": checks, "passed": passed, "failed": failed,
        "verdict": verdict, "notes": notes,
        "suggestion": suggestion, "hit_detail": hit_detail,
    }


def evaluate_and_version(conn, customer_id: str, period: str, engine: str = "Mock") -> Dict:
    """生成报告 → 评估 → 落库版本。返回 {report, eval}。"""
    import uuid, datetime
    report = run_weekly_review(conn, customer_id, period, get_llm())
    ev = evaluate_report(conn, report, customer_id, period)
    vid = "RV_" + uuid.uuid4().hex[:10]
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        dbm.save_report_version(conn, vid, customer_id, period, ts,
                                report.diagnosis, report.render(), ev["score"],
                                ev["checks"], ev["verdict"], engine)
    except Exception:
        pass
    return {"report": report, "eval": ev, "version_id": vid}


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    conn = dbm.init_db(os.path.join(here, "..", "data", "adpilot.db"))
    period = dbm.latest_period(conn)
    for cid in ("C001", "C005", "C010"):
        r = evaluate_and_version(conn, cid, period)
        print(f"{cid}: 分数 {r['eval']['score']} / {r['eval']['verdict']}")
        print("  通过:", r['eval']['passed'])
        if r['eval']['failed']:
            print("  未过:", r['eval']['failed'])
            print("  建议:", r['eval']['suggestion'])

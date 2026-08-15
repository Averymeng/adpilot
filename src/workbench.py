"""
workbench.py : AdPilot 多模块工作台渲染层
========================================
把「互联网商业化销售 AI 工作台」拆成 9 个业务模块，统一由 app.py 路由：
  ① 工作台总览  ② 每周复盘  ③ 每日异常预警(盯盘)  ④ 待办与跟进
  ⑤ Badcase 库  ⑥ 竞争媒体情报  ⑦ 行业大盘对标  ⑧ 企微沟通洞察  ⑨ 素材/内容库

所有模块共享同一套归一化数据（schema.py 的 5 张表 + alerts/tasks/badcases 派生表），
并统一「本平台(小红书)=销售经营的客资收集账户 / 竞争媒体=情报视角」的业务视角。
"""
import os
import sys
import ast
import streamlit as st
import pandas as pd
import altair as alt

from weekly_review import (compute_aggregates, run_weekly_review,
                           STAGE_CN, HOME_PLATFORM, PLATFORM_CN)
import db as dbm
from llm import get_llm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

HIDE_CHROME_CSS = """
<style>
#MainMenu {visibility: hidden !important;}
header[data-testid="stHeader"] {display: none !important;}
footer {visibility: hidden !important;}
[data-testid="stToolbar"] {display: none !important;}
[data-testid="stDecoration"] {display: none !important;}
[data-testid="stStatusWidget"] {visibility: hidden !important;}
[data-testid="stDeployButton"] {display: none !important;}
</style>
"""
H3 = '<h3 style="margin: 0.6em 0 0.3em 0; font-size: 1.15rem; font-weight: 600;">{text}</h3>'
H4 = '<h4 style="margin: 0.4em 0 0.2em 0; font-size: 1.0rem; font-weight: 600;">{text}</h4>'

STAGE_CN = STAGE_CN
STAGE_EMOJI = {"at_risk": "🔴 流失风险", "growing": "🟢 高速增长",
               "onboarding": "🟡 新客期", "stable": "🔵 稳定期"}
SEV_EMOJI = {"high": "🔴", "medium": "🟠", "low": "🟡", "info": "🔵"}
SEV_CN = {"high": "高", "medium": "中", "low": "低", "info": "提示"}


# ----------------------------- 共享工具 -----------------------------
def _weeks(conn):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]


def _prev_period(conn, period):
    weeks = _weeks(conn)
    if period in weeks:
        i = weeks.index(period)
        return weeks[i - 1] if i > 0 else period
    return period


def _stage_emoji(stage):
    return STAGE_EMOJI.get(stage, stage)


def _customer_week_agg(conn, cid, period):
    """本平台(小红书)某客户某周的核心聚合（线索经营口径）。"""
    ads = [a for a in dbm.get_ads(conn, cid, period) if a.platform == HOME_PLATFORM]
    all_ads = dbm.get_ads(conn, cid, period)
    cash = sum(a.cash_spend for a in ads)
    budget = sum(a.budget_spend for a in ads)
    lead = sum(a.pm_lead for a in ads)
    opn = sum(a.pm_open for a in ads)
    wx = sum(a.pm_wechat for a in ads)
    cons = sum(a.pm_consult for a in ads)
    all_cash = sum(a.cash_spend for a in all_ads)
    bench = conn.execute(
        "SELECT AVG(benchmark_cpl) FROM benchmarks WHERE platform=? AND industry=? AND period=?",
        (HOME_PLATFORM, dbm.get_customer(conn, cid).industry, period)).fetchone()[0] or 0
    return {
        "cash_home": round(cash, 1),
        "budget_home": round(budget, 1),
        "lead": lead, "open": opn, "wechat": wx, "consult": cons,
        "cpl": round(cash / lead, 1) if lead else 0,
        "util": round(cash / (budget / 1.12) * 100, 1) if budget else 0,
        "open_rate": round(opn / cons * 100, 1) if cons else 0,
        "wechat_rate": round(wx / lead * 100, 1) if lead else 0,
        "bench": round(bench, 1),
        "home_share": round(cash / all_cash * 100, 1) if all_cash else 0,
        "comp_share": round((all_cash - cash) / all_cash * 100, 1) if all_cash else 0,
    }


def _apply_global_filter(customers, f):
    out = []
    for c in customers:
        if f.get("industry") and f["industry"] != "全部" and c.industry != f["industry"]:
            continue
        if f.get("tier") and f["tier"] != "全部" and c.tier != f["tier"]:
            continue
        if f.get("stage") and f["stage"] != "全部" and c.lifecycle_stage != f["stage"]:
            continue
        out.append(c)
    return out


# ================================ ① 工作台总览 ================================
def render_home(conn, f):
    weeks = _weeks(conn)
    period = f.get("week") or weeks[-1]
    customers = [dbm.get_customer(conn, r[0]) for r in
                 conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
    ka = sum(1 for c in customers if c.tier == "KA")
    at_risk = [c for c in customers if c.lifecycle_stage == "at_risk"]

    # 全平台 / 本平台本周消耗
    all_cash = conn.execute(
        "SELECT SUM(cash_spend) FROM ads WHERE period=?", (period,)).fetchone()[0] or 0
    home_cash = conn.execute(
        "SELECT SUM(cash_spend) FROM ads WHERE period=? AND platform=?",
        (period, HOME_PLATFORM)).fetchone()[0] or 0
    # 本平台平均 CPL vs 基准
    cpl_rows = conn.execute(
        "SELECT c.customer_id, SUM(a.cash_spend), SUM(a.pm_lead) FROM ads a "
        "JOIN customers c ON c.customer_id=a.customer_id "
        "WHERE a.period=? AND a.platform=? GROUP BY c.customer_id",
        (period, HOME_PLATFORM)).fetchall()
    tot_cash = sum(r[1] for r in cpl_rows); tot_lead = sum(r[2] for r in cpl_rows)
    avg_cpl = round(tot_cash / tot_lead, 1) if tot_lead else 0
    avg_bench = conn.execute(
        "SELECT AVG(benchmark_cpl) FROM benchmarks WHERE platform=? AND period=?",
        (HOME_PLATFORM, period)).fetchone()[0] or 0
    # 未处理高优预警 / P0 待办
    open_high = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE period=? AND severity='high' AND is_resolved=0",
        (period,)).fetchone()[0]
    p0 = len(dbm.get_tasks(conn, priority="P0"))

    st.markdown(H3.format(text="🏠 工作台总览"), unsafe_allow_html=True)
    st.caption(f"复盘周 {period} · 本平台 = {PLATFORM_CN[HOME_PLATFORM]}（销售经营的客资收集账户）")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("服务客户", f"{len(customers)}", f"KA {ka} / SMB {len(customers)-ka}")
    m2.metric("本周全平台消耗", f"¥{int(all_cash):,}", f"本平台 ¥{int(home_cash):,}")
    m3.metric("本平台平均CPL", f"¥{avg_cpl:.0f}", f"基准 ¥{avg_bench:.0f}（{avg_cpl-avg_bench:+.0f}）")
    m4.metric("流失风险客户", f"{len(at_risk)}", "需优先维稳")
    m5.metric("高优未处理预警", f"{open_high}", "🔴")
    m6.metric("P0 待办", f"{p0}", "本周必须推进")

    # 双 Watchlist：风险 vs 增长
    st.markdown(H4.format(text="📌 重点客户看板"), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🔴 流失风险客户（优先维稳回访）**")
        rows = []
        for c in at_risk:
            a = _customer_week_agg(conn, c.customer_id, period)
            rows.append({"客户": f"{c.name} ({c.customer_id})", "行业": c.industry,
                         "负责人": c.owner, "本平台消耗": f"¥{int(a['cash_home']):,}",
                         "CPL": f"¥{a['cpl']:.0f}", "预算花完率": f"{a['util']:.0f}%",
                         "vs基准": f"{a['cpl']-a['bench']:+.0f}"})
        if rows:
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                         column_config={"客户": st.column_config.TextColumn(width=200)})
    with c2:
        st.markdown("**🟢 高速增长客户（可提案增投）**")
        rows = []
        for c in [c for c in customers if c.lifecycle_stage == "growing"]:
            a = _customer_week_agg(conn, c.customer_id, period)
            rows.append({"客户": f"{c.name} ({c.customer_id})", "行业": c.industry,
                         "负责人": c.owner, "本平台消耗": f"¥{int(a['cash_home']):,}",
                         "CPL": f"¥{a['cpl']:.0f}", "占全平台": f"{a['home_share']:.0f}%",
                         "vs基准": f"{a['cpl']-a['bench']:+.0f}"})
        if rows:
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                         column_config={"客户": st.column_config.TextColumn(width=200)})

    # 近期预警流
    st.markdown(H4.format(text="🔔 近期预警（按严重度）"), unsafe_allow_html=True)
    alerts = dbm.get_alerts(conn)
    alerts = [a for a in alerts if a.period == period and a.severity in ("high", "medium")]
    if alerts:
        for a in alerts[:8]:
            cust = dbm.get_customer(conn, a.customer_id)
            st.markdown(f"{SEV_EMOJI[a.severity]} **[{SEV_CN[a.severity]}] {a.title}** "
                        f"— {cust.name}（{a.customer_id}）：{a.message}")
    else:
        st.success("本周无高/中优预警 ✅")


# ================================ ② 每周复盘 ================================
def render_weekly(conn, f):
    weeks = _weeks(conn)
    period = f.get("week") or weeks[-1]
    use_real = os.environ.get("OPENAI_API_KEY") is not None

    customers = _apply_global_filter(
        [dbm.get_customer(conn, r[0]) for r in
         conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()], f)
    if not customers:
        st.info("当前筛选条件下无客户。")
        return

    # 客户一览表
    rows = []
    for c in customers:
        a = _customer_week_agg(conn, c.customer_id, period)
        rows.append({
            "客户": f"{c.name} ({c.customer_id})", "行业": c.industry, "等级": c.tier,
            "客户阶段": _stage_emoji(c.lifecycle_stage), "负责人": c.owner,
            "本平台现金消耗(¥)": int(a["cash_home"]), "留资成本CPL(¥)": a["cpl"],
            "留资数": a["lead"], "加微数": a["wechat"],
            "预算花完率": f"{a['util']:.0f}%", "竞争媒体占比": f"{a['comp_share']}%",
        })
    df = pd.DataFrame(rows)
    hc1, hc2 = st.columns([6, 1.3])
    with hc1:
        st.markdown(H4.format(text="客户一览"), unsafe_allow_html=True)
    with hc2:
        cid_options = [f"{c.name} ({c.customer_id})" for c in customers]
        cid_map = {f"{c.name} ({c.customer_id})": c.customer_id for c in customers}
        sel = st.selectbox("选择复盘对象", cid_options, key="wk_sel", label_visibility="collapsed")
        cid = cid_map[sel]
        gen = st.button("▶ 生成本周复盘", type="primary", width='stretch', key="wk_gen")

    if not df.empty:
        st.dataframe(df, width='stretch', hide_index=True,
                     column_config={"客户": st.column_config.TextColumn(width=260),
                                    "本平台现金消耗(¥)": st.column_config.NumberColumn(format="%d")})
        st.caption(f"已加载 {len(df)} 个客户 · 复盘周 {period} · 本平台：{PLATFORM_CN[HOME_PLATFORM]} · "
                   f"引擎：{'OpenAI' if use_real else 'Mock'}")

    if gen:
        st.session_state["wk_generated"] = cid
    if st.session_state.get("wk_generated") and cid:
        _render_report(conn, cid, period)
    else:
        st.info("👆 选择客户后点击「生成本周复盘」。")


def _render_report(conn, cid, period):
    with st.spinner("AI 生成中…"):
        prev = _prev_period(conn, period)
        contents = dbm.get_contents(conn, {a.content_id for a in dbm.get_ads(conn, cid, period)})
        comms = dbm.get_comms(conn, cid, period)
        agg_all = compute_aggregates(conn, cid, period, prev, contents, comms)
        agg_home = compute_aggregates(conn, cid, period, prev, contents, comms, platform=HOME_PLATFORM)
        r = run_weekly_review(conn, cid, period, get_llm())
        weeks = _weeks(conn)

    profile = dbm.get_customer(conn, cid)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("客户", f"{profile.name} ({profile.customer_id})")
    c2.metric("行业", profile.industry)
    c3.metric("等级", profile.tier)
    c4.metric("负责人", profile.owner)
    c5.metric("客户阶段", _stage_emoji(profile.lifecycle_stage))

    st.markdown(H4.format(text="【一句话诊断】"), unsafe_allow_html=True)
    if profile.lifecycle_stage == "at_risk":
        st.error(r.diagnosis)
    elif profile.lifecycle_stage == "growing":
        st.success(r.diagnosis)
    else:
        st.info(r.diagnosis)

    cur = agg_home["cur"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("留资成本 CPL", f"¥{r.cpl:.0f}", f"行业基准 ¥{r.cpl_benchmark:.0f}（{r.cpl-r.cpl_benchmark:+.0f}）")
    m2.metric("留资数", f"{cur['pm_lead']:,}", f"{agg_home['wow']['pm_lead']:+.1f}% WoW")
    m3.metric("加微数", f"{cur['pm_wechat']:,}", f"{agg_home['wow']['pm_wechat']:+.1f}% WoW")
    m4.metric("预算花完率", f"{cur['budget_util']:.0f}%", help="实际现金消耗 / 计划预算（广告币折算）")

    st.markdown(H3.format(text="① 总览与结论"), unsafe_allow_html=True)
    st.markdown(r.overview)
    st.markdown(H3.format(text="② 私信转化漏斗（咨询 → 开口 → 留资 → 加微信）"), unsafe_allow_html=True)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("私信咨询", f"{cur['pm_consult']:,}", f"咨询成本 ¥{cur['consult_cost']:.0f}")
    p2.metric("私信开口", f"{cur['pm_open']:,}", f"开口率 {cur['open_rate']:.0f}% · 开口成本 ¥{cur['open_cost']:.0f}")
    p3.metric("私信留资", f"{cur['pm_lead']:,}", f"留资率 {cur['lead_rate']:.0f}% · **CPL ¥{cur['cpl']:.0f}**")
    p4.metric("添加微信", f"{cur['pm_wechat']:,}", f"加微率 {cur['wechat_rate']:.0f}% · 加微成本 ¥{cur['wechat_cost']:.0f}")
    funnel_df = pd.DataFrame([
        {"阶段": "咨询", "值": cur['pm_consult']}, {"阶段": "开口", "值": cur['pm_open']},
        {"阶段": "留资", "值": cur['pm_lead']}, {"阶段": "加微信", "值": cur['pm_wechat']}])
    st.altair_chart(alt.Chart(funnel_df).mark_bar().encode(
        x=alt.X("阶段:N", title=None, sort=["咨询", "开口", "留资", "加微信"], axis=alt.Axis(labelAngle=0)),
        y=alt.Y("值:Q", title="人数"),
        color=alt.Color("阶段:N", scale=alt.Scale(scheme="tealblues"), legend=None), tooltip=["阶段", "值"]).
        properties(height=240, title="本平台私信转化漏斗"), width='stretch')
    st.markdown(r.pm_funnel)

    st.markdown(H3.format(text="③ 出价与预算效率"), unsafe_allow_html=True)
    kfs_rows = []
    for ad_type in ("信息流", "搜索"):
        d = agg_home["kfs"][ad_type]
        if d["cash"] == 0:
            continue
        kfs_rows.append({"KFS 位置": ad_type, "现金消耗(¥)": int(d["cash"]), "CPL(¥)": round(d["cpl"], 1),
                         "CPC(¥)": d["cpc"], "CTR": f"{d['ctr']*100:.2f}%"})
    if kfs_rows:
        st.dataframe(pd.DataFrame(kfs_rows), width='stretch', hide_index=True)
    bid_rows = [{"出价方式": bt, "现金消耗(¥)": int(d["cash"]), "CPL(¥)": round(d["cpl"], 1), "CPC(¥)": d["cpc"]}
                for bt, d in sorted(agg_home["by_bid"].items(), key=lambda x: -x[1]["cash"])]
    if bid_rows:
        st.markdown("**出价方式分布**")
        st.dataframe(pd.DataFrame(bid_rows), width='stretch', hide_index=True)
    st.markdown(r.bid_budget)

    st.markdown(H3.format(text="④ 人群与地域"), unsafe_allow_html=True)
    demo = agg_home.get("demo")
    if demo:
        d1, d2, d3 = st.columns(3)
        d1.metric("主力地域", demo.top_region); d2.metric("兴趣关键词", demo.top_interest)
        d3.metric("25-40岁占比", f"{(demo.age_25_30+demo.age_31_40)*100:.0f}%")
        age_df = pd.DataFrame([
            {"年龄段": "25-30", "占比(%)": demo.age_25_30*100}, {"年龄段": "31-40", "占比(%)": demo.age_31_40*100},
            {"年龄段": "41-50", "占比(%)": demo.age_41_50*100}, {"年龄段": "50+", "占比(%)": demo.age_50_plus*100}])
        st.altair_chart(alt.Chart(age_df).mark_bar().encode(
            x=alt.X("年龄段:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("占比(%):Q", title="占比 %"),
            color=alt.Color("年龄段:N", scale=alt.Scale(scheme="blues"), legend=None), tooltip=["年龄段", "占比(%)"]).
            properties(height=220), width='stretch')
    aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: x[1]["cpl"])
    aud_df = pd.DataFrame([{"人群维度": k, "现金消耗(¥)": int(d["cash"]), "留资数": d["lead"], "CPL(¥)": round(d["cpl"], 1)}
                           for k, d in aud_sorted])
    if not aud_df.empty:
        st.markdown("**按定向方式拆 CPL**")
        st.dataframe(aud_df, width='stretch', hide_index=True)
    st.markdown(r.audience_geo)

    st.markdown(H3.format(text="⑤ 笔记 / 素材（线索视角）"), unsafe_allow_html=True)
    ct_sorted = sorted(agg_home["by_content"].items(), key=lambda x: x[1]["cpl"])
    ct_rows = [{"素材标题": d["title"][:32], "CTR": f"{d['ctr']*100:.2f}%",
                "留资成本CPL(¥)": round(d["cpl"], 1), "现金消耗(¥)": int(d["cash"])} for _, d in ct_sorted]
    if ct_rows:
        st.markdown(f"**爆文率 {agg_home['burst_rate']}% · 平均互动率 {agg_home['engage_avg']}%**")
        st.dataframe(pd.DataFrame(ct_rows), width='stretch', hide_index=True)
    st.markdown(r.content_lead)

    st.markdown(H3.format(text="⑥ 话术与承接"), unsafe_allow_html=True)
    s1, s2, s3 = st.columns(3)
    s1.metric("开口率", f"{cur['open_rate']:.0f}%", help="话术健康度（行业健康线 ~45%）")
    s2.metric("留资转化率", f"{cur['lead_rate']:.0f}%", help="自动回复 / 留资卡承接")
    s3.metric("加微率", f"{cur['wechat_rate']:.0f}%", help="商家名片 / 私域引导")
    st.markdown(r.script)

    st.markdown(H3.format(text="⑦ 行业对标 + 竞争媒体情报"), unsafe_allow_html=True)
    st.markdown(f"**行业 CPL 基准（{profile.industry}）：¥{r.cpl_benchmark:.0f} / 条；"
                f"本客户 ¥{r.cpl:.0f}（{r.cpl-r.cpl_benchmark:+.0f}）。**")
    comp_rows = []
    total_all = agg_all["cur"]["cash_spend"]
    for p, d in agg_all["by_platform"].items():
        if p == HOME_PLATFORM:
            continue
        share = round(d["cash"]/total_all*100, 1) if total_all else 0
        comp_rows.append({"竞争平台": PLATFORM_CN.get(p, p), "现金消耗(¥)": int(d["cash"]),
                          "CPL(¥)": round(d["cpl"], 1), "占全平台比": f"{share}%"})
    if comp_rows:
        st.dataframe(pd.DataFrame(comp_rows), width='stretch', hide_index=True)
    st.caption(f"客户全平台预算中，【{PLATFORM_CN[HOME_PLATFORM]}】占 {r.home_share}%，竞争媒体合计占 {r.comp_share}%。")
    st.markdown(r.benchmark_comp)

    st.markdown(H3.format(text="⑧ 下一步行动"), unsafe_allow_html=True)
    st.markdown(r.next_actions)

    st.markdown(H4.format(text="📈 跨周趋势（本平台）"), unsafe_allow_html=True)
    hist_rows = []
    for w in weeks:
        ads = [a for a in dbm.get_ads(conn, cid, w) if a.platform == HOME_PLATFORM]
        sp = sum(a.cash_spend for a in ads); lead = sum(a.pm_lead for a in ads)
        hist_rows.append({"period": w, "现金消耗": int(sp), "留资成本CPL": round(sp/lead, 1) if lead else 0, "留资数": lead})
    history = pd.DataFrame(hist_rows)
    if not history.empty:
        trend_long = history.melt(id_vars=["period"], value_vars=["现金消耗", "留资成本CPL", "留资数"],
                                  var_name="指标", value_name="值")
        st.altair_chart(alt.Chart(trend_long).mark_line(point=True).encode(
            x=alt.X("period:N", title="周", sort=weeks, axis=alt.Axis(labelAngle=0)), y=alt.Y("值:Q"),
            color=alt.Color("指标:N", scale=alt.Scale(scheme="category10")), tooltip=["period", "指标", "值"]).
            properties(height=260), width='stretch')

    with st.expander("📄 完整 Markdown 报告"):
        st.code(r.render(), language="markdown")
        st.download_button("📥 下载报告 (.md)", r.render(), file_name=f"adpilot_{cid}_{period}.md", mime="text/markdown")


# ================================ ③ 每日异常预警（盯盘） ================================
def render_alerts(conn, f):
    period = f.get("week") or _weeks(conn)[-1]
    st.markdown(H3.format(text="🔔 每日异常预警（盯盘助手）"), unsafe_allow_html=True)
    st.caption("规则引擎基于小红书聚光「盯盘助手」逻辑：掉量(消耗环比↓>30%) / 超成本(CPL>基准×1.2) / "
               "成本上升(CPL环比↑>30%) / 预算花不完(<70%) / 负面反馈 / 高潜增投。")

    sev = st.radio("严重度", ["全部", "high", "medium", "low", "info"], horizontal=True,
                   format_func=lambda x: {"全部": "全部", "high": "🔴 高", "medium": "🟠 中",
                                          "low": "🟡 低", "info": "🔵 提示"}[x])
    only_week = st.checkbox("只看本周", value=True)

    alerts = dbm.get_alerts(conn, severity=None if sev == "全部" else sev)
    if only_week:
        alerts = [a for a in alerts if a.period == period]
    # 全局行业/等级/阶段筛选
    cust_ids = {c.customer_id for c in _apply_global_filter(
        [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers").fetchall()], f)}
    if f.get("industry") and f["industry"] != "全部":
        alerts = [a for a in alerts if a.customer_id in cust_ids]

    st.markdown(f"共 {len(alerts)} 条预警")
    if not alerts:
        st.success("无预警 ✅")
        return
    for a in alerts:
        cust = dbm.get_customer(conn, a.customer_id)
        with st.expander(f"{SEV_EMOJI[a.severity]} [{SEV_CN[a.severity]}] {a.title} — {cust.name}（{a.customer_id}）· {a.period}"):
            st.markdown(f"**指标**：{a.metric_name} = {a.metric_value}（阈值 {a.threshold}）")
            st.markdown(f"**现象**：{a.message}")
            st.info(f"**建议动作**：{a.suggested_action}")


# ================================ ④ 待办与跟进 ================================
def render_tasks(conn, f):
    st.markdown(H3.format(text="✅ 待办与跟进"), unsafe_allow_html=True)
    st.caption("来自「每周复盘行动项 + 异常预警 + 企微投诉」的拆解，按优先级排期。")

    prio = st.radio("优先级", ["全部", "P0", "P1", "P2"], horizontal=True)
    tasks = dbm.get_tasks(conn, priority=None if prio == "全部" else prio)
    cust_ids = {c.customer_id for c in _apply_global_filter(
        [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers").fetchall()], f)}
    if f.get("industry") and f["industry"] != "全部":
        tasks = [t for t in tasks if t.customer_id in cust_ids]

    rows = []
    for t in tasks:
        cust = dbm.get_customer(conn, t.customer_id)
        rows.append({"优先级": t.priority, "客户": f"{cust.name} ({t.customer_id})", "来源": t.source,
                     "事项": t.title, "详情": t.detail, "负责人": t.owner,
                     "建议截止": t.due_week, "状态": t.status})
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                     column_config={"客户": st.column_config.TextColumn(width=200),
                                    "详情": st.column_config.TextColumn(width=300)})
    else:
        st.success("暂无待办 ✅")


# ================================ ⑤ Badcase 库 ================================
def render_badcase(conn, f):
    st.markdown(H3.format(text="🗂️ Badcase 库（归因沉淀）"), unsafe_allow_html=True)
    st.caption("高成本计划 / 低质素材的归因与修复沉淀，对应真实复盘中「素材复盘 / 人群复盘」资产。")
    ctype = st.radio("类型", ["全部", "高成本计划", "低质素材"], horizontal=True)
    cases = dbm.get_badcases(conn)
    if ctype != "全部":
        cases = [c for c in cases if c.case_type == ctype]
    if f.get("industry") and f["industry"] != "全部":
        cust_ids = {c.customer_id for c in _apply_global_filter(
            [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers").fetchall()], f)}
        cases = [c for c in cases if c.customer_id in cust_ids]

    if not cases:
        st.success("暂无 Badcase ✅")
        return
    for c in cases:
        cust = dbm.get_customer(conn, c.customer_id)
        with st.expander(f"[{c.case_type}] {c.object_name} — {cust.name}（{c.customer_id}）· {c.period}"):
            st.markdown(f"**现象**：{c.symptom}")
            st.markdown(f"**根因**：{c.root_cause}")
            st.markdown(f"**修复**：{c.fix}")
            if c.impact_value:
                st.warning(f"💸 估算预算浪费：¥{c.impact_value:,.0f}")


# ================================ ⑥ 竞争媒体情报 ================================
def render_competitor(conn, f):
    weeks = _weeks(conn)
    period = f.get("week") or weeks[-1]
    st.markdown(H3.format(text="🧭 竞争媒体情报"), unsafe_allow_html=True)
    st.caption("客户在各平台的投放分布与 CPL 对比：本平台(小红书)是客资收集主阵地，抖音/腾讯/快手为竞争媒体（情报视角）。")

    customers = _apply_global_filter(
        [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()], f)
    opts = [f"{c.name} ({c.customer_id})" for c in customers]
    cid_map = {f"{c.name} ({c.customer_id})": c.customer_id for c in customers}
    sel = st.selectbox("选择客户", opts, key="comp_sel")
    cid = cid_map[sel]

    rows = []
    for p in ("xhs", "douyin", "tencent", "kuaishou"):
        ads = [a for a in dbm.get_ads(conn, cid, period) if a.platform == p]
        cash = sum(a.cash_spend for a in ads); lead = sum(a.pm_lead for a in ads)
        rows.append({"平台": PLATFORM_CN.get(p, p), "现金消耗(¥)": int(cash), "留资数": lead,
                     "CPL(¥)": round(cash/lead, 1) if lead else 0, "计划数": len(ads)})
    df = pd.DataFrame(rows)
    total = df["现金消耗(¥)"].sum()
    df["占全平台比"] = (df["现金消耗(¥)"]/total*100).round(1).astype(str) + "%"
    st.dataframe(df, width='stretch', hide_index=True)
    st.altair_chart(alt.Chart(df).mark_bar().encode(
        x=alt.X("平台:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("现金消耗(¥):Q", title="现金消耗"),
        color=alt.Color("平台:N", legend=None), tooltip=["平台", "现金消耗(¥)", "CPL(¥)", "占全平台比"]).
        properties(height=260, title="各平台现金消耗分布"), width='stretch')
    home = df[df["平台"] == PLATFORM_CN[HOME_PLATFORM]].iloc[0]
    st.markdown(f"**结论**：本平台 CPL ¥{home['CPL(¥)']:.0f}，占全平台消耗 {home['占全平台比']}。"
                f"若本平台 CPL 优于竞争媒体，应作为**增预算 / 挪量**的支点，把客户更多预算拉到本平台。")


# ================================ ⑦ 行业大盘对标 ================================
def render_benchmark(conn, f):
    st.markdown(H3.format(text="📊 行业大盘对标"), unsafe_allow_html=True)
    weeks = _weeks(conn)
    industries = [r[0] for r in conn.execute("SELECT DISTINCT industry FROM benchmarks ORDER BY industry").fetchall()]
    ind = st.selectbox("行业", industries, key="bm_ind")
    ad_type = st.radio("投放位置", ["全部", "信息流", "搜索"], horizontal=True)
    rows = []
    for w in weeks:
        q = "SELECT AVG(benchmark_cpl), AVG(avg_ctr) FROM benchmarks WHERE platform=? AND industry=? AND period=?"
        args = [HOME_PLATFORM, ind, w]
        if ad_type != "全部":
            q += " AND ad_type=?"; args.append(ad_type)
        r = conn.execute(q, args).fetchone()
        if r and r[0]:
            rows.append({"周": w, "行业CPL(¥)": round(r[0], 1), "行业CTR": round(r[1]*100, 2)})
    df = pd.DataFrame(rows)
    if not df.empty:
        st.altair_chart(alt.Chart(df).mark_line(point=True).encode(
            x=alt.X("周:N", title="周", sort=weeks, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("行业CPL(¥):Q", title="行业留资成本 CPL"),
            tooltip=["周", "行业CPL(¥)", "行业CTR"]).properties(height=260,
            title=f"{ind} 行业 CPL 基准走势（{PLATFORM_CN[HOME_PLATFORM]}）"), width='stretch')

    # 客户 vs 基准（最新周）
    period = weeks[-1]
    st.markdown(H4.format(text="客户 CPL vs 行业基准（最新周）"), unsafe_allow_html=True)
    bench = conn.execute(
        "SELECT AVG(benchmark_cpl) FROM benchmarks WHERE platform=? AND industry=? AND period=?",
        (HOME_PLATFORM, ind, period)).fetchone()[0] or 0
    rows = []
    for c in [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers WHERE industry=? ORDER BY customer_id", (ind,)).fetchall()]:
        a = _customer_week_agg(conn, c.customer_id, period)
        rows.append({"客户": f"{c.name} ({c.customer_id})", "本平台CPL(¥)": a["cpl"],
                     "行业基准(¥)": round(bench, 1), "vs基准": f"{a['cpl']-bench:+.0f}",
                     "预算花完率": f"{a['util']:.0f}%"})
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                     column_config={"客户": st.column_config.TextColumn(width=220)})


# ================================ ⑧ 企微沟通洞察 ================================
def render_comms(conn, f):
    st.markdown(H3.format(text="💬 企微沟通洞察"), unsafe_allow_html=True)
    st.caption("企业微信会话存档（adapter 真实接入点，本demo为 Mock）。洞察客户情绪、投诉主题与续费信号。")

    # 全局情绪分布
    total = conn.execute("SELECT COUNT(*) FROM comms").fetchone()[0]
    pos = conn.execute("SELECT COUNT(*) FROM comms WHERE sentiment='positive'").fetchone()[0]
    neu = conn.execute("SELECT COUNT(*) FROM comms WHERE sentiment='neutral'").fetchone()[0]
    neg = total - pos - neu
    s1, s2, s3 = st.columns(3)
    s1.metric("正面", f"{pos}", f"{pos/total*100:.0f}%")
    s2.metric("中性", f"{neu}", f"{neu/total*100:.0f}%")
    s3.metric("负面", f"{neg}", f"{neg/total*100:.0f}%")

    customers = _apply_global_filter(
        [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()], f)
    opts = ["全部"] + [f"{c.name} ({c.customer_id})" for c in customers]
    cid_map = {f"{c.name} ({c.customer_id})": c.customer_id for c in customers}
    sel = st.selectbox("查看客户沟通", opts, key="com_sel")
    where = "" if sel == "全部" else f"AND customer_id='{cid_map[sel]}'"
    msgs = conn.execute(
        f"SELECT customer_id, sender_role, intent_tag, sentiment, text, timestamp FROM comms "
        f"WHERE 1=1 {where} ORDER BY timestamp DESC LIMIT 60").fetchall()
    rows = []
    for cid, role, intent, sent, text, ts in msgs:
        cust = dbm.get_customer(conn, cid)
        rows.append({"客户": f"{cust.name}", "角色": "客户" if role == "customer" else "销售",
                     "意图": intent, "情绪": {"positive": "😊正面", "neutral": "😐中性", "negative": "😠负面"}[sent],
                     "内容": text, "时间": ts})
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True,
                     column_config={"内容": st.column_config.TextColumn(width=360)})
    else:
        st.info("暂无沟通记录。")


# ================================ ⑨ 素材 / 内容库 ================================
def render_content(conn, f):
    st.markdown(H3.format(text="🎨 素材 / 内容库"), unsafe_allow_html=True)
    st.caption("小红书笔记（绑定投放）。按互动率、是否爆文、原创度与绑定计划的 CTR 评估素材质量。")

    customers = _apply_global_filter(
        [dbm.get_customer(conn, r[0]) for r in conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()], f)
    cust_ids = [c.customer_id for c in customers]
    if not cust_ids:
        st.info("当前筛选无客户。"); return
    notes = conn.execute(
        f"SELECT content_id, platform, format, title, key_metrics, is_original, share_cnt FROM contents "
        f"WHERE content_id IN (SELECT DISTINCT content_id FROM ads WHERE customer_id IN "
        f"({','.join('?'*len(cust_ids))}))", cust_ids).fetchall()
    rows = []
    for nid, platform, fmt, title, km, is_orig, share in notes:
        d = ast.literal_eval(km) if isinstance(km, str) else km
        # 该笔记绑定计划的 CTR
        bound = conn.execute(
            "SELECT ctr FROM ads WHERE content_id=? AND impressions>0", (nid,)).fetchall()
        avg_ctr = round(sum(r[0] for r in bound)/len(bound)*100, 2) if bound else 0
        cust = conn.execute(
            "SELECT c.customer_id, c.name FROM ads a JOIN customers c ON c.customer_id=a.customer_id "
            "WHERE a.content_id=? LIMIT 1", (nid,)).fetchone()
        rows.append({"素材": title[:30], "客户": cust[1] if cust else "-",
                     "形式": fmt, "互动率": f"{d.get('engage_rate',0)*100:.1f}%",
                     "爆文": d.get("is_hot", ""), "原创": "是" if is_orig else "否",
                     "绑定CTR": f"{avg_ctr}%", "分享": share})
    df = pd.DataFrame(rows).drop_duplicates(subset=["素材", "客户"])
    st.dataframe(df, width='stretch', hide_index=True,
                 column_config={"素材": st.column_config.TextColumn(width=240)})
    st.caption(f"共 {len(df)} 篇笔记。互动率健康线 ~5%；绑定 CTR<2% 的素材建议重做封面标题（见 Badcase 库）。")


# --------------------------- 💬 AI 助手（Agent 编排层） ---------------------------
def render_agent(conn, f):
    """对话式入口：自然语言 → 意图识别 → 调用后端工具(DB) → 多步编排 → 可观测轨迹。"""
    st.markdown(H3.format(text="💬 AI 助手 · AdPilot Agent"), unsafe_allow_html=True)
    st.caption("非纯前端：底层是 Python 后端 + SQLite + 工具调用工作流 + 业务语义 System Prompt。"
               "输入自然语言，agent 会自主选工具、查真实数据、给出可执行的复盘结论。")

    engine = "OpenAI" if os.environ.get("OPENAI_API_KEY") else "Mock（基于真实数据调度）"
    st.info(f"🧠 引擎：{engine} ｜ 业务本体：小红书线索经营（CPL / 留资 / 加微 / 私信漏斗）")

    # 示例问句
    examples = [
        "帮我复盘一下 C001",
        "C003 这周有哪些异常预警？",
        "C005 的高成本计划有哪些，怎么优化？",
        "C002 的 CPL 在行业里算什么水平？",
        "客户 C004 在其他平台投了多少？",
        "C007 整体情况怎么样？",
    ]
    cols = st.columns(3)
    for i, ex in enumerate(examples):
        if cols[i % 3].button(ex, key=f"ex_{i}"):
            st.session_state["agent_input"] = ex

    q = st.text_input("向 AdPilot 提问（可指定客户编号，如 C001）",
                      value=st.session_state.get("agent_input", ""),
                      key="agent_q", placeholder="例如：帮我复盘 C001，并看看它的异常预警")

    if st.button("🚀 运行 Agent", key="agent_run") and q.strip():
        cust = None
        for r in conn.execute("SELECT customer_id, name FROM customers").fetchall():
            if r[0].lower() in q.lower() or r[1] in q:
                cust = r[0]; break
        default_cid = cust or "C001"
        with st.spinner("Agent 正在编排工具调用…"):
            import agent as agent_mod
            result = agent_mod.run_agent(conn, q, default_cid=default_cid)

        # 轨迹（可观测）
        with st.expander("🔍 Agent 运行轨迹（意图 → 工具 → 观察）", expanded=True):
            st.markdown(f"**识别意图**：`{result['intent']}` ｜ **调用工具数**：{result['tool_count']} ｜ **引擎**：{result['engine']}")
            for i, s in enumerate(result["steps"], 1):
                st.markdown(f"**Step {i} · {s['tool']}**  `参数: {s['args']}`")
                st.markdown(f"&nbsp;&nbsp;↳ 观察：{s['observation']}")

        # 回答
        st.markdown("### 📌 Agent 回答")
        st.markdown(result["answer"])

    # 历史运行（来自 DB agent_logs，证明可观测）
    with st.expander("🗂 历史运行记录（持久化于 agent_logs）"):
        runs = dbm.recent_agent_runs(conn, 10)
        if not runs:
            st.caption("暂无运行记录。")
        else:
            for rid, ts, query, intent, tcount, eng in runs:
                st.markdown(f"`{ts}` ｜ `{eng}` ｜ 意图 `{intent}` ｜ 工具 {tcount} ｜ {query}")


# --------------------------- 🧪 报告评测与版本（评估-优化闭环） ---------------------------
def render_eval(conn, f):
    """评估器给报告打分 → 低分自动给出改写方向 → 版本留存 / 回测对比。"""
    st.markdown(H3.format(text="🧪 报告评测与版本 · 评估-优化闭环"), unsafe_allow_html=True)
    st.caption("对标 xhslink 分享的「评估器打分 → 低分归因改写 → 版本留存」逻辑："
               "每版复盘报告都经评分器校验（结构/数字/命中真实异常/行动/对标），低分自动给出改写方向。")

    cids = [r[0] for r in conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
    cid_options = [f"{r[0]} · {dbm.get_customer(conn, r[0]).name}" for r in [(c,) for c in cids]]
    sel = st.selectbox("选择复盘对象", cid_options, key="ev_sel", label_visibility="collapsed")
    cid = sel.split(" · ")[0]
    period = f["week"]

    if st.button("🔄 生成并评测本报告", key="ev_run"):
        with st.spinner("生成报告 + 评估器打分中…"):
            import evaluator as ev_mod
            res = ev_mod.evaluate_and_version(conn, cid, period)
            ev = res["eval"]

        # 分数卡
        score = ev["score"]
        color = "🟢" if score >= 85 else ("🟡" if score >= 70 else "🔴")
        st.markdown(f"### {color} 评分 **{score}/100** · {ev['verdict']}")
        if ev["hit_detail"]:
            st.success(f"✅ 命中真实信号：{ev['hit_detail']}")

        # 检查清单
        st.markdown("**评估维度**")
        for k, v in ev["checks"].items():
            st.markdown(f"{'✅' if v else '❌'} {k}")
        if ev["notes"]:
            with st.expander("⚠️ 细节提示"):
                for n in ev["notes"]:
                    st.markdown(f"• {n}")

        # 低分 → 优化建议（闭环核心）
        if ev["failed"]:
            st.markdown("### 🛠 优化建议（低分归因改写方向）")
            st.info(ev["suggestion"])
            if st.button("🔁 按建议重测并对比分数", key="ev_rerun"):
                with st.spinner("重新生成并评测…"):
                    res2 = ev_mod.evaluate_and_version(conn, cid, period)
                    ev2 = res2["eval"]
                delta = ev2["score"] - score
                st.markdown(f"重测分数 **{ev2['score']}/100**（{'↑' if delta>=0 else '↓'} {abs(delta)}）")
                if ev2["failed"]:
                    st.markdown("仍需优化：" + "、".join(ev2["failed"]))
                else:
                    st.success("已达标 ✅")

        # 报告预览
        with st.expander("📄 本版报告全文", expanded=False):
            st.markdown(res["report"].render())

    # 版本历史（回测对比）
    with st.expander("🗂 版本历史（report_versions）", expanded=True):
        vers = dbm.list_report_versions(conn, customer_id=cid, limit=15)
        if not vers:
            st.caption("该客户暂无报告版本，先点上方「生成并评测」生成第一版。")
        else:
            rows = [{"版本": v[0][:14], "周期": v[2], "时间": v[3], "分数": v[4],
                     "结论": v[5], "引擎": v[6]} for v in vers]
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
            sc = [v[4] for v in vers]
            if len(sc) >= 2:
                st.caption(f"近 {len(sc)} 版分数走势：{' → '.join(str(s) for s in reversed(sc))}（趋势："
                           f"{'上升 ↑' if sc[0] > sc[-1] else '下降 ↓' if sc[0] < sc[-1] else '持平 →'}）")

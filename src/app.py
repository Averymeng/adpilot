"""
app.py : AdPilot 网页演示 v8
===========================
v8 业务定位：小红书「线索经营」商业化销售周报。
核心 KPI：留资成本 CPL / 加微成本 / 开口率（不是 GMV/ROI）。
视角：本平台（小红书）= 销售经营的客资收集账户 = 复盘核心；竞争媒体 = 情报视角。

UI（按用户反馈）：
- 隐藏 Streamlit 原生英文 UI（toolbar/main menu/deploy/status/footer）
- 侧边栏「筛选」：行业 / 等级 / 客户阶段 / 复盘周，Excel 式下拉
- 「复盘对象」并入筛选模块（联动下拉），不再单独成块
- 「客户一览」标题左、右上角「▶ 生成本周复盘」按钮
- 「客户」列固定 260px，品牌名 + 编号完整显示
- 无外链 / 跳转按钮；图表横坐标文字横排
"""
import os
import sys
import streamlit as st
import pandas as pd
import altair as alt

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "data", "adpilot.db")
sys.path.insert(0, HERE)
import db as dbm
from weekly_review import (run_weekly_review, compute_aggregates, STAGE_CN,
                           HOME_PLATFORM, PLATFORM_CN)
from llm import get_llm


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


@st.cache_resource
def get_conn():
    if not os.path.exists(DB_PATH):
        import main; main.build()
    return dbm.init_db(DB_PATH)


def _weeks(conn):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]


def _prev_period(conn, period):
    weeks = _weeks(conn)
    if period in weeks:
        i = weeks.index(period)
        return weeks[i - 1] if i > 0 else period
    return period


def _customer_history(conn, cid, weeks):
    """跨周趋势：现金消耗 & 留资成本 CPL & 留资数（本平台）。"""
    rows = []
    for w in weeks:
        ads = [a for a in dbm.get_ads(conn, cid, w) if a.platform == HOME_PLATFORM]
        sp = sum(a.cash_spend for a in ads)
        lead = sum(a.pm_lead for a in ads)
        rows.append({"period": w, "现金消耗": int(sp),
                     "留资成本CPL": round(sp / lead, 1) if lead else 0,
                     "留资数": lead})
    return pd.DataFrame(rows)


def _stage_emoji(stage):
    return {"at_risk": "🔴 流失风险", "growing": "🟢 高速增长",
            "onboarding": "🟡 新客期", "stable": "🔵 稳定期"}.get(stage, stage)


def _overview_table(conn, weeks, filter_industry=None, filter_tier=None, filter_stage=None):
    """默认页面显示的全量客户表（本平台线索经营视角）。"""
    customers = [dbm.get_customer(conn, r[0]) for r in conn.execute(
        "SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
    latest = weeks[-1] if weeks else None
    if not latest:
        return pd.DataFrame()
    rows = []
    for c in customers:
        if filter_industry and filter_industry != "全部" and c.industry != filter_industry:
            continue
        if filter_tier and filter_tier != "全部" and c.tier != filter_tier:
            continue
        if filter_stage and filter_stage != "全部" and c.lifecycle_stage != filter_stage:
            continue
        ads_all = dbm.get_ads(conn, c.customer_id, latest)
        ads_home = [a for a in ads_all if a.platform == HOME_PLATFORM]
        sp = sum(a.cash_spend for a in ads_home)
        lead = sum(a.pm_lead for a in ads_home)
        wx = sum(a.pm_wechat for a in ads_home)
        cpl = round(sp / lead, 1) if lead else 0
        util = 0.0
        bsum = sum(a.budget_spend for a in ads_home)
        util = round(sp / (bsum / 1.12) * 100, 1) if bsum else 0
        all_sp = sum(a.cash_spend for a in ads_all)
        comp_share = round((all_sp - sp) / all_sp * 100, 1) if all_sp else 0
        rows.append({
            "客户": f"{c.name} ({c.customer_id})",
            "行业": c.industry, "等级": c.tier,
            "客户阶段": _stage_emoji(c.lifecycle_stage),
            "负责人": c.owner,
            "本平台现金消耗(¥)": int(sp),
            "留资成本CPL(¥)": cpl,
            "留资数": lead,
            "加微数": wx,
            "预算花完率": f"{util:.0f}%",
            "竞争媒体占比": f"{comp_share}%",
        })
    return pd.DataFrame(rows)


def main():
    st.set_page_config(page_title="AdPilot · 线索经营周报", page_icon="📊", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)

    conn = get_conn()
    llm = get_llm()
    use_real = os.environ.get("OPENAI_API_KEY") is not None
    weeks = _weeks(conn)
    home_cn = PLATFORM_CN.get(HOME_PLATFORM, HOME_PLATFORM)
    latest = weeks[-1] if weeks else None

    st.markdown(H3.format(text="📊 AdPilot · 小红书线索经营周报工作台"), unsafe_allow_html=True)
    st.info(f"本工作台视角：销售代表 **【{home_cn}】** 服务客户 → 复盘核心 = 客户在{home_cn}的「客资收集」账户"
            f"（KPI：留资成本 / 加微）；客户在抖音 / 腾讯 / 快手等投放视为**竞争媒体**（情报视角）。")

    industries = ["全部"] + [r[0] for r in conn.execute(
        "SELECT DISTINCT industry FROM customers ORDER BY industry").fetchall()]
    tiers = ["全部", "KA", "SMB"]

    # —— 筛选模块（Excel 式下拉）——
    with st.sidebar:
        st.markdown(H4.format(text="筛选"), unsafe_allow_html=True)
        f_industry = st.selectbox("行业", industries, index=0, key="f_industry")
        f_tier = st.selectbox("等级", tiers, index=0, key="f_tier")
        f_stage = st.selectbox("客户阶段", ["全部", "流失风险", "高速增长", "稳定期", "新客期"],
                               index=0, key="f_stage")
        f_stage_key = {"全部": "全部", "流失风险": "at_risk", "高速增长": "growing",
                       "稳定期": "stable", "新客期": "onboarding"}[f_stage]
        period = st.selectbox("复盘周", weeks, index=len(weeks) - 1, key="f_period")

        st.divider()
        all_cust = [r[0] for r in conn.execute(
            "SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
        avail = []
        for c in all_cust:
            cu = dbm.get_customer(conn, c)
            if f_industry != "全部" and cu.industry != f_industry:
                continue
            if f_tier != "全部" and cu.tier != f_tier:
                continue
            if f_stage_key != "全部" and cu.lifecycle_stage != f_stage_key:
                continue
            avail.append(cu)
        display = [f"{cu.name} ({cu.customer_id})" for cu in avail]
        cid_map = {f"{cu.name} ({cu.customer_id})": cu.customer_id for cu in avail}
        if display:
            sel = st.selectbox("复盘对象（选客户生成复盘）", display, index=0, key="f_cid")
            cid = cid_map[sel]
        else:
            st.caption("当前筛选条件下无客户")
            cid = None

    # ---- 客户一览：右上角「生成本周复盘」按钮 ----
    overview = _overview_table(conn, weeks, f_industry, f_tier, f_stage_key)
    hc1, hc2 = st.columns([6, 1.3])
    with hc1:
        st.markdown(H4.format(text="客户一览"), unsafe_allow_html=True)
    with hc2:
        gen_clicked = st.button("▶ 生成本周复盘", type="primary",
                                use_container_width=True, key="gen_btn")
    if overview.empty:
        st.caption("当前筛选条件下无客户。")
    else:
        st.dataframe(overview, use_container_width=True, hide_index=True,
                     column_config={
                         "客户": st.column_config.TextColumn(width=260),
                         "本平台现金消耗(¥)": st.column_config.NumberColumn(format="%d"),
                     })
        st.caption(f"已加载 {len(overview)} 个客户 · 数据周 {period} · 本平台：{home_cn} · 引擎：{'OpenAI' if use_real else 'Mock'}")

    st.divider()

    if cid is None:
        st.info("当前筛选条件下无可选客户，请调整左侧筛选。")
    elif gen_clicked:
        with st.spinner("AI 生成中…"):
            prev = _prev_period(conn, period)
            contents = dbm.get_contents(conn, {a.content_id for a in dbm.get_ads(conn, cid, period)})
            comms = dbm.get_comms(conn, cid, period)
            agg_all = compute_aggregates(conn, cid, period, prev, contents, comms)
            agg_home = compute_aggregates(conn, cid, period, prev, contents, comms,
                                         platform=HOME_PLATFORM)
            r = run_weekly_review(conn, cid, period, llm)

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

        # 关键指标卡（线索经营视角）
        cur = agg_home["cur"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("留资成本 CPL", f"¥{r.cpl:.0f}",
                  f"行业基准 ¥{r.cpl_benchmark:.0f}（{r.cpl - r.cpl_benchmark:+.0f}）")
        m2.metric("留资数", f"{cur['pm_lead']:,}", f"{agg_home['wow']['pm_lead']:+.1f}% WoW")
        m3.metric("加微数", f"{cur['pm_wechat']:,}", f"{agg_home['wow']['pm_wechat']:+.1f}% WoW")
        m4.metric("预算花完率", f"{cur['budget_util']:.0f}%",
                  help="实际现金消耗 / 计划预算（广告币折算）")

        # ① 总览与结论
        st.markdown(H3.format(text="① 总览与结论"), unsafe_allow_html=True)
        st.markdown(r.overview)

        # ② 私信转化漏斗（4 段）
        st.markdown(H3.format(text="② 私信转化漏斗（咨询 → 开口 → 留资 → 加微信）"), unsafe_allow_html=True)
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("私信咨询", f"{cur['pm_consult']:,}", f"咨询成本 ¥{cur['consult_cost']:.0f}")
        p2.metric("私信开口", f"{cur['pm_open']:,}",
                  f"开口率 {cur['open_rate']:.0f}% · 开口成本 ¥{cur['open_cost']:.0f}")
        p3.metric("私信留资", f"{cur['pm_lead']:,}",
                  f"留资率 {cur['lead_rate']:.0f}% · **CPL ¥{cur['cpl']:.0f}**")
        p4.metric("添加微信", f"{cur['pm_wechat']:,}",
                  f"加微率 {cur['wechat_rate']:.0f}% · 加微成本 ¥{cur['wechat_cost']:.0f}")
        funnel_df = pd.DataFrame([
            {"阶段": "咨询", "值": cur['pm_consult']},
            {"阶段": "开口", "值": cur['pm_open']},
            {"阶段": "留资", "值": cur['pm_lead']},
            {"阶段": "加微信", "值": cur['pm_wechat']},
        ])
        st.altair_chart(
            alt.Chart(funnel_df).mark_bar().encode(
                x=alt.X("阶段:N", title=None, sort=["咨询", "开口", "留资", "加微信"],
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("值:Q", title="人数"),
                color=alt.Color("阶段:N", scale=alt.Scale(scheme="tealblues"), legend=None),
                tooltip=["阶段", "值"],
            ).properties(height=240, title="本平台私信转化漏斗"),
            use_container_width=True,
        )
        st.markdown(r.pm_funnel)

        # ③ 出价与预算效率
        st.markdown(H3.format(text="③ 出价与预算效率"), unsafe_allow_html=True)
        kfs_rows = []
        for ad_type in ("信息流", "搜索"):
            d = agg_home["kfs"][ad_type]
            if d["cash"] == 0:
                continue
            kfs_rows.append({
                "KFS 位置": ad_type,
                "现金消耗(¥)": int(d["cash"]),
                "CPL(¥)": round(d["cpl"], 1),
                "CPC(¥)": d["cpc"],
                "CTR": f"{d['ctr']*100:.2f}%",
            })
        if kfs_rows:
            st.dataframe(pd.DataFrame(kfs_rows), use_container_width=True, hide_index=True)
        bid_rows = [{"出价方式": bt, "现金消耗(¥)": int(d["cash"]),
                     "CPL(¥)": round(d["cpl"], 1), "CPC(¥)": d["cpc"]}
                    for bt, d in sorted(agg_home["by_bid"].items(), key=lambda x: -x[1]["cash"])]
        if bid_rows:
            st.markdown("**出价方式分布**")
            st.dataframe(pd.DataFrame(bid_rows), use_container_width=True, hide_index=True)
        st.markdown(r.bid_budget)

        # ④ 人群与地域
        st.markdown(H3.format(text="④ 人群与地域"), unsafe_allow_html=True)
        demo = agg_home.get("demo")
        if demo:
            d1, d2, d3 = st.columns(3)
            d1.metric("主力地域", demo.top_region)
            d2.metric("兴趣关键词", demo.top_interest)
            d3.metric("25-40岁占比", f"{(demo.age_25_30 + demo.age_31_40)*100:.0f}%")
            age_df = pd.DataFrame([
                {"年龄段": "25-30", "占比(%)": demo.age_25_30*100},
                {"年龄段": "31-40", "占比(%)": demo.age_31_40*100},
                {"年龄段": "41-50", "占比(%)": demo.age_41_50*100},
                {"年龄段": "50+", "占比(%)": demo.age_50_plus*100},
            ])
            st.altair_chart(
                alt.Chart(age_df).mark_bar().encode(
                    x=alt.X("年龄段:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("占比(%):Q", title="占比 %"),
                    color=alt.Color("年龄段:N", scale=alt.Scale(scheme="blues"), legend=None),
                    tooltip=["年龄段", "占比(%)"],
                ).properties(height=220),
                use_container_width=True,
            )
        aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: x[1]["cpl"])
        aud_df = pd.DataFrame([{
            "人群维度": k, "现金消耗(¥)": int(d["cash"]),
            "留资数": d["lead"], "CPL(¥)": round(d["cpl"], 1),
        } for k, d in aud_sorted])
        if not aud_df.empty:
            st.markdown("**按定向方式拆 CPL**")
            st.dataframe(aud_df, use_container_width=True, hide_index=True)
        st.markdown(r.audience_geo)

        # ⑤ 笔记/素材（线索视角）
        st.markdown(H3.format(text="⑤ 笔记 / 素材（线索视角）"), unsafe_allow_html=True)
        ct_sorted = sorted(agg_home["by_content"].items(), key=lambda x: x[1]["cpl"])
        ct_rows = []
        for _, d in ct_sorted:
            ct_rows.append({
                "素材标题": d["title"][:32],
                "CTR": f"{d['ctr']*100:.2f}%",
                "留资成本CPL(¥)": round(d["cpl"], 1),
                "现金消耗(¥)": int(d["cash"]),
            })
        if ct_rows:
            st.markdown(f"**爆文率 {agg_home['burst_rate']}% · 平均互动率 {agg_home['engage_avg']}%**")
            st.dataframe(pd.DataFrame(ct_rows), use_container_width=True, hide_index=True)
        st.markdown(r.content_lead)

        # ⑥ 话术与承接
        st.markdown(H3.format(text="⑥ 话术与承接"), unsafe_allow_html=True)
        s1, s2, s3 = st.columns(3)
        s1.metric("开口率", f"{cur['open_rate']:.0f}%", help="话术健康度（行业健康线 ~45%）")
        s2.metric("留资转化率", f"{cur['lead_rate']:.0f}%", help="自动回复 / 留资卡承接")
        s3.metric("加微率", f"{cur['wechat_rate']:.0f}%", help="商家名片 / 私域引导")
        st.markdown(r.script)

        # ⑦ 行业对标 + 竞争媒体
        st.markdown(H3.format(text="⑦ 行业对标 + 竞争媒体情报"), unsafe_allow_html=True)
        st.markdown(f"**行业 CPL 基准（{profile.industry}）：¥{r.cpl_benchmark:.0f} / 条；"
                    f"本客户 ¥{r.cpl:.0f}（{r.cpl - r.cpl_benchmark:+.0f}）。**")
        comp_rows = []
        total_all = agg_all["cur"]["cash_spend"]
        for p, d in agg_all["by_platform"].items():
            if p == HOME_PLATFORM:
                continue
            share = round(d["cash"] / total_all * 100, 1) if total_all else 0
            comp_rows.append({
                "竞争平台": PLATFORM_CN.get(p, p),
                "现金消耗(¥)": int(d["cash"]),
                "CPL(¥)": round(d["cpl"], 1),
                "占全平台比": f"{share}%",
            })
        if comp_rows:
            st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
        st.caption(f"客户全平台预算中，【{home_cn}】占 {r.home_share}%，竞争媒体合计占 {r.comp_share}%。"
                   f"若本平台 CPL 更优，应作为增预算 / 挪量话术支点。")
        st.markdown(r.benchmark_comp)

        # ⑧ 下一步行动
        st.markdown(H3.format(text="⑧ 下一步行动"), unsafe_allow_html=True)
        st.markdown(r.next_actions)

        # 跨周趋势（CPL / 消耗）
        st.markdown(H4.format(text="📈 跨周趋势（本平台）"), unsafe_allow_html=True)
        history = _customer_history(conn, cid, weeks)
        if not history.empty:
            trend_long = history.melt(id_vars=["period"], value_vars=["现金消耗", "留资成本CPL", "留资数"],
                                      var_name="指标", value_name="值")
            st.altair_chart(
                alt.Chart(trend_long).mark_line(point=True).encode(
                    x=alt.X("period:N", title="周", sort=weeks, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("值:Q"),
                    color=alt.Color("指标:N", scale=alt.Scale(scheme="category10")),
                    tooltip=["period", "指标", "值"],
                ).properties(height=260),
                use_container_width=True,
            )

        with st.expander("📄 完整 Markdown 报告"):
            st.code(r.render(), language="markdown")
            st.download_button("📥 下载报告 (.md)", r.render(),
                               file_name=f"adpilot_{cid}_{period}.md", mime="text/markdown")


if __name__ == "__main__":
    main()

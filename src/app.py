"""
app.py : AdPilot 网页演示 v3
===========================
- 隐藏 Streamlit 英文工具栏 / 部署按钮 / 底栏
- 标题用 HTML 渲染（去掉 markdown 自动的锚点 # 图标）
- 客户阶段（替代"生命周期"）
- 侧边栏筛选：行业 / 等级 / 客户阶段
- 打开默认显示：全部客户总览表
- 客户信息条 4 指标改为 5 指标（行业 / 等级 拆开）
- 关键指标卡顺序：GMV / 消耗 / ROI / 转化
- CTR / CVR 一律以百分数呈现
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
from weekly_review import run_weekly_review, compute_aggregates, STAGE_CN
from llm import get_llm


# ---------- 隐藏 Streamlit 自带英文 UI ----------
HIDE_CHROME_CSS = """
<style>
#MainMenu {visibility: hidden;}
header[data-testid="stHeader"] {display: none;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {visibility: hidden;}
[data-testid="stDecoration"] {display: none;}
[data-testid="stStatusWidget"] {visibility: hidden;}
</style>
"""

H3 = '<h3 style="margin: 0.6em 0 0.3em 0; font-size: 1.15rem; font-weight: 600;">{text}</h3>'
H4 = '<h4 style="margin: 0.4em 0 0.2em 0; font-size: 1.0rem; font-weight: 600;">{text}</h4>'


@st.cache_resource
def get_conn():
    if not os.path.exists(DB_PATH):
        import main; main.build()
    return dbm.init_db(DB_PATH)


def _prev_period(conn, period):
    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
    if period in weeks:
        i = weeks.index(period)
        return weeks[i - 1] if i > 0 else period
    return period


def _customer_history(conn, cid, weeks):
    rows = []
    for w in weeks:
        ads = dbm.get_ads(conn, cid, w)
        sp = sum(a.spend for a in ads); gm = sum(a.gmv for a in ads)
        cv = sum(a.conversions for a in ads)
        rows.append({
            "period": w,
            "spend": int(sp), "gmv": int(gm),
            "roi": round(gm / sp, 2) if sp else 0,
            "conv": cv,
        })
    return pd.DataFrame(rows)


def _stage_emoji(stage):
    return {"at_risk": "🔴 流失风险", "growing": "🟢 高速增长",
            "onboarding": "🟡 新客期", "stable": "🔵 稳定期"}.get(stage, stage)


def _overview_table(conn, filter_industry=None, filter_tier=None, filter_stage=None):
    """默认页面显示的全量客户表。"""
    customers = [dbm.get_customer(conn, r[0]) for r in conn.execute(
        "SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
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
        ads = dbm.get_ads(conn, c.customer_id, latest)
        sp = sum(a.spend for a in ads); gm = sum(a.gmv for a in ads)
        cv = sum(a.conversions for a in ads); im = sum(a.impressions for a in ads)
        clk = sum(a.clicks for a in ads)
        rows.append({
            "客户": f"{c.name}  ({c.customer_id})",
            "行业": c.industry, "等级": c.tier,
            "客户阶段": _stage_emoji(c.lifecycle_stage),
            "负责人": c.owner,
            "本周消耗(¥)": int(sp),
            "本周GMV(¥)": int(gm),
            "ROI": round(gm / sp, 2) if sp else 0,
            "CTR": f"{(clk/im*100 if im else 0):.2f}%",
            "本周转化": cv,
        })
    return pd.DataFrame(rows)


def main():
    st.set_page_config(page_title="AdPilot · 投放复盘", page_icon="📊", layout="wide")
    st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)

    conn = get_conn()
    llm = get_llm()
    use_real = os.environ.get("OPENAI_API_KEY") is not None

    st.markdown(H3.format(text="📊 AdPilot · 互联网商业化投放复盘工作台"), unsafe_allow_html=True)

    industries = ["全部"] + [r[0] for r in conn.execute(
        "SELECT DISTINCT industry FROM customers ORDER BY industry").fetchall()]
    tiers = ["全部", "KA", "SMB"]
    stages = ["全部", "at_risk", "growing", "stable", "onboarding"]

    with st.sidebar:
        st.markdown(H4.format(text="⚙️ 筛选"), unsafe_allow_html=True)
        f_industry = st.selectbox("行业", industries, index=0)
        f_tier = st.selectbox("等级", tiers, index=0)
        f_stage = st.selectbox("客户阶段", ["全部", "流失风险", "高速增长", "稳定期", "新客期"], index=0)
        f_stage_key = {"全部": "全部", "流失风险": "at_risk", "高速增长": "growing",
                       "稳定期": "stable", "新客期": "onboarding"}[f_stage]

        st.divider()
        st.markdown(H4.format(text="🔍 单客户复盘"), unsafe_allow_html=True)
        avail = [r[0] for r in conn.execute(
            "SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
        cid = st.selectbox("客户编号", avail, index=0)
        weeks = [r[0] for r in conn.execute(
            "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
        period = st.selectbox("周", weeks, index=len(weeks) - 1)
        st.divider()
        st.write(f"**报告引擎**：{'🟢 真实 OpenAI' if use_real else '🟡 Mock 模板'}")

    # ---- 默认：全量客户总览 ----
    st.markdown(H4.format(text="📋 全部客户本周总览"), unsafe_allow_html=True)
    overview = _overview_table(conn, f_industry, f_tier, f_stage_key)
    st.dataframe(overview, use_container_width=True, hide_index=True,
                 column_config={
                     "本周消耗(¥)": st.column_config.NumberColumn(format="%d"),
                     "本周GMV(¥)": st.column_config.NumberColumn(format="%d"),
                 })
    st.caption(f"已加载 {len(overview)} 个客户 · 数据周 {period} · 引擎：{'OpenAI' if use_real else 'Mock'}")

    st.divider()

    if st.button("▶ 生成本周复盘", type="primary"):
        with st.spinner("AI 生成中…"):
            r = run_weekly_review(conn, cid, period, llm)
            contents = dbm.get_contents(conn, {a.content_id for a in dbm.get_ads(conn, cid, period)})
            comms = dbm.get_comms(conn, cid, period)
            agg = compute_aggregates(conn, cid, period, _prev_period(conn, period), contents, comms)

        profile = dbm.get_customer(conn, cid)

        # 客户信息条（5 个指标：客户名 / 行业 / 等级 / 负责人 / 客户阶段）
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("客户", f"{profile.name}  ({profile.customer_id})")
        c2.metric("行业", profile.industry)
        c3.metric("等级", profile.tier)
        c4.metric("负责人", profile.owner)
        c5.metric("客户阶段", _stage_emoji(profile.lifecycle_stage))

        # 一句话诊断
        st.markdown(H4.format(text="【一句话诊断】"), unsafe_allow_html=True)
        if profile.lifecycle_stage == "at_risk":
            st.error(r.diagnosis)
        elif profile.lifecycle_stage == "growing":
            st.success(r.diagnosis)
        else:
            st.info(r.diagnosis)

        # 关键指标卡（GMV / 消耗 / ROI / 转化 + CTR 百分数）
        cur, wow = agg["cur"], agg["wow"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("GMV ¥", f"{int(cur['gmv']):,}", f"{wow['gmv']:+.1f}% WoW")
        m2.metric("消耗 ¥", f"{int(cur['spend']):,}", f"{wow['spend']:+.1f}% WoW")
        m3.metric("ROI", f"{cur['roi']}", f"{wow['roi']:+.2f} WoW")
        m4.metric("转化", f"{cur['conversions']:,}",
                  f"CTR {cur['ctr']*100:.2f}% · CVR {cur['cvr']*100:.2f}%")

        # ① 总览与结论
        st.markdown(H3.format(text="① 总览与结论"), unsafe_allow_html=True)
        st.markdown(r.overview)

        # ② 广告布局 / 漏斗分配
        st.markdown(H3.format(text="② 广告布局 / 漏斗分配"), unsafe_allow_html=True)
        plat_rows = []
        for p, d in sorted(agg["by_platform"].items(), key=lambda x: -x[1]["spend"]):
            bench = agg["bench"].get(p) or 0
            plat_rows.append({
                "平台": p, "消耗(¥)": int(d["spend"]), "GMV(¥)": int(d["gmv"]),
                "ROI": d["roi"], "行业基准 ROI": bench, "vs 基准": round(d["roi"] - bench, 2),
            })
        st.dataframe(pd.DataFrame(plat_rows), use_container_width=True, hide_index=True)
        chart_df = pd.DataFrame([
            {"平台": row["平台"], "类型": k, "值": v}
            for row in plat_rows
            for k, v in [("实际 ROI", row["ROI"]), ("行业基准", row["行业基准 ROI"])]
        ])
        st.altair_chart(
            alt.Chart(chart_df).mark_bar().encode(
                x=alt.X("平台:N", title=None),
                y=alt.Y("值:Q", title="ROI"),
                color=alt.Color("类型:N", scale=alt.Scale(scheme="set2")),
                xOffset="类型:N",
                tooltip=["平台", "类型", "值"],
            ).properties(height=280),
            use_container_width=True,
        )
        st.caption(r.layout.split("\n")[-1] if r.layout else "")

        # ③ 各层级成效 + 跨周趋势
        st.markdown(H3.format(text="③ 各层级成效（按周对比趋势）"), unsafe_allow_html=True)
        history = _customer_history(conn, cid, weeks)
        if not history.empty:
            trend_long = history.melt(id_vars=["period"],
                                      value_vars=["spend", "gmv", "roi"],
                                      var_name="指标", value_name="值")
            st.altair_chart(
                alt.Chart(trend_long).mark_line(point=True).encode(
                    x=alt.X("period:N", title="周", sort=weeks),
                    y=alt.Y("值:Q"),
                    color=alt.Color("指标:N", scale=alt.Scale(scheme="category10")),
                    tooltip=["period", "指标", "值"],
                ).properties(height=280),
                use_container_width=True,
            )
        st.markdown(r.layer_perf)

        # ④ 广告组合成效
        st.markdown(H3.format(text="④ 广告组合成效（受众 + 素材双维度）"), unsafe_allow_html=True)
        aud_sorted = sorted(agg["by_audience"].items(), key=lambda x: -x[1]["roi"])
        aud_df = pd.DataFrame([{
            "人群": k, "消耗(¥)": int(d["spend"]), "GMV(¥)": int(d["gmv"]),
            "转化": d["conv"], "ROI": d["roi"],
        } for k, d in aud_sorted])
        st.markdown("**人群维度（按 ROI 降序）**")
        st.dataframe(aud_df, use_container_width=True, hide_index=True)

        ct_sorted = sorted(agg["by_content"].items(), key=lambda x: -x[1]["roi"])
        ct_df = pd.DataFrame([{
            "素材标题": d["title"][:28], "消耗(¥)": int(d["spend"]),
            "GMV(¥)": int(d["gmv"]), "转化": d["conv"], "ROI": d["roi"],
        } for _, d in ct_sorted])
        st.markdown("**素材维度（按 ROI 降序）**")
        st.dataframe(ct_df, use_container_width=True, hide_index=True)
        st.caption(r.combo_perf)

        # ⑤ 下一步行动
        st.markdown(H3.format(text="⑤ 下一步行动"), unsafe_allow_html=True)
        st.markdown(r.next_actions)

        with st.expander("📄 完整 Markdown 报告"):
            st.code(r.render(), language="markdown")


if __name__ == "__main__":
    main()

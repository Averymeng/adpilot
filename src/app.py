"""
app.py : AdPilot 网页演示 v4
===========================
视角修正：本平台（小红书）= 销售经营的账户 = 复盘核心；
          竞争媒体（抖音/腾讯/快手）= 客户跨平台投放 = 情报视角。
- 隐藏 Streamlit 原生英文工具栏（无法汉化），改用侧边栏中文按钮替代
- 客户阶段 / 筛选 / 默认全量总览 / CTR·CVR 百分数 / 本平台视角
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


# ---------- 隐藏 Streamlit 自带英文 UI（其文字写死英文，无法汉化）----------
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


def _weeks(conn):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]


def _customer_history(conn, cid, weeks, platform):
    rows = []
    for w in weeks:
        ads = [a for a in dbm.get_ads(conn, cid, w) if a.platform == platform]
        sp = sum(a.spend for a in ads); gm = sum(a.gmv for a in ads)
        cv = sum(a.conversions for a in ads)
        rows.append({"period": w, "spend": int(sp), "gmv": int(gm),
                     "roi": round(gm / sp, 2) if sp else 0, "conv": cv})
    return pd.DataFrame(rows)


def _stage_emoji(stage):
    return {"at_risk": "🔴 流失风险", "growing": "🟢 高速增长",
            "onboarding": "🟡 新客期", "stable": "🔵 稳定期"}.get(stage, stage)


def _overview_table(conn, weeks, filter_industry=None, filter_tier=None, filter_stage=None):
    """默认页面显示的全量客户表（以【本平台】为视角）。"""
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
        sp = sum(a.spend for a in ads_home); gm = sum(a.gmv for a in ads_home)
        cv = sum(a.conversions for a in ads_home)
        im = sum(a.impressions for a in ads_home); clk = sum(a.clicks for a in ads_home)
        all_sp = sum(a.spend for a in ads_all)
        comp_share = round((all_sp - sp) / all_sp * 100, 1) if all_sp else 0
        rows.append({
            "客户": f"{c.name}  ({c.customer_id})",
            "行业": c.industry, "等级": c.tier,
            "客户阶段": _stage_emoji(c.lifecycle_stage),
            "负责人": c.owner,
            f"本平台消耗(¥)": int(sp),
            f"本平台GMV(¥)": int(gm),
            "本平台ROI": round(gm / sp, 2) if sp else 0,
            "CTR": f"{(clk/im*100 if im else 0):.2f}%",
            "本周转化": cv,
            "竞争媒体占比": f"{comp_share}%",
        })
    return pd.DataFrame(rows)


def main():
    st.set_page_config(page_title="AdPilot · 投放复盘", page_icon="📊", layout="wide")
    st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)

    conn = get_conn()
    llm = get_llm()
    use_real = os.environ.get("OPENAI_API_KEY") is not None
    weeks = _weeks(conn)
    home_cn = PLATFORM_CN.get(HOME_PLATFORM, HOME_PLATFORM)

    st.markdown(H3.format(text="📊 AdPilot · 互联网商业化投放复盘工作台"), unsafe_allow_html=True)
    st.info(f"本工作台视角：销售代表 **【{home_cn}】** 服务客户 → 复盘核心 = 客户在{home_cn}的账户；"
            f"客户在抖音 / 腾讯 / 快手等投放视为**竞争媒体**（情报视角）。")

    industries = ["全部"] + [r[0] for r in conn.execute(
        "SELECT DISTINCT industry FROM customers ORDER BY industry").fetchall()]
    tiers = ["全部", "KA", "SMB"]

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
        period = st.selectbox("周", weeks, index=len(weeks) - 1)

        st.divider()
        # —— 中文按钮（替代无法汉化的 Streamlit 原生英文菜单）——
        st.markdown(H4.format(text="🛠 操作"), unsafe_allow_html=True)
        if st.button("🔄 重新生成模拟数据"):
            import main as _m
            _m.build()
            st.cache_resource.clear()
            st.rerun()
        st.write(f"**报告引擎**：{'🟢 真实 OpenAI' if use_real else '🟡 Mock 模板'}")
        st.caption("ℹ️ Streamlit 原生右上角菜单为英文且无法汉化，已用上方中文按钮替代。")

    # ---- 默认：全量客户总览（本平台视角）----
    st.markdown(H4.format(text="📋 全部客户本周总览（本平台视角）"), unsafe_allow_html=True)
    overview = _overview_table(conn, weeks, f_industry, f_tier, f_stage_key)
    st.dataframe(overview, use_container_width=True, hide_index=True,
                 column_config={
                     "本平台消耗(¥)": st.column_config.NumberColumn(format="%d"),
                     "本平台GMV(¥)": st.column_config.NumberColumn(format="%d"),
                 })
    st.caption(f"已加载 {len(overview)} 个客户 · 数据周 {period} · 本平台：{home_cn} · 引擎：{'OpenAI' if use_real else 'Mock'}")

    st.divider()

    if st.button("▶ 生成本周复盘", type="primary"):
        with st.spinner("AI 生成中…"):
            prev = _prev_period(conn, period)
            r = run_weekly_review(conn, cid, period, llm)
            contents = dbm.get_contents(conn, {a.content_id for a in dbm.get_ads(conn, cid, period)})
            comms = dbm.get_comms(conn, cid, period)
            agg_all = compute_aggregates(conn, cid, period, prev, contents, comms)
            agg_home = compute_aggregates(conn, cid, period, prev, contents, comms,
                                          platform=HOME_PLATFORM)

        profile = dbm.get_customer(conn, cid)

        # 客户信息条
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

        # 关键指标卡（本平台）
        cur, wow = agg_home["cur"], agg_home["wow"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"本平台 GMV ¥", f"{int(cur['gmv']):,}", f"{wow['gmv']:+.1f}% WoW")
        m2.metric(f"本平台 消耗 ¥", f"{int(cur['spend']):,}", f"{wow['spend']:+.1f}% WoW")
        m3.metric("本平台 ROI", f"{cur['roi']}", f"{wow['roi']:+.2f} WoW")
        m4.metric("本平台 转化", f"{cur['conversions']:,}",
                  f"CTR {cur['ctr']*100:.2f}% · CVR {cur['cvr']*100:.2f}%")

        # ① 总览与结论
        st.markdown(H3.format(text="① 总览与结论"), unsafe_allow_html=True)
        st.markdown(r.overview)

        # ② 广告布局 / 漏斗分配（跨平台，本平台 vs 竞争媒体）
        st.markdown(H3.format(text="② 广告布局 / 漏斗分配"), unsafe_allow_html=True)
        plat_rows = []
        total_all = agg_all["cur"]["spend"]
        for p, d in sorted(agg_all["by_platform"].items(), key=lambda x: -x[1]["spend"]):
            bench = agg_all["bench"].get(p) or 0
            share = round(d["spend"] / total_all * 100, 1) if total_all else 0
            plat_rows.append({
                "平台": f"{PLATFORM_CN.get(p, p)}" + ("【本平台】" if p == HOME_PLATFORM else "（竞争媒体）"),
                "消耗(¥)": int(d["spend"]), "GMV(¥)": int(d["gmv"]),
                "ROI": d["roi"], "占全平台比": f"{share}%",
                "行业基准 ROI": bench, "vs 基准": round(d["roi"] - bench, 2),
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

        # 🌐 竞争媒体投放分布（情报视角）
        st.markdown(H3.format(text="🌐 竞争媒体投放分布（情报视角）"), unsafe_allow_html=True)
        comp_rows = []
        for p, d in agg_all["by_platform"].items():
            if p == HOME_PLATFORM:
                continue
            comp_rows.append({
                "竞争平台": PLATFORM_CN.get(p, p),
                "消耗(¥)": int(d["spend"]), "GMV(¥)": int(d["gmv"]),
                "ROI": d["roi"],
                "占全平台比": f"{round(d['spend']/total_all*100, 1)}%" if total_all else "0%",
            })
        if comp_rows:
            st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
            st.caption(f"客户全平台预算中，竞争媒体合计占 {r.comp_share}%，"
                       f"【{home_cn}】仅占 {r.home_share}%。"
                       f"若{home_cn} ROI 更优，应作为增预算 / 挪量话术支点。")
        else:
            st.caption("该客户暂无竞争媒体投放。")

        # ③ 各层级成效（本平台）+ 跨周趋势
        st.markdown(H3.format(text="③ 各层级成效（按周对比趋势）"), unsafe_allow_html=True)
        history = _customer_history(conn, cid, weeks, HOME_PLATFORM)
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

        # ④ 广告组合成效（本平台：受众 + 素材）
        st.markdown(H3.format(text="④ 广告组合成效（受众 + 素材双维度）"), unsafe_allow_html=True)
        aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: -x[1]["roi"])
        aud_df = pd.DataFrame([{
            "人群": k, "消耗(¥)": int(d["spend"]), "GMV(¥)": int(d["gmv"]),
            "转化": d["conv"], "ROI": d["roi"],
        } for k, d in aud_sorted])
        st.markdown("**受众维度（按 ROI 降序）**")
        st.dataframe(aud_df, use_container_width=True, hide_index=True)

        ct_sorted = sorted(agg_home["by_content"].items(), key=lambda x: -x[1]["roi"])
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
            st.download_button("📥 下载报告 (.md)", r.render(),
                               file_name=f"adpilot_{cid}_{period}.md", mime="text/markdown")


if __name__ == "__main__":
    main()

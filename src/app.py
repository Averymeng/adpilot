"""
app.py : AdPilot 网页演示（Streamlit v2）
- ①-⑤ 严格按编号顺序渲染（修复顺序错位）
- 数据用表格 + Altair 干净图表（修复 bar_chart 奇怪条纹）
- 顶部客户信息卡 + 关键指标卡
- ③ 加跨周趋势折线图（新增图表类型）
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
from weekly_review import run_weekly_review, compute_aggregates
from llm import get_llm


@st.cache_resource
def get_conn():
    if not os.path.exists(DB_PATH):
        import main; main.build()
    return dbm.init_db(DB_PATH)


def _stage_label(stage):
    return {"at_risk": "RED 风险", "growing": "GREEN 增长",
            "onboarding": "YELLOW 新接", "stable": "BLUE 平稳"}.get(stage, stage)


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


def main():
    st.set_page_config(page_title="AdPilot", page_icon="📊", layout="wide")
    conn = get_conn()
    llm = get_llm()
    use_real = os.environ.get("OPENAI_API_KEY") is not None

    st.title("📊 AdPilot · 互联网商业化投放复盘工作台")
    st.caption("MVP 锚点：每周投放复盘 = 一句话诊断 + RACAE 五段式 ｜ 架构：最小公共 schema + adapter 归一化")

    cids = [r[0] for r in conn.execute(
        "SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]

    with st.sidebar:
        st.header("⚙️ 复盘配置")
        cid = st.selectbox("选择客户", cids, index=0)
        period = st.selectbox("选择周", weeks, index=len(weeks) - 1)
        st.divider()
        st.write("**报告引擎**", "🟢 真实 OpenAI" if use_real else "🟡 Mock 模板")
        if not use_real:
            st.info("设置 OPENAI_API_KEY 环境变量后切换为真实自然语言。")
        st.divider()
        n_c = len(cids); n_ads = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
        st.write(f"客户 {n_c} · 广告 {n_ads} · 周 {len(weeks)}")

    if st.button("▶ 生成本周复盘", type="primary"):
        with st.spinner("AI 生成中…"):
            r = run_weekly_review(conn, cid, period, llm)
            contents = dbm.get_contents(conn, {a.content_id for a in dbm.get_ads(conn, cid, period)})
            comms = dbm.get_comms(conn, cid, period)
            agg = compute_aggregates(conn, cid, period, _prev_period(conn, period), contents, comms)

        profile = dbm.get_customer(conn, cid)

        # 客户信息条
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("客户", profile.customer_id)
        c2.metric("行业 / 等级", f"{profile.industry} / {profile.tier}")
        c3.metric("负责人", profile.owner)
        c4.metric("生命周期", _stage_label(profile.lifecycle_stage))

        # 一句话诊断
        st.markdown("#### 【一句话诊断】")
        stage = profile.lifecycle_stage
        if stage == "at_risk":
            st.error(r.diagnosis)
        elif stage == "growing":
            st.success(r.diagnosis)
        else:
            st.info(r.diagnosis)

        # 关键指标卡
        cur, wow = agg["cur"], agg["wow"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("消耗 ¥", f"{int(cur['spend']):,}", f"{wow['spend']:+.1f}% WoW")
        m2.metric("GMV ¥", f"{int(cur['gmv']):,}", f"{wow['gmv']:+.1f}% WoW")
        m3.metric("ROI", f"{cur['roi']}", f"{wow['roi']:+.2f} WoW")
        m4.metric("转化 / CTR", f"{cur['conversions']:,}", f"CTR {cur['ctr']*100:.2f}%")

        # ① 总览与结论
        st.markdown("### ① 总览与结论")
        st.markdown(r.overview)

        # ② 广告布局 / 漏斗分配：表格 + Altair 分组柱图
        st.markdown("### ② 广告布局 / 漏斗分配")
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

        # ③ 各层级成效：跨周趋势折线 + 文字
        st.markdown("### ③ 各层级成效（按周对比趋势）")
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

        # ④ 广告组合成效：双表格 + 文字
        st.markdown("### ④ 广告组合成效（受众 + 素材双维度）")
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
        st.markdown("### ⑤ 下一步行动")
        st.markdown(r.next_actions)

        with st.expander("📄 完整 Markdown 报告"):
            st.code(r.render(), language="markdown")

        st.caption(f"报告引擎：{'真实 OpenAI' if use_real else 'Mock 模板'} · "
                   f"数据：{os.path.basename(DB_PATH)}")


if __name__ == "__main__":
    main()

"""
app.py : AdPilot 网页演示 v5
===========================
视角：本平台（小红书）= 销售经营的账户 = 复盘核心；竞争媒体 = 客户跨平台投放 = 情报视角。

UI 改进（按用户反馈）：
- 隐藏 Streamlit 原生英文 UI（toolbar/main menu/deploy/status/footer）
- 侧边栏「筛选」模块：行业 / 等级 / 客户阶段 / 复盘周，标准下拉（Excel 式，不搞特殊）
- 「复盘对象」作为筛选模块的一部分（受上方筛选联动的普通下拉），不再单独成块
- 客户一览表：标题左侧、右上角放「▶ 生成本周复盘」按钮（点击即对所选复盘对象出报告）
- 「客户」列固定列宽 260px，品牌名 + 编号完整显示、不再被挤压截断
- 客户总览表无外链 / 跳转按钮
- 负责人全去重（20 个不同姓名）；图表横坐标文字横排
- 等级（KA/SMB）由「周均本平台（小红书）消耗」阈值判定（数据驱动，与表格口径自洽，可被验证）
- 复盘结构 v7（对齐真实小红书蒲公英后台复盘维度）：
  ① 总览与结论
  ② 私信转化漏斗（蒲公英核心 5 段：消耗→开口→留资→深度→进店）
  ③ KFS 投放布局（信息流 vs 搜索 + 出价）
  ④ 内容类型 × 广告效果（含 CPE / CPM / 计划数 / 素材数 / 笔记数）
  ⑤ 素材创意占比（饼图）+ 笔记活跃度（新增/原创/评论/分享/赞藏）
  ⑥ 漏斗诊断（跨周趋势）+ 人群定向（四细分）
  ⑦ 口碑关键词（好评率/私信打开率/私聊好评占比）+ 竞争媒体情报
  ⑧ 下一步行动
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
# 保留 sidebar 和页面本身。仅藏 toolbar/main menu/deploy/status/footer。
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
            "客户": f"{c.name} ({c.customer_id})",  # 显示完整品牌名 + 编号
            "行业": c.industry, "等级": c.tier,
            "客户阶段": _stage_emoji(c.lifecycle_stage),
            "负责人": c.owner,
            "本平台消耗(¥)": int(sp),
            "本平台GMV(¥)": int(gm),
            "本平台ROI": round(gm / sp, 2) if sp else 0,
            "CTR": f"{(clk/im*100 if im else 0):.2f}%",
            "本周转化": cv,
            "竞争媒体占比": f"{comp_share}%",
        })
    return pd.DataFrame(rows)


def main():
    st.set_page_config(page_title="AdPilot · 投放复盘", page_icon="📊", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)

    conn = get_conn()
    llm = get_llm()
    use_real = os.environ.get("OPENAI_API_KEY") is not None
    weeks = _weeks(conn)
    home_cn = PLATFORM_CN.get(HOME_PLATFORM, HOME_PLATFORM)
    latest = weeks[-1] if weeks else None

    st.markdown(H3.format(text="📊 AdPilot · 互联网商业化投放复盘工作台"), unsafe_allow_html=True)
    st.info(f"本工作台视角：销售代表 **【{home_cn}】** 服务客户 → 复盘核心 = 客户在{home_cn}的账户；"
            f"客户在抖音 / 腾讯 / 快手等投放视为**竞争媒体**（情报视角）。")

    industries = ["全部"] + [r[0] for r in conn.execute(
        "SELECT DISTINCT industry FROM customers ORDER BY industry").fetchall()]
    tiers = ["全部", "KA", "SMB"]

    # —— 筛选模块（Excel 式下拉，普通不特殊）——
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
        # 复盘对象：作为筛选模块的一部分（受上方筛选联动），Excel 式下拉
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

    # ---- 客户一览：置顶右上角「生成本周复盘」按钮；列宽保证客户名完整 ----
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
                         # 固定客户名列宽，避免品牌名被挤压截断
                         "客户": st.column_config.TextColumn(width=260),
                         "本平台消耗(¥)": st.column_config.NumberColumn(format="%d"),
                         "本平台GMV(¥)": st.column_config.NumberColumn(format="%d"),
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

        # 客户信息条
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("客户", f"{profile.name} ({profile.customer_id})")
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
        m1.metric("本平台 GMV", f"¥{int(cur['gmv']):,}", f"{wow['gmv']:+.1f}% WoW")
        m2.metric("本平台 消耗", f"¥{int(cur['spend']):,}", f"{wow['spend']:+.1f}% WoW")
        m3.metric("本平台 ROI", f"{cur['roi']}", f"{wow['roi']:+.2f} WoW")
        m4.metric("本平台 转化", f"{cur['conversions']:,}",
                  f"CTR {cur['ctr']*100:.2f}% · CVR {cur['cvr']*100:.2f}%")

        # ① 总览与结论
        st.markdown(H3.format(text="① 总览与结论"), unsafe_allow_html=True)
        st.markdown(r.overview)

        # ② 私信转化漏斗（蒲公英核心 5 段：消耗 → 开口 → 留资 → 深度 → 进店）
        st.markdown(H3.format(text="② 私信转化漏斗（蒲公英 5 段）"), unsafe_allow_html=True)
        cur = agg_home["cur"]
        prev = agg_home["prev"]
        wow = agg_home["wow"]
        pm_inq, pm_ld, pm_dp, sv = cur["pm_inquiry"], cur["pm_lead"], cur["pm_deep"], cur["store_visit"]
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("本平台消耗", f"¥{int(cur['spend']):,}", f"{wow['spend']:+.1f}%")
        p2.metric("私信开口", f"{pm_inq:,}", f"{wow['pm_inquiry']:+.1f}%")
        p3.metric("私信留资", f"{pm_ld:,}",
                  f"留资率 {(pm_ld/pm_inq*100 if pm_inq else 0):.1f}%")
        p4.metric("私信深度(企微/咨询)", f"{pm_dp:,}",
                  f"深度率 {(pm_dp/pm_ld*100 if pm_ld else 0):.1f}%")
        p5.metric("进店访问", f"{sv:,}",
                  f"进店率 {(sv/pm_dp*100 if pm_dp else 0):.1f}%")
        # 漏斗柱状图
        funnel_df = pd.DataFrame([
            {"阶段": "消耗(¥)", "值": int(cur['spend'])},
            {"阶段": "开口", "值": pm_inq},
            {"阶段": "留资", "值": pm_ld},
            {"阶段": "深度", "值": pm_dp},
            {"阶段": "进店", "值": sv},
        ])
        st.altair_chart(
            alt.Chart(funnel_df).mark_bar().encode(
                x=alt.X("阶段:N", title=None, sort=["消耗(¥)", "开口", "留资", "深度", "进店"],
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("值:Q"),
                color=alt.Color("阶段:N", scale=alt.Scale(scheme="tealblues"), legend=None),
                tooltip=["阶段", "值"],
            ).properties(height=240, title="本平台私信转化漏斗"),
            use_container_width=True,
        )
        st.markdown(r.pm_funnel)

        # ③ KFS 投放布局（信息流 F vs 搜索 S）+ 出价维度
        st.markdown(H3.format(text="③ KFS 投放布局（信息流 vs 搜索）"), unsafe_allow_html=True)
        kfs_rows = []
        for ad_type in ("信息流", "搜索"):
            d = agg_home["kfs"][ad_type]
            if d["spend"] == 0:
                continue
            b = agg_home["bench_xhs_ad"].get(ad_type, 0) or 0
            kfs_rows.append({
                "KFS 位置": ad_type,
                "消耗(¥)": int(d["spend"]),
                "GMV(¥)": int(d["gmv"]),
                "ROI": d["roi"],
                "CTR": f"{d['ctr']*100:.2f}%",
                "CVR": f"{d['cvr']*100:.2f}%",
                "行业基准 ROI": b,
                "vs 基准": round(d["roi"] - b, 2),
            })
        if kfs_rows:
            st.dataframe(pd.DataFrame(kfs_rows), use_container_width=True, hide_index=True)
            kfs_chart_df = pd.DataFrame([
                {"位置": rr["KFS 位置"], "类型": k, "值": v}
                for rr in kfs_rows
                for k, v in [("实际 ROI", rr["ROI"]), ("行业基准", rr["行业基准 ROI"])]
            ])
            st.altair_chart(
                alt.Chart(kfs_chart_df).mark_bar().encode(
                    x=alt.X("位置:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("值:Q", title="ROI"),
                    color=alt.Color("类型:N", scale=alt.Scale(scheme="set2")),
                    xOffset="类型:N",
                    tooltip=["位置", "类型", "值"],
                ).properties(height=260),
                use_container_width=True,
            )
        bid_rows = [{"出价类型": bt,
                     "消耗(¥)": int(d["spend"]),
                     "GMV(¥)": int(d["gmv"]),
                     "ROI": d["roi"]} for bt, d in agg_home["by_bid"].items()]
        if bid_rows:
            st.markdown("**出价类型分布**")
            st.dataframe(pd.DataFrame(bid_rows), use_container_width=True, hide_index=True)
        st.markdown(r.kfs_layout)

        # ④ 内容类型 × 广告效果（含 CPE）—— 蒲公英口径
        st.markdown(H3.format(text="④ 内容类型 × 广告效果（含 CPE）"), unsafe_allow_html=True)
        sub_rows = []
        sorted_sub = sorted(agg_home["by_subtype"].items(), key=lambda x: -x[1]["spend"])
        for st_, d in sorted_sub:
            sub_rows.append({
                "内容类型": st_,
                "消耗(¥)": int(d["spend"]),
                "点击": d["clicks"],
                "CTR": f"{d['ctr']*100:.2f}%",
                "CPC(¥)": d["cpc"],
                "CPM(¥)": d["cpm"],
                "计划数": d["plan_cnt"],
                "素材数": d["creative_cnt"],
                "笔记数": d["note_cnt"],
            })
        if sub_rows:
            st.dataframe(pd.DataFrame(sub_rows), use_container_width=True, hide_index=True)
        st.markdown(r.content_type_perf)

        # ⑤ 素材创意占比 + 笔记活跃度
        st.markdown(H3.format(text="⑤ 素材创意占比 + 笔记活跃度"), unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns(5)
        ns = agg_home["note_stats"]
        c1.metric("新增笔记", f"{ns['total']} 篇")
        c2.metric("原创占比", f"{(ns['original']/max(ns['total'],1)*100):.1f}%")
        c3.metric("评论", f"{ns['comments']:,}")
        c4.metric("分享", f"{ns['shares']:,}")
        c5.metric("赞藏", f"{ns['likes_collects']:,}")
        # 创意占比饼图（按计划数）
        plan_total = sum(d["plan_cnt"] for d in agg_home["by_subtype"].values()) or 1
        pie_df = pd.DataFrame([
            {"内容类型": st_, "计划占比(%)": round(d["plan_cnt"]/plan_total*100, 1)}
            for st_, d in agg_home["by_subtype"].items()
        ])
        if not pie_df.empty:
            st.altair_chart(
                alt.Chart(pie_df).mark_arc(innerRadius=60).encode(
                    theta=alt.Theta("计划占比(%):Q"),
                    color=alt.Color("内容类型:N", scale=alt.Scale(scheme="set2")),
                    tooltip=["内容类型", "计划占比(%)"],
                ).properties(height=240, title="素材创意占比（按计划数）"),
                use_container_width=True,
            )
        # TOP 素材表
        ct_sorted = sorted(agg_home["by_content"].items(), key=lambda x: -x[1]["roi"])
        ct_rows = []
        for cid_, d in ct_sorted:
            hot = d["metrics"].get("is_hot", "常文")
            er = d["metrics"].get("engage_rate", 0) * 100
            ct_rows.append({
                "素材标题": d["title"][:35],
                "类型": "🔥 爆文" if hot == "爆文" else "常文",
                "互动率": f"{er:.2f}%",
                "消耗(¥)": int(d["spend"]),
                "GMV(¥)": int(d["gmv"]),
                "转化": d["conv"],
                "ROI": d["roi"],
            })
        if ct_rows:
            st.dataframe(pd.DataFrame(ct_rows), use_container_width=True, hide_index=True)
        if r.decay_signal:
            st.warning(f"⚠️ {r.decay_signal}")
        st.markdown(r.creative_note)

        # ⑥ 漏斗诊断 + 人群定向
        st.markdown(H3.format(text="⑥ 漏斗诊断 + 人群定向"), unsafe_allow_html=True)
        history = _customer_history(conn, cid, weeks, HOME_PLATFORM)
        if not history.empty:
            trend_long = history.melt(id_vars=["period"],
                                      value_vars=["spend", "gmv", "roi"],
                                      var_name="指标", value_name="值")
            st.altair_chart(
                alt.Chart(trend_long).mark_line(point=True).encode(
                    x=alt.X("period:N", title="周", sort=weeks,
                            axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("值:Q"),
                    color=alt.Color("指标:N", scale=alt.Scale(scheme="category10")),
                    tooltip=["period", "指标", "值"],
                ).properties(height=260),
                use_container_width=True,
            )
        aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: -x[1]["roi"])
        aud_df = pd.DataFrame([{
            "人群维度": k, "消耗(¥)": int(d["spend"]),
            "GMV(¥)": int(d["gmv"]), "转化": d["conv"],
            "CTR": f"{d['ctr']*100:.2f}%", "ROI": d["roi"],
        } for k, d in aud_sorted])
        if not aud_df.empty:
            st.dataframe(aud_df, use_container_width=True, hide_index=True)
        st.markdown(r.funnel_audience)

        # ⑦ 口碑关键词 + 竞争媒体情报
        st.markdown(H3.format(text="⑦ 口碑关键词 + 竞争媒体情报"), unsafe_allow_html=True)
        rep = agg_home["rep_stats"]
        k1, k2, k3 = st.columns(3)
        k1.metric("口碑好评率", f"{rep['review_rate']}%",
                  help="客户正面沟通占比（基于企微消息情感）")
        k2.metric("私信打开率", f"{rep['pm_open_rate']}%",
                  help="留资/开口，反映承接话术效果")
        k3.metric("私聊好评占比", f"{rep['pm_review_share']}%",
                  help="沟通中 praise 类占比")
        # 竞争媒体
        comp_rows = []
        total_all = agg_all["cur"]["spend"]
        for p, d in agg_all["by_platform"].items():
            if p == HOME_PLATFORM:
                continue
            share = round(d["spend"] / total_all * 100, 1) if total_all else 0
            comp_rows.append({
                "竞争平台": PLATFORM_CN.get(p, p),
                "消耗(¥)": int(d["spend"]),
                "GMV(¥)": int(d["gmv"]),
                "ROI": d["roi"],
                "占全平台比": f"{share}%",
            })
        if comp_rows:
            st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
        st.caption(f"客户全平台预算中，【{home_cn}】占 {r.home_share}%，竞争媒体合计占 {r.comp_share}%。"
                   f"若{home_cn} ROI 更优，应作为增预算 / 挪量话术支点。")
        st.markdown(r.reputation_competitor)

        # ⑧ 下一步行动
        st.markdown(H3.format(text="⑧ 下一步行动"), unsafe_allow_html=True)
        st.markdown(r.next_actions)

        with st.expander("📄 完整 Markdown 报告"):
            st.code(r.render(), language="markdown")
            st.download_button("📥 下载报告 (.md)", r.render(),
                               file_name=f"adpilot_{cid}_{period}.md", mime="text/markdown")


if __name__ == "__main__":
    main()
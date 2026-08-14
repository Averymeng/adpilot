"""
app.py : AdPilot 网页演示（Streamlit）
====================================
运行：
  cd adpilot/src
  streamlit run app.py
功能：选择客户 + 周，查看 AI 每周投放复盘报告（一句话诊断 + RACAE 五段）。
LLM：默认 MockLLM（无需联网）；设置 OPENAI_API_KEY 后自动切换为真实 OpenAI。
"""
import os
import sys
import sqlite3

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "data", "adpilot.db")
sys.path.insert(0, HERE)

import db as dbm
from weekly_review import run_weekly_review
from llm import get_llm


@st.cache_resource
def get_conn():
    if not os.path.exists(DB_PATH):
        import main
        main.build()
    return dbm.init_db(DB_PATH)


def main():
    st.set_page_config(page_title="AdPilot · 投放复盘工作台", page_icon="📊", layout="wide")
    conn = get_conn()

    llm = get_llm()
    use_real = os.environ.get("OPENAI_API_KEY") is not None

    st.title("📊 AdPilot · 互联网商业化投放复盘工作台")
    st.caption("MVP 锚点：每周投放复盘 = 一句话诊断 + RACAE 五段式报告 ｜ 架构：最小公共 schema + adapter 归一化（全模拟数据）")

    # ---- 侧边栏 ----
    cids = [r[0] for r in conn.execute("SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]
    weeks = [r[0] for r in conn.execute("SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]

    with st.sidebar:
        st.header("⚙️ 复盘配置")
        cid = st.selectbox("选择客户", cids, index=0)
        period = st.selectbox("选择周", weeks, index=len(weeks) - 1)
        st.divider()
        mode = "🟢 真实 OpenAI" if use_real else "🟡 Mock（模板）"
        st.write("**报告引擎**", mode)
        if not use_real:
            st.info("设置环境变量 `OPENAI_API_KEY` 后自动切换为真实自然语言报告。")
        st.divider()
        n_c = len(cids); n_ads = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
        st.write(f"客户 {n_c} · 广告 {n_ads} · 周 {len(weeks)}")

    if st.button("▶ 生成本周复盘", type="primary"):
        with st.spinner("AI 正在生成复盘报告…"):
            r = run_weekly_review(conn, cid, period, llm)

        profile = dbm.get_customer(conn, cid)

        # 一句话诊断（风险红 / 增长绿 / 平稳蓝）
        stage = profile.lifecycle_stage
        if stage == "at_risk":
            st.error("🔴 **【一句话诊断】** " + r.diagnosis)
        elif stage == "growing":
            st.success("🟢 **【一句话诊断】** " + r.diagnosis)
        else:
            st.info("🔵 **【一句话诊断】** " + r.diagnosis)

        # 平台 ROI vs 行业基准
        st.subheader("② 各平台 ROI 对标")
        rows = []
        for p, d in sorted(r and _platform_roi(conn, cid, period).items(), key=lambda x: -x[1]["roi"]):
            b = _bench(conn, p, period)
            rows.append({"平台": p, "ROI": d["roi"], "行业基准": b or 0})
        if rows:
            st.bar_chart({x["平台"]: [x["ROI"], x["行业基准"]] for x in rows},
                         use_container_width=True)

        # 五段式正文
        st.subheader("① 总览与结论")
        st.markdown(r.overview)
        st.subheader("② 广告布局 / 漏斗分配")
        st.markdown(r.layout)
        st.subheader("③ 各层级成效（按周对比趋势）")
        st.markdown(r.layer_perf)
        st.subheader("④ 广告组合成效（受众 + 素材双维度）")
        st.markdown(r.combo_perf)
        st.subheader("⑤ 下一步行动")
        st.markdown(r.next_actions)

        with st.expander("📄 查看完整 Markdown 报告"):
            st.code(r.render(), language="markdown")

        st.caption(f"报告引擎：{'真实 OpenAI' if use_real else 'Mock（数据驱动模板）'} ｜ 数据来源：本地模拟库 {os.path.basename(DB_PATH)}")


def _platform_roi(conn, cid, period):
    cur = dbm.get_ads(conn, cid, period)
    out = {}
    for a in cur:
        d = out.setdefault(a.platform, {"spend": 0, "gmv": 0})
        d["spend"] += a.spend; d["gmv"] += a.gmv
    for p, d in out.items():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0
    return out


def _bench(conn, platform, period):
    rows = conn.execute(
        "SELECT benchmark_roi FROM benchmarks WHERE platform=? AND period=?",
        (platform, period)).fetchall()
    return round(sum(r[0] for r in rows) / len(rows), 2) if rows else None


if __name__ == "__main__":
    main()

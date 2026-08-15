"""
app.py : AdPilot 多模块工作台入口（路由器）
========================================
侧边栏：全局筛选（行业 / 等级 / 客户阶段 / 复盘周）+ 模块导航。
主页由 workbench.py 的各 render_* 函数渲染。
"""
import os
import sys
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db as dbm
from workbench import (HIDE_CHROME_CSS, _weeks, render_home, render_weekly,
                       render_alerts, render_tasks, render_badcase,
                       render_competitor, render_benchmark, render_comms, render_content,
                       render_agent, render_eval)

PAGES = {
    "🏠 工作台总览": render_home,
    "② 每周复盘": render_weekly,
    "③ 每日异常预警": render_alerts,
    "④ 待办与跟进": render_tasks,
    "⑤ Badcase 库": render_badcase,
    "⑥ 竞争媒体情报": render_competitor,
    "⑦ 行业大盘对标": render_benchmark,
    "⑧ 企微沟通洞察": render_comms,
    "⑨ 素材 / 内容库": render_content,
    "💬 AI 助手 (Agent)": render_agent,
    "🧪 报告评测与版本": render_eval,
}


@st.cache_resource
def get_conn():
    DB_PATH = os.path.join(HERE, "..", "data", "adpilot.db")
    if not os.path.exists(DB_PATH):
        import main
        main.build()
    return dbm.init_db(DB_PATH)


def main():
    st.set_page_config(page_title="AdPilot · 商业化销售 AI 工作台", page_icon="📊",
                       layout="wide", initial_sidebar_state="expanded")
    st.markdown(HIDE_CHROME_CSS, unsafe_allow_html=True)

    conn = get_conn()
    weeks = _weeks(conn)
    latest = weeks[-1] if weeks else None
    home_cn = "小红书"

    # —— 侧边栏：全局筛选 + 导航 ——
    with st.sidebar:
        st.markdown("## AdPilot")
        st.caption("互联网商业化销售 AI 工作台")
        st.markdown("---")
        st.markdown("**📐 全局筛选**")
        industries = ["全部"] + [r[0] for r in conn.execute(
            "SELECT DISTINCT industry FROM customers ORDER BY industry").fetchall()]
        tiers = ["全部", "KA", "SMB"]
        stages = ["全部", "流失风险", "高速增长", "稳定期", "新客期"]
        stage_key = {"全部": "全部", "流失风险": "at_risk", "高速增长": "growing",
                    "稳定期": "stable", "新客期": "onboarding"}

        fi = st.selectbox("行业", industries, key="g_industry")
        ft = st.selectbox("等级", tiers, key="g_tier")
        fs = st.selectbox("客户阶段", stages, key="g_stage")
        fw = st.selectbox("复盘周", weeks, index=len(weeks)-1, key="g_week")
        st.markdown("---")
        st.markdown("**🧭 模块**")
        page = st.radio("选择模块", list(PAGES.keys()), key="nav", label_visibility="collapsed")

    f = {"industry": fi, "tier": ft, "stage": stage_key[fs], "week": fw}

    # 顶部说明（仅首页之外也常驻，给用户业务视角锚定）
    if page not in ("🏠 工作台总览", "💬 AI 助手 (Agent)", "🧪 报告评测与版本"):
        st.markdown(f"### 📊 AdPilot · {page}")
        st.caption(f"业务视角：销售代表服务客户 → 复盘核心 = 客户在**{home_cn}**的「客资收集」账户"
                   f"（KPI：留资成本 / 加微）；客户在抖音/腾讯/快手投放视为**竞争媒体**（情报视角）。")

    PAGES[page](conn, f)


if __name__ == "__main__":
    main()

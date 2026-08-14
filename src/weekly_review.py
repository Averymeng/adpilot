"""
weekly_review.py : 核心 AI 节点 —— 每周投放复盘
================================================
输入：customer_id + period（周）
输出：一句话诊断 + 8 段式「小红书线索经营」周报（v8 框架）

业务定位（关键修正）：
  本工作台属于「某一家互联网公司」的商业化销售团队（本平台 = 小红书）。
  - 这类销售卖的是「线索」，不是 GMV。核心 KPI = 留资成本(CPL) / 加微成本 / 开口率。
  - 复盘对象 = 客户的「客资收集」账户（私信开口 / 表单留资）。
  - 竞争媒体（抖音 / 腾讯 / 快手）= 客户在其他平台的投放，仅作情报视角（拿不到它们的私信漏斗）。

复盘结构（v8，对齐真实聚光/蒲公英后台 + 行业复盘方法论）：
  ① 总览与结论      → 现金/预算消耗、预算花完率、留资数、CPL、加微数、净值、同比上周 + 行业 CPL 对标
  ② 私信转化漏斗     → 咨询 → 开口 → 留资 → 加微信（4 段，每段转化数 + 转化率 + 单步成本），诊断断点
  ③ 出价与预算效率   → 预算花完率、CPC、信息流 vs 搜索 CPL 对比、出价方式(手动/自动/oCPX)效果
  ④ 人群与地域       → 年龄分布、兴趣关键词/地域，高转化人群扩量
  ⑤ 笔记/素材(线索视角)→ 爆文率、互动率、素材四象限(CTR×留资成本)、王牌/关停建议
  ⑥ 话术与承接       → 开口率(话术健康度)、留资转化率、加微率，话术迭代建议
  ⑦ 行业对标 + 竞争媒体→ 行业 CPL 基准（分行业），客户 CPL vs 基准；竞争媒体情报
  ⑧ 下一步行动       → 话术迭代 / 出价调整 / 预算重分配 / 人群扩量 / 素材赛马

流程（aipm-chain L0-L8）：
  L1 触发 -> L2 输入(归一化数据) -> L3 预处理(聚合/WoW/对标)
  -> L4 核心处理(AI 诊断+归因) -> L5 输出(报告) -> L6 反馈 -> L7 状态持久化 -> L8 下一步触发
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import db as dbm
from schema import AdPerformance, CustomerProfile, CommunicationRecord, ContentItem, Demographics
from llm import LLMClient, MockLLM

# 本平台（销售所代表的互联网公司）。竞争媒体 = 客户在其他平台的投放。
HOME_PLATFORM = "xhs"
PLATFORM_CN = {
    "xhs": "小红书", "douyin": "抖音", "tencent": "腾讯广告", "kuaishou": "快手磁力",
}
STAGE_CN = {"at_risk": "流失风险", "growing": "高速增长",
            "onboarding": "新客期", "stable": "稳定期"}


@dataclass
class Report:
    customer_id: str
    period: str
    diagnosis: str
    overview: str
    pm_funnel: str          # ② 私信转化漏斗
    bid_budget: str         # ③ 出价与预算效率
    audience_geo: str       # ④ 人群与地域
    content_lead: str       # ⑤ 笔记/素材（线索视角）
    script: str             # ⑥ 话术与承接
    benchmark_comp: str     # ⑦ 行业对标 + 竞争媒体
    next_actions: str
    raw: str = ""
    home_platform: str = HOME_PLATFORM
    home_share: float = 0.0
    comp_share: float = 0.0
    # 扩展指标（供 UI 渲染）
    cpl: float = 0.0
    cpl_benchmark: float = 0.0
    open_rate: float = 0.0
    lead_rate: float = 0.0
    wechat_rate: float = 0.0
    budget_util: float = 0.0
    burst_rate: float = 0.0
    # 漏斗各段（供 UI 图表）
    funnel_vals: Dict = field(default_factory=dict)
    funnel_costs: Dict = field(default_factory=dict)

    def render(self) -> str:
        return (
            f"# 每周投放复盘 · {self.customer_id} · {self.period}\n\n"
            f"【一句话诊断】{self.diagnosis}\n\n"
            f"① 总览与结论\n{self.overview}\n\n"
            f"② 私信转化漏斗（咨询→开口→留资→加微信）\n{self.pm_funnel}\n\n"
            f"③ 出价与预算效率\n{self.bid_budget}\n\n"
            f"④ 人群与地域\n{self.audience_geo}\n\n"
            f"⑤ 笔记/素材（线索视角）\n{self.content_lead}\n\n"
            f"⑥ 话术与承接\n{self.script}\n\n"
            f"⑦ 行业对标 + 竞争媒体情报\n{self.benchmark_comp}\n\n"
            f"⑧ 下一步行动\n{self.next_actions}\n"
        )


# ----------------------------- 派生指标工具 -----------------------------
def _cpl(cash, lead):
    return round(cash / lead, 1) if lead else 0.0

def _pct(a, b):
    return round((a - b) / b * 100, 1) if b else 0.0

def _rate(a, b):
    return round(a / b * 100, 1) if b else 0.0


# ----------------------------- 聚合（L3 预处理） -----------------------------
def _totals(ads: List[AdPerformance]) -> Dict:
    cash = sum(a.cash_spend for a in ads)
    budget = sum(a.budget_spend for a in ads)
    gmv = sum(a.gmv for a in ads)
    imp = sum(a.impressions for a in ads)
    clk = sum(a.clicks for a in ads)
    cons = sum(a.pm_consult for a in ads)
    opn = sum(a.pm_open for a in ads)
    lead = sum(a.pm_lead for a in ads)
    wx = sum(a.pm_wechat for a in ads)
    return {
        "impressions": imp, "clicks": clk, "cash_spend": round(cash, 1),
        "budget_spend": round(budget, 1), "gmv": round(gmv, 1),
        "pm_consult": cons, "pm_open": opn, "pm_lead": lead, "pm_wechat": wx,
        "ctr": round(clk / imp, 4) if imp else 0,
        "cpc": round(cash / clk, 2) if clk else 0,
        "cpl": _cpl(cash, lead),
        "open_cost": _cpl(cash, opn), "consult_cost": _cpl(cash, cons),
        "wechat_cost": _cpl(cash, wx),
        "open_rate": _rate(opn, cons), "lead_rate": _rate(lead, opn),
        "wechat_rate": _rate(wx, lead),
        "budget_util": round(cash / (budget / 1.12) * 100, 1) if budget else 0,
    }


def compute_aggregates(conn, customer_id: str, period: str, prev_period: str,
                       contents: List[ContentItem], comms: List[CommunicationRecord],
                       demo: Optional[Demographics] = None,
                       platform: Optional[str] = None):
    """聚合某客户投放数据。platform=None 全平台；指定则只算该平台。"""
    cur = dbm.get_ads(conn, customer_id, period)
    prev = dbm.get_ads(conn, customer_id, prev_period)
    if platform:
        cur = [a for a in cur if a.platform == platform]
        prev = [a for a in prev if a.platform == platform]
    t_cur, t_prev = _totals(cur), _totals(prev)

    wow = {
        "cash_spend": _pct(t_cur["cash_spend"], t_prev["cash_spend"]),
        "gmv": _pct(t_cur["gmv"], t_prev["gmv"]),
        "pm_consult": _pct(t_cur["pm_consult"], t_prev["pm_consult"]),
        "pm_open": _pct(t_cur["pm_open"], t_prev["pm_open"]),
        "pm_lead": _pct(t_cur["pm_lead"], t_prev["pm_lead"]),
        "pm_wechat": _pct(t_cur["pm_wechat"], t_prev["pm_wechat"]),
        "cpl": round(t_cur["cpl"] - t_prev["cpl"], 1),
    }

    # 分平台
    by_platform = {}
    for a in cur:
        d = by_platform.setdefault(a.platform, {"cash": 0, "gmv": 0, "clicks": 0, "impr": 0, "lead": 0})
        d["cash"] += a.cash_spend; d["gmv"] += a.gmv; d["clicks"] += a.clicks
        d["impr"] += a.impressions; d["lead"] += a.pm_lead
    for p, d in by_platform.items():
        d["cpl"] = _cpl(d["cash"], d["lead"])
        d["cpc"] = round(d["cash"] / d["clicks"], 2) if d["clicks"] else 0

    # KFS：信息流 vs 搜索（仅本平台）
    kfs = {}
    for ad_type in ("信息流", "搜索"):
        d = {"cash": 0, "clicks": 0, "impr": 0, "lead": 0}
        for a in cur:
            if a.platform == HOME_PLATFORM and a.ad_type == ad_type:
                d["cash"] += a.cash_spend; d["clicks"] += a.clicks
                d["impr"] += a.impressions; d["lead"] += a.pm_lead
        d["cpl"] = _cpl(d["cash"], d["lead"])
        d["cpc"] = round(d["cash"] / d["clicks"], 2) if d["clicks"] else 0
        d["ctr"] = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0
        kfs[ad_type] = d

    # 出价方式效果
    by_bid = {}
    for a in cur:
        if not a.bid_type:
            continue
        d = by_bid.setdefault(a.bid_type, {"cash": 0, "lead": 0, "clicks": 0})
        d["cash"] += a.cash_spend; d["lead"] += a.pm_lead; d["clicks"] += a.clicks
    for d in by_bid.values():
        d["cpl"] = _cpl(d["cash"], d["lead"])
        d["cpc"] = round(d["cash"] / d["clicks"], 2) if d["clicks"] else 0

    # 行业 CPL 基准（本平台本行业本周）
    bench_rows = conn.execute(
        "SELECT benchmark_cpl FROM benchmarks WHERE platform=? AND industry=? AND period=?",
        (HOME_PLATFORM, dbm.get_customer(conn, customer_id).industry, period)).fetchall()
    cpl_bench = round(sum(r[0] for r in bench_rows) / len(bench_rows), 1) if bench_rows else 0

    # 人群（按 audience_segment 拆 CPL）
    by_audience = {}
    for a in cur:
        if not a.audience_segment:
            continue
        d = by_audience.setdefault(a.audience_segment, {"cash": 0, "lead": 0, "clicks": 0})
        d["cash"] += a.cash_spend; d["lead"] += a.pm_lead; d["clicks"] += a.clicks
    for d in by_audience.values():
        d["cpl"] = _cpl(d["cash"], d["lead"])

    # 素材四象限（按绑定笔记聚合 CTR × 留资成本）
    by_content = {}
    title_map = {c.content_id: c.title for c in contents}
    metrics_map = {c.content_id: c.key_metrics for c in contents}
    for a in cur:
        ct = by_content.setdefault(a.content_id, {
            "cash": 0, "lead": 0, "clicks": 0, "impr": 0,
            "title": title_map.get(a.content_id, a.content_id),
            "metrics": metrics_map.get(a.content_id, {}),
        })
        ct["cash"] += a.cash_spend; ct["lead"] += a.pm_lead
        ct["clicks"] += a.clicks; ct["impr"] += a.impressions
    for d in by_content.values():
        d["cpl"] = _cpl(d["cash"], d["lead"])
        d["ctr"] = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0

    # 爆文率 / 互动率
    burst, engage = (0.0, 0.0)
    if contents:
        burst = round(sum(1 for c in contents if c.key_metrics.get("is_hot") == "爆文") / len(contents) * 100, 1)
        engage = round(sum(c.key_metrics.get("engage_rate", 0) for c in contents) / len(contents) * 100, 2)

    # 沟通信号
    neg = [c for c in comms if c.sentiment == "negative"]
    complaints = [c.text for c in comms if c.intent_tag == "complaint"]

    # 衰减信号（边际 CPL 连续 3 周恶化）
    weeks = [r[0] for r in conn.execute("SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
    decay_alert = ""
    if (platform == HOME_PLATFORM or platform is None) and customer_id in [r[0] for r in conn.execute("SELECT DISTINCT customer_id FROM ads")]:
        idx = weeks.index(period) if period in weeks else -1
        if idx >= 3:
            cpl_series = []
            for w in weeks[max(0, idx - 5):idx + 1]:
                a_w = [a for a in dbm.get_ads(conn, customer_id, w) if (platform or a.platform == HOME_PLATFORM)]
                cash = sum(a.cash_spend for a in a_w); lead = sum(a.pm_lead for a in a_w)
                cpl_series.append((w, _cpl(cash, lead)))
            if cpl_series:
                base = cpl_series[0][1] or 1
                tail3 = cpl_series[-3:]
                if base > 0 and all(c > base * 1.15 for _, c in tail3):
                    decay_alert = (f"近 3 周留资成本持续高于基线 ¥{base:.0f} 的 15%，"
                                   f"建议本周新建计划替换（不要救旧计划）。")

    return {
        "cur": t_cur, "prev": t_prev, "wow": wow,
        "by_platform": by_platform, "kfs": kfs, "by_bid": by_bid,
        "cpl_bench": cpl_bench, "by_audience": by_audience, "by_content": by_content,
        "burst_rate": burst, "engage_avg": engage,
        "neg_count": len(neg), "complaints": complaints,
        "decay_alert": decay_alert, "demo": demo,
    }


# ----------------------------- 报告生成（L4 核心） -----------------------------
def build_report(profile: CustomerProfile, agg_home: Dict, agg_all: Dict, period: str) -> Report:
    cur, wow = agg_home["cur"], agg_home["wow"]
    home_cn = PLATFORM_CN.get(HOME_PLATFORM, HOME_PLATFORM)
    cpl_bench = agg_all["cpl_bench"]
    neg = agg_home["neg_count"]
    who = f"{profile.name}（{profile.customer_id}，{profile.industry}）"
    stage_cn = STAGE_CN.get(profile.lifecycle_stage, profile.lifecycle_stage)

    home_cash = cur["cash_spend"]
    all_cash = agg_all["cur"]["cash_spend"]
    comp_cash = all_cash - home_cash
    comp_share = round(comp_cash / all_cash * 100, 1) if all_cash else 0
    home_share = round(home_cash / all_cash * 100, 1) if all_cash else 0

    cpl = cur["cpl"]
    vs_bench = round(cpl - cpl_bench, 1)
    cpl_tag = "低于行业" if vs_bench < 0 else "高于行业"
    net_value = round(cur["gmv"] - cur["cash_spend"], 1)

    # —— 一句话诊断 ——
    if profile.lifecycle_stage == "at_risk":
        diag = (f"{who}「{stage_cn}」：本周留资成本 ¥{cpl:.0f}（{cpl_tag}基准 ¥{cpl_bench:.0f} {vs_bench:+.0f}），"
                f"CPL 环比 {wow['cpl']:+.0f}；预算花完率仅 {cur['budget_util']:.0f}%，"
                f"开口率 {cur['open_rate']:.0f}%（话术承接弱）；"
                f"建议先稳住本平台账户、用话术+出价把 CPL 压回基线，再以高 ROI 推动增预算。")
    elif profile.lifecycle_stage == "growing":
        diag = (f"{who}「{stage_cn}」：本周留资成本 ¥{cpl:.0f}（{cpl_tag}基准 ¥{cpl_bench:.0f} {vs_bench:+.0f}），"
                f"CPL 环比 {wow['cpl']:+.0f}，加微 {cur['pm_wechat']} 条（环比 {wow['pm_wechat']:+.0f}%）；"
                f"客户仅 {home_share}% 预算在本平台、{comp_share}% 在竞争媒体，增量空间大，建议增预算挪量。")
    else:
        diag = (f"{who}「{stage_cn}」：本周留资成本 ¥{cpl:.0f}（{cpl_tag}基准 ¥{cpl_bench:.0f} {vs_bench:+.0f}），"
                f"加微 {cur['pm_wechat']} 条，预算花完率 {cur['budget_util']:.0f}%；"
                f"客户全平台本平台占 {home_share}%，可维持当前结构。")

    # ① 总览与结论
    overview = (
        f"【{home_cn}·客资收集】本周现金消耗 ¥{int(round(home_cash)):,}（环比 {wow['cash_spend']}%），"
        f"预算消耗 ¥{int(round(cur['budget_spend'])):,}（广告币），预算花完率 {cur['budget_util']:.0f}%。\n"
        f"私信咨询 {cur['pm_consult']} / 开口 {cur['pm_open']} / 留资 {cur['pm_lead']} / 加微信 {cur['pm_wechat']}（均环比见各段）。\n"
        f"核心指标：**留资成本 CPL ¥{cpl:.0f}**（行业基准 ¥{cpl_bench:.0f}，{cpl_tag} {vs_bench:+.0f}；环比 {wow['cpl']:+.0f}）；"
        f"加微成本 ¥{cur['wechat_cost']:.0f}；成交 GMV ¥{int(round(cur['gmv'])):,}，净值 ¥{int(round(net_value)):,}。\n"
        f"客户全平台总投放 ¥{int(round(all_cash)):,}，其中本平台占 {home_share}%、竞争媒体占 {comp_share}%。"
        + (f"\n⚠️ 客户侧收到 {neg} 条负面反馈，需重点关注。" if neg else "\n客户沟通情绪整体平稳。")
    )

    # ② 私信转化漏斗
    cons, opn, lead, wx = cur["pm_consult"], cur["pm_open"], cur["pm_lead"], cur["pm_wechat"]
    pm_funnel = (
        f"消耗 ¥{int(round(home_cash)):,}\n"
        f"  → 私信咨询 {cons}（咨询成本 ¥{cur['consult_cost']:.0f}）\n"
        f"  → 私信开口 {opn}（开口率 {cur['open_rate']:.0f}%，开口成本 ¥{cur['open_cost']:.0f}）\n"
        f"  → 私信留资 {lead}（留资率 {cur['lead_rate']:.0f}%，**留资成本 CPL ¥{cpl:.0f}**）\n"
        f"  → 添加微信 {wx}（加微率 {cur['wechat_rate']:.0f}%，加微成本 ¥{cur['wechat_cost']:.0f}）\n"
        f"环比：咨询 {wow['pm_consult']:+}% / 开口 {wow['pm_open']:+}% / 留资 {wow['pm_lead']:+}% / 加微 {wow['pm_wechat']:+}%。\n"
        "断点诊断："
        + (" 开口率偏低 → 素材 CTA/欢迎语弱，用户进了私信不说话，先改话术。"
           if cur["open_rate"] < 35 else " 开口端正常，")
        + (" 留资率偏低 → 自动回复/留资卡没接住，优化承接。"
           if cons and cur["lead_rate"] < 40 else " 留资端正常，")
        + (" 加微率偏低 → 私域引导弱（没上商家名片/留资卡）。"
           if lead and cur["wechat_rate"] < 35 else " 加微端正常。")
    )

    # ③ 出价与预算效率
    kfs_lines = []
    for at in ("信息流", "搜索"):
        d = agg_home["kfs"][at]
        if d["cash"] == 0:
            kfs_lines.append(f"  - {at}：本周无投放")
            continue
        kfs_lines.append(f"  - {at}：现金消耗 ¥{d['cash']:,.0f}，CPL ¥{d['cpl']:.0f}，"
                         f"CPC ¥{d['cpc']:.2f}，CTR {d['ctr']*100:.2f}%")
    bid_lines = [f"  - {bt}：现金消耗 ¥{d['cash']:,.0f}，CPL ¥{d['cpl']:.0f}，CPC ¥{d['cpc']:.2f}"
                 for bt, d in sorted(agg_home["by_bid"].items(), key=lambda x: -x[1]["cash"])]
    util = cur["budget_util"]
    bid_advice = ("预算花不完（{:.0f}%）→ 提日预算/放宽定向，让系统多出量；"
                  if util < 70 else "预算利用率健康，").format(util)
    bid_advice += ("若 CPL 偏高且高出价在跑，可把部分手动出价切到 oCPX 让系统优化留资目标。"
                  if cur["cpl"] > cpl_bench else "当前出价方式下 CPL 已优，保持。")
    bid_budget = (
        f"预算花完率 {util:.0f}%（计划预算 ¥{int(round(cur['budget_spend']/1.12)):,}，实际花 ¥{int(round(home_cash)):,}）；"
        f"整体 CPC ¥{cur['cpc']:.2f}。\n"
        "KFS（信息流种草 / 搜索收割）：\n" + "\n".join(kfs_lines) + "\n"
        "出价方式分布：\n" + ("\n".join(bid_lines) if bid_lines else "  （无数据）") + "\n"
        f"建议：{bid_advice}"
    )

    # ④ 人群与地域
    demo = agg_home.get("demo")
    age_txt = ""
    if demo:
        age_txt = (f"年龄分布：25-30岁 {demo.age_25_30*100:.0f}% / 31-40岁 {demo.age_31_40*100:.0f}% / "
                   f"41-50岁 {demo.age_41_50*100:.0f}% / 50岁+ {demo.age_50_plus*100:.0f}%；"
                   f"主力地域 {demo.top_region}，兴趣词「{demo.top_interest}」")
    aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: x[1]["cpl"])
    aud_lines = [f"  - {k}：现金消耗 ¥{d['cash']:,.0f}，CPL ¥{d['cpl']:.0f}" for k, d in aud_sorted]
    best_aud = aud_sorted[0] if aud_sorted else None
    audience_geo = (
        (age_txt + "\n") if age_txt else "（无人群画像数据）\n"
    ) + "按定向方式拆 CPL：\n" + ("\n".join(aud_lines) if aud_lines else "  （无数据）") + "\n" \
        + (f"建议：对 CPL 最优的「{best_aud[0]}」（¥{best_aud[1]['cpl']:.0f}）做相似人群扩展放量。"
           if best_aud else "")

    # ⑤ 笔记/素材（线索视角）
    ct_sorted = sorted(agg_home["by_content"].items(), key=lambda x: x[1]["cpl"])
    quad = {"王牌(高CTR低CPL)": [], "引流(高CTR高CPL)": [], "收割(低CTR低CPL)": [], "垃圾(低CTR高CPL)": []}
    for cid, d in agg_home["by_content"].items():
        if d["clicks"] == 0:
            continue
        hi_ctr = d["ctr"] >= 0.02
        lo_cpl = d["cpl"] <= cpl_bench if cpl_bench else d["cpl"] <= cpl
        if hi_ctr and lo_cpl: quad["王牌(高CTR低CPL)"].append(d)
        elif hi_ctr and not lo_cpl: quad["引流(高CTR高CPL)"].append(d)
        elif not hi_ctr and lo_cpl: quad["收割(低CTR低CPL)"].append(d)
        else: quad["垃圾(低CTR高CPL)"].append(d)
    top = ct_sorted[:2]
    top_lines = [f"  🔥 {d['title'][:28]}：CTR {d['ctr']*100:.2f}%，CPL ¥{d['cpl']:.0f}" for _, d in top]
    junk = [d for d in quad["垃圾(低CTR高CPL)"]]
    junk_lines = [f"  ✗ {d['title'][:28]}：CTR {d['ctr']*100:.2f}%，CPL ¥{d['cpl']:.0f}" for d in junk[:2]]
    content_lead = (
        f"爆文率 {agg_home['burst_rate']}%，平均互动率 {agg_home['engage_avg']}%。\n"
        "素材四象限（按 CTR × 留资成本）：\n"
        f"  - 王牌 {len(quad['王牌(高CTR低CPL)'])} 篇 / 引流型 {len(quad['引流(高CTR高CPL)'])} 篇 / "
        f"收割型 {len(quad['收割(低CTR低CPL)'])} 篇 / 垃圾 {len(quad['垃圾(低CTR高CPL)'])} 篇\n"
        "TOP 素材（CPL 最低）：\n" + ("\n".join(top_lines) if top_lines else "  （无）") + "\n"
        "建议关停：\n" + ("\n".join(junk_lines) if junk_lines else "  （无）") + "\n"
        "赛马建议：复制王牌素材钩子到新计划；引流型检查正文与私信承接话术；垃圾素材直接关停换创意。"
    )

    # ⑥ 话术与承接
    script = (
        f"话术健康度：开口率 {cur['open_rate']:.0f}%（行业健康线 ~45%）→ "
        + ("话术/欢迎语弱，用户进私信不开口。" if cur["open_rate"] < 38 else "开口承接 OK。")
        + f" 留资转化率 {cur['lead_rate']:.0f}%（健康线 ~45%）→ "
        + ("自动回复/留资卡没接住。" if (cons and cur['lead_rate'] < 40) else "留资承接 OK。")
        + f" 加微率 {cur['wechat_rate']:.0f}%（健康线 ~45%）→ "
        + ("未上商家名片/留资卡，私域引导弱。" if (lead and cur['wechat_rate'] < 40) else "私域引导 OK。")
        + "\n建议：先用「三段式开场」（感谢+认同 → 问需求/城市 → 给价值/避坑指南）替代干巴巴的「你好」；"
          "给高意向用户上「留资卡」+「商家名片」，实测可显著拉低留资成本、提升加微率。"
    )

    # ⑦ 行业对标 + 竞争媒体
    comp_rows = []
    for p, d in agg_all["by_platform"].items():
        if p == HOME_PLATFORM:
            continue
        share = round(d["cash"] / all_cash * 100, 1) if all_cash else 0
        comp_rows.append((PLATFORM_CN.get(p, p), d["cash"], d["cpl"], share))
    comp_rows.sort(key=lambda x: -x[1])
    comp_lines = [f"  - {n}：现金消耗 ¥{s:,.0f}，CPL ¥{c:.0f}（占全平台 {sh}%）" for n, s, c, sh in comp_rows]
    benchmark_comp = (
        f"行业 CPL 基准（{profile.industry}）：¥{cpl_bench:.0f}/条。"
        f"本客户 ¥{cpl:.0f} → **{cpl_tag} {abs(vs_bench):.0f} 元**"
        + ("（成本可控，可作为增预算支点）" if vs_bench < 0 else "（需先降本再谈增量）") + "。\n"
        f"竞争媒体情报：客户全平台预算中本平台仅占 {home_share}%、竞争媒体合计 {comp_share}%。\n"
        + ("\n".join(comp_lines) if comp_lines else "  （暂无竞争媒体投放数据）") + "\n"
        f"话术建议：以「本平台 CPL ¥{cpl:.0f} vs 竞争媒体」作为增预算/挪量支点。"
    )

    # ⑧ 下一步行动
    actions = []
    if agg_home.get("decay_alert"):
        actions.append(f"🚨 【衰减】新建计划替换，参考王牌素材选题/钩子；不要在旧计划上调价。")
    if util < 70:
        actions.append(f"预算花不完（{util:.0f}%）→ 提日预算或放宽定向，让系统多出量、积累转化样本。")
    if cur["open_rate"] < 38:
        actions.append(f"话术迭代：用三段式开场+自动回复替换「你好」，目标开口率提到 45%+。")
    if cons and cur["lead_rate"] < 40:
        actions.append(f"留资承接：上「留资卡」+ 优化自动回复，目标留资率提到 45%+。")
    if lead and cur["wechat_rate"] < 40:
        actions.append(f"私域引导：上「商家名片」一键复制微信，目标加微率提到 45%+。")
    if cur["cpl"] > cpl_bench:
        actions.append(f"CPL 高于行业 {abs(vs_bench):.0f} 元 → 主因在留资率/加微率，优先改话术与承接，而非加预算。")
    if best_aud:
        actions.append(f"人群扩容：对「{best_aud[0]}」（CPL ¥{best_aud[1]['cpl']:.0f}）做相似人群扩展。")
    for d in quad["王牌(高CTR低CPL)"]:
        actions.append(f"素材赛马：复制王牌「{d['title'][:16]}…」钩子到新计划放量。")
    for d in junk[:1]:
        actions.append(f"关停垃圾素材「{d['title'][:16]}…」（CTR 低且 CPL 高），回收预算。")
    actions.append(f"以「本平台 CPL ¥{cpl:.0f} vs 竞争媒体」为支点，向客户提案增预算/挪量"
                   f"（当前本平台仅占全平台 {home_share}%）。")
    next_actions = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(actions))

    return Report(
        customer_id=profile.customer_id, period=period, diagnosis=diag,
        overview=overview, pm_funnel=pm_funnel, bid_budget=bid_budget,
        audience_geo=audience_geo, content_lead=content_lead, script=script,
        benchmark_comp=benchmark_comp, next_actions=next_actions,
        home_platform=HOME_PLATFORM, home_share=home_share, comp_share=comp_share,
        cpl=cpl, cpl_benchmark=cpl_bench, open_rate=cur["open_rate"],
        lead_rate=cur["lead_rate"], wechat_rate=cur["wechat_rate"],
        budget_util=util, burst_rate=agg_home["burst_rate"],
        funnel_vals={"咨询": cons, "开口": opn, "留资": lead, "加微信": wx},
        funnel_costs={"咨询成本": cur["consult_cost"], "开口成本": cur["open_cost"],
                      "留资成本CPL": cpl, "加微成本": cur["wechat_cost"]},
    )


# ----------------------------- 主入口（L1/L5/L8） -----------------------------
_conn_ref = None  # 仅用于 build_report 内取本平台消耗（见下）

def run_weekly_review(conn, customer_id: str, period: str, llm: LLMClient,
                      prev_period: Optional[str] = None, _conn=None) -> Report:
    global _conn_ref
    _conn_ref = conn
    profile = dbm.get_customer(conn, customer_id)
    if not profile:
        raise ValueError(f"customer {customer_id} not found")
    if prev_period is None:
        weeks = [r[0] for r in conn.execute("SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
        if period in weeks:
            idx = weeks.index(period)
            prev_period = weeks[idx - 1] if idx > 0 else period

    content_ids = {a.content_id for a in dbm.get_ads(conn, customer_id, period)}
    contents = dbm.get_contents(conn, content_ids)
    comms = dbm.get_comms(conn, customer_id, period)
    demo_rows = conn.execute(
        "SELECT * FROM demographics WHERE customer_id=? AND period=?",
        (customer_id, period)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM demographics").description]
    demo = Demographics(**dict(zip(cols, demo_rows[0]))) if demo_rows else None

    agg_all = compute_aggregates(conn, customer_id, period, prev_period, contents, comms, demo)
    agg_home = compute_aggregates(conn, customer_id, period, prev_period, contents, comms, demo,
                                 platform=HOME_PLATFORM)

    report = build_report(profile, agg_home, agg_all, period)

    if isinstance(llm, MockLLM):
        report.raw = report.render()
        return report

    prompt = _build_llm_prompt(profile, agg_home, agg_all, report)
    out = llm.complete(prompt)
    parsed = _parse_report(out, customer_id, period)
    if parsed and parsed.diagnosis:
        parsed.raw = out
        return parsed
    report.raw = report.render()
    return report


def _build_llm_prompt(profile, agg_home, agg_all, report: Report) -> str:
    home_cn = PLATFORM_CN.get(HOME_PLATFORM, HOME_PLATFORM)
    return f"""你是小红书聚光「线索经营」商业化销售的周报专家。本工作台属于「{home_cn}」的商业化销售团队，卖的是线索（留资/加微信），不是 GMV。

客户：{profile.customer_id}（{profile.industry}，{profile.tier}），负责人 {profile.owner}

【本平台 {home_cn}·客资收集】本周聚合：{agg_home['cur']}
环比：{agg_home['wow']}
私信漏斗单步成本：{agg_home['cur']}
KFS（信息流/搜索）：{agg_home['kfs']}
出价方式：{agg_home['by_bid']}
分人群：{agg_home['by_audience']}
分素材：{agg_home['by_content']}
爆文率：{agg_home['burst_rate']}%  互动率：{agg_home['engage_avg']}%
行业 CPL 基准：{agg_all['cpl_bench']}
衰减信号：{agg_home.get('decay_alert', '无')}

【全平台（含竞争媒体）】分平台：{agg_all['by_platform']}
客户负面反馈：{agg_home['complaints']}

请严格按以下格式输出（标题不可改）：
【一句话诊断】<一句话>
① 总览与结论
② 私信转化漏斗（咨询→开口→留资→加微信）
③ 出价与预算效率
④ 人群与地域
⑤ 笔记/素材（线索视角）
⑥ 话术与承接
⑦ 行业对标 + 竞争媒体情报
⑧ 下一步行动

参考范式：
{report.render()}
"""


def _parse_report(text: str, customer_id, period) -> Optional[Report]:
    import re
    def _sec(name, *nexts):
        next_pat = "|".join(re.escape(n) for n in nexts)
        m = re.search(rf"{re.escape(name)}\s*(.*?)(?={next_pat}|$)", text, re.S)
        return m.group(1).strip() if m else ""
    diag_m = re.search(r"【一句话诊断】\s*(.*)", text)
    return Report(
        customer_id=customer_id, period=period,
        diagnosis=diag_m.group(1).strip() if diag_m else "",
        overview=_sec("①", "②"),
        pm_funnel=_sec("②", "③"),
        bid_budget=_sec("③", "④"),
        audience_geo=_sec("④", "⑤"),
        content_lead=_sec("⑤", "⑥"),
        script=_sec("⑥", "⑦"),
        benchmark_comp=_sec("⑦", "⑧"),
        next_actions=_sec("⑧"), raw=text,
    )

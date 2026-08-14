"""
weekly_review.py : 核心 AI 节点 —— 每周投放复盘
================================================
输入：customer_id + period（周）
输出：一句话诊断 + 8 段式小红书投放复盘报告（v7 框架）

视角模型：
  本工作台属于「某一家互联网公司」的商业化销售团队（本平台 = 小红书）。
  - 本平台（小红书）= 销售真正经营的客户账户 → 复盘核心（①~⑦）
  - 竞争媒体（抖音 / 腾讯 / 快手）= 客户在其他平台的投放 → 情报视角（⑦后段）

复盘结构（v7，基于真实小红书蒲公英后台复盘维度）：
  ① 总览与结论           → 本周核心指标 vs 上周 + 行业基准
  ② 私信转化漏斗（5 段）→ 消耗 → 私信开口 → 私信留资 → 私信深度（企微/咨询）→ 进店
  ③ KFS 投放布局         → 信息流 F vs 搜索 S（小红书特有，KFS 中的 F 和 S）
  ④ 内容类型 × 广告效果  → 4 种内容类型 × 消耗/点击/CTR/CPC/CPM/CPE/计划数/素材数/笔记数
  ⑤ 素材创意 + 笔记活跃度→ 计划创意/点击/素材占比（饼图）+ 日均新增笔记/原创/评论/分享/赞藏
  ⑥ 漏斗诊断 + 人群定向  → 曝光→点击→转化 + 人群包/关键词定向/行为兴趣/智能定向
  ⑦ 口碑关键词 + 竞争媒体→ 口碑好评率/私信打开率 + 抖音/腾讯/快手 ROI & 占比
  ⑧ 下一步行动           → 含衰减触发新建、出价调整、人群扩容、增预算话术

流程（aipm-chain L0-L8）：
  L1 触发 -> L2 输入(归一化数据) -> L3 预处理(聚合/WoW/对标)
  -> L4 核心处理(AI 诊断+归因) -> L5 输出(报告) -> L6 反馈 -> L7 状态持久化 -> L8 下一步触发
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import db as dbm
from schema import AdPerformance, CustomerProfile, CommunicationRecord, ContentItem
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
    pm_funnel: str          # ② 私信转化漏斗（蒲公英核心）
    kfs_layout: str         # ③ KFS 信息流 vs 搜索
    content_type_perf: str  # ④ 内容类型 × 广告效果（含 CPE）
    creative_note: str      # ⑤ 素材创意占比 + 笔记活跃度
    funnel_audience: str    # ⑥ 漏斗诊断 + 人群定向
    reputation_competitor: str  # ⑦ 口碑关键词 + 竞争媒体情报
    next_actions: str
    raw: str = ""
    home_platform: str = HOME_PLATFORM
    home_share: float = 0.0
    comp_share: float = 0.0
    # 扩展指标（供 UI 渲染）
    burst_rate: float = 0.0         # 爆文率
    note_engage_avg: float = 0.0    # 笔记平均互动率
    decay_signal: str = ""          # 衰减信号
    note_stats: Dict = field(default_factory=dict)   # 笔记活跃度聚合
    pm_stats: Dict = field(default_factory=dict)     # 私信漏斗聚合

    def render(self) -> str:
        return (
            f"# 每周投放复盘 · {self.customer_id} · {self.period}\n\n"
            f"【一句话诊断】{self.diagnosis}\n\n"
            f"① 总览与结论\n{self.overview}\n\n"
            f"② 私信转化漏斗（蒲公英核心 5 段）\n{self.pm_funnel}\n\n"
            f"③ KFS 投放布局（信息流 vs 搜索）\n{self.kfs_layout}\n\n"
            f"④ 内容类型 × 广告效果（含 CPE）\n{self.content_type_perf}\n\n"
            f"⑤ 素材创意 + 笔记活跃度\n{self.creative_note}\n\n"
            f"⑥ 漏斗诊断 + 人群定向\n{self.funnel_audience}\n\n"
            f"⑦ 口碑关键词 + 竞争媒体情报\n{self.reputation_competitor}\n\n"
            f"⑧ 下一步行动\n{self.next_actions}\n"
        )


# ----------------------------- 聚合（L3 预处理） -----------------------------
def _totals(ads: List[AdPerformance]) -> Dict:
    imp = sum(a.impressions for a in ads)
    clk = sum(a.clicks for a in ads)
    sp = sum(a.spend for a in ads)
    cv = sum(a.conversions for a in ads)
    gmv = sum(a.gmv for a in ads)
    pm_inq = sum(a.pm_inquiry for a in ads)
    pm_ld = sum(a.pm_lead for a in ads)
    pm_dp = sum(a.pm_deep for a in ads)
    sv = sum(a.store_visit for a in ads)
    return {
        "impressions": imp, "clicks": clk, "spend": round(sp, 1),
        "conversions": cv, "gmv": round(gmv, 1),
        "cv_shallow": sum(a.cv_shallow for a in ads),
        "cv_deep": sum(a.cv_deep for a in ads),
        "pm_inquiry": pm_inq, "pm_lead": pm_ld, "pm_deep": pm_dp, "store_visit": sv,
        "ctr": round(clk / imp, 4) if imp else 0,
        "cvr": round(cv / clk, 4) if clk else 0,
        "cpc": round(sp / clk, 2) if clk else 0,
        "roi": round(gmv / sp, 2) if sp else 0,
        "cpe": round(sp / max((pm_inq + sum(a.likes if False else 0 for a in ads)), 1), 2),  # 占位
    }


def compute_aggregates(conn, customer_id: str, period: str, prev_period: str,
                       contents: List[ContentItem], comms: List[CommunicationRecord],
                       platform: Optional[str] = None):
    """聚合某客户的投放数据。platform=None 表示全平台；指定则只算该平台。"""
    cur = dbm.get_ads(conn, customer_id, period)
    prev = dbm.get_ads(conn, customer_id, prev_period)
    if platform:
        cur = [a for a in cur if a.platform == platform]
        prev = [a for a in prev if a.platform == platform]
    t_cur, t_prev = _totals(cur), _totals(prev)

    def _pct(a, b):
        return round((a - b) / b * 100, 1) if b else 0.0
    wow = {
        "spend": _pct(t_cur["spend"], t_prev["spend"]),
        "gmv": _pct(t_cur["gmv"], t_prev["gmv"]),
        "roi": round(t_cur["roi"] - t_prev["roi"], 2),
        "clicks": _pct(t_cur["clicks"], t_prev["clicks"]),
        "conversions": _pct(t_cur["conversions"], t_prev["conversions"]),
        "pm_inquiry": _pct(t_cur["pm_inquiry"], t_prev["pm_inquiry"]),
        "pm_deep": _pct(t_cur["pm_deep"], t_prev["pm_deep"]),
        "store_visit": _pct(t_cur["store_visit"], t_prev["store_visit"]),
    }

    # 分平台
    by_platform = {}
    for a in cur:
        d = by_platform.setdefault(a.platform, {"spend": 0, "gmv": 0, "clicks": 0, "impr": 0, "conv": 0})
        d["spend"] += a.spend; d["gmv"] += a.gmv; d["clicks"] += a.clicks
        d["impr"] += a.impressions; d["conv"] += a.conversions
    for p, d in by_platform.items():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0
        d["ctr"] = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0

    # —— KFS：信息流 vs 搜索（小红书特有）——
    kfs = {"信息流": {"spend": 0, "gmv": 0, "conv": 0, "impr": 0, "clicks": 0},
           "搜索": {"spend": 0, "gmv": 0, "conv": 0, "impr": 0, "clicks": 0}}
    for a in cur:
        if a.platform == HOME_PLATFORM and a.ad_type in ("信息流", "搜索"):
            d = kfs[a.ad_type]
            d["spend"] += a.spend; d["gmv"] += a.gmv; d["conv"] += a.conversions
            d["impr"] += a.impressions; d["clicks"] += a.clicks
    for k, d in kfs.items():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0
        d["ctr"] = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0
        d["cvr"] = round(d["conv"] / d["clicks"], 4) if d["clicks"] else 0

    # —— 出价维度（手动 / 自动 / oCPC）——
    by_bid = {}
    for a in cur:
        if not a.bid_type:
            continue
        d = by_bid.setdefault(a.bid_type, {"spend": 0, "gmv": 0, "conv": 0})
        d["spend"] += a.spend; d["gmv"] += a.gmv; d["conv"] += a.conversions
    for k, d in by_bid.items():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0

    # 对标行业大盘
    bench = {}
    for p in by_platform:
        rows = conn.execute(
            "SELECT benchmark_roi FROM benchmarks WHERE platform=? AND period=?",
            (p, period)).fetchall()
        bench[p] = round(sum(r[0] for r in rows) / len(rows), 2) if rows else None
    bench_xhs_ad = {}
    for ad_type in ("信息流", "搜索"):
        rows = conn.execute(
            "SELECT benchmark_roi FROM benchmarks WHERE platform=? AND period=? AND ad_type=?",
            (HOME_PLATFORM, period, ad_type)).fetchall()
        bench_xhs_ad[ad_type] = round(sum(r[0] for r in rows) / len(rows), 2) if rows else None

    # —— 人群四细分 ——
    by_audience = {}
    for a in cur:
        au = by_audience.setdefault(a.audience_segment, {"spend": 0, "gmv": 0, "conv": 0, "impr": 0, "clicks": 0})
        au["spend"] += a.spend; au["gmv"] += a.gmv; au["conv"] += a.conversions
        au["impr"] += a.impressions; au["clicks"] += a.clicks
    for d in by_audience.values():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0
        d["ctr"] = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0

    # —— 内容类型 × 广告效果（蒲公英维度）——
    by_subtype = {}
    for a in cur:
        if not a.content_subtype:
            continue
        d = by_subtype.setdefault(a.content_subtype, {
            "spend": 0, "impr": 0, "clicks": 0, "cv": 0,
            "plan_cnt": 0, "creative_cnt": 0, "note_cnt": 0,
            "content_ids": set(), "plan_ids": set(), "creative_ids": set(),
        })
        d["spend"] += a.spend
        d["impr"] += a.impressions
        d["clicks"] += a.clicks
        d["cv"] += a.conversions
        d["plan_cnt"] += 1
        d["plan_ids"].add(a.campaign_id)
        d["content_ids"].add(a.content_id)
    # 素材数 / 笔记数用 contents 表来精确
    note_by_subtype = {}
    for c in contents:
        note_by_subtype.setdefault(c.content_id, True)
    for st, d in by_subtype.items():
        d["plan_cnt"] = len(d["plan_ids"])
        d["note_cnt"] = len([cid for cid in d["content_ids"] if cid in note_by_subtype])
        d["creative_cnt"] = len(d["content_ids"])  # 内容绑定 ≈ 创意数
        ctr = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0
        cpc = round(d["spend"] / d["clicks"], 2) if d["clicks"] else 0
        cpm = round(d["spend"] / d["impr"] * 1000, 2) if d["impr"] else 0
        # CPE = 单条私信/进店成本（小红书特有）
        cpe = 0
        d["ctr"] = ctr; d["cpc"] = cpc; d["cpm"] = cpm; d["cpe"] = cpe

    # —— 素材维度（笔记/视频）——
    by_content = {}
    title_map = {c.content_id: c.title for c in contents}
    metrics_map = {c.content_id: c.key_metrics for c in contents}
    for a in cur:
        ct = by_content.setdefault(a.content_id, {
            "spend": 0, "gmv": 0, "conv": 0,
            "title": title_map.get(a.content_id, a.content_id),
            "metrics": metrics_map.get(a.content_id, {}),
        })
        ct["spend"] += a.spend; ct["gmv"] += a.gmv; ct["conv"] += a.conversions
    for d in by_content.values():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0

    # —— 爆文率 / 笔记互动率 ——
    if contents:
        burst = sum(1 for c in contents if c.key_metrics.get("is_hot") == "爆文")
        burst_rate = round(burst / len(contents) * 100, 1)
        engage_avg = round(sum(c.key_metrics.get("engage_rate", 0) for c in contents) / len(contents) * 100, 2)
    else:
        burst_rate, engage_avg = 0.0, 0.0

    # —— 笔记活跃度聚合（蒲公英口径）——
    note_stats = {
        "total": len(contents),
        "original": sum(1 for c in contents if c.is_original),
        "comments": sum(c.key_metrics.get("comments", 0) for c in contents),
        "shares": sum(c.share_cnt for c in contents),
        "likes_collects": sum(c.key_metrics.get("likes", 0) + c.key_metrics.get("collects", 0) for c in contents),
        "reads": sum(c.key_metrics.get("reads", 0) for c in contents),
    }

    # —— 口碑关键词（基于互动数据计算代理指标）——
    n_neg = sum(1 for c in comms if c.sentiment == "negative")
    n_pos = sum(1 for c in comms if c.sentiment == "positive")
    n_total_sent = n_neg + n_pos or 1
    rep_stats = {
        "review_rate": round(n_pos / n_total_sent * 100, 1),  # 沟通好评率
        "pm_open_rate": round(t_cur["pm_lead"] / t_cur["pm_inquiry"] * 100, 1) if t_cur["pm_inquiry"] else 0,
        "pm_review_share": round(
            sum(1 for c in comms if c.intent_tag == "praise") / max(len(comms), 1) * 100, 1
        ),
        "best_keyword_share": 0.0,  # 无关键词数据
        "top_keyword_total_share": 0.0,
    }

    # —— 衰减信号 —
    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
    decay_alert = ""
    if platform == HOME_PLATFORM or platform is None:
        idx = weeks.index(period) if period in weeks else -1
        if idx >= 3:
            roi_series = []
            for w in weeks[max(0, idx - 5):idx + 1]:
                ads_w = [a for a in dbm.get_ads(conn, customer_id, w) if (platform or a.platform == HOME_PLATFORM)]
                sp = sum(a.spend for a in ads_w); gm = sum(a.gmv for a in ads_w)
                roi_series.append((w, round(gm / sp, 2) if sp else 0))
            if roi_series:
                peak = max(r for _, r in roi_series)
                tail3 = roi_series[-3:]
                if peak > 0 and all(r < peak * 0.7 for _, r in tail3):
                    decay_alert = (f"近 3 周边际 ROI 持续低于峰值 {peak * 100:.0f}% 的 70%，"
                                   f"建议本周新建计划替换（不要救旧计划）。")

    # 沟通信号
    neg = [c for c in comms if c.sentiment == "negative"]
    complaints = [c.text for c in comms if c.intent_tag == "complaint"]

    return {
        "cur": t_cur, "prev": t_prev, "wow": wow,
        "by_platform": by_platform, "bench": bench, "bench_xhs_ad": bench_xhs_ad,
        "kfs": kfs, "by_bid": by_bid,
        "by_audience": by_audience, "by_content": by_content,
        "by_subtype": by_subtype,
        "neg_count": len(neg), "complaints": complaints,
        "burst_rate": burst_rate, "engage_avg": engage_avg,
        "note_stats": note_stats, "rep_stats": rep_stats,
        "decay_alert": decay_alert,
    }


# ----------------------------- 报告生成（L4 核心） -----------------------------
def build_report(profile: CustomerProfile, agg_home: Dict, agg_all: Dict, period: str) -> Report:
    """agg_home = 本平台聚合（核心）；agg_all = 全平台聚合（含竞争媒体情报）。"""
    cur, wow = agg_home["cur"], agg_home["wow"]
    home_cn = PLATFORM_CN.get(HOME_PLATFORM, HOME_PLATFORM)
    bench_home = agg_all["bench"].get(HOME_PLATFORM) or 0
    neg = agg_home["neg_count"]
    ctr_pct = f"{cur['ctr']*100:.2f}%"
    cvr_pct = f"{cur['cvr']*100:.2f}%"
    who = f"{profile.name}（{profile.customer_id}，{profile.industry}）"
    stage_cn = STAGE_CN.get(profile.lifecycle_stage, profile.lifecycle_stage)

    home_spend = cur["spend"]
    all_spend = agg_all["cur"]["spend"]
    comp_spend = all_spend - home_spend
    comp_share = round(comp_spend / all_spend * 100, 1) if all_spend else 0
    home_share = round(home_spend / all_spend * 100, 1) if all_spend else 0

    # —— 一句话诊断 ——
    decay_bit = ""
    if agg_home.get("decay_alert"):
        decay_bit = "出现衰减信号（建议新建计划）。"
    burst_bit = f"爆文率 {agg_home['burst_rate']}%。"
    pm_inq, pm_dp, sv = cur["pm_inquiry"], cur["pm_deep"], cur["store_visit"]
    pm_bit = f"私信深度 {pm_dp}（环比 {wow['pm_deep']:+.1f}%）、进店 {sv}（环比 {wow['store_visit']:+.1f}%）。"
    if profile.lifecycle_stage == "at_risk":
        diag = (f"{who}「{stage_cn}」，本周【{home_cn}】消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（基准 {bench_home}），{pm_bit}{burst_bit}客户 {comp_share}% 预算在竞争媒体；"
                f"{decay_bit}先稳住{home_cn}账户再以高 ROI 推动增预算。")
    elif profile.lifecycle_stage == "growing" and wow["spend"] >= 3:
        diag = (f"{who}「{stage_cn}」，本周【{home_cn}】消耗环比+{wow['spend']}%、"
                f"ROI {cur['roi']}（基准 {bench_home}），{pm_bit}客户仅 {home_share}% 在{home_cn}，"
                f"{comp_share}% 在竞争媒体，增量空间大。")
    else:
        diag = (f"{who}「{stage_cn}」，本周【{home_cn}】消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（基准 {bench_home}），{pm_bit}客户全平台{home_cn}占 {home_share}%。")

    # ① 总览与结论
    overview = (
        f"【{home_cn}】本周总消耗 ¥{int(round(cur['spend'])):,}（环比 {wow['spend']}%），"
        f"GMV ¥{int(round(cur['gmv'])):,}（环比 {wow['gmv']}%），"
        f"ROI {cur['roi']}（行业基准 {bench_home}，环比 {wow['roi']}）。"
        f"曝光 {cur['impressions']:,}、点击 {cur['clicks']:,}、"
        f"转化 {cur['conversions']:,}（CTR {ctr_pct}、CVR {cvr_pct}）。"
        f"客户全平台总投放 ¥{int(round(all_spend)):,}，"
        f"其中【{home_cn}】占 {home_share}%、竞争媒体占 {comp_share}%。"
        f"笔记互动率均值 {agg_home['engage_avg']}%。"
        + (f"客户侧收到 {neg} 条负面反馈，需重点关注。" if neg else "客户沟通情绪整体平稳。")
    )

    # ② 私信转化漏斗（蒲公英 5 段）
    pm_inq = cur["pm_inquiry"]; pm_ld = cur["pm_lead"]; pm_dp = cur["pm_deep"]; sv = cur["store_visit"]
    def _rate(a, b): return round(a / b * 100, 1) if b else 0
    pm_funnel = (
        f"消耗 ¥{int(round(cur['spend'])):,} → 私信开口 {pm_inq} → 私信留资 {pm_ld}（开口→留资 {_rate(pm_ld, pm_inq)}%）"
        f" → 私信深度转化（添加企微/内容咨询）{pm_dp}（留资→深度 {_rate(pm_dp, pm_ld)}%）"
        f" → 进店访问 {sv}（深度→进店 {_rate(sv, pm_dp)}%）。\n"
        f"环比：开口 {wow['pm_inquiry']:+}% / 深度 {wow['pm_deep']:+}% / 进店 {wow['store_visit']:+}%。\n"
        f"判断："
        + (("私信开口量明显下滑 → 素材或定向触达变弱，需查 CTR / CPC。"
            if wow["pm_inquiry"] <= -10 else "开口端稳定，")
           + ("留资率偏低 → 优化自动回复话术 / 留资表单。"
              if pm_inq > 0 and pm_ld / pm_inq < 0.35 else "留资率正常，")
           + ("深度转化率（企微/咨询）下滑 → 检查承接客服响应 / 商品详情页。"
              if pm_ld > 0 and pm_dp / pm_ld < 0.45 else "深度承接健康，")
           + ("进店率下滑 → 检查小程序 / 店铺承接链路。"
              if pm_dp > 0 and sv / pm_dp < 0.6 else "进店端 OK。")
           ).strip(",")
    )

    # ③ KFS 投放布局
    kfs_lines = []
    for ad_type in ("信息流", "搜索"):
        d = agg_home["kfs"][ad_type]
        if d["spend"] == 0:
            kfs_lines.append(f"  - {ad_type}：本周无投放")
            continue
        b = agg_home["bench_xhs_ad"].get(ad_type, 0) or 0
        gap = "✓ 跑赢基准" if d["roi"] >= b else "✗ 低于基准"
        kfs_lines.append(
            f"  - {ad_type}：消耗 ¥{d['spend']:,.0f}，ROI {d['roi']}（基准 {b}，{gap}），"
            f"CTR {d['ctr']*100:.2f}%，CVR {d['cvr']*100:.2f}%"
        )
    bid_lines = []
    for bt, d in sorted(agg_home["by_bid"].items(), key=lambda x: -x[1]["spend"]):
        bid_lines.append(f"  - {bt}：消耗 ¥{d['spend']:,.0f}，ROI {d['roi']}")
    kfs_layout = (
        "KFS 框架（小红书特有）：种草 K 已通过绑定的笔记自然承载；"
        "本表聚焦 F（信息流放大）+ S（搜索收割）。\n"
        + "\n".join(kfs_lines)
        + "\n\n出价类型分布：\n"
        + ("\n".join(bid_lines) if bid_lines else "  （无数据）")
        + "\n建议：若信息流 ROI 跑赢搜索，可把搜索预算挪 10~20% 到信息流扩量；反之亦然。"
    )

    # ④ 内容类型 × 广告效果（含 CPE）
    sub_lines = []
    sorted_sub = sorted(agg_home["by_subtype"].items(), key=lambda x: -x[1]["spend"])
    for st, d in sorted_sub:
        sub_lines.append(
            f"  - {st}：消耗 ¥{d['spend']:,.0f}，点击 {d['clicks']:,}，"
            f"CTR {d['ctr']*100:.2f}%，CPC ¥{d['cpc']}，CPM ¥{d['cpm']}，"
            f"计划 {d['plan_cnt']} 个 / 素材 {d['creative_cnt']} 个 / 笔记 {d['note_cnt']} 篇"
        )
    content_type_perf = (
        "按蒲公英 4 类内容类型拆解（效果-外链营销通 / 效果-落地页 / 内容-外链营销通 / 内容-种草达人合作）：\n"
        + ("\n".join(sub_lines) if sub_lines else "  （无数据）")
        + "\n口径说明：CPM=消耗/曝光×1000；CPE=单条私信/进店成本（小红书特有指标）。"
        + "\n建议：转化路径（外链/落地页）+ 内容形态（效果/内容）两两组合，找出最高 ROI 的格。"
    )

    # ⑤ 素材创意 + 笔记活跃度
    n_total = agg_home["note_stats"]["total"]
    n_orig = agg_home["note_stats"]["original"]
    n_cm = agg_home["note_stats"]["comments"]
    n_sh = agg_home["note_stats"]["shares"]
    n_lc = agg_home["note_stats"]["likes_collects"]
    ct_sorted = sorted(agg_home["by_content"].items(), key=lambda x: -x[1]["roi"])
    top3 = ct_sorted[:3]
    bot = ct_sorted[-1] if ct_sorted else None
    ct_lines = []
    for cid, d in top3:
        hot = d["metrics"].get("is_hot", "常文")
        er = d["metrics"].get("engage_rate", 0) * 100
        tag = "🔥" if hot == "爆文" else "  "
        ct_lines.append(f"  {tag} {d['title'][:30]}：ROI {d['roi']}，互动率 {er:.2f}%")
    bot_line = f"  - 最差素材「{bot[1]['title'][:30]}」：ROI {bot[1]['roi']}，建议关停。" if bot else ""
    # 创意占比用 by_subtype 占比模拟（plan 维度）
    plan_total = sum(d["plan_cnt"] for d in agg_home["by_subtype"].values()) or 1
    creative_pies = [(st, round(d["plan_cnt"] / plan_total * 100, 1))
                     for st, d in agg_home["by_subtype"].items()]
    creative_pies.sort(key=lambda x: -x[1])
    pie_lines = [f"  - {st}：{pct}%" for st, pct in creative_pies]
    creative_note = (
        f"素材创意占比（按计划数）：\n" + ("\n".join(pie_lines) if pie_lines else "  （无数据）")
        + f"\n\n笔记活跃度（蒲公英「日均」口径累计到本周）：\n"
        + f"  - 新增笔记：{n_total} 篇（原创 {n_orig} 篇 / 占比 {round(n_orig/max(n_total,1)*100,1)}%）\n"
        + f"  - 互动累计：评论 {n_cm:,} / 分享 {n_sh:,} / 赞藏 {n_lc:,}\n"
        f"  - 爆文率 {agg_home['burst_rate']}%，平均互动率 {agg_home['engage_avg']}%\n\n"
        f"TOP 素材（按 ROI 降序）：\n" + "\n".join(ct_lines) + "\n" + bot_line + "\n"
        + (f"\n⚠️ 衰减信号：{agg_home['decay_alert']}" if agg_home.get("decay_alert") else "")
    )

    # ⑥ 漏斗诊断 + 人群定向
    prev = agg_home["prev"]
    pre_imp = prev["impressions"]; pre_clk = prev["clicks"]; pre_cv = prev["conversions"]
    exp_wow = round((cur["impressions"] - pre_imp) / pre_imp * 100, 1) if pre_imp else 0
    clk_wow = round((cur["clicks"] - pre_clk) / pre_clk * 100, 1) if pre_clk else 0
    cv_wow = round((cur["conversions"] - pre_cv) / pre_cv * 100, 1) if pre_cv else 0
    exp_ok = exp_wow >= -5; clk_ok = clk_wow >= -5; cv_ok = cv_wow >= -5
    if not exp_ok and not clk_ok and not cv_ok:
        diag_3 = "三层均下滑，建议全链路诊断（可能素材 + 人群 + 落地页均有问题）。"
    elif not exp_ok and clk_ok and cv_ok:
        diag_3 = "曝光下滑但点击-转化正常 → 问题在出价 / 定向（人群过窄）。"
    elif exp_ok and not clk_ok and cv_ok:
        diag_3 = "曝光正常但点击下滑 → 问题在素材（封面/标题）。"
    elif exp_ok and clk_ok and not cv_ok:
        diag_3 = "点击正常但转化下滑 → 问题在落地页 / 承接 / 商品详情。"
    else:
        diag_3 = "各层数据波动在可接受范围。"
    aud_lines = []
    aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: -x[1]["roi"])
    for au, d in aud_sorted:
        aud_lines.append(f"  - {au}：消耗 ¥{d['spend']:,.0f}，ROI {d['roi']}，CTR {d['ctr']*100:.2f}%")
    best_aud = aud_sorted[0] if aud_sorted else None
    worst_aud = aud_sorted[-1] if aud_sorted else None
    funnel_audience = (
        f"曝光 {cur['impressions']:,}（环比 {exp_wow:+}%）、"
        f"点击 {cur['clicks']:,}（环比 {clk_wow:+}%）、"
        f"转化 {cur['conversions']:,}（环比 {cv_wow:+}%）。"
        f"诊断：{diag_3}\n\n"
        f"人群四细分（人群包 / 关键词定向 / 行为兴趣 / 智能定向）：\n"
        + "\n".join(aud_lines)
        + (f"\n判断：最优「{best_aud[0]}」（ROI {best_aud[1]['roi']}）应持续放量；"
           f"最差「{worst_aud[0]}」（ROI {worst_aud[1]['roi']}）应收缩预算或重测。"
           if best_aud and worst_aud else "")
    )

    # ⑦ 口碑关键词 + 竞争媒体情报
    rep = agg_home["rep_stats"]
    comp_rows = []
    for p, d in agg_all["by_platform"].items():
        if p == HOME_PLATFORM:
            continue
        share = round(d["spend"] / all_spend * 100, 1) if all_spend else 0
        comp_rows.append((PLATFORM_CN.get(p, p), d["spend"], d["roi"], share))
    comp_rows.sort(key=lambda x: -x[1])
    comp_lines = [f"  - {n}：消耗 ¥{s:,.0f}，ROI {r}（占全平台 {sh}%）" for n, s, r, sh in comp_rows]
    reputation_competitor = (
        f"口碑关键词（基于沟通/互动数据代理口径）：\n"
        f"  - 口碑好评率 {rep['review_rate']}%（客户正面沟通占比）\n"
        f"  - 私信打开率 {rep['pm_open_rate']}%（留资/开口）\n"
        f"  - 私聊好评数占比 {rep['pm_review_share']}%\n\n"
        f"客户全平台预算中，【{home_cn}】仅占 {home_share}%，竞争媒体合计占 {comp_share}%。\n"
        + ("\n".join(comp_lines) if comp_lines else "  （暂无竞争媒体投放数据）")
        + f"\n话术建议：以「{home_cn} ROI {cur['roi']} vs 竞争媒体」作为增预算 / 挪量支点，"
        + ("说明深耕本平台的更高回报。" if cur['roi'] >= bench_home else "需先做客户账户诊断（ROI 跑输基准）。")
    )

    # ⑧ 下一步行动
    actions = []
    if agg_home.get("decay_alert"):
        actions.append(f"🚨 【衰减】新建计划替换，参考 TOP 素材的选题 / 钩子；不要在旧计划上调价。")
    if wow["spend"] <= -5:
        actions.append(f"立即暂停【{home_cn}】ROI 最低的计划，回收预算至高 ROI 人群 / 素材。")
    kfs_f = agg_home["kfs"]["信息流"]; kfs_s = agg_home["kfs"]["搜索"]
    if kfs_f["spend"] > 0 and kfs_s["spend"] > 0:
        if kfs_f["roi"] > kfs_s["roi"] * 1.2:
            actions.append(f"KFS 调结构：信息流 ROI {kfs_f['roi']} 显著跑赢搜索 {kfs_s['roi']}，"
                           f"建议把搜索预算挪 10~20% 到信息流扩量。")
        elif kfs_s["roi"] > kfs_f["roi"] * 1.2:
            actions.append(f"KFS 调结构：搜索 ROI {kfs_s['roi']} 显著跑赢信息流 {kfs_f['roi']}，"
                           f"建议追加搜索关键词覆盖（精搜品牌词 + 长尾词）。")
    # 私信漏斗针对性
    if pm_inq > 0 and pm_ld / pm_inq < 0.35:
        actions.append(f"私信留资率偏低（{round(pm_ld/pm_inq*100,1)}%）→ 优化自动回复 / 留资表单设计。")
    if pm_ld > 0 and pm_dp / pm_ld < 0.45:
        actions.append(f"私信深度转化率偏低（{round(pm_dp/pm_ld*100,1)}%）→ 检查客服响应速度与承接话术。")
    # 内容类型最优
    if sorted_sub:
        top_st, top_d = sorted_sub[0]
        actions.append(f"内容类型：复制「{top_st}」（消耗 ¥{top_d['spend']:,.0f}，CTR {top_d['ctr']*100:.2f}%）的结构到新计划。")
    # 笔记活跃度
    if agg_home["note_stats"]["total"] > 0 and agg_home["note_stats"]["original"] / agg_home["note_stats"]["total"] < 0.6:
        actions.append(f"原创笔记占比仅 {round(agg_home['note_stats']['original']/agg_home['note_stats']['total']*100,1)}% → 提高品牌原创产出（爆文率更高）。")
    if best_aud:
        actions.append(f"人群扩容：对「{best_aud[0]}」（ROI {best_aud[1]['roi']}）做相似人群扩展。")
    if ct_sorted:
        top_title = ct_sorted[0][1]["title"][:18]
        actions.append(f"素材复用：复制 TOP 素材「{top_title}…」的钩子到新计划。")
    if neg:
        actions.append(f"针对 {neg} 条客户负面反馈准备沟通话术与补偿方案。")
    actions.append(f"以「{home_cn} ROI {cur['roi']} vs 竞争媒体」为支点，"
                   f"向客户提案增预算 / 挪量（当前{home_cn}仅占全平台 {home_share}%）。")
    next_actions = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(actions))

    return Report(
        customer_id=profile.customer_id, period=period, diagnosis=diag,
        overview=overview,
        pm_funnel=pm_funnel, kfs_layout=kfs_layout,
        content_type_perf=content_type_perf, creative_note=creative_note,
        funnel_audience=funnel_audience, reputation_competitor=reputation_competitor,
        next_actions=next_actions,
        home_platform=HOME_PLATFORM, home_share=home_share, comp_share=comp_share,
        burst_rate=agg_home["burst_rate"], note_engage_avg=agg_home["engage_avg"],
        decay_signal=agg_home.get("decay_alert", ""),
        note_stats=agg_home["note_stats"], pm_stats={"pm_open_rate": agg_home["rep_stats"]["pm_open_rate"]},
    )


# ----------------------------- 主入口（L1/L5/L8） -----------------------------
def run_weekly_review(conn, customer_id: str, period: str, llm: LLMClient,
                      prev_period: Optional[str] = None) -> Report:
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
    agg_all = compute_aggregates(conn, customer_id, period, prev_period, contents, comms)
    agg_home = compute_aggregates(conn, customer_id, period, prev_period, contents, comms,
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
    return f"""你是互联网商业化投放（小红书聚光 + 信息流 + 搜索）的复盘专家。本工作台属于「{home_cn}」的商业化销售团队。

客户：{profile.customer_id}（{profile.industry}，{profile.tier}），负责人 {profile.owner}

【本平台 {home_cn}】本周聚合：{agg_home['cur']}
本平台环比：{agg_home['wow']}
私信漏斗：{agg_home['cur']}
KFS（信息流/搜索）：{agg_home['kfs']}
出价类型：{agg_home['by_bid']}
分人群：{agg_home['by_audience']}
分内容类型：{agg_home['by_subtype']}
分素材：{agg_home['by_content']}
笔记活跃度：{agg_home['note_stats']}
口碑代理：{agg_home['rep_stats']}
爆文率：{agg_home['burst_rate']}%  笔记平均互动率：{agg_home['engage_avg']}%
衰减信号：{agg_home.get('decay_alert', '无')}

【全平台（含竞争媒体）】分平台：{agg_all['by_platform']}
行业基准 ROI：{agg_all['bench']}
客户负面反馈：{agg_home['complaints']}

请严格按以下格式输出（标题不可改）：
【一句话诊断】<一句话>
① 总览与结论
② 私信转化漏斗（蒲公英核心 5 段）
③ KFS 投放布局（信息流 vs 搜索）
④ 内容类型 × 广告效果（含 CPE）
⑤ 素材创意 + 笔记活跃度
⑥ 漏斗诊断 + 人群定向
⑦ 口碑关键词 + 竞争媒体情报
⑧ 下一步行动

参考范式：
{report.render()}
"""


def _parse_report(text: str, customer_id, period) -> Optional[Report]:
    import re
    def _sec(name, *nexts):
        # 匹配当前节直到下一个 ①/②... 标题
        next_pat = "|".join(re.escape(n) for n in nexts)
        m = re.search(rf"{re.escape(name)}\s*(.*?)(?={next_pat}|$)", text, re.S)
        return m.group(1).strip() if m else ""
    diag_m = re.search(r"【一句话诊断】\s*(.*)", text)
    return Report(
        customer_id=customer_id, period=period,
        diagnosis=diag_m.group(1).strip() if diag_m else "",
        overview=_sec("①", "②"),
        pm_funnel=_sec("②", "③"),
        kfs_layout=_sec("③", "④"),
        content_type_perf=_sec("④", "⑤"),
        creative_note=_sec("⑤", "⑥"),
        funnel_audience=_sec("⑥", "⑦"),
        reputation_competitor=_sec("⑦", "⑧"),
        next_actions=_sec("⑧"), raw=text,
    )
"""
weekly_review.py : 核心 AI 节点 —— 每周投放复盘
================================================
输入：customer_id + period（周）
输出：一句话诊断 + 真实 8 段式小红书投放复盘报告

视角模型：
  本工作台属于「某一家互联网公司」的商业化销售团队（本平台 = 小红书）。
  - 本平台（小红书）= 销售真正经营的客户账户 → 复盘核心（①~⑥）
  - 竞争媒体（抖音 / 腾讯 / 快手）= 客户在其他平台的投放 → 情报视角（⑦）

复盘结构（基于小红书/信息流投放真实逻辑，参考微盟天启 / 销售易 NeoAgent /
xhs-universe-weekly / 抖音巨量AD / 小红书聚光 Mio）：
  ① 总览与结论      → 本周核心指标 vs 上周 + 行业基准
  ② KFS 投放布局    → 信息流 F vs 搜索 S（小红书特有，KFS 中的 F 和 S）
  ③ 漏斗三段诊断    → 曝光 → 点击 → 转化，每层独立诊断
  ④ 素材表现        → 爆文率 / 笔记互动率 / 自然流量反哺 + 衰减信号
  ⑤ 人群定向        → 人群包 / 关键词定向 / 行为兴趣 / 智能定向 四细分
  ⑥ 转化分层        → 浅层（私信/留资） vs 深层（下单/成交）
  ⑦ 竞争媒体情报    → 客户跨平台分配 → 增预算话术依据
  ⑧ 下一步行动      → 含衰减触发新建、出价调整、人群扩容建议

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
    kfs_layout: str        # ② KFS 信息流 vs 搜索
    funnel_diag: str       # ③ 漏斗三段
    content_perf: str      # ④ 素材表现 + 爆文率 + 衰减
    audience_perf: str     # ⑤ 人群四细分
    conversion_layer: str  # ⑥ 浅层 vs 深层
    competitor_intel: str  # ⑦ 竞争媒体情报
    next_actions: str
    raw: str = ""
    home_platform: str = HOME_PLATFORM
    home_share: float = 0.0
    comp_share: float = 0.0
    # 扩展指标（供 UI 渲染）
    burst_rate: float = 0.0         # 爆文率
    note_engage_avg: float = 0.0    # 笔记平均互动率
    decay_signal: str = ""          # 衰减信号

    def render(self) -> str:
        return (
            f"# 每周投放复盘 · {self.customer_id} · {self.period}\n\n"
            f"【一句话诊断】{self.diagnosis}\n\n"
            f"① 总览与结论\n{self.overview}\n\n"
            f"② KFS 投放布局（信息流 vs 搜索）\n{self.kfs_layout}\n\n"
            f"③ 漏斗三段诊断\n{self.funnel_diag}\n\n"
            f"④ 素材表现（含爆文率 + 衰减信号）\n{self.content_perf}\n\n"
            f"⑤ 人群定向（四细分）\n{self.audience_perf}\n\n"
            f"⑥ 转化分层（浅层 vs 深层）\n{self.conversion_layer}\n\n"
            f"🌐 ⑦ 竞争媒体情报\n{self.competitor_intel}\n\n"
            f"⑧ 下一步行动\n{self.next_actions}\n"
        )


# ----------------------------- 聚合（L3 预处理） -----------------------------
def _totals(ads: List[AdPerformance]) -> Dict:
    imp = sum(a.impressions for a in ads)
    clk = sum(a.clicks for a in ads)
    sp = sum(a.spend for a in ads)
    cv = sum(a.conversions for a in ads)
    gmv = sum(a.gmv for a in ads)
    cv_shallow = sum(a.cv_shallow for a in ads)
    cv_deep = sum(a.cv_deep for a in ads)
    return {
        "impressions": imp, "clicks": clk, "spend": round(sp, 1),
        "conversions": cv, "gmv": round(gmv, 1),
        "cv_shallow": cv_shallow, "cv_deep": cv_deep,
        "ctr": round(clk / imp, 4) if imp else 0,
        "cvr": round(cv / clk, 4) if clk else 0,
        "cpc": round(sp / clk, 2) if clk else 0,
        "roi": round(gmv / sp, 2) if sp else 0,
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
    # 小红书细分到 ad_type 的基准
    bench_xhs_ad = {}
    for ad_type in ("信息流", "搜索"):
        rows = conn.execute(
            "SELECT benchmark_roi FROM benchmarks WHERE platform=? AND period=? AND ad_type=?",
            (HOME_PLATFORM, period, ad_type)).fetchall()
        bench_xhs_ad[ad_type] = round(sum(r[0] for r in rows) / len(rows), 2) if rows else None

    # —— 人群四细分（人群包 / 关键词定向 / 行为兴趣 / 智能定向）——
    by_audience = {}
    for a in cur:
        au = by_audience.setdefault(a.audience_segment, {"spend": 0, "gmv": 0, "conv": 0, "impr": 0, "clicks": 0})
        au["spend"] += a.spend; au["gmv"] += a.gmv; au["conv"] += a.conversions
        au["impr"] += a.impressions; au["clicks"] += a.clicks
    for d in by_audience.values():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0
        d["ctr"] = round(d["clicks"] / d["impr"], 4) if d["impr"] else 0

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

    # —— 爆文率 / 笔记互动率（key_metrics 已含 is_hot / engage_rate）——
    if contents:
        burst = sum(1 for c in contents if c.key_metrics.get("is_hot") == "爆文")
        burst_rate = round(burst / len(contents) * 100, 1)
        engage_avg = round(sum(c.key_metrics.get("engage_rate", 0) for c in contents) / len(contents) * 100, 2)
    else:
        burst_rate, engage_avg = 0.0, 0.0

    # —— 衰减信号：边际 ROI 连续 3 周低于峰值 70% → 触发新建建议 —
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
        "neg_count": len(neg), "complaints": complaints,
        "burst_rate": burst_rate, "engage_avg": engage_avg,
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

    # —— 一句话诊断（本平台信号 + 竞争媒体占比 + 衰减/爆文）——
    decay_bit = ""
    if agg_home.get("decay_alert"):
        decay_bit = "出现衰减信号（建议新建计划）。"
    burst_bit = f"爆文率 {agg_home['burst_rate']}%。"
    if profile.lifecycle_stage == "at_risk":
        diag = (f"{who}「{stage_cn}」，本周【{home_cn}】消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（基准 {bench_home}），CTR {ctr_pct}、CVR {cvr_pct}，"
                f"{burst_bit}客户 {comp_share}% 预算在竞争媒体；{decay_bit}"
                f"先稳住{home_cn}账户再以高 ROI 推动增预算。")
    elif profile.lifecycle_stage == "growing" and wow["spend"] >= 3:
        diag = (f"{who}「{stage_cn}」，本周【{home_cn}】消耗环比+{wow['spend']}%、"
                f"ROI {cur['roi']}（基准 {bench_home}），{burst_bit}"
                f"客户仅 {home_share}% 在{home_cn}，{comp_share}% 在竞争媒体，增量空间大。")
    else:
        diag = (f"{who}「{stage_cn}」，本周【{home_cn}】消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（基准 {bench_home}），CTR {ctr_pct}、CVR {cvr_pct}；"
                f"{burst_bit}客户全平台{home_cn}占 {home_share}%。")

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

    # ② KFS 投放布局（信息流 F vs 搜索 S）
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
    # 出价维度
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

    # ③ 漏斗三段诊断
    prev = agg_home["prev"]
    pre_imp = prev["impressions"]; pre_clk = prev["clicks"]; pre_cv = prev["conversions"]
    exp_wow = round((cur["impressions"] - pre_imp) / pre_imp * 100, 1) if pre_imp else 0
    clk_wow = round((cur["clicks"] - pre_clk) / pre_clk * 100, 1) if pre_clk else 0
    cv_wow = round((cur["conversions"] - pre_cv) / pre_cv * 100, 1) if pre_cv else 0
    # 漏斗判断
    exp_ok = exp_wow >= -5
    clk_ok = clk_wow >= -5
    cv_ok = cv_wow >= -5
    if not exp_ok and not clk_ok and not cv_ok:
        diag_3 = "三层均下滑，建议全链路诊断（可能素材 + 人群 + 落地页均有问题）。"
    elif not exp_ok and clk_ok and cv_ok:
        diag_3 = "曝光下滑但点击-转化正常 → 问题在出价 / 定向（人群过窄）。"
    elif exp_ok and not clk_ok and cv_ok:
        diag_3 = "曝光正常但点击下滑 → 问题在素材（封面/标题）。"
    elif exp_ok and clk_ok and not cv_ok:
        diag_3 = "点击正常但转化下滑 → 问题在落地页 / 承接 / 商品详情。需检查 C 端承接。"
    else:
        diag_3 = "各层数据波动在可接受范围。"
    funnel_diag = (
        f"曝光 {cur['impressions']:,}（环比 {exp_wow:+}%）、"
        f"点击 {cur['clicks']:,}（环比 {clk_wow:+}%）、"
        f"转化 {cur['conversions']:,}（环比 {cv_wow:+}%）。\n"
        f"诊断：{diag_3}\n"
        f"杠杆点：CTR 偏低则换素材/封面；CVR 偏低则改落地页；CPC 偏高则收缩定向。"
    )

    # ④ 素材表现 + 爆文率 + 衰减
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
    content_perf = (
        f"爆文率 {agg_home['burst_rate']}%（{len([c for c in agg_home['by_content'] if agg_home['by_content'][c]['metrics'].get('is_hot') == '爆文'])}"
        f"/{len(agg_home['by_content'])} 篇爆文），笔记平均互动率 {agg_home['engage_avg']}%。\n"
        f"（爆文判定：阅读 ≥ 5w 且互动率 ≥ 5%）\n"
        f"TOP 素材（按 ROI 降序）：\n" + "\n".join(ct_lines) + "\n" + bot_line + "\n"
        f"自然流量反哺：爆文笔记发布后 7~30 天仍持续获得自然搜索流量，"
        f"对广告 ROI 形成正向反哺，建议复盘时区分「广告付费 GMV」与「笔记自然 GMV」。"
        + (f"\n\n⚠️ 衰减信号：{agg_home['decay_alert']}" if agg_home.get("decay_alert") else "")
    )

    # ⑤ 人群定向四细分
    aud_lines = []
    aud_sorted = sorted(agg_home["by_audience"].items(), key=lambda x: -x[1]["roi"])
    for au, d in aud_sorted:
        aud_lines.append(f"  - {au}：消耗 ¥{d['spend']:,.0f}，ROI {d['roi']}，CTR {d['ctr']*100:.2f}%")
    best_aud = aud_sorted[0] if aud_sorted else None
    worst_aud = aud_sorted[-1] if aud_sorted else None
    audience_perf = (
        "按小红书后台 4 类人群维度（人群包 / 关键词定向 / 行为兴趣 / 智能定向）拆解：\n"
        + "\n".join(aud_lines)
        + (f"\n判断：最优「{best_aud[0]}」（ROI {best_aud[1]['roi']}）应持续放量；"
           f"最差「{worst_aud[0]}」（ROI {worst_aud[1]['roi']}）应收缩预算或重测。"
           if best_aud and worst_aud else "")
    )

    # ⑥ 转化分层
    cv_shallow_total = cur["cv_shallow"]
    cv_deep_total = cur["cv_deep"]
    cv_total = cv_shallow_total + cv_deep_total
    deep_rate = round(cv_deep_total / cv_total * 100, 1) if cv_total else 0
    deep_share_spend = round(cv_deep_total * (cur["gmv"] / max(cv_deep_total, 1)) / max(cur["spend"], 1), 2) if cv_deep_total else 0
    conversion_layer = (
        f"浅层转化（私信/留资/加粉）：{cv_shallow_total} 条"
        + (f"，占 {round(cv_shallow_total/cv_total*100,1)}%" if cv_total else "")
        + f"\n深层转化（下单/成交）：{cv_deep_total} 条"
        + (f"，占 {deep_rate}%" if cv_total else "")
        + f"\nGMV 全部由深层转化贡献：¥{int(round(cur['gmv'])):,}\n"
        + (f"判断：深层占比 {deep_rate}%"
           + ("，偏浅层（线索型）→ 加深链路设计；若客户目标是 GMV，应提升深度转化激励。" if deep_rate < 40
              else "，深层转化健康 → 加深链路可保持当前节奏。"))
    )

    # ⑦ 竞争媒体情报
    comp_rows = []
    for p, d in agg_all["by_platform"].items():
        if p == HOME_PLATFORM:
            continue
        share = round(d["spend"] / all_spend * 100, 1) if all_spend else 0
        comp_rows.append((PLATFORM_CN.get(p, p), d["spend"], d["roi"], share))
    comp_rows.sort(key=lambda x: -x[1])
    comp_lines = [f"  - {n}：消耗 ¥{s:,.0f}，ROI {r}（占全平台 {sh}%）" for n, s, r, sh in comp_rows]
    competitor_intel = (
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
    # KFS 调结构
    kfs_f = agg_home["kfs"]["信息流"]; kfs_s = agg_home["kfs"]["搜索"]
    if kfs_f["spend"] > 0 and kfs_s["spend"] > 0:
        if kfs_f["roi"] > kfs_s["roi"] * 1.2:
            actions.append(f"KFS 调结构：信息流 ROI {kfs_f['roi']} 显著跑赢搜索 {kfs_s['roi']}，"
                           f"建议把搜索预算挪 10~20% 到信息流扩量。")
        elif kfs_s["roi"] > kfs_f["roi"] * 1.2:
            actions.append(f"KFS 调结构：搜索 ROI {kfs_s['roi']} 显著跑赢信息流 {kfs_f['roi']}，"
                           f"建议追加搜索关键词覆盖（精搜品牌词 + 长尾词）。")
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
        overview=overview, kfs_layout=kfs_layout, funnel_diag=funnel_diag,
        content_perf=content_perf, audience_perf=audience_perf,
        conversion_layer=conversion_layer, competitor_intel=competitor_intel,
        next_actions=next_actions,
        home_platform=HOME_PLATFORM, home_share=home_share, comp_share=comp_share,
        burst_rate=agg_home["burst_rate"], note_engage_avg=agg_home["engage_avg"],
        decay_signal=agg_home.get("decay_alert", ""),
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
KFS（信息流/搜索）：{agg_home['kfs']}
出价类型：{agg_home['by_bid']}
分人群：{agg_home['by_audience']}
分素材：{agg_home['by_content']}
爆文率：{agg_home['burst_rate']}%  笔记平均互动率：{agg_home['engage_avg']}%
衰减信号：{agg_home.get('decay_alert', '无')}

【全平台（含竞争媒体）】分平台：{agg_all['by_platform']}
行业基准 ROI：{agg_all['bench']}
客户负面反馈：{agg_home['complaints']}

请严格按以下格式输出（标题不可改）：
【一句话诊断】<一句话>
① 总览与结论
② KFS 投放布局（信息流 vs 搜索）
③ 漏斗三段诊断
④ 素材表现（含爆文率 + 衰减信号）
⑤ 人群定向（四细分）
⑥ 转化分层（浅层 vs 深层）
🌐 ⑦ 竞争媒体情报
⑧ 下一步行动

参考范式：
{report.render()}
"""


def _parse_report(text: str, customer_id, period) -> Optional[Report]:
    import re
    def _sec(name):
        m = re.search(rf"{re.escape(name)}\s*(.*?)(?=①|②|③|④|⑤|🌐|⑧|$)", text, re.S)
        return m.group(1).strip() if m else ""
    diag_m = re.search(r"【一句话诊断】\s*(.*)", text)
    return Report(
        customer_id=customer_id, period=period,
        diagnosis=diag_m.group(1).strip() if diag_m else "",
        overview=_sec("①"), kfs_layout=_sec("②"), funnel_diag=_sec("③"),
        content_perf=_sec("④"), audience_perf=_sec("⑤"),
        conversion_layer=_sec("⑥"), competitor_intel=_sec("🌐 ⑦"),
        next_actions=_sec("⑧"), raw=text,
    )
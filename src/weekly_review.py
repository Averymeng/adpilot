"""
weekly_review.py : 核心 AI 节点 —— 每周投放复盘
================================================
输入：customer_id + period（周）
输出：一句话诊断 + RACAE 五段式完整报告

视角模型（关键修正）：
  本工作台属于「某一家互联网公司」的商业化销售团队（本平台 = 小红书）。
  - 本平台（小红书）= 销售真正经营的客户账户 → 复盘核心（①~④）
  - 竞争媒体（抖音 / 腾讯 / 快手）= 客户在其他平台的投放 → 情报视角（增预算话术依据）

  ⚠️ 不再采用「上帝视角 / 代理商视角」把所有平台当成本公司经营。

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


@dataclass
class Report:
    customer_id: str
    period: str
    diagnosis: str
    overview: str
    layout: str
    layer_perf: str
    combo_perf: str
    next_actions: str
    raw: str = ""
    home_platform: str = HOME_PLATFORM
    home_share: float = 0.0
    comp_share: float = 0.0

    def render(self) -> str:
        return (
            f"# 每周投放复盘 · {self.customer_id} · {self.period}\n\n"
            f"【一句话诊断】{self.diagnosis}\n\n"
            f"① 总览与结论\n{self.overview}\n\n"
            f"② 广告布局 / 漏斗分配\n{self.layout}\n\n"
            f"③ 各层级成效（按周对比趋势）\n{self.layer_perf}\n\n"
            f"④ 广告组合成效（受众 + 素材双维度）\n{self.combo_perf}\n\n"
            f"⑤ 下一步行动\n{self.next_actions}\n"
        )


# ----------------------------- 聚合（L3 预处理） -----------------------------
def _totals(ads: List[AdPerformance]) -> Dict:
    imp = sum(a.impressions for a in ads)
    clk = sum(a.clicks for a in ads)
    sp = sum(a.spend for a in ads)
    cv = sum(a.conversions for a in ads)
    gmv = sum(a.gmv for a in ads)
    return {
        "impressions": imp, "clicks": clk, "spend": round(sp, 1),
        "conversions": cv, "gmv": round(gmv, 1),
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

    # 环比
    def _pct(a, b):
        return round((a - b) / b * 100, 1) if b else 0.0
    wow = {
        "spend": _pct(t_cur["spend"], t_prev["spend"]),
        "gmv": _pct(t_cur["gmv"], t_prev["gmv"]),
        "roi": round(t_cur["roi"] - t_prev["roi"], 2),
        "clicks": _pct(t_cur["clicks"], t_prev["clicks"]),
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

    # 对标行业大盘（取各平台本周基准 ROI 均值）
    bench = {}
    for p in by_platform:
        rows = conn.execute(
            "SELECT benchmark_roi FROM benchmarks WHERE platform=? AND period=?",
            (p, period)).fetchall()
        bench[p] = round(sum(r[0] for r in rows) / len(rows), 2) if rows else None

    # 广告组合：按受众 / 素材
    by_audience = {}
    by_content = {}
    title_map = {c.content_id: c.title for c in contents}
    for a in cur:
        au = by_audience.setdefault(a.audience_segment, {"spend": 0, "gmv": 0, "conv": 0})
        au["spend"] += a.spend; au["gmv"] += a.gmv; au["conv"] += a.conversions
        ct = by_content.setdefault(a.content_id, {"spend": 0, "gmv": 0, "conv": 0, "title": title_map.get(a.content_id, a.content_id)})
        ct["spend"] += a.spend; ct["gmv"] += a.gmv; ct["conv"] += a.conversions
    for d in by_audience.values():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0
    for d in by_content.values():
        d["roi"] = round(d["gmv"] / d["spend"], 2) if d["spend"] else 0

    # 沟通信号
    neg = [c for c in comms if c.sentiment == "negative"]
    complaints = [c.text for c in comms if c.intent_tag == "complaint"]

    return {
        "cur": t_cur, "prev": t_prev, "wow": wow,
        "by_platform": by_platform, "bench": bench,
        "by_audience": by_audience, "by_content": by_content,
        "neg_count": len(neg), "complaints": complaints,
    }


# ----------------------------- 报告生成（L4 核心） -----------------------------
STAGE_CN = {"at_risk": "流失风险", "growing": "高速增长",
            "onboarding": "新客期", "stable": "稳定期"}


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

    # 竞争媒体占比（客户在抖音/腾讯/快手等平台的预算份额）
    home_spend = cur["spend"]
    all_spend = agg_all["cur"]["spend"]
    comp_spend = all_spend - home_spend
    comp_share = round(comp_spend / all_spend * 100, 1) if all_spend else 0
    home_share = round(home_spend / all_spend * 100, 1) if all_spend else 0

    # —— 一句话诊断（本平台信号 + 竞争媒体占比）—— 
    if profile.lifecycle_stage == "at_risk":
        diag = (f"{who} 处于「{stage_cn}」，本周在【{home_cn}】消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（行业基准 {bench_home}），叠加 {neg} 条负面反馈；"
                f"客户全平台 {comp_share}% 预算流向竞争媒体，建议先稳住{home_cn}账户，再以高 ROI 推动增预算。")
    elif profile.lifecycle_stage == "growing" and wow["spend"] >= 3:
        diag = (f"{who}「{stage_cn}」，本周在【{home_cn}】消耗环比+{wow['spend']}%、"
                f"ROI {cur['roi']}（行业基准 {bench_home}），增长健康；"
                f"但客户仅 {home_share}% 预算在{home_cn}、竞争媒体占 {comp_share}%，存在明显增量空间。")
    else:
        diag = (f"{who}「{stage_cn}」，本周在【{home_cn}】消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（行业基准 {bench_home}），整体平稳；"
                f"客户全平台预算中{home_cn}占 {home_share}%、竞争媒体占 {comp_share}%。")

    # ① 总览（本平台账户 + 跨平台占比）
    overview = (
        f"【{home_cn}】账户本周总览：总消耗 ¥{int(round(cur['spend'])):,}（环比 {wow['spend']}%），"
        f"GMV ¥{int(round(cur['gmv'])):,}（环比 {wow['gmv']}%），综合 ROI {cur['roi']}（行业基准 {bench_home}，环比 {wow['roi']}）。"
        f"曝光 {cur['impressions']:,}、点击 {cur['clicks']:,}、转化 {cur['conversions']:,}，CTR {ctr_pct}、CVR {cvr_pct}。"
        f"客户全平台总投放 ¥{int(round(all_spend)):,}，其中【{home_cn}】占 {home_share}%、竞争媒体（抖音/腾讯/快手）占 {comp_share}%。"
        + (f"客户侧收到 {neg} 条负面反馈，需重点关注。" if neg else "客户沟通情绪整体平稳。")
    )

    # ② 广告布局 / 漏斗分配（跨平台视角，本平台 vs 竞争媒体）
    plat_lines = []
    for p, d in sorted(agg_all["by_platform"].items(), key=lambda x: -x[1]["spend"]):
        tag = "【本平台】" if p == HOME_PLATFORM else "（竞争媒体）"
        b = agg_all["bench"].get(p)
        flag = f"（行业基准 ROI {b}）" if b else ""
        plat_lines.append(f"  - {PLATFORM_CN.get(p, p)} {tag}: 消耗 ¥{d['spend']:,.0f}，ROI {d['roi']}{flag}")
    layout = "预算分配与漏斗结构（跨平台视角）：\n" + "\n".join(plat_lines) + (
        f"\n关键判断：客户在【{home_cn}】仅占 {home_share}% 预算、竞争媒体占 {comp_share}%；"
        f"若{home_cn} ROI 高于竞争媒体，应以此为支点推动客户增预算 / 挪量。"
    )

    # ③ 各层级成效（本平台，按周对比）
    layer_perf = (
        f"【{home_cn}】本周 vs 上周：消耗 {wow['spend']}%、点击 {wow['clicks']}%、GMV {wow['gmv']}%、ROI {wow['roi']}。"
        f"漏斗看，点击层（CTR {ctr_pct}）与转化层（CVR {cvr_pct}）是主要杠杆点；"
        f"若 CTR 正常但 CVR 偏低，问题在落地页 / 承接，而非素材。"
    )

    # ④ 广告组合成效（本平台：受众 + 素材）
    aud = sorted(agg_home["by_audience"].items(), key=lambda x: -x[1]["roi"])
    best_aud, worst_aud = aud[0], aud[-1]
    ct = sorted(agg_home["by_content"].items(), key=lambda x: -x[1]["roi"])
    best_ct = ct[0]
    combo = (
        f"【{home_cn}】受众维度：最优「{best_aud[0]}」ROI {best_aud[1]['roi']}，最差「{worst_aud[0]}」ROI {worst_aud[1]['roi']}，"
        f"建议把预算从最差人群迁到最优人群。\n"
        f"素材维度：表现最佳素材「{best_ct[1]['title']}」ROI {best_ct[1]['roi']}，可复制其选题 / 钩子到新计划。"
    )

    # ⑤ 下一步（本平台优化 + 竞争媒体增预算话术）
    actions = []
    if wow["spend"] <= -5:
        actions.append(f"立即暂停【{home_cn}】ROI 最低的计划，回收预算至高 ROI 人群。")
    if neg:
        actions.append(f"针对客户负面反馈（如：{agg_home['complaints'][0][:30]}…）准备沟通话术与补偿方案。")
    actions.append(
        f"以「{home_cn} ROI {cur['roi']} vs 竞争媒体」为支点，向客户提案增预算 / 挪量"
        f"（当前{home_cn}仅占全平台 {home_share}%）。")
    actions.append(f"将【{home_cn}】预算向最优人群「{best_aud[0]}」与优质素材「{best_ct[1]['title'][:15]}」倾斜。")
    actions.append("下周复盘前重测 1~2 组高意向人群定向，验证 ROI 是否回升。")
    next_actions = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(actions))

    return Report(
        customer_id=profile.customer_id, period=period, diagnosis=diag,
        overview=overview, layout=layout, layer_perf=layer_perf,
        combo_perf=combo, next_actions=next_actions,
        home_platform=HOME_PLATFORM, home_share=home_share, comp_share=comp_share,
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
    # 双视角聚合：本平台（核心）+ 全平台（含竞争媒体情报）
    agg_all = compute_aggregates(conn, customer_id, period, prev_period, contents, comms)
    agg_home = compute_aggregates(conn, customer_id, period, prev_period, contents, comms,
                                  platform=HOME_PLATFORM)

    report = build_report(profile, agg_home, agg_all, period)

    if isinstance(llm, MockLLM):
        report.raw = report.render()
        return report

    # 真实 LLM：把数据 + 规范喂进去，要求同格式输出；失败则回退到数据驱动报告
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
    return f"""你是互联网商业化投放的复盘专家。本工作台属于「{home_cn}」的商业化销售团队，
因此【本平台 = {home_cn}】是销售真正经营的客户账户（复盘核心），
客户在抖音/腾讯/快手等平台的花销属于「竞争媒体」（作为增预算话术的情报）。

客户：{profile.customer_id}（{profile.industry}，{profile.tier}），负责人 {profile.owner}

【本平台 {home_cn}】本周聚合：{agg_home['cur']}
本平台环比：{agg_home['wow']}
本平台分受众：{agg_home['by_audience']}
本平台分素材：{agg_home['by_content']}

【全平台（含竞争媒体）】分平台：{agg_all['by_platform']}
行业基准ROI：{agg_all['bench']}
客户负面反馈：{agg_home['complaints']}

请严格按以下格式输出（标题不可改）：
【一句话诊断】<一句话，要点出本平台表现 + 竞争媒体占比>
① 总览与结论
<2-3句，本平台数据 + 全平台占比>
② 广告布局 / 漏斗分配
<跨平台分配结论 + 本平台 vs 竞争媒体建议>
③ 各层级成效（按周对比趋势）
<本平台环比 + 漏斗判断>
④ 广告组合成效（受众 + 素材双维度）
<本平台最优/最差人群与素材>
⑤ 下一步行动
<3-4条，含一条"以高 ROI 推动客户在{home_cn}增预算"的话术>

参考范式：
{report.render()}
"""


def _parse_report(text: str, customer_id, period) -> Optional[Report]:
    import re
    def _sec(name):
        m = re.search(rf"{name}\s*(.*?)(?=①|②|③|④|⑤|$)", text, re.S)
        return m.group(1).strip() if m else ""
    diag_m = re.search(r"【一句话诊断】\s*(.*)", text)
    return Report(
        customer_id=customer_id, period=period,
        diagnosis=diag_m.group(1).strip() if diag_m else "",
        overview=_sec("①"), layout=_sec("②"),
        layer_perf=_sec("③"), combo_perf=_sec("④"),
        next_actions=_sec("⑤"), raw=text,
    )

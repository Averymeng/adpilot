"""
weekly_review.py : 核心 AI 节点 —— 每周投放复盘
================================================
输入：customer_id + period（周）
输出：一句话诊断 + RACAE 五段式完整报告
  RACAE: ① 总览与结论 ② 广告布局/漏斗分配 ③ 各层级成效(按周对比)
         ④ 广告组合成效(受众+素材双维度) ⑤ 下一步行动

流程（aipm-chain L0-L8）：
  L1 触发 -> L2 输入(归一化数据) -> L3 预处理(聚合/WoW/对标)
  -> L4 核心处理(AI 诊断+归因) -> L5 输出(报告) -> L6 反馈 -> L7 状态持久化 -> L8 下一步触发
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import db as dbm
from schema import AdPerformance, CustomerProfile, CommunicationRecord, ContentItem
from llm import LLMClient, MockLLM


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
                       contents: List[ContentItem], comms: List[CommunicationRecord]):
    cur = dbm.get_ads(conn, customer_id, period)
    prev = dbm.get_ads(conn, customer_id, prev_period)
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
def build_report(profile: CustomerProfile, agg: Dict, period: str) -> Report:
    cur, wow = agg["cur"], agg["wow"]
    bench_vals = [v for v in agg["bench"].values() if v]
    bench_avg = round(sum(bench_vals) / len(bench_vals), 2) if bench_vals else 0
    neg = agg["neg_count"]

    # —— 一句话诊断（结合客户生命周期阶段 + 真实环比数据，保证故事自洽）——
    if profile.lifecycle_stage == "at_risk":
        diag = (f"{profile.customer_id}（{profile.industry}）处于风险阶段，本周消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（行业基准 {bench_avg}），叠加 {neg} 条客户负面反馈，"
                f"建议立即收缩低效计划并重启高意向人群测试。")
    elif profile.lifecycle_stage == "growing" and wow["spend"] >= 3:
        diag = (f"{profile.customer_id}（{profile.industry}）本周消耗环比+{wow['spend']}%、"
                f"ROI {cur['roi']}（行业基准 {bench_avg}），增长健康，建议加预算放大优质计划。")
    else:
        diag = (f"{profile.customer_id}（{profile.industry}）本周消耗环比{wow['spend']}%、"
                f"ROI {cur['roi']}（行业基准 {bench_avg}），整体平稳，重点优化短板计划即可。")

    # ① 总览
    overview = (
        f"本周总消耗 ¥{int(round(cur['spend'])):,}（环比 {wow['spend']}%），GMV ¥{int(round(cur['gmv'])):,}（环比 {wow['gmv']}%），"
        f"综合 ROI {cur['roi']}（环比 {wow['roi']}）。曝光 {cur['impressions']:,}、点击 {cur['clicks']:,}、"
        f"转化 {cur['conversions']:,}，CTR {cur['ctr']}、CVR {cur['cvr']}。"
        + (f"客户侧收到 {agg['neg_count']} 条负面反馈，需重点关注。" if agg['neg_count'] else "客户沟通情绪整体平稳。")
    )

    # ② 广告布局 / 漏斗分配（战略）
    plat_lines = []
    for p, d in sorted(agg["by_platform"].items(), key=lambda x: -x[1]["spend"]):
        b = agg["bench"].get(p)
        flag = f"（行业基准 ROI {b}）" if b else ""
        plat_lines.append(f"  - {p}: 消耗 ¥{d['spend']:,.0f}，ROI {d['roi']}{flag}")
    layout = "预算分配与漏斗结构：\n" + "\n".join(plat_lines) + (
        "\n建议：向 ROI 高于基准的平台倾斜预算，对低于基准且消耗占比高的平台做结构收缩。"
    )

    # ③ 各层级成效（按周对比）
    layer_perf = (
        f"本周 vs 上周：消耗 {wow['spend']}%、点击 {wow['clicks']}%、GMV {wow['gmv']}%、ROI {wow['roi']}。"
        f"漏斗看，点击层（CTR {cur['ctr']}）与转化层（CVR {cur['cvr']}）是主要杠杆点；"
        f"若 CTR 正常但 CVR 偏低，问题在落地页/承接，而非素材。"
    )

    # ④ 广告组合成效（受众 + 素材）
    aud = sorted(agg["by_audience"].items(), key=lambda x: -x[1]["roi"])
    best_aud, worst_aud = aud[0], aud[-1]
    ct = sorted(agg["by_content"].items(), key=lambda x: -x[1]["roi"])
    best_ct = ct[0]
    combo = (
        f"受众维度：最优「{best_aud[0]}」ROI {best_aud[1]['roi']}，最差「{worst_aud[0]}」ROI {worst_aud[1]['roi']}，"
        f"建议把预算从最差人群迁到最优人群。\n"
        f"素材维度：表现最佳素材「{best_ct[1]['title']}」ROI {best_ct[1]['roi']}，可复制其选题/钩子到新计划。"
    )

    # ⑤ 下一步
    actions = []
    if wow["spend"] <= -5:
        actions.append("立即暂停 ROI 最低的计划，回收预算至高 ROI 平台/人群。")
    if agg["neg_count"]:
        actions.append(f"针对客户负面反馈（如：{agg['complaints'][0][:30]}…）准备沟通话术与补偿方案。")
    actions.append(f"将预算向最优人群「{best_aud[0]}」与优质素材「{best_ct[1]['title'][:15]}」倾斜。")
    actions.append("下周复盘前重测 1~2 组高意向人群定向，验证 ROI 是否回升。")
    next_actions = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(actions))

    return Report(
        customer_id=profile.customer_id, period=period, diagnosis=diag,
        overview=overview, layout=layout, layer_perf=layer_perf,
        combo_perf=combo, next_actions=next_actions,
    )


# ----------------------------- 主入口（L1/L5/L8） -----------------------------
def run_weekly_review(conn, customer_id: str, period: str, llm: LLMClient,
                      prev_period: Optional[str] = None) -> Report:
    profile = dbm.get_customer(conn, customer_id)
    if not profile:
        raise ValueError(f"customer {customer_id} not found")
    if prev_period is None:
        # 取上一周
        weeks = [r[0] for r in conn.execute("SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
        if period in weeks:
            idx = weeks.index(period)
            prev_period = weeks[idx - 1] if idx > 0 else period

    content_ids = {a.content_id for a in dbm.get_ads(conn, customer_id, period)}
    contents = dbm.get_contents(conn, content_ids)
    comms = dbm.get_comms(conn, customer_id, period)
    agg = compute_aggregates(conn, customer_id, period, prev_period, contents, comms)

    report = build_report(profile, agg, period)

    if isinstance(llm, MockLLM):
        report.raw = report.render()
        return report

    # 真实 LLM：把数据+规范喂进去，要求同格式输出；失败则回退到数据驱动报告
    prompt = _build_llm_prompt(profile, agg, report)
    out = llm.complete(prompt)
    parsed = _parse_report(out, customer_id, period)
    if parsed and parsed.diagnosis:
        parsed.raw = out
        return parsed
    report.raw = report.render()
    return report


def _build_llm_prompt(profile, agg, report: Report) -> str:
    return f"""你是互联网商业化投放的复盘专家。请基于以下真实聚合数据，输出一份每周投放复盘报告。
客户：{profile.customer_id}（{profile.industry}，{profile.tier}），负责人 {profile.owner}

本周聚合：{agg['cur']}
环比：{agg['wow']}
分平台：{agg['by_platform']}
行业基准ROI：{agg['bench']}
分受众：{agg['by_audience']}
分素材：{agg['by_content']}
客户负面反馈：{agg['complaints']}

请严格按以下格式输出（标题不可改）：
【一句话诊断】<一句话>
① 总览与结论
<2-3句>
② 广告布局 / 漏斗分配
<分平台结论+建议>
③ 各层级成效（按周对比趋势）
<环比+漏斗判断>
④ 广告组合成效（受众 + 素材双维度）
<最优/最差人群与素材>
⑤ 下一步行动
<3-4条可执行动作>

参考范式：
{report.render()}
"""


def _parse_report(text: str, customer_id, period) -> Optional[Report]:
    def _sec(name):
        import re
        m = re.search(rf"{name}\s*(.*?)(?=①|②|③|④|⑤|$)", text, re.S)
        return m.group(1).strip() if m else ""
    diag_m = __import__("re").search(r"【一句话诊断】\s*(.*)", text)
    return Report(
        customer_id=customer_id, period=period,
        diagnosis=diag_m.group(1).strip() if diag_m else "",
        overview=_sec("①"), layout=_sec("②"),
        layer_perf=_sec("③"), combo_perf=_sec("④"),
        next_actions=_sec("⑤"), raw=text,
    )

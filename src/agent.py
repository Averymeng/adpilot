"""
agent.py : AdPilot 的「智能体编排层」
=====================================
为什么需要这一层（对照 xhslink 那条定义）：
  一个真正的 agent = 非纯前端 vibe coding，必须同时具备：
    ✅ Backend（Python 计算）   ✅ DB（SQLite 真实存取）
    ✅ API（OpenAI function-calling / Mock 调度）
    ✅ Workflow（多步：意图识别 → 选工具 → 执行 → 观察 → 回答）
    ✅ System Prompt（业务语义本体，让 agent「懂业务」）
  之前 weekly_review 只是「一次生成即结束」的脚本；本层把它升级为
  可对话、可多步调用工具、可观测（带运行轨迹日志）的 agent。

设计：
  - TOOLS：一组「后端工具」，每个都真正打到 DB / 计算层（不是假函数）。
  - SYSTEM_PROMPT：编码「小红书线索经营」业务语义本体（销售易式业务语义层）。
  - run_agent()：接收自然语言意图 → 决定调用哪些工具 → 执行 → 综合回答。
    · 有 OPENAI_API_KEY 走真实 function-calling 多轮；
    · 否则走 Mock dispatcher（关键词意图路由，仍执行真实工具并出有据回答）。
  - 每次运行都落库 agent_logs（意图 / 工具步骤 / 回答），满足可观测性。
"""
import json
import sqlite3
import datetime as _dt
from typing import Callable, Dict, List, Optional

import db as dbm
from llm import LLMClient, MockLLM, get_llm
from weekly_review import (
    compute_aggregates, run_weekly_review, HOME_PLATFORM, PLATFORM_CN, STAGE_CN,
)
from schema import AdPerformance, ContentItem, CommunicationRecord, Demographics


# --------------------------- 业务语义本体（System Prompt） ---------------------------
SYSTEM_PROMPT = """你是「AdPilot」——面向互联网商业化销售 / 优化师的 AI 工作助手。
你的业务本体是「小红书线索经营」：我们（本平台=小红书）把广告位卖给客户，
客户用这些位子收集「线索（留资）」，而不是卖货。因此你的核心口径必须严格区分：

【核心 KPI（按重要性）】
  1. 留资成本 CPL（cash_spend / pm_lead）—— 越低越好，行业基准见 benchmarks 表。
  2. 加微成本 / 加微率（pm_wechat）—— 线索沉淀到私域的关键。
  3. 开口率（pm_open / pm_consult）—— 话术健康度（私信咨询是否愿意开口）。
  4. 预算花完率（cash_spend / 预算含返点）—— 预算没花完 = 量级不足 / 定向过窄。
【私信转化漏斗】 咨询 → 开口 → 留资 → 加微信（4 段，每段有转化数与单步成本）。
【竞争媒体】 抖音/腾讯/快手 = 客户在「其他平台」的投放，仅作情报对比，拿不到其私信漏斗。
【客户分层】 KA=周均小红书消耗≥¥1.5万；SMB 为其余。生命周期：新客期/稳定期/高速增长/流失风险。

你的行为准则：
  - 永远基于真实 DB 数据回答，不臆造数字；引用结论时说明数据来源（哪张表/哪个指标）。
  - 用工具拿数据，再综合；不要凭空下结论。
  - 回答用中文，给销售可执行的下一步（话术/出价/预算/人群/素材）。
  - 若用户问题超出数据范围，明确说明「数据未覆盖」，并建议补哪类数据。
"""


# ------------------------------- 工具定义（真实后端） -------------------------------
def _tool_customer_overview(conn, customer_id: str, period: str) -> Dict:
    cust = dbm.get_customer(conn, customer_id)
    if not cust:
        return {"error": f"未找到客户 {customer_id}"}
    prev = dbm.latest_period(conn)
    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads WHERE customer_id=? ORDER BY period",
        (customer_id,)).fetchall()]
    prev_p = weeks[-2] if len(weeks) >= 2 else period
    ads = dbm.get_ads(conn, customer_id, period)
    home = [a for a in ads if a.platform == HOME_PLATFORM]
    agg = compute_aggregates(conn, customer_id, period, prev_p,
                             dbm.get_contents(conn, {a.content_id for a in ads if a.content_id}),
                             dbm.get_comms(conn, customer_id, period), platform=HOME_PLATFORM)
    cur = agg["cur"]
    return {
        "customer_id": customer_id, "name": cust.name, "industry": cust.industry,
        "tier": cust.tier, "stage": STAGE_CN.get(cust.lifecycle_stage, cust.lifecycle_stage),
        "owner": cust.owner,
        "本平台_现金消耗": cur["cash_spend"], "留资数": cur["pm_lead"],
        "CPL": cur["cpl"], "开口率": cur["open_rate"], "留资率": cur["lead_rate"],
        "加微率": cur["wechat_rate"], "预算花完率": cur["budget_util"],
        "本平台广告数": len(home),
    }


def _tool_weekly_review(conn, customer_id: str, period: str) -> Dict:
    rep = run_weekly_review(conn, customer_id, period, get_llm())
    return {
        "diagnosis": rep.diagnosis,
        "report": rep.render(),
        "cpl": rep.cpl, "cpl_benchmark": rep.cpl_benchmark,
    }


def _tool_alerts(conn, customer_id: str, severity: Optional[str] = None) -> Dict:
    alerts = dbm.get_alerts(conn, customer_id=customer_id, severity=severity)
    return {
        "count": len(alerts),
        "items": [
            {"type": a.alert_type, "severity": a.severity, "title": a.title,
             "action": a.suggested_action, "value": a.metric_value, "threshold": a.threshold}
            for a in alerts
        ],
    }


def _tool_badcases(conn, customer_id: str) -> Dict:
    bc = dbm.get_badcases(conn, customer_id=customer_id)
    return {
        "count": len(bc),
        "items": [
            {"type": b.case_type, "object": b.object_name, "root_cause": b.root_cause,
             "fix": b.fix, "impact": b.impact_value}
            for b in bc
        ],
    }


def _tool_benchmark(conn, customer_id: str, period: str) -> Dict:
    cust = dbm.get_customer(conn, customer_id)
    if not cust:
        return {"error": "no customer"}
    bench = dbm.get_benchmarks(conn, HOME_PLATFORM, cust.industry, period)
    return {
        "industry": cust.industry, "platform": PLATFORM_CN[HOME_PLATFORM],
        "benchmark_cpl": bench.benchmark_cpl if bench else None,
        "benchmark_ctr": bench.avg_ctr if bench else None,
        "super_cost_line": round(bench.benchmark_cpl * 1.2, 1) if bench else None,
    }


def _tool_competitor(conn, customer_id: str, period: str) -> Dict:
    ads = dbm.get_ads(conn, customer_id, period)
    by_plat = {}
    for a in ads:
        d = by_plat.setdefault(a.platform, {"cash": 0.0, "lead": 0})
        d["cash"] += a.cash_spend; d["lead"] += a.pm_lead
    total = sum(d["cash"] for d in by_plat.values()) or 1
    return {
        "shares": {PLATFORM_CN.get(p, p): round(d["cash"] / total * 100, 1)
                   for p, d in by_plat.items()},
        "home_cpl": _tool_benchmark(conn, customer_id, period).get("benchmark_cpl"),
    }


# 工具注册表：name -> (callable, 描述, JSON 参数 schema)
TOOLS: Dict[str, Dict] = {
    "customer_overview": {
        "fn": _tool_customer_overview,
        "desc": "查询某客户某周的概览指标（消耗/留资/CPL/开口率/预算花完率/分层/阶段）。",
        "params": {"customer_id": "str", "period": "str"},
    },
    "weekly_review": {
        "fn": _tool_weekly_review,
        "desc": "生成某客户某周的完整 AI 复盘报告（一句话诊断 + 8 段）。",
        "params": {"customer_id": "str", "period": "str"},
    },
    "list_alerts": {
        "fn": _tool_alerts,
        "desc": "列出某客户的异常预警（可指定 severity: high/mid/low）。",
        "params": {"customer_id": "str", "severity": "str|null"},
    },
    "list_badcases": {
        "fn": _tool_badcases,
        "desc": "列出某客户的高成本计划 / 低质素材归因库。",
        "params": {"customer_id": "str"},
    },
    "industry_benchmark": {
        "fn": _tool_benchmark,
        "desc": "查询某客户所在行业的 CPL / CTR 基准与超成本线。",
        "params": {"customer_id": "str", "period": "str"},
    },
    "competitor_media": {
        "fn": _tool_competitor,
        "desc": "查询客户在各平台的预算占比（本平台 vs 竞争媒体）。",
        "params": {"customer_id": "str", "period": "str"},
    },
}


# ------------------------------- 意图路由（Mock dispatcher） -------------------------------
def _classify_intent(query: str) -> List[str]:
    q = query.lower()
    out = []
    if any(k in q for k in ["复盘", "周报", "review", "报告", "分析一下", "分析这"]):
        out.append("weekly_review")
    if any(k in q for k in ["预警", "异常", "报警", "风险", "掉量", "超成本", "alert"]):
        out.append("list_alerts")
    if any(k in q for k in ["badcase", "高成本", "低效", "低质", "归因", "问题计划", "浪费"]):
        out.append("list_badcases")
    if any(k in q for k in ["对标", "行业", "基准", "benchmark", "算好算差", "健康线"]):
        out.append("industry_benchmark")
    if any(k in q for k in ["竞媒", "竞争", "其他平台", "抖音", "腾讯", "快手", "占比"]):
        out.append("competitor_media")
    if any(k in q for k in ["概览", "总览", "情况", "现状", "怎么样", "好不好", "概況"]):
        out.append("customer_overview")
    if not out:
        out = ["customer_overview"]
    return out


def _resolve_customer(conn, query: str, default_cid: str) -> str:
    # 优先从输入里匹配客户 id 或名称
    for cid, name in conn.execute("SELECT customer_id, name FROM customers").fetchall():
        if cid.lower() in query.lower() or name in query:
            return cid
    return default_cid


def _summarize(tool: str, res: Dict) -> str:
    if "error" in res:
        return f"⚠️ {res['error']}"
    if tool == "customer_overview":
        return (f"{res['name']}（{res['industry']} / {res['tier']} / {res['stage']}，负责人 {res['owner']}）："
                f"本平台现金消耗 ¥{res['本平台_现金消耗']:.0f}，留资 {res['留资数']} 条，"
                f"CPL ¥{res['CPL']:.0f}，开口率 {res['开口率']}%，留资率 {res['留资率']}%，"
                f"加微率 {res['加微率']}%，预算花完率 {res['预算花完率']}%。")
    if tool == "weekly_review":
        return f"【一句话诊断】{res['diagnosis']}\n\n{res['report']}"
    if tool == "list_alerts":
        if not res["items"]:
            return "✅ 本周无异常预警。"
        lines = [f"• [{a['severity']}] {a['title']} → 建议：{a['action']}" for a in res["items"]]
        return f"共 {res['count']} 条预警：\n" + "\n".join(lines)
    if tool == "list_badcases":
        if not res["items"]:
            return "✅ 暂无 badcase。"
        lines = [f"• [{b['type']}] {b['object']}：根因={b['root_cause']}；动作={b['fix']}"
                 + (f"（浪费约 ¥{b['impact']:.0f}）" if b['impact'] else "") for b in res["items"]]
        return f"共 {res['count']} 条 badcase：\n" + "\n".join(lines)
    if tool == "industry_benchmark":
        if res.get("benchmark_cpl") is None:
            return "⚠️ 该行业/平台暂无基准数据。"
        return (f"{res['industry']}行业 · {res['platform']} 基准：CPL ¥{res['benchmark_cpl']:.0f}，"
                f"CTR {res['benchmark_ctr']*100:.1f}%；超成本线 ¥{res['super_cost_line']:.0f}。")
    if tool == "competitor_media":
        shares = "，".join(f"{k} {v}%" for k, v in res["shares"].items())
        return f"客户预算平台分布：{shares}。"
    return json.dumps(res, ensure_ascii=False)


# --------------------------------- 主入口 ---------------------------------
def run_agent(conn, user_query: str, default_cid: str = "C001") -> Dict:
    """执行一次 agent 调用，返回 {intent, steps, answer, tool_count, engine}。"""
    engine = "OpenAI" if isinstance(get_llm(), MockLLM) is False else "Mock"
    cid = _resolve_customer(conn, user_query, default_cid)
    period = dbm.latest_period(conn)
    steps: List[Dict] = []

    # —— 真实 OpenAI function-calling 路径 ——
    llm = get_llm()
    if not isinstance(llm, MockLLM):
        try:
            return _run_openai(conn, llm, user_query, cid, period, engine)
        except Exception:
            pass  # 失败时回退 Mock

    # —— Mock dispatcher 路径（仍执行真实工具） ——
    intents = _classify_intent(user_query)
    parts = []
    for tool in intents:
        fn = TOOLS[tool]["fn"]
        # 只传该工具声明的参数（避免 period 误传给不接受它的工具）
        accepted = TOOLS[tool]["params"]
        args = {"customer_id": cid, "period": period}
        if tool == "list_alerts" and ("高" in user_query or "high" in user_query.lower()):
            args["severity"] = "high"
        call_args = {k: v for k, v in args.items() if k in accepted}
        try:
            res = fn(conn, **call_args)
            obs = _summarize(tool, res)
        except Exception as e:
            obs = f"⚠️ 工具 {tool} 执行出错：{e}"
            res = {}
        steps.append({"tool": tool, "args": call_args,
                      "observation": obs[:400]})
        parts.append(obs)

    answer = "\n\n".join(parts)
    if len(intents) > 1:
        answer = f"已为你查询 {cid}（{period}）的 {len(intents)} 个维度：\n\n" + answer
    tool_count = len(intents)

    # 落库（可观测）
    _persist(conn, user_query, "+".join(intents), steps, answer, tool_count, engine)
    return {"intent": "+".join(intents), "steps": steps, "answer": answer,
            "tool_count": tool_count, "engine": engine}


def _run_openai(conn, llm: LLMClient, user_query: str, cid: str, period: str, engine: str) -> Dict:
    from openai import OpenAI
    import os
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    tools_schema = [{
        "type": "function",
        "function": {
            "name": name,
            "description": meta["desc"],
            "parameters": {
                "type": "object",
                "properties": {k: {"type": v.split("|")[0]} for k, v in meta["params"].items()},
                "required": list(meta["params"].keys()),
            },
        },
    } for name, meta in TOOLS.items()]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"客户上下文：默认 customer_id={cid}，周期={period}。用户问题：{user_query}"},
    ]
    steps: List[Dict] = []
    parts = []
    for _ in range(4):  # 最多 4 步工具调用
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, tools=tools_schema, tool_choice="auto")
        msg = resp.choices[0].message
        if not msg.tool_calls:
            parts.append(msg.content or "")
            break
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            args.setdefault("customer_id", cid)
            args.setdefault("period", period)
            args.setdefault("severity", None)
            res = TOOLS[name]["fn"](conn, **{k: v for k, v in args.items() if k in ("customer_id", "period", "severity")})
            obs = _summarize(name, res)
            steps.append({"tool": name, "args": args, "observation": obs[:400]})
            parts.append(obs)
            messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
            messages.append({"role": "tool", "name": name, "content": json.dumps(res, ensure_ascii=False)})
    answer = "\n\n".join(p for p in parts if p)
    tool_count = len(steps)
    _persist(conn, user_query, "+".join(s["tool"] for s in steps), steps, answer, tool_count, engine)
    return {"intent": "+".join(s["tool"] for s in steps), "steps": steps,
            "answer": answer, "tool_count": tool_count, "engine": engine}


def _persist(conn, query, intent, steps, answer, tool_count, engine):
    import uuid
    run_id = "RUN_" + uuid.uuid4().hex[:10]
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        dbm.log_agent_run(conn, run_id, ts, query, intent, steps, answer, tool_count, engine)
    except Exception:
        pass

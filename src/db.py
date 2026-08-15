"""
db.py : 本地 SQLite 存储 + 查询接口
====================================
把 adapter 归一化后的数据落库，并向上层（AI 节点 / eval）提供查询。
这是"真实架构层"的一部分：数据虽是模拟生成，但存取路径与真实生产一致。
"""
import sqlite3
import ast
from typing import Dict, List, Optional
from schema import (
    CustomerProfile, AdPerformance, ContentItem,
    CommunicationRecord, IndustryBenchmark, Demographics,
    Alert, Task, BadCase,
)
from adapters import (
    CustomerAdapter, XhsAdAdapter, DouyinAdAdapter,
    TencentAdAdapter, KuaishouAdAdapter, XhsNoteAdapter,
    WeComMessageAdapter, IndustryDataAdapter,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY, name TEXT, company TEXT, industry TEXT,
    tier TEXT, owner TEXT, wecom_id TEXT, account_status TEXT,
    joined_at TEXT, lifecycle_stage TEXT
);
CREATE TABLE IF NOT EXISTS ads (
    record_id TEXT PRIMARY KEY, customer_id TEXT, platform TEXT, campaign_id TEXT,
    ad_group_id TEXT, period TEXT, impressions INTEGER, clicks INTEGER,
    cash_spend REAL, budget_spend REAL, gmv REAL, ctr REAL, cpc REAL, roi REAL,
    pm_consult INTEGER, pm_open INTEGER, pm_lead INTEGER, pm_wechat INTEGER,
    ad_type TEXT, bid_type TEXT, audience_segment TEXT, content_id TEXT
);
CREATE TABLE IF NOT EXISTS contents (
    content_id TEXT PRIMARY KEY, platform TEXT, format TEXT, title TEXT,
    body_text TEXT, cover_url TEXT, cta TEXT, landing_link TEXT,
    publish_time TEXT, key_metrics TEXT, is_original INTEGER, share_cnt INTEGER
);
CREATE TABLE IF NOT EXISTS comms (
    msg_id TEXT PRIMARY KEY, customer_id TEXT, sender_role TEXT, channel TEXT,
    timestamp TEXT, text TEXT, media_type TEXT, intent_tag TEXT, sentiment TEXT
);
CREATE TABLE IF NOT EXISTS benchmarks (
    benchmark_id TEXT PRIMARY KEY, platform TEXT, industry TEXT, period TEXT,
    avg_ctr REAL, avg_cvr REAL, avg_cpm REAL, benchmark_roi REAL,
    benchmark_cpl REAL, trend TEXT, ad_type TEXT
);
CREATE TABLE IF NOT EXISTS demographics (
    customer_id TEXT, period TEXT,
    age_25_30 REAL, age_31_40 REAL, age_41_50 REAL, age_50_plus REAL,
    top_region TEXT, top_interest TEXT,
    PRIMARY KEY (customer_id, period)
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY, customer_id TEXT, period TEXT, alert_type TEXT,
    severity TEXT, metric_name TEXT, metric_value REAL, threshold REAL,
    title TEXT, message TEXT, suggested_action TEXT, is_resolved INTEGER
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY, customer_id TEXT, owner TEXT, source TEXT,
    title TEXT, detail TEXT, priority TEXT, due_week TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS badcases (
    case_id TEXT PRIMARY KEY, customer_id TEXT, period TEXT, case_type TEXT,
    object_name TEXT, symptom TEXT, root_cause TEXT, fix TEXT,
    impact_value REAL, is_archived INTEGER
);
CREATE TABLE IF NOT EXISTS agent_logs (
    run_id TEXT PRIMARY KEY, ts TEXT, user_query TEXT, intent TEXT,
    steps TEXT, answer TEXT, tool_count INTEGER, engine TEXT
);
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def load_from_store(conn: sqlite3.Connection, store: Dict[str, list]) -> None:
    """用 8 个 adapter 把原始 store 归一化后写入 SQLite。"""
    cur = conn.cursor()
    # 清空（保证可重复加载）
    for t in ("customers", "ads", "contents", "comms", "benchmarks",
              "demographics", "alerts", "tasks", "badcases"):
        cur.execute(f"DELETE FROM {t}")

    for cust in CustomerAdapter.fetch(store):
        cur.execute("INSERT OR REPLACE INTO customers VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [cust.customer_id, cust.name, cust.company, cust.industry,
                     cust.tier, cust.owner, cust.wecom_id, cust.account_status,
                     cust.joined_at, cust.lifecycle_stage])

    for Adapter in (XhsAdAdapter, DouyinAdAdapter, TencentAdAdapter, KuaishouAdAdapter):
        for a in Adapter.fetch(store):
            cur.execute("INSERT OR REPLACE INTO ads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [a.record_id, a.customer_id, a.platform, a.campaign_id,
                         a.ad_group_id, a.period, a.impressions, a.clicks,
                         a.cash_spend, a.budget_spend, a.gmv, a.ctr, a.cpc, a.roi,
                         a.pm_consult, a.pm_open, a.pm_lead, a.pm_wechat,
                         a.ad_type, a.bid_type, a.audience_segment, a.content_id])

    for c in XhsNoteAdapter.fetch(store):
        cur.execute("INSERT OR REPLACE INTO contents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [c.content_id, c.platform, c.format, c.title, c.body_text,
                     c.cover_url, c.cta, c.landing_link, c.publish_time,
                     str(c.key_metrics), int(c.is_original), c.share_cnt])

    for m in WeComMessageAdapter.fetch(store):
        cur.execute("INSERT OR REPLACE INTO comms VALUES (?,?,?,?,?,?,?,?,?)",
                    [m.msg_id, m.customer_id, m.sender_role, m.channel,
                     m.timestamp, m.text, m.media_type, m.intent_tag, m.sentiment])

    for b in IndustryDataAdapter.fetch(store):
        cur.execute("INSERT OR REPLACE INTO benchmarks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [b.benchmark_id, b.platform, b.industry, b.period,
                     b.avg_ctr, b.avg_cvr, b.avg_cpm, b.benchmark_roi,
                     b.benchmark_cpl, b.trend, b.ad_type])

    for d in store.get("demographics", []):
        cur.execute("INSERT OR REPLACE INTO demographics VALUES (?,?,?,?,?,?,?,?)",
                    [d["customer_id"], d["period"], d.get("age_25_30", 0),
                     d.get("age_31_40", 0), d.get("age_41_50", 0),
                     d.get("age_50_plus", 0), d.get("top_region", ""),
                     d.get("top_interest", "")])
    conn.commit()


# ------------------------- 查询接口（供 AI 节点使用） -------------------------
def get_customer(conn, customer_id: str) -> Optional[CustomerProfile]:
    row = conn.execute("SELECT * FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM customers").description]
    return CustomerProfile(**dict(zip(cols, row)))


def get_ads(conn, customer_id: str, period: Optional[str] = None) -> List[AdPerformance]:
    sql = "SELECT * FROM ads WHERE customer_id=?"
    args = [customer_id]
    if period:
        sql += " AND period=?"
        args.append(period)
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM ads").description]
    return [AdPerformance(**dict(zip(cols, r))) for r in rows]


def get_contents(conn, content_ids: set) -> List[ContentItem]:
    if not content_ids:
        return []
    q = f"SELECT * FROM contents WHERE content_id IN ({','.join('?'*len(content_ids))})"
    rows = conn.execute(q, list(content_ids)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM contents").description]
    items = []
    for r in rows:
        d = dict(zip(cols, r))
        # key_metrics 在 DB 里存的是字符串，还原回 dict
        if isinstance(d.get("key_metrics"), str):
            import ast
            try:
                d["key_metrics"] = ast.literal_eval(d["key_metrics"])
            except (ValueError, SyntaxError):
                d["key_metrics"] = {}
        items.append(ContentItem(**d))
    return items


def get_comms(conn, customer_id: str, period: Optional[str] = None) -> List[CommunicationRecord]:
    sql = "SELECT * FROM comms WHERE customer_id=?"
    args = [customer_id]
    if period:
        sql += " AND timestamp LIKE ?"
        args.append(f"%{period[:4]}%")
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM comms").description]
    return [CommunicationRecord(**dict(zip(cols, r))) for r in rows]


def get_benchmarks(conn, platform: str, industry: str, period: str) -> Optional[IndustryBenchmark]:
    row = conn.execute(
        "SELECT * FROM benchmarks WHERE platform=? AND industry=? AND period=?",
        (platform, industry, period)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM benchmarks").description]
    return IndustryBenchmark(**dict(zip(cols, row)))


def all_customer_ids(conn) -> List[str]:
    return [r[0] for r in conn.execute("SELECT customer_id FROM customers").fetchall()]


def latest_period(conn) -> str:
    return conn.execute("SELECT MAX(period) FROM ads").fetchone()[0]


# ------------------------- 派生表：预警 / 待办 / Badcase -------------------------
# 这些表不是"平台原生数据"，而是 AI 工作台对归一化数据的二次分析产出，
# 对应真实聚光「盯盘助手」的规则引擎（掉量/超成本/成本上升/潜力 等）。
def _xhs_agg(conn, cid: str, period: str) -> dict:
    rows = conn.execute(
        "SELECT cash_spend, budget_spend, pm_consult, pm_open, pm_lead, pm_wechat "
        "FROM ads WHERE customer_id=? AND period=? AND platform='xhs'",
        (cid, period)).fetchall()
    cash = sum(r[0] for r in rows)
    budget = sum(r[1] for r in rows)
    return {
        "cash": round(cash, 1),
        "budget": round(budget, 1),
        "pm_consult": sum(r[2] for r in rows),
        "pm_open": sum(r[3] for r in rows),
        "pm_lead": sum(r[4] for r in rows),
        "pm_wechat": sum(r[5] for r in rows),
        "cpl": round(cash / sum(r[4] for r in rows), 1) if sum(r[4] for r in rows) else 0,
        "util": round(cash / (budget / 1.12) * 100, 1) if budget else 0,
    }


def _bench_cpl(conn, cid: str, period: str) -> float:
    industry = conn.execute(
        "SELECT industry FROM customers WHERE customer_id=?", (cid,)).fetchone()[0]
    rows = conn.execute(
        "SELECT benchmark_cpl FROM benchmarks WHERE platform='xhs' AND industry=? AND period=?",
        (industry, period)).fetchall()
    return round(sum(r[0] for r in rows) / len(rows), 1) if rows else 0


def load_derived(conn) -> None:
    """基于归一化数据生成 预警 / 待办 / Badcase 三张派生表。"""
    cur = conn.cursor()
    for t in ("alerts", "tasks", "badcases"):
        cur.execute(f"DELETE FROM {t}")

    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT period FROM ads ORDER BY period").fetchall()]
    cids = [r[0] for r in conn.execute(
        "SELECT customer_id FROM customers ORDER BY customer_id").fetchall()]

    for cid in cids:
        profile = get_customer(conn, cid)
        idx = {w: i for i, w in enumerate(weeks)}
        # 逐周生成预警（除首周）
        for wi, period in enumerate(weeks):
            if wi == 0:
                continue
            prev = weeks[wi - 1]
            a = _xhs_agg(conn, cid, period)
            a0 = _xhs_agg(conn, cid, prev)
            bench = _bench_cpl(conn, cid, period)
            # 负反馈（本周企微负面）
            neg = conn.execute(
                "SELECT COUNT(*) FROM comms WHERE customer_id=? AND sentiment='negative' "
                "AND timestamp LIKE ?", (cid, f"%{period[:4]}%")).fetchone()[0]
            # 素材疲劳（本周笔记平均互动率）
            cids_note = [r[0] for r in conn.execute(
                "SELECT DISTINCT content_id FROM ads WHERE customer_id=? AND period=? AND platform='xhs'",
                (cid, period)).fetchall()]
            eng = [ast.literal_eval(r[0]).get("engage_rate", 0) for r in conn.execute(
                f"SELECT key_metrics FROM contents WHERE content_id IN "
                f"({','.join('?'*len(cids_note))})", cids_note).fetchall()] if cids_note else []
            avg_engage = round(sum(eng) / len(eng) * 100, 2) if eng else 0

            _emit_alerts(cur, cid, period, a, a0, bench, neg, avg_engage, profile)

        # 待办：来自最新周高优预警 + 客户阶段
        latest = weeks[-1]
        a = _xhs_agg(conn, cid, latest)
        bench = _bench_cpl(conn, cid, latest)
        home_share = _home_share(conn, cid, latest)
        _emit_tasks(cur, cid, latest, a, bench, home_share, profile)

        # Badcase：最新周的高成本计划 / 低质素材
        _emit_badcases(cur, conn, cid, latest)

    conn.commit()


def _emit_alerts(cur, cid, period, a, a0, bench, neg, avg_engage, profile):
    def add(at, sev, mname, mval, thr, title, msg, act):
        cur.execute(
            "INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (f"AL_{cid}_{period}_{at}", cid, period, at, sev, mname,
             round(mval, 2), round(thr, 2), title, msg, act))

    # 掉量：本周现金消耗 环比 ↓>30%（聚光盯盘：消费环比 ↓50%+ 为掉量）
    if a0["cash"] > 0 and a["cash"] < a0["cash"] * 0.7:
        pct = round((a["cash"] - a0["cash"]) / a0["cash"] * 100, 1)
        add("掉量", "high", "现金消耗", a["cash"], a0["cash"] * 0.7,
            "消耗掉量", f"本周本平台现金消耗 ¥{a['cash']:,.0f}，环比 {pct}%（预警线 -30%）。",
            "检查定向是否过窄 / 出价是否下调 / 账户是否频繁操作；先放宽定向或小幅加价 10% 内观察 24h。")
    # 超成本（效果未达成）：CPL > 行业基准 × 1.2
    if bench and a["cpl"] > bench * 1.2:
        add("超成本", "high", "留资成本CPL", a["cpl"], bench * 1.2,
            "留资成本超基准", f"本周 CPL ¥{a['cpl']:.0f} > 行业基准 ¥{bench:.0f}×1.2。",
            "优先改话术与承接（开口率/留资率/加微率），而非加预算；用 oCPX 让系统优化留资目标。")
    # 成本上升：CPL 环比 ↑>30%
    elif bench and a0["cpl"] and a["cpl"] > a0["cpl"] * 1.3:
        pct = round((a["cpl"] - a0["cpl"]) / a0["cpl"] * 100, 1)
        add("成本上升", "medium", "留资成本CPL", a["cpl"], a0["cpl"] * 1.3,
            "成本上升", f"本周 CPL ¥{a['cpl']:.0f}，环比 +{pct}%（预警线 +30%）。",
            "排查是否新建计划处于学习期（前 4 天正常波动，观察 5 日）；避免频繁调价（单次 ≤10%）。")
    # 预算花不完：利用率 < 70%（计划跑不动）
    if a["util"] < 70:
        add("预算花不完", "medium", "预算花完率", a["util"], 70,
            "预算花不完", f"本周预算花完率仅 {a['util']:.0f}%（低于 70%）。",
            "提日预算 / 放宽定向让系统多出量，先积累转化样本（计划日预算建议 >5 个转化成本）。")
    # 负反馈
    if neg > 0:
        add("负反馈", "medium", "负面沟通", neg, 0,
            "收到客户负面反馈", f"本周企微收到 {neg} 条负面/投诉。",
            "当日回访客户，先共情再给方案；把投诉点拆解进本周优化动作。")
    # 高潜增投（growing + CPL 低于基准 90% + 预算花完）
    if profile.lifecycle_stage == "growing" and bench and a["cpl"] < bench * 0.9 and a["util"] >= 85:
        add("高潜增投", "info", "留资成本CPL", a["cpl"], bench * 0.9,
            "高潜可增投", f"本周 CPL ¥{a['cpl']:.0f} < 基准 ¥{bench:.0f}，预算已花完。",
            "以「本平台 CPL 优于竞争媒体」为支点，向客户提案增预算 / 挪量。")
    # 素材疲劳：平均互动率 < 3%
    if avg_engage < 3.0:
        add("素材疲劳", "low", "平均互动率", avg_engage, 3.0,
            "素材疲劳", f"本周笔记平均互动率仅 {avg_engage}%（健康线 ~5%）。",
            "单一素材连续投放易疲劳，上新笔记分流；复制王牌钩子到新计划。")


def _home_share(conn, cid, period) -> float:
    total = conn.execute(
        "SELECT SUM(cash_spend) FROM ads WHERE customer_id=? AND period=?",
        (cid, period)).fetchone()[0] or 0
    home = conn.execute(
        "SELECT SUM(cash_spend) FROM ads WHERE customer_id=? AND period=? AND platform='xhs'",
        (cid, period)).fetchone()[0] or 0
    return round(home / total * 100, 1) if total else 0


def _emit_tasks(cur, cid, period, a, bench, home_share, profile):
    due = weeks_due(period)
    _n = [0]

    def add(prio, source, title, detail):
        _n[0] += 1
        cur.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)",
            (f"TK_{cid}_{_n[0]}", cid, profile.owner, source, title, detail,
             prio, due, "pending"))

    # 高优：超成本 / 掉量
    if bench and a["cpl"] > bench * 1.2:
        add("P0", "异常预警", f"压降 {profile.name} 留资成本",
            f"CPL ¥{a['cpl']:.0f} 超基准 ¥{bench:.0f}×1.2，本周用话术+出价(oCPX)压回基线。")
    if a["cpl"] and bench and a["cpl"] > bench:
        add("P1", "每周复盘", f"优化 {profile.name} 私信承接",
            "开口率/留资率/加微率任一项低于健康线(45%)，上留资卡+商家名片+三段式话术。")
    if a["util"] < 70:
        add("P1", "每周复盘", f"放开 {profile.name} 预算/定向",
            f"预算花完率 {a['util']:.0f}% 偏低，提日预算或放宽定向多出量。")
    if profile.lifecycle_stage == "at_risk":
        add("P0", "每周复盘", f"维稳回访 {profile.name}",
            "客户处流失风险，本周必须人工回访确认续费意向与问题清单。")
    if profile.lifecycle_stage == "growing" and home_share < 35:
        add("P1", "每周复盘", f"向 {profile.name} 提案增预算挪量",
            f"本平台仅占其全平台 {home_share}%，以 CPL 优势为支点提案增投。")


def weeks_due(period: str, n: int = 1) -> str:
    # period 形如 2026-W32
    try:
        y, w = period.split("-W")
        wn = int(w) + n
        if wn > 52:
            wn -= 52; y = str(int(y) + 1)
        return f"{y}-W{w:02d}"
    except Exception:
        return period


def _emit_badcases(cur, conn, cid, period):
    bench = _bench_cpl(conn, cid, period)
    # 高成本计划：本平台 xhs 广告中 CPL 最高且 > 基准×1.15
    rows = conn.execute(
        "SELECT record_id, campaign_id, cash_spend, pm_lead, ctr, audience_segment, bid_type "
        "FROM ads WHERE customer_id=? AND period=? AND platform='xhs' AND pm_lead>0",
        (cid, period)).fetchall()
    if rows:
        worst = max(rows, key=lambda r: (r[2] / r[3]) if r[3] else 0)
        wcpl = worst[2] / worst[3] if worst[3] else 0
        if bench and wcpl > bench * 1.15:
            extra = round((wcpl - bench) * worst[3], 1)
            if worst[4] < 0.02:
                rc, fix = "素材质量差（CTR 低于 2%）", "换高点击封面/标题，A/B 测试新素材。"
            elif worst[5] in ("人群包", "关键词定向"):
                rc, fix = "定向过窄/跑偏", "放宽定向或扩量相似人群，覆盖量级建议 >200w。"
            else:
                rc, fix = "出价偏高", "下调出价（单次 ≤10%）或切 oCPX 让系统优化留资目标。"
            cur.execute(
                "INSERT INTO badcases VALUES (?,?,?,?,?,?,?,?,?,0)",
                (f"BC_{cid}_plan", cid, period, "高成本计划",
                 f"{worst[0]}（{worst[1]}）",
                 f"留资成本 ¥{wcpl:.0f}（基准 ¥{bench:.0f}），预算浪费明显。",
                 rc, fix, extra))
    # 低质素材：绑定笔记中「平均 CTR」最低，且 < 2%（聚光：CTR<2% 果断换素材）
    note_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT content_id FROM ads WHERE customer_id=? AND period=? AND platform='xhs'",
        (cid, period)).fetchall()]
    if not note_ids:
        return
    scored = []
    for nid in note_ids:
        bound = conn.execute(
            "SELECT ctr FROM ads WHERE customer_id=? AND period=? AND platform='xhs' "
            "AND content_id=? AND impressions>0",
            (cid, period, nid)).fetchall()
        if not bound:
            continue
        avg_ctr = sum(r[0] for r in bound) / len(bound)
        title = conn.execute("SELECT title FROM contents WHERE content_id=?",
                             (nid,)).fetchone()[0]
        scored.append((nid, title, avg_ctr))
    if scored:
        worst_note = min(scored, key=lambda x: x[2])
        if worst_note[2] < 0.02:
            cur.execute(
                "INSERT INTO badcases VALUES (?,?,?,?,?,?,?,?,?,0)",
                (f"BC_{cid}_note", cid, period, "低质素材",
                 f"{worst_note[0]} · {worst_note[1][:24]}",
                 f"绑定计划平均 CTR 仅 {worst_note[2]*100:.1f}%，低于健康线（信息流 3-5%）。",
                 "封面/标题吸引力不足，用户不点",
                 "重做封面与标题钩子，A/B 测试新素材；低质素材直接关停换创意。", 0.0))


def get_alerts(conn, customer_id=None, severity=None) -> List[Alert]:
    sql = "SELECT * FROM alerts WHERE 1=1"
    args = []
    if customer_id:
        sql += " AND customer_id=?"; args.append(customer_id)
    if severity:
        sql += " AND severity=?"; args.append(severity)
    sql += " ORDER BY period DESC, CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END"
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM alerts").description]
    return [Alert(**dict(zip(cols, r))) for r in rows]


def get_tasks(conn, customer_id=None, priority=None) -> List[Task]:
    sql = "SELECT * FROM tasks WHERE 1=1"
    args = []
    if customer_id:
        sql += " AND customer_id=?"; args.append(customer_id)
    if priority:
        sql += " AND priority=?"; args.append(priority)
    sql += " ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END"
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM tasks").description]
    return [Task(**dict(zip(cols, r))) for r in rows]


def get_badcases(conn, customer_id=None) -> List[BadCase]:
    sql = "SELECT * FROM badcases WHERE 1=1"
    args = []
    if customer_id:
        sql += " AND customer_id=?"; args.append(customer_id)
    sql += " ORDER BY impact_value DESC"
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM badcases").description]
    return [BadCase(**dict(zip(cols, r))) for r in rows]


def log_agent_run(conn, run_id: str, ts: str, user_query: str, intent: str,
                  steps: list, answer: str, tool_count: int, engine: str) -> None:
    """持久化一次 agent 运行的完整轨迹（意图→工具→观察→回答），满足可观测性。"""
    import json
    conn.execute(
        "INSERT OR REPLACE INTO agent_logs VALUES (?,?,?,?,?,?,?,?)",
        (run_id, ts, user_query, intent, json.dumps(steps, ensure_ascii=False),
         answer, tool_count, engine))
    conn.commit()


def recent_agent_runs(conn, limit: int = 10) -> List[tuple]:
    return conn.execute(
        "SELECT run_id, ts, user_query, intent, tool_count, engine "
        "FROM agent_logs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()

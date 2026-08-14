"""
db.py : 本地 SQLite 存储 + 查询接口
====================================
把 adapter 归一化后的数据落库，并向上层（AI 节点 / eval）提供查询。
这是"真实架构层"的一部分：数据虽是模拟生成，但存取路径与真实生产一致。
"""
import sqlite3
from typing import Dict, List, Optional
from schema import (
    CustomerProfile, AdPerformance, ContentItem,
    CommunicationRecord, IndustryBenchmark, Demographics,
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
    for t in ("customers", "ads", "contents", "comms", "benchmarks", "demographics"):
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

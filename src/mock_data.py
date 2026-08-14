"""
mock_data.py : 全模拟虚拟数据集生成器
=====================================
生成"平台原生形态"的原始数据（字段名刻意各不相同），用来真实演示
adapter 的"翻译/归一化"价值：

  - 小红书笔记 : note_id / desc / jump_link / read_cnt ...
  - 小红书广告 : ad_id / plan_name / note_bind / cost / order_cnt / gmv_amt / ad_type / bid_type ...
  - 抖音广告   : vid_id / ad_name / video_bind / show / engage / pay_gmv ...
  - 腾讯广告   : cid / campaign / creative_id / exposure / click_num / revenue ...
  - 快手广告   : adid / plan / photo_id / disp / clk / 消耗 / 人群 / 周 ...   （含中文键）

所有数字由固定 seed 生成，保证可复现、eval 稳定。
"""
import random
from collections import defaultdict
from typing import Dict, List, Any

PLATFORMS = ["xhs", "douyin", "tencent", "kuaishou"]
INDUSTRIES = ["美妆", "食品饮料", "3C数码", "母婴", "服饰", "教育", "家居"]

# 20 个负责人，每人专属（避免重复）
OWNERS = [
    "张优化", "李增长", "王投放", "赵媒介", "陈内容", "周策略",
    "吴投放", "郑复盘", "钱优化", "孙媒介", "周大伟", "郑小红",
    "陈思琪", "吴梓萱", "钱博文", "孙明阳", "李梓涵", "王昊然",
    "张雨彤", "赵宇辰",
]
WEEKS = [f"2026-W{w:02d}" for w in range(21, 33)]  # 12 周

# 行业 → 真实品牌（用于 mock 客户名；非商业用途）
BRANDS = {
    "美妆":     ["完美日记", "花西子", "毛戈平", "橘朵", "彩棠"],
    "食品饮料": ["三只松鼠", "良品铺子", "王小卤", "元气森林", "钟薛高"],
    "3C数码":   ["小米", "OPPO", "大疆", "石头科技", "倍轻松"],
    "母婴":     ["Babycare", "飞鹤", "君乐宝", "贝亲", "好奇"],
    "服饰":     ["蕉下", "Ubras", "内外", "MAIA ACTIVE", "lululemon"],
    "教育":     ["作业帮", "斑马英语", "火花思维", "学而思", "猿辅导"],
    "家居":     ["林氏木业", "源氏木语", "欧派", "索菲亚", "全友家居"],
}

# 小红书特有的"投放位置"分类：信息流 F vs 搜索 S（KFS 框架中的 F 和 S）
# K (达人种草) 不计入 ad 投放表，只走笔记
XHS_AD_TYPES = ["信息流", "搜索"]
# 内容类型（蒲公英后台口径）：4 种，按用途 × 链接类型划分
XHS_CONTENT_SUBTYPES = ["效果-外链营销通", "效果-落地页", "内容-外链营销通", "内容-种草达人合作"]
# 出价类型
BID_TYPES = ["手动出价", "自动出价", "oCPC"]
# 受众四细分（真实小红书后台：人群包 / 关键词定向 / 行为兴趣 / 智能定向）
AUDIENCE_TYPES = ["人群包", "关键词定向", "行为兴趣", "智能定向"]


# 客户"人设"：trend 决定整体消耗走势，制造可诊断的信号
# 第 5 项为「本平台（小红书）月均投放预算体量（¥）」—— 作为投放量级缩放因子，使大客户消耗更高、更真实。
# 等级（KA/SMB）最终由「周均本平台消耗」阈值推导（见文末 post-pass），保证与展示口径自洽、可被验证。
CUSTOMER_PROFILES = [
    ("C001", "at_risk",   -0.14, "美妆",     180_000),
    ("C002", "growing",    0.18, "食品饮料",   45_000),
    ("C003", "stable",     0.01, "3C数码",   320_000),
    ("C004", "growing",    0.12, "母婴",       60_000),
    ("C005", "at_risk",   -0.09, "服饰",       35_000),
    ("C006", "growing",    0.22, "教育",     210_000),
    ("C007", "stable",     0.0,  "家居",       70_000),
    ("C008", "at_risk",   -0.20, "美妆",       40_000),
    ("C009", "growing",    0.15, "食品饮料", 150_000),
    ("C010", "stable",     0.02, "3C数码",     55_000),
    ("C011", "growing",    0.10, "母婴",     130_000),
    ("C012", "at_risk",   -0.07, "服饰",     110_000),
    ("C013", "growing",    0.20, "教育",       80_000),
    ("C014", "stable",    -0.01, "家居",     280_000),
    ("C015", "growing",    0.13, "美妆",       50_000),
    ("C016", "at_risk",   -0.11, "食品饮料",   30_000),
    ("C017", "growing",    0.17, "3C数码",   190_000),
    ("C018", "stable",     0.03, "母婴",       65_000),
    ("C019", "growing",    0.09, "服饰",     160_000),
    ("C020", "at_risk",   -0.16, "教育",       42_000),
]


def _round(x, n=2):
    return round(x, n)


def generate_raw_dataset(seed: int = 42) -> Dict[str, List[Dict[str, Any]]]:
    rnd = random.Random(seed)
    raw: Dict[str, List[Dict[str, Any]]] = {
        "customers": [], "xhs_notes": [], "xhs_ads": [], "douyin_ads": [],
        "tencent_ads": [], "kuaishou_ads": [], "wecom": [], "benchmarks": [],
    }

    for (cid, persona, trend, industry, monthly_budget) in CUSTOMER_PROFILES:
        # 预算缩放因子：让投放量级与等级自洽（月预算 10w 对应 1.0 基准）
        budget_factor = monthly_budget / 100_000.0
        # 每个客户专属一个负责人（按 customer_id 索引，确保无重复）
        owner = OWNERS[int(cid[-2:]) - 1]
        joined = f"2025-{rnd.randint(1,12):02d}-{rnd.randint(1,28):02d}"
        stage = {"at_risk": "at_risk", "growing": "growing", "stable": "stable"}[persona]
        status = "active" if persona != "at_risk" or rnd.random() < .6 else "paused"
        brand_idx = int(cid[-2:]) - 1
        brand_name = BRANDS[industry][brand_idx % len(BRANDS[industry])]
        # tier 暂置占位，文末按「周均本平台消耗」阈值统一重算（见 post-pass）
        tier = "SMB"
        raw["customers"].append({
            "cust_id": cid,
            "name": brand_name,
            "company": f"{brand_name}旗舰店",
            "industry": industry, "tier": tier, "owner": owner,
            "wecom": f"wx_{cid}", "status": status, "joined": joined, "stage": stage,
        })

        # —— 内容（小红书笔记）：2~4 篇 ——
        notes_list = []
        for n in range(rnd.randint(2, 4)):
            note_id = f"NOTE_{cid}_{n}"
            notes_list.append(note_id)
            reads = rnd.randint(2000, 80000)
            like = int(reads * rnd.uniform(0.03, 0.12))
            collect = int(reads * rnd.uniform(0.01, 0.05))
            comment = int(reads * rnd.uniform(0.005, 0.02))
            share = int(reads * rnd.uniform(0.005, 0.025))
            # 爆文率判定：阅读 ≥ 50k 且互动率 ≥ 5% → 爆文
            engage_rate = (like + collect + comment + share) / reads if reads else 0
            is_hot = "爆文" if (reads >= 50000 and engage_rate >= 0.05) else "常文"
            is_original = rnd.random() < 0.7  # 70% 概率为品牌原创
            raw["xhs_notes"].append({
                "note_id": note_id,
                "title": f"{industry}种草笔记#{n} {rnd.choice(['实测','攻略','测评','开箱'])}",
                "desc": f"这是一篇关于{industry}的种草内容，主打真实体验与性价比。",
                "cover": f"https://cdn.example.com/{note_id}.jpg",
                "jump_link": f"https://xhs.example.com/note/{note_id}",
                "publish_date": f"2026-{rnd.randint(5,8):02d}-{rnd.randint(1,28):02d}",
                "read_cnt": reads, "like_cnt": like, "collect_cnt": collect,
                "comment_cnt": comment, "share_cnt": share,
                "is_hot": is_hot, "is_original": is_original,
                "engage_rate": _round(engage_rate, 4),
            })

        # —— 各平台投放：每客户×平台固定计划数（保证周环比由设计走势主导）——
        campaign_counts = {p: rnd.randint(1, 3) for p in PLATFORMS}
        for wi, week in enumerate(WEEKS):
            week_factor = (1 + trend) ** wi
            # 客户首周投放计划总数，决定本周边际 ROI 衰减分析的"基线"
            for p in PLATFORMS:
                for c in range(campaign_counts[p]):
                    noise = rnd.uniform(0.93, 1.07)
                    base_imp = int(rnd.randint(30000, 250000) * budget_factor)
                    impress = int(base_imp * week_factor * noise)
                    ctr_raw = rnd.uniform(0.008, 0.045)
                    clicks = max(1, int(impress * ctr_raw))
                    cpc = rnd.uniform(0.6, 3.2)
                    spend = _round(clicks * cpc, 1)
                    # 转化分浅层（私信/留资）+ 深层（下单）
                    cvr_raw = rnd.uniform(0.02, 0.12)
                    cv_total = max(0, int(clicks * cvr_raw))
                    deep_rate = rnd.uniform(0.3, 0.7)  # 深层转化占比
                    cv_deep = int(cv_total * deep_rate)
                    cv_shallow = cv_total - cv_deep
                    aov = rnd.uniform(80, 600)
                    gmv = _round(cv_deep * aov, 1)
                    audience = rnd.choice(AUDIENCE_TYPES)
                    note_bind = rnd.choice(notes_list)
                    bid_type = rnd.choice(BID_TYPES)

                    if p == "xhs":
                        # 小红书特有：信息流 vs 搜索（KFS 框架）
                        ad_type = rnd.choice(XHS_AD_TYPES)
                        content_subtype = rnd.choice(XHS_CONTENT_SUBTYPES)
                        # 蒲公英 5 段私信漏斗：消耗 → 开口 → 留资 → 深度(企微/咨询) → 进店
                        # at_risk 客户整体漏斗效率偏低，制造可诊断信号
                        pm_decay = 0.55 if persona == "at_risk" else (1.15 if persona == "growing" else 1.0)
                        pm_inquiry = max(0, int(clicks * rnd.uniform(0.005, 0.025) * pm_decay))
                        pm_lead = max(0, int(pm_inquiry * rnd.uniform(0.30, 0.60)))
                        pm_deep = max(0, int(pm_lead * rnd.uniform(0.40, 0.70)))
                        store_visit = max(0, int(pm_deep * rnd.uniform(0.50, 0.90)))
                        raw["xhs_ads"].append({
                            "ad_id": f"XAD_{cid}_{week}_{c}",
                            "plan_name": f"{industry}{ad_type}_{c}",
                            "note_bind": note_bind, "impress": impress, "click": clicks,
                            "cost": spend,
                            "cv_shallow": cv_shallow, "cv_deep": cv_deep,
                            "gmv_amt": gmv,
                            "audience": audience, "week": week,
                            "ad_type": ad_type, "bid_type": bid_type,
                            "content_subtype": content_subtype,
                            "pm_inquiry": pm_inquiry, "pm_lead": pm_lead,
                            "pm_deep": pm_deep, "store_visit": store_visit,
                        })
                    elif p == "douyin":
                        raw["douyin_ads"].append({
                            "vid_id": f"DAD_{cid}_{week}_{c}", "ad_name": f"{industry}千川_{c}",
                            "video_bind": note_bind, "show": impress, "engage": clicks,
                            "spend": spend,
                            "cv_shallow": cv_shallow, "cv_deep": cv_deep,
                            "pay_gmv": gmv,
                            "crowd": audience, "week": week,
                            "bid_type": bid_type,
                        })
                    elif p == "tencent":
                        raw["tencent_ads"].append({
                            "cid": f"TAD_{cid}_{week}_{c}", "campaign": f"{industry}朋友圈_{c}",
                            "creative_id": note_bind, "exposure": impress, "click_num": clicks,
                            "cost": spend,
                            "cv_shallow": cv_shallow, "cv_deep": cv_deep,
                            "revenue": gmv,
                            "target": audience, "week": week,
                            "bid_type": bid_type,
                        })
                    else:  # kuaishou —— 中文键
                        raw["kuaishou_ads"].append({
                            "adid": f"KAD_{cid}_{week}_{c}", "plan": f"{industry}磁力_{c}",
                            "photo_id": note_bind, "disp": impress, "clk": clicks,
                            "消耗": spend,
                            "cv_浅层": cv_shallow, "cv_深层": cv_deep,
                            "gmv": gmv,
                            "人群": audience, "周": week,
                            "出价方式": bid_type,
                        })

        # —— 企微沟通：3~8 条 ——
        n_msg = rnd.randint(3, 8)
        for m in range(n_msg):
            neg_bias = 0.5 if persona == "at_risk" else 0.15
            roll = rnd.random()
            if roll < neg_bias:
                intent, sent, text = "complaint", "negative", rnd.choice([
                    "这周消耗又涨了转化没起来，怎么回事？",
                    "ROI 比上周差太多，先停掉几个计划吧。",
                    "同行投得比我们好，你们给的策略不行啊。",
                ])
            elif roll < neg_bias + 0.25:
                intent, sent, text = "renewal", "positive", "续费没问题，下季度预算加 20%。"
            elif roll < neg_bias + 0.4:
                intent, sent, text = "inquiry", "neutral", "新品类想试试信息流，给个方案？"
            else:
                intent, sent, text = "praise", "positive", "上周那条爆款笔记带量不错，继续。"
            raw["wecom"].append({
                "msg_id": f"WX_{cid}_{m}", "cust": cid, "role": "customer",
                "ts": f"2026-{rnd.randint(5,8):02d}-{rnd.randint(1,28):02d} 1{rnd.randint(0,9)}:{rnd.randint(10,59)}",
                "text": text, "media": "text", "intent": intent, "emotion": sent,
            })

        # —— 行业大盘：每平台每周一条基准 ——
        for p in PLATFORMS:
            for week in WEEKS:
                # 小红书行业基准分信息流 / 搜索两条（更精细）
                if p == "xhs":
                    for ad_type in XHS_AD_TYPES:
                        raw["benchmarks"].append({
                            "bid": f"BM_{p}_{industry}_{ad_type}_{week}", "platform": p,
                            "industry": industry, "week": week, "ad_type": ad_type,
                            "ctr": _round(rnd.uniform(0.012, 0.03), 4),
                            "cvr": _round(rnd.uniform(0.03, 0.08), 4),
                            "cpm": _round(rnd.uniform(15, 45), 2),
                            "roi": _round(rnd.uniform(1.2, 3.5), 2),
                            "trend": rnd.choice(["up", "down", "flat"]),
                        })
                else:
                    raw["benchmarks"].append({
                        "bid": f"BM_{p}_{industry}_{week}", "platform": p,
                        "industry": industry, "week": week, "ad_type": None,
                        "ctr": _round(rnd.uniform(0.012, 0.03), 4),
                        "cvr": _round(rnd.uniform(0.03, 0.08), 4),
                        "cpm": _round(rnd.uniform(15, 45), 2),
                        "roi": _round(rnd.uniform(1.2, 3.5), 2),
                        "trend": rnd.choice(["up", "down", "flat"]),
                    })

    # —— 等级分类（数据驱动、与展示口径自洽）——
    # 口径：按「本平台（小红书）周均消耗」分档。
    #   KA（大客户）= 周均本平台消耗 ≥ KA_WEEKLY_SPEND（默认 ¥25,000）
    #   SMB（中小客户）= 周均本平台消耗 <  KA_WEEKLY_SPEND
    # 这样客户一览表中的「等级」列与「本平台消耗」列始终一致，可被直接验证。
    KA_WEEKLY_SPEND = 15_000.0
    _sp = defaultdict(float)
    for ad in raw["xhs_ads"]:
        _sp[ad["ad_id"].split("_")[1]] += ad["cost"]
    n_weeks = len(WEEKS) or 1
    for c in raw["customers"]:
        avg_weekly = _sp.get(c["cust_id"], 0.0) / n_weeks
        c["tier"] = "KA" if avg_weekly >= KA_WEEKLY_SPEND else "SMB"

    return raw


if __name__ == "__main__":
    d = generate_raw_dataset()
    print("customers:", len(d["customers"]))
    print("xhs_notes:", len(d["xhs_notes"]))
    print("xhs_ads:", len(d["xhs_ads"]), "douyin:", len(d["douyin_ads"]),
          "tencent:", len(d["tencent_ads"]), "kuaishou:", len(d["kuaishou_ads"]))
    print("wecom:", len(d["wecom"]), "benchmarks:", len(d["benchmarks"]))
"""
mock_data.py : 全模拟虚拟数据集生成器
=====================================
生成"平台原生形态"的原始数据（字段名刻意各不相同），用来真实演示
adapter 的"翻译/归一化"价值：

  - 小红书笔记 : note_id / desc / jump_link / read_cnt ...
  - 小红书广告 : ad_id / plan_name / note_bind / cash_cost / budget_cost /
                pm_consult / pm_open / pm_lead / pm_wechat / ad_type / bid_type ...
  - 抖音广告   : vid_id / ad_name / video_bind / show / engage / cash_cost ...
  - 腾讯广告   : cid / campaign / creative_id / exposure / click_num / revenue ...
  - 快手广告   : adid / plan / photo_id / disp / clk / 消耗 / 人群 / 周 ...（含中文键）

业务口径（v8 小红书「线索经营」商业化销售周报）：
  - 核心 KPI 是「留资成本 CPL = 现金消耗 / 私资留资数」，不是 GMV/ROI。
  - 私信转化漏斗：咨询 → 开口 → 留资 → 加微信（4 段，每段一个成本）。
  - 预算消耗(广告币，含返点) vs 现金消耗(人民币) 分开。
  - 预算花完率 = 现金消耗 / 计划预算；at_risk 客户花不完、growing 客户花得快。
  - 行业 CPL 基准按行业给，at_risk 实际 CPL 高于基准、growing 低于基准（制造可诊断信号）。

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

# 行业留资成本(CPL)大盘基准（元/条）—— 参考公开行业数据（教育 80~130、美妆 80~150 等），用于对标
INDUSTRY_CPL = {
    "美妆": 95, "食品饮料": 60, "3C数码": 110, "母婴": 100,
    "服饰": 70, "教育": 120, "家居": 115,
}
# 行业客单价（用于估算成交 GMV）
INDUSTRY_AOV = {
    "美妆": 350, "食品饮料": 120, "3C数码": 1800, "母婴": 480,
    "服饰": 420, "教育": 2600, "家居": 2500,
}
# 行业主力人群年龄画像（占比，合计 1.0）—— 教育=家长 30~50、美妆=25~40 等
INDUSTRY_AGE = {
    "美妆":     {"age_25_30": 0.38, "age_31_40": 0.42, "age_41_50": 0.16, "age_50_plus": 0.04},
    "食品饮料": {"age_25_30": 0.30, "age_31_40": 0.40, "age_41_50": 0.22, "age_50_plus": 0.08},
    "3C数码":   {"age_25_30": 0.34, "age_31_40": 0.44, "age_41_50": 0.18, "age_50_plus": 0.04},
    "母婴":     {"age_25_30": 0.42, "age_31_40": 0.46, "age_41_50": 0.10, "age_50_plus": 0.02},
    "服饰":     {"age_25_30": 0.36, "age_31_40": 0.43, "age_41_50": 0.17, "age_50_plus": 0.04},
    "教育":     {"age_25_30": 0.18, "age_31_40": 0.47, "age_41_50": 0.29, "age_50_plus": 0.06},
    "家居":     {"age_25_30": 0.22, "age_31_40": 0.48, "age_41_50": 0.25, "age_50_plus": 0.05},
}
# 行业主力地域与兴趣词（mock，用于人群拆解展示）
INDUSTRY_GEO = {
    "美妆":     ("江浙沪", "护肤成分党"),
    "食品饮料": ("华南", "零食测评"),
    "3C数码":   ("一线", "数码极客"),
    "母婴":     ("新一线", "育儿经验"),
    "服饰":     ("全国", "穿搭灵感"),
    "教育":     ("北上广深", "升学规划"),
    "家居":     ("新一线", "装修避坑"),
}

# 小红书特有的"投放位置"分类：信息流 F vs 搜索 S（KFS 框架）
XHS_AD_TYPES = ["信息流", "搜索"]
# 出价类型
BID_TYPES = ["手动出价", "自动出价", "oCPX"]
# 受众四细分（真实小红书后台：人群包 / 关键词定向 / 行为兴趣 / 智能定向）
AUDIENCE_TYPES = ["人群包", "关键词定向", "行为兴趣", "智能定向"]

# 客户"人设"：trend 决定整体消耗走势，persona 决定漏斗健康度
# monthly_budget 作为投放量级缩放因子（月预算 10w 对应 1.0 基准）；等级最终由周均本平台现金消耗阈值推导
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
# persona → 漏斗各段系数（开口率 / 留资率 / 加微率）与 预算花完率 / CPL 偏离倍数
PERSONA = {
    "at_risk": dict(open_rate=0.30, lead_rate=0.34, wechat_rate=0.30,
                    spend_ratio=0.55, cpl_mult=1.45, comp_share=0.55),
    "stable":  dict(open_rate=0.42, lead_rate=0.46, wechat_rate=0.45,
                    spend_ratio=0.82, cpl_mult=1.02, comp_share=0.35),
    "growing": dict(open_rate=0.52, lead_rate=0.56, wechat_rate=0.60,
                    spend_ratio=0.95, cpl_mult=0.72, comp_share=0.22),
}


def _round(x, n=2):
    return round(x, n)


def generate_raw_dataset(seed: int = 42) -> Dict[str, List[Dict[str, Any]]]:
    rnd = random.Random(seed)
    raw: Dict[str, List[Dict[str, Any]]] = {
        "customers": [], "xhs_notes": [], "xhs_ads": [], "douyin_ads": [],
        "tencent_ads": [], "kuaishou_ads": [], "wecom": [], "benchmarks": [],
        "demographics": [],
    }

    for (cid, persona, trend, industry, monthly_budget) in CUSTOMER_PROFILES:
        pp = PERSONA[persona]
        budget_factor = monthly_budget / 100_000.0
        owner = OWNERS[int(cid[-2:]) - 1]
        joined = f"2025-{rnd.randint(1,12):02d}-{rnd.randint(1,28):02d}"
        status = "active" if persona != "at_risk" or rnd.random() < .6 else "paused"
        brand_idx = int(cid[-2:]) - 1
        brand_name = BRANDS[industry][brand_idx % len(BRANDS[industry])]
        raw["customers"].append({
            "cust_id": cid, "name": brand_name,
            "company": f"{brand_name}旗舰店",
            "industry": industry, "tier": "SMB", "owner": owner,
            "wecom": f"wx_{cid}", "status": status, "joined": joined, "stage": persona,
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
            engage_rate = (like + collect + comment + share) / reads if reads else 0
            is_hot = "爆文" if (reads >= 50000 and engage_rate >= 0.05) else "常文"
            is_original = rnd.random() < 0.7
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

        # 计划数：本平台(小红书) 2~4 个；竞争媒体合计 1~3 个
        xhs_campaigns = rnd.randint(2, 4)
        comp_campaigns = max(1, int(rnd.randint(1, 3) * pp["comp_share"] * 2))
        weekly_planned = monthly_budget / 4.0  # 计划周预算（人民币，抛开返点）

        for wi, week in enumerate(WEEKS):
            week_factor = (1 + trend) ** wi
            # —— 小红书（本平台，复盘核心）——
            for c in range(xhs_campaigns):
                noise = rnd.uniform(0.93, 1.07)
                # 现金消耗：受预算花完率与走势影响
                planned_week_cash = weekly_planned * week_factor  # 计划周预算随走势放大/收缩
                cash_spend = _round(planned_week_cash * pp["spend_ratio"] * noise / xhs_campaigns, 1)
                # 预算消耗（广告币，= 计划现金预算 × 含返点 12%）—— 用于算「预算花完率」
                rebate = 0.12
                budget_cost = _round((planned_week_cash / xhs_campaigns) * (1 + rebate), 1)
                ctr_raw = rnd.uniform(0.008, 0.045)
                clicks = max(1, int((cash_spend / rnd.uniform(0.6, 3.2)) ))  # 由 cpc 反推点击
                impress = max(clicks, int(clicks / ctr_raw))
                # 私信漏斗：先定目标 CPL → 反推留资数 → 反推开口/咨询/加微
                target_cpl = INDUSTRY_CPL[industry] * pp["cpl_mult"] * rnd.uniform(0.9, 1.12)
                pm_lead = max(1, int(round(cash_spend / target_cpl)))
                pm_open = max(pm_lead, int(round(pm_lead / pp["lead_rate"] * rnd.uniform(0.95, 1.05))))
                pm_consult = max(pm_open, int(round(pm_open / pp["open_rate"] * rnd.uniform(0.95, 1.05))))
                pm_wechat = max(0, int(round(pm_lead * pp["wechat_rate"] * rnd.uniform(0.9, 1.1))))
                # 成交 GMV：来自加微后的成交（线索型客户 GMV 较小）
                aov = INDUSTRY_AOV[industry]
                close_rate = rnd.uniform(0.10, 0.30)
                gmv = _round(pm_wechat * aov * close_rate, 1)
                audience = rnd.choice(AUDIENCE_TYPES)
                note_bind = rnd.choice(notes_list)
                bid_type = rnd.choice(BID_TYPES)
                ad_type = rnd.choice(XHS_AD_TYPES)
                raw["xhs_ads"].append({
                    "ad_id": f"XAD_{cid}_{week}_{c}",
                    "plan_name": f"{industry}{ad_type}_{c}",
                    "note_bind": note_bind, "impress": impress, "click": clicks,
                    "cash_cost": cash_spend, "budget_cost": budget_cost,
                    "gmv_amt": gmv, "audience": audience, "week": week,
                    "ad_type": ad_type, "bid_type": bid_type,
                    "pm_consult": pm_consult, "pm_open": pm_open,
                    "pm_lead": pm_lead, "pm_wechat": pm_wechat,
                })

            # —— 竞争媒体（客户在其他平台的投放，仅作情报视角）——
            other_spend = _round(weekly_planned * pp["comp_share"] * week_factor / max(comp_campaigns,1), 1)
            other_aov = INDUSTRY_AOV[industry]
            for c in range(comp_campaigns):
                p = rnd.choice(["douyin", "tencent", "kuaishou"])
                o_sp = _round(other_spend * rnd.uniform(0.8, 1.2), 1)
                o_clicks = max(1, int(o_sp / rnd.uniform(0.8, 3.5)))
                o_imp = max(o_clicks, int(o_clicks / rnd.uniform(0.01, 0.05)))
                o_gmv = _round(o_clicks * rnd.uniform(0.01, 0.05) * other_aov, 1)
                note_bind = rnd.choice(notes_list)
                bid_type = rnd.choice(BID_TYPES)
                if p == "douyin":
                    raw["douyin_ads"].append({
                        "vid_id": f"DAD_{cid}_{week}_{c}", "ad_name": f"{industry}千川_{c}",
                        "video_bind": note_bind, "show": o_imp, "engage": o_clicks,
                        "cash_cost": o_sp, "budget_cost": _round(o_sp*1.1,1), "pay_gmv": o_gmv,
                        "crowd": rnd.choice(AUDIENCE_TYPES), "week": week, "bid_type": bid_type,
                        "pm_consult":0,"pm_open":0,"pm_lead":0,"pm_wechat":0})
                elif p == "tencent":
                    raw["tencent_ads"].append({
                        "cid": f"TAD_{cid}_{week}_{c}", "campaign": f"{industry}朋友圈_{c}",
                        "creative_id": note_bind, "exposure": o_imp, "click_num": o_clicks,
                        "cash_cost": o_sp, "budget_cost": _round(o_sp*1.1,1), "revenue": o_gmv,
                        "target": rnd.choice(AUDIENCE_TYPES), "week": week, "bid_type": bid_type,
                        "pm_consult":0,"pm_open":0,"pm_lead":0,"pm_wechat":0})
                else:
                    raw["kuaishou_ads"].append({
                        "adid": f"KAD_{cid}_{week}_{c}", "plan": f"{industry}磁力_{c}",
                        "photo_id": note_bind, "disp": o_imp, "clk": o_clicks,
                        "cash_cost": o_sp, "budget_cost": _round(o_sp*1.1,1), "gmv": o_gmv,
                        "人群": rnd.choice(AUDIENCE_TYPES), "周": week, "出价方式": bid_type,
                        "pm_consult":0,"pm_open":0,"pm_lead":0,"pm_wechat":0})

            # —— 人群画像（每客户每周一条）——
            age = INDUSTRY_AGE[industry]
            jitter = {k: max(0.02, v + rnd.uniform(-0.05, 0.05)) for k, v in age.items()}
            s = sum(jitter.values())
            jitter = {k: _round(v / s, 3) for k, v in jitter.items()}
            geo, interest = INDUSTRY_GEO[industry]
            raw["demographics"].append({
                "customer_id": cid, "period": week,
                "age_25_30": jitter["age_25_30"], "age_31_40": jitter["age_31_40"],
                "age_41_50": jitter["age_41_50"], "age_50_plus": jitter["age_50_plus"],
                "top_region": geo, "top_interest": interest,
            })

        # —— 企微沟通：3~8 条 ——
        n_msg = rnd.randint(3, 8)
        for m in range(n_msg):
            neg_bias = 0.5 if persona == "at_risk" else 0.15
            roll = rnd.random()
            if roll < neg_bias:
                intent, sent, text = "complaint", "negative", rnd.choice([
                    "这周留资成本又涨了，转化没起来，怎么回事？",
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

        # —— 行业大盘：每平台每周（小红书分信息流/搜索）——
        for p in PLATFORMS:
            for week in WEEKS:
                if p == "xhs":
                    for ad_type in XHS_AD_TYPES:
                        raw["benchmarks"].append({
                            "bid": f"BM_{p}_{industry}_{ad_type}_{week}", "platform": p,
                            "industry": industry, "week": week, "ad_type": ad_type,
                            "ctr": _round(rnd.uniform(0.012, 0.03), 4),
                            "cvr": _round(rnd.uniform(0.03, 0.08), 4),
                            "cpm": _round(rnd.uniform(15, 45), 2),
                            "roi": _round(rnd.uniform(1.2, 3.5), 2),
                            "cpl": _round(INDUSTRY_CPL[industry] * rnd.uniform(0.92, 1.08), 1),
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
                        "cpl": _round(INDUSTRY_CPL[industry] * rnd.uniform(0.9, 1.1), 1),
                        "trend": rnd.choice(["up", "down", "flat"]),
                    })

    # —— 等级分类（数据驱动、与展示口径自洽）——
    # 口径：按「本平台（小红书）周均现金消耗」分档。
    #   KA = 周均 ≥ 15,000；SMB = 周均 < 15,000
    KA_WEEKLY_SPEND = 15_000.0
    _sp = defaultdict(float)
    for ad in raw["xhs_ads"]:
        _sp[ad["ad_id"].split("_")[1]] += ad["cash_cost"]
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
    print("wecom:", len(d["wecom"]), "benchmarks:", len(d["benchmarks"]),
          "demographics:", len(d["demographics"]))

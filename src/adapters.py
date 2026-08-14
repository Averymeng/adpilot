"""
adapters.py : 5 个适配器，把"平台原生数据"归一化到统一 schema
=============================================================
这是 B 方案「最小公共 schema + adapter 归一化」的代码实现。
- 每个 adapter 暴露 `normalize(raw) -> 统一模型` 与 `fetch(store, ...) -> List[模型]`。
- AI 分析层只调用 fetch，拿到的永远是统一格式，不感知平台差异。
- 接新平台 = 新增一个 adapter，AI 代码零改动。
"""
from typing import Any, Dict, List, Optional
from schema import (
    CustomerProfile, AdPerformance, ContentItem,
    CommunicationRecord, IndustryBenchmark,
)


class BaseAdapter:
    """统一接口：从原始数据集 store 中筛选并归一化。"""
    model = None

    @classmethod
    def normalize(cls, raw: Dict[str, Any]):
        raise NotImplementedError

    @classmethod
    def fetch(cls, store: Dict[str, List[Dict[str, Any]]],
              customer_id: Optional[str] = None,
              period: Optional[str] = None) -> List[Any]:
        out = []
        for raw in store.get(cls.raw_key, []):
            rec = cls.normalize(raw)
            if customer_id and getattr(rec, "customer_id", None) != customer_id:
                continue
            if period and getattr(rec, "period", None) != period:
                continue
            out.append(rec)
        return out


# ---------------------------------------------------------------------------
# 1) 客户档案适配器
# ---------------------------------------------------------------------------
class CustomerAdapter(BaseAdapter):
    model = CustomerProfile
    raw_key = "customers"

    @classmethod
    def normalize(cls, r: Dict[str, Any]) -> CustomerProfile:
        return CustomerProfile(
            customer_id=r["cust_id"], name=r["name"], company=r["company"],
            industry=r["industry"], tier=r["tier"], owner=r["owner"],
            wecom_id=r["wecom"], account_status=r["status"],
            joined_at=r["joined"], lifecycle_stage=r["stage"],
        )


# ---------------------------------------------------------------------------
# 2) 内容（小红书笔记）适配器  —— 原生字段 desc / jump_link / read_cnt ...
# ---------------------------------------------------------------------------
class XhsNoteAdapter(BaseAdapter):
    model = ContentItem
    raw_key = "xhs_notes"

    @classmethod
    def normalize(cls, r: Dict[str, Any]) -> ContentItem:
        return ContentItem(
            content_id=r["note_id"], platform="xhs", format="note",
            title=r["title"], body_text=r["desc"], cover_url=r["cover"],
            cta="点击查看更多", landing_link=r["jump_link"],
            publish_time=r["publish_date"],
            key_metrics={
                "reads": r["read_cnt"], "likes": r["like_cnt"],
                "collects": r["collect_cnt"], "comments": r["comment_cnt"],
                "shares": r.get("share_cnt", 0),
                "is_hot": r.get("is_hot", "常文"),
                "is_original": r.get("is_original", True),
                "engage_rate": r.get("engage_rate", 0),
            },
            is_original=r.get("is_original", True),
            share_cnt=r.get("share_cnt", 0),
        )

    @classmethod
    def fetch(cls, store, customer_id=None, period=None, content_ids=None):
        out = [cls.normalize(r) for r in store.get(cls.raw_key, [])]
        if content_ids:
            s = set(content_ids)
            out = [c for c in out if c.content_id in s]
        return out


# ---------------------------------------------------------------------------
# 3) 投放成效适配器（4 个平台，字段名各不相同）
# ---------------------------------------------------------------------------
def _common_ad(record_id, customer_id, platform, campaign_id, ad_group_id,
               period, impress, clicks, spend, conv, gmv, audience, content_id,
               ad_type="", bid_type="", cv_shallow=0, cv_deep=0,
               content_subtype="", pm_inquiry=0, pm_lead=0, pm_deep=0, store_visit=0):
    ctr = round(clicks / impress, 4) if impress else 0.0
    cvr = round(conv / clicks, 4) if clicks else 0.0
    cpc = round(spend / clicks, 2) if clicks else 0.0
    roi = round(gmv / spend, 2) if spend else 0.0
    return AdPerformance(
        record_id=record_id, customer_id=customer_id, platform=platform,
        campaign_id=campaign_id, ad_group_id=ad_group_id, period=period,
        impressions=impress, clicks=clicks, spend=spend, conversions=conv,
        gmv=gmv, ctr=ctr, cvr=cvr, cpc=cpc, roi=roi,
        audience_segment=audience, content_id=content_id,
        ad_type=ad_type, bid_type=bid_type,
        cv_shallow=cv_shallow, cv_deep=cv_deep,
        content_subtype=content_subtype,
        pm_inquiry=pm_inquiry, pm_lead=pm_lead, pm_deep=pm_deep, store_visit=store_visit,
    )


class XhsAdAdapter(BaseAdapter):
    model = AdPerformance
    raw_key = "xhs_ads"

    @classmethod
    def normalize(cls, r):
        # 原生: ad_id / plan_name / note_bind / impress / click / cost /
        #       cv_shallow / cv_deep / gmv_amt / ad_type / bid_type /
        #       content_subtype / pm_inquiry / pm_lead / pm_deep / store_visit
        return _common_ad(r["ad_id"], _cid(r["ad_id"]), "xhs", r["plan_name"],
                          r["ad_id"], r["week"], r["impress"], r["click"],
                          r["cost"], r["cv_shallow"] + r["cv_deep"], r["gmv_amt"], r["audience"],
                          r["note_bind"],
                          ad_type=r.get("ad_type", ""), bid_type=r.get("bid_type", ""),
                          cv_shallow=r.get("cv_shallow", 0), cv_deep=r.get("cv_deep", 0),
                          content_subtype=r.get("content_subtype", ""),
                          pm_inquiry=r.get("pm_inquiry", 0), pm_lead=r.get("pm_lead", 0),
                          pm_deep=r.get("pm_deep", 0), store_visit=r.get("store_visit", 0))


class DouyinAdAdapter(BaseAdapter):
    model = AdPerformance
    raw_key = "douyin_ads"

    @classmethod
    def normalize(cls, r):
        return _common_ad(r["vid_id"], _cid(r["vid_id"]), "douyin", r["ad_name"],
                          r["vid_id"], r["week"], r["show"], r["engage"],
                          r["spend"], r["cv_shallow"] + r["cv_deep"], r["pay_gmv"], r["crowd"],
                          r["video_bind"],
                          bid_type=r.get("bid_type", ""),
                          cv_shallow=r.get("cv_shallow", 0), cv_deep=r.get("cv_deep", 0))


class TencentAdAdapter(BaseAdapter):
    model = AdPerformance
    raw_key = "tencent_ads"

    @classmethod
    def normalize(cls, r):
        return _common_ad(r["cid"], _cid(r["cid"]), "tencent", r["campaign"],
                          r["cid"], r["week"], r["exposure"], r["click_num"],
                          r["cost"], r["cv_shallow"] + r["cv_deep"], r["revenue"], r["target"],
                          r["creative_id"],
                          bid_type=r.get("bid_type", ""),
                          cv_shallow=r.get("cv_shallow", 0), cv_deep=r.get("cv_deep", 0))


class KuaishouAdAdapter(BaseAdapter):
    model = AdPerformance
    raw_key = "kuaishou_ads"

    @classmethod
    def normalize(cls, r):
        return _common_ad(r["adid"], _cid(r["adid"]), "kuaishou", r["plan"],
                          r["adid"], r["周"], r["disp"], r["clk"],
                          r["消耗"], r["cv_浅层"] + r["cv_深层"], r["gmv"], r["人群"],
                          r["photo_id"],
                          bid_type=r.get("出价方式", ""),
                          cv_shallow=r.get("cv_浅层", 0), cv_deep=r.get("cv_深层", 0))


# 从 record_id（形如 XAD_C001_2026-W32_0）里提取 customer_id
def _cid(record_id: str) -> str:
    # 各平台 id 格式均为 <PREFIX>_<CID>_<week>_<idx>
    parts = record_id.split("_")
    for p in parts:
        if p.startswith("C") and p[1:].isdigit():
            return p
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# 4) 企微沟通适配器（真实接入点：企业微信会话存档 API）
# ---------------------------------------------------------------------------
class WeComMessageAdapter(BaseAdapter):
    model = CommunicationRecord
    raw_key = "wecom"

    @classmethod
    def normalize(cls, r: Dict[str, Any]) -> CommunicationRecord:
        return CommunicationRecord(
            msg_id=r["msg_id"], customer_id=r["cust"], sender_role=r["role"],
            channel="wecom", timestamp=r["ts"], text=r["text"],
            media_type=r["media"], intent_tag=r["intent"], sentiment=r["emotion"],
        )


# ---------------------------------------------------------------------------
# 5) 行业大盘适配器
# ---------------------------------------------------------------------------
class IndustryDataAdapter(BaseAdapter):
    model = IndustryBenchmark
    raw_key = "benchmarks"

    @classmethod
    def normalize(cls, r: Dict[str, Any]) -> IndustryBenchmark:
        return IndustryBenchmark(
            benchmark_id=r["bid"], platform=r["platform"], industry=r["industry"],
            period=r["week"], avg_ctr=r["ctr"], avg_cvr=r["cvr"],
            avg_cpm=r["cpm"], benchmark_roi=r["roi"], trend=r["trend"],
            ad_type=r.get("ad_type") or "",
        )


# 便捷汇总：一次拿到某客户某周所需的全部归一化数据
def collect_for_review(store, customer_id, period):
    ads = []
    for Adapter in (XhsAdAdapter, DouyinAdAdapter, TencentAdAdapter, KuaishouAdAdapter):
        ads += Adapter.fetch(store, customer_id=customer_id, period=period)
    customer = CustomerAdapter.fetch(store, customer_id=customer_id)
    customer = customer[0] if customer else None
    content_ids = {a.content_id for a in ads}
    contents = XhsNoteAdapter.fetch(store, content_ids=content_ids)
    comms = WeComMessageAdapter.fetch(store, customer_id=customer_id)
    benchmarks = IndustryDataAdapter.fetch(store, customer_id=None)  # 全量，调用方再筛
    return {
        "customer": customer, "ads": ads, "contents": contents,
        "comms": comms, "benchmarks": benchmarks,
    }

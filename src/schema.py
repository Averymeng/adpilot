"""
AdPilot — 互联网商业化销售 AI 工作台
====================================
schema.py : 5 张「最小公共 schema」的统一定义（B 方案核心）。

设计原则（普适性）：
- AI 分析层只认这 5 张表，不认识任何具体平台（小红书 / 抖音 / 腾讯 / 快手）。
- 每个平台 / 系统通过一个 adapter 把各自的"原生字段"翻译成下面的统一字段。
- 以后接新平台，只新增一个 adapter，AI 代码零改动。

业务口径（v8：小红书「线索经营」商业化销售周报，基于真实聚光/蒲公英后台逻辑）：
- 目标不是 GMV，是「线索」：私信开口 / 留资 / 加微信。
- 私信转化漏斗：咨询 → 开口 → 留资 → 加微信（4 段，每段一个成本）。
- 预算消耗(广告币) vs 现金消耗(人民币)：返点逻辑，销售必须分开盯。
- 出价方式：手动 / 自动 / oCPX（线索质量目标用 oCPX）。
- 投放位置：信息流(种草) vs 搜索(收割) —— KFS 框架的 F / S。
- 行业基准用「留资成本 CPL」而非 ROI。

（用标准库 dataclasses，零第三方依赖，保证可移植运行。）
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class CustomerProfile:
    """客户档案（跨平台唯一标识）"""
    customer_id: str
    name: str
    company: str
    industry: str
    tier: str                 # KA（大客户）/ SMB（中小）—— 由周均现金消耗阈值推导
    owner: str                # 负责的销售 / 优化师
    wecom_id: str             # 企业微信内部标识（真实接入点）
    account_status: str       # active / paused / churned
    joined_at: str
    lifecycle_stage: str      # at_risk / growing / onboarding / stable


@dataclass
class AdPerformance:
    """投放成效（按 周·计划 聚合，跨平台同构）—— 线索经营口径"""
    record_id: str
    customer_id: str
    platform: str             # xhs / douyin / tencent / kuaishou
    campaign_id: str
    ad_group_id: str
    period: str               # 例：2026-W32
    impressions: int          # 曝光
    clicks: int               # 点击
    cash_spend: float         # 现金消耗（人民币，抛开返点）—— 真实成本
    budget_spend: float       # 预算消耗（广告币，含返点）
    gmv: float                # 成交 GMV（仅深层成交贡献，线索型客户通常很小）
    # —— 私信转化漏斗（核心）——
    pm_consult: int = 0       # 私信咨询（广告触发的私信进线）
    pm_open: int = 0          # 私信开口（用户主动发第一条消息）
    pm_lead: int = 0          # 私信留资（留下联系方式）
    pm_wechat: int = 0        # 添加微信（引导加私域）
    # —— 投放结构 ——
    ad_type: str = ""         # 信息流 / 搜索（小红书 KFS 的 F / S）
    bid_type: str = ""        # 手动出价 / 自动出价 / oCPX
    audience_segment: str = ""# 人群定向（人群包 / 关键词定向 / 行为兴趣 / 智能定向）
    content_id: str = ""      # 外键 -> ContentItem
    # —— 派生指标（供 UI，入库时算好）——
    ctr: float = 0.0
    cpc: float = 0.0
    roi: float = 0.0          # GMV / 现金消耗（线索型客户次要）

    @property
    def cash_cpl(self) -> float:
        """留资成本 = 现金消耗 / 留资数"""
        return round(self.cash_spend / self.pm_lead, 2) if self.pm_lead else 0.0


@dataclass
class ContentItem:
    """内容 / 素材（笔记 / 视频 / 图文，跨平台同构）"""
    content_id: str
    platform: str
    format: str               # note / video / image / carousel
    title: str
    body_text: str
    cover_url: str
    cta: str
    landing_link: str
    publish_time: str
    key_metrics: Dict[str, Any]  # 阅读/点赞/收藏/评论/爆文/互动率
    is_original: bool = True
    share_cnt: int = 0


@dataclass
class CommunicationRecord:
    """企微沟通记录（真实接入点：企业微信会话存档 API）"""
    msg_id: str
    customer_id: str
    sender_role: str          # sales / customer
    channel: str
    timestamp: str
    text: str
    media_type: str
    intent_tag: str           # complaint / inquiry / renewal / praise
    sentiment: str            # positive / neutral / negative


@dataclass
class IndustryBenchmark:
    """行业大盘（用于横向对比，判断客户留资成本是否健康）"""
    benchmark_id: str
    platform: str
    industry: str
    period: str
    avg_ctr: float
    avg_cvr: float
    avg_cpm: float
    benchmark_roi: float
    benchmark_cpl: float = 0.0   # 行业留资成本基准（元/条）—— 核心对标指标
    trend: str = "flat"          # up / down / flat
    ad_type: str = ""            # 信息流 / 搜索


@dataclass
class Demographics:
    """人群画像（按 周·客户 聚合，来自定向后台）"""
    customer_id: str
    period: str
    age_25_30: float = 0.0
    age_31_40: float = 0.0
    age_41_50: float = 0.0
    age_50_plus: float = 0.0
    top_region: str = ""
    top_interest: str = ""


SCHEMA_MODELS = {
    "customer": CustomerProfile,
    "ad": AdPerformance,
    "content": ContentItem,
    "comms": CommunicationRecord,
    "benchmark": IndustryBenchmark,
    "demographics": Demographics,
}

"""
AdPilot — 互联网商业化销售 AI 工作台
====================================
schema.py : 5 张「最小公共 schema」的统一定义（B 方案核心）。

设计原则（普适性）：
- AI 分析层只认这 5 张表，不认识任何具体平台（小红书 / 抖音 / 腾讯 / 快手）。
- 每个平台 / 系统通过一个 adapter 把各自的"原生字段"翻译成下面的统一字段。
- 以后接新平台，只新增一个 adapter，AI 代码零改动。

字段命名升级（基于真实小红书 / 信息流广告投放逻辑）：
- ad_type: 投放位置（信息流 / 搜索）—— 小红书 KFS 框架的 F 和 S
- bid_type: 出价类型（手动 / 自动 / oCPC）
- cv_shallow / cv_deep: 浅层转化（私信/留资）vs 深层转化（下单/成交）
- 内容侧：爆文标记 / 互动率（笔记自然流量反哺）

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
    tier: str                 # KA（大客户）/ SMB（中小）
    owner: str                # 负责的销售 / 优化师
    wecom_id: str             # 企业微信内部标识（真实接入点）
    account_status: str       # active / paused / churned
    joined_at: str
    lifecycle_stage: str      # prospect / onboarding / growing / at_risk / churned


@dataclass
class AdPerformance:
    """投放成效（按 周 聚合，跨平台同构）"""
    record_id: str
    customer_id: str
    platform: str             # xhs / douyin / tencent / kuaishou
    campaign_id: str
    ad_group_id: str
    period: str               # 例：2026-W32
    impressions: int
    clicks: int
    spend: float
    conversions: int          # 总转化（=浅层+深层）
    gmv: float
    ctr: float
    cvr: float
    cpc: float
    roi: float
    audience_segment: str     # 受众定向（人群包 / 关键词定向 / 行为兴趣 / 智能定向）
    content_id: str           # 外键 -> ContentItem
    # —— 升级字段（基于小红书真实复盘维度）——
    ad_type: str = ""         # 投放位置：信息流 / 搜索（小红书特有；其他平台留空）
    bid_type: str = ""        # 出价类型：手动出价 / 自动出价 / oCPC
    cv_shallow: int = 0       # 浅层转化（私信/留资/加粉）
    cv_deep: int = 0          # 深层转化（下单/成交）
    # —— v7 升级字段（蒲公英 5 段私信漏斗 + 内容类型拆解）——
    content_subtype: str = "" # 内容类型：效果-外链营销通 / 效果-落地页 / 内容-外链营销通 / 内容-种草达人合作
    pm_inquiry: int = 0       # 私信开口
    pm_lead: int = 0          # 私信留资
    pm_deep: int = 0          # 私信深度转化（添加企微 / 内容咨询）
    store_visit: int = 0      # 进店访问


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
    key_metrics: Dict[str, Any]  # 平台特有的扩展指标（阅读/点赞/完播/爆文/互动率）
    # —— v7 升级（笔记活跃度）——
    is_original: bool = True  # 是否原创
    share_cnt: int = 0        # 分享次数


@dataclass
class CommunicationRecord:
    """企微沟通记录（真实接入点：企业微信会话存档 API）"""
    msg_id: str
    customer_id: str
    sender_role: str          # sales / customer
    channel: str              # wecom
    timestamp: str
    text: str
    media_type: str           # text / image / voice
    intent_tag: str           # complaint / inquiry / renewal / praise
    sentiment: str            # positive / neutral / negative


@dataclass
class IndustryBenchmark:
    """行业大盘（用于横向对比，判断客户是好是差）"""
    benchmark_id: str
    platform: str
    industry: str
    period: str
    avg_ctr: float
    avg_cvr: float
    avg_cpm: float
    benchmark_roi: float
    trend: str                # up / down / flat
    ad_type: str = ""         # 信息流 / 搜索（小红书分两条）


SCHEMA_MODELS = {
    "customer": CustomerProfile,
    "ad": AdPerformance,
    "content": ContentItem,
    "comms": CommunicationRecord,
    "benchmark": IndustryBenchmark,
}
# AdPilot — 互联网商业化销售 AI 工作台（作品集原型）

> 面向**互联网商业化广告销售（线索经营方向）**的 AI 工作台。灵感来自真实实习观察，但架构**完全通用**，不依赖任何单一公司或真实数据。
>
> **核心定位**：把优化师一周里最痛的 9 件事——**盯盘预警、每周复盘、待办跟进、badcase 归因、竞媒情报、行业对标、企微洞察、素材库**——收进一个工作台，数据驱动、可解释、不靠拍脑袋。
>
> **MVP 锚点（aipm-anchor）**：C — 每周投放复盘助手。AI 自动打通「平台投放数据 + 内容素材 + 企微沟通 + 行业大盘」，输出**一句话诊断 + 八段式完整复盘报告**（不是只有一句话）。

---

## 1. 为什么做（问题）

商业化（线索经营）团队的销售/优化师每天面对三处碎片化信息：
- **平台后台**：小红书聚光 / 抖音巨量 / 腾讯 / 快手，各家字段、口径、API 都不一样；
- **内容侧**：笔记 / 视频 / 图文，形式与元素各不相同；
- **客户沟通**：散落在企业微信里，客户抱怨/续费意向难以及时沉淀；
- **盯盘压力**：多账户、多计划，异常（掉量 / 超成本 / 预算花不完）往往隔天才发现。

于是销售/优化师每天 = 手动拉数 + 翻笔记 + 凭经验想策略 + 漏看异常。本工作台把这件事**自动化 + 智能化 + 预警化**。

## 2. 架构（最小公共 schema + adapter 归一化 + 规则引擎派生）

```
                 ┌─────────── 统一 schema（6 张基础表 + 3 张派生表）───────────┐
  平台原生数据 ──►│ CustomerProfile / AdPerformance / ContentItem /             │
  (字段各不相同)  │ CommunicationRecord / IndustryBenchmark / Demographics      │
                 │    ▼ load_derived 规则引擎 ▼                                │
                 │ AnomalyAlert（盯盘预警）/ Task（待办跟进）/ Badcase（归因库）│
                 └─────────────────────────────────────────────────────────────┘
     │  XHS 聚光           │  Douyin 巨量引擎      │  Tencent 广告      │  Kuaishou 磁力
     ▼                    ▼                      ▼                   ▼
 XhsAdAdapter ──►  fetch(customer_id, period) ──► 返回统一 AdPerformance
 DouyinAdAdapter  (把 exposure/click_num/... 翻译成 impressions/clicks/...)
 TencentAdAdapter / KuaishouAdAdapter (把中文键翻译成统一字段)
 WeComMessageAdapter (企业微信会话存档 API 的真实接入点，用 Mock 实现)
 IndustryDataAdapter (行业大盘基准)
```

**关键设计**：AI 分析层只认统一 schema，不感知平台。接新平台 = 新增一个 adapter，**AI 代码零改动**。派生表（预警/待办/badcase）由 `load_derived` 用**可解释规则**自动生成（对标小红书聚光「盯盘助手」、巨量「规则预警」），保证每一条都源自 DB 真实数字、可溯源。这正是「普适性 + 可解释」的工程底座。

## 3. 工作台九大模块

| # | 模块 | 解决什么痛点 | 关键产出 |
|---|------|-------------|---------|
| 🏠 | 工作台总览 | 一屏看全盘 | 核心指标卡 + 预警/待办/风险客户速览 |
| ② | 每周复盘（AI） | 手动拉数写周报 | 一句话诊断 + 八段式报告（漏斗/出价/人群/素材/话术/对标/行动） |
| ③ | 每日异常预警 | 异常隔天才发现 | 规则引擎即时预警：掉量/超成本/成本上升/预算花不完/负面/高潜 |
| ④ | 待办与跟进 | 行动项散落 | 由预警自动派发的 TODO，含负责人、优先级、DDL、关联根因 |
| ⑤ | Badcase 库 | 高成本/低质反复踩坑 | 高成本计划 + 低质素材归因，含根因与优化动作 |
| ⑥ | 竞争媒体情报 | 不知道客户还投了谁 | 各平台预算/CPL 占比与跨媒体对比 |
| ⑦ | 行业大盘对标 | 不知道自己算好算差 | 客户 CPL vs 行业基准（$\\times 1.2$ 超成本线 / $\\le$ 基准为优） |
| ⑧ | 企微沟通洞察 | 客户情绪难沉淀 | 会话情绪/意向/高频话题/风险信号 |
| ⑨ | 素材/内容库 | 好素材全靠记忆 | 笔记表现榜（爆文/CTA/互动），支撑素材赛马 |

**核心 AI 节点（每周复盘，aipm-chain L0–L8）**：输入 `customer_id + 周` → 拉取归一化数据 → 计算环比(WoW)与行业对标 → 生成：
- **一句话诊断**：结合客户生命周期阶段（at_risk / growing / stable）+ 真实环比数据（例：*「C001 处于风险阶段，本周消耗环比 -22.9%、CPL ¥XX（超基准 1.2×），叠加 2 条负面反馈，建议收缩低效计划并重测高意向人群」*）
- **八段式报告**：① 总览与结论 ② 私信转化漏斗（咨询→开口→留资→加微信）③ 出价与预算 ④ 人群与地域 ⑤ 笔记/素材 ⑥ 话术与承接 ⑦ 行业对标+竞争媒体 ⑧ 下一步行动

LLM 接口可配置：有 `OPENAI_API_KEY` 走真实模型；否则用 **MockLLM**——基于真实聚合数字生成报告，保证无 key 也能跑通 demo。

## 4. 运行方式

**A. 网页演示（推荐，最直观）**
```bash
cd adpilot/src
pip install streamlit openai      # 仅 UI + 真实 LLM 需要；核心逻辑仍零依赖
python3 main.py build             # 生成虚拟数据 + 建库（首次运行）
streamlit run app.py              # 打开 http://localhost:8501
```
左侧 9 个模块导航：总览 → 每周复盘（选客户+周，一键生成八段式报告）→ 每日异常预警 → 待办跟进 → Badcase 库 → 竞媒情报 → 行业对标 → 企微洞察 → 素材库。

**B. 命令行**
```bash
python3 main.py build          # 生成虚拟数据 + 建库（20 客户 / 4 平台 / 12 周 / 1044 条广告 + 9 张表）
python3 main.py review C001    # 对 C001 跑本周复盘
python3 main.py eval           # 全量自测：20/20 通过（结构完整 + 数字与 DB 一致）
```

**真实自然语言报告（可选）**：复制 `.env.example` 为 `.env` 并填入 `OPENAI_API_KEY`，重启 `streamlit run app.py` 即自动切换为真实 OpenAI 生成（仍基于 DB 真实数字，防幻觉）。不填则用 MockLLM（数据驱动模板），本机零联网也能演示。

核心逻辑依赖：**仅 Python 标准库**（dataclasses / sqlite3）。Streamlit / openai 仅用于演示界面与增强语言能力。

## 5. 数据说明（诚实声明，简历必写）

本项目为**求职作品集原型**，全部数据为**本地模拟生成**（固定 seed，可复现），用于演示架构与 AI 逻辑；企业微信/各广告平台接入在 **adapter 层真实实现（Mock 数据）**，生产环境替换为真实 API 即可。**未在简历中夸大真实业务指标。**

## 6. 文件结构

```
adpilot/
├── src/
│   ├── schema.py          # 9 张统一 schema（6 基础 + 3 派生）
│   ├── mock_data.py       # 虚拟数据集生成（平台原生字段形态 + 线索经营口径）
│   ├── adapters.py        # 5 个适配器：平台原生 -> 统一 schema
│   ├── db.py              # SQLite 存储 + 查询 + load_derived 规则引擎
│   ├── llm.py             # LLM 接口（真实 / Mock 回退）
│   ├── weekly_review.py   # 核心 AI 节点（诊断 + 八段式报告）
│   ├── workbench.py       # 9 大模块 render 函数
│   ├── eval_review.py     # 自测评估
│   ├── main.py            # 一键 build / review / eval
│   └── app.py             # Streamlit 路由（侧边栏 9 模块导航）
├── .env.example           # OPENAI_API_KEY 模板
└── data/adpilot.db
```

## 7. 仓库

GitHub：https://github.com/Averymeng/adpilot（公开，可作作品集展示）

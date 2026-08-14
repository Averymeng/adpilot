# AdPilot — 互联网商业化销售 AI 工作台（作品集原型）

> 面向**互联网商业化广告销售 / 优化师**的 AI 工作台。灵感来自真实实习观察，但架构**完全通用**，不依赖任何单一公司或真实数据。
>
> **MVP 锚点（aipm-anchor）**：C — 每周投放复盘助手。AI 自动打通「平台投放数据 + 内容素材 + 企微沟通 + 行业大盘」，输出**一句话诊断 + RACAE 五段式完整复盘报告**（不是只有一句话）。

---

## 1. 为什么做（问题）

商业化团队的销售/优化师每天面对三处碎片化信息：
- **平台后台**：小红书 / 抖音 / 腾讯 / 快手，各家字段、口径、API 都不一样；
- **内容侧**：笔记 / 视频 / 图文，形式与元素各不相同；
- **客户沟通**：散落在企业微信里，客户抱怨/续费意向难以及时沉淀。

于是「每周复盘」= 手动拉数 + 翻笔记 + 凭经验想策略，耗时且易漏。本工作台把这件事自动化、智能化。

## 2. 架构（B 方案：最小公共 schema + adapter 归一化）

```
                 ┌──────────────── 统一 schema（5 张表）────────────────┐
                 │ CustomerProfile / AdPerformance / ContentItem /      │
  平台原生数据 ──►│ CommunicationRecord / IndustryBenchmark              │
  (字段各不相同)  └─────────────────────────────────────────────────────┘
     │  XHS 广告 API         │  Douyin 巨量引擎      │  Tencent 广告      │  Kuaishou 磁力
     ▼                      ▼                      ▼                   ▼
 XhsAdAdapter ──►  fetch(customer_id, period) ──► 返回统一 AdPerformance
 TencentAdAdapter (把 exposure/click_num/... 翻译成 impressions/clicks/...)
 KuaishouAdAdapter (把「消耗/clk/周」中文键翻译成统一字段)
 WeComMessageAdapter (企业微信会话存档 API 的真实接入点，用 Mock 实现)
 IndustryDataAdapter (行业大盘基准)
```

**关键设计**：AI 分析层只认统一 schema，不感知平台。接新平台 = 新增一个 adapter，**AI 代码零改动**。这正是「普适性」的工程底座（业界同思路：字节跨端广告 JSON Schema、Hightouch Universal CAPI）。

## 3. 核心 AI 节点（每周复盘，aipm-chain L0–L8）

输入 `customer_id + 周` → 拉取归一化数据 → 计算环比(WoW)与行业对标 → 生成：
- **一句话诊断**：结合客户生命周期阶段 + 真实环比数据（例：*「C001 处于风险阶段，本周消耗环比 -22.9%、ROI 8.97，叠加 2 条负面反馈，建议收缩低效计划并重测高意向人群」*）
- **RACAE 五段**：① 总览与结论 ② 广告布局/漏斗分配 ③ 各层级成效(按周对比) ④ 广告组合成效(受众+素材双维度) ⑤ 下一步行动

LLM 接口可配置：有 `OPENAI_API_KEY` 走真实模型；否则用 **MockLLM**——基于真实聚合数字生成报告，保证无 key 也能跑通 demo。

## 4. 运行方式

```bash
cd adpilot/src
python3 main.py build     # 生成虚拟数据 + 建库（20 客户 / 4 平台 / 12 周 / 1911 条广告）
python3 main.py review C001   # 对 C001 跑本周复盘
python3 main.py eval      # 全量自测：20/20 通过（结构完整 + 数字与 DB 一致）
```

依赖：**仅 Python 标准库**（dataclasses / sqlite3），零第三方包，可移植运行。

## 5. 数据说明（诚实声明，简历必写）

本项目为**求职作品集原型**，全部数据为**本地模拟生成**（固定 seed，可复现），用于演示架构与 AI 逻辑；企业微信/各广告平台接入在 **adapter 层真实实现（Mock 数据）**，生产环境替换为真实 API 即可。**未在简历中夸大真实业务指标。**

## 6. 文件结构

```
adpilot/
├── src/
│   ├── schema.py          # 5 张统一 schema（dataclass）
│   ├── mock_data.py       # 虚拟数据集生成（平台原生字段形态）
│   ├── adapters.py        # 5 个适配器：平台原生 -> 统一 schema
│   ├── db.py              # SQLite 存储 + 查询
│   ├── llm.py             # LLM 接口（真实 / Mock 回退）
│   ├── weekly_review.py   # 核心 AI 节点（诊断 + RACAE）
│   ├── eval_review.py     # 自测评估
│   └── main.py            # 一键 build / review / eval
└── data/adpilot.db
```

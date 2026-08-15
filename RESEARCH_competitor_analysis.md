# 竞品与市场调研：销售易 NeoAgent 及同类「AI 销售/CRM 工作台」

> 用途：为 AdPilot（互联网商业化销售 AI 工作台）做竞品对标与借鉴梳理。
> 调研时间：2026-08-15。资料来源：销售易官网/腾讯云/赛迪/凤凰/首席数智官等公开报道 + GitHub 开源项目 + 小红书分享。

---

## 一、GitHub 及全网「同类工作台」盘点

### 1. 开源 / 类开源（GitHub 为主）
| 项目 | 地址 | 形态 | 与我们的关系 |
|---|---|---|---|
| **Cordys CRM** | https://github.com/1Panel-dev/CordysCRM | 开源 AI CRM（Java+Vue，L2C 全流程） | 飞致云出品，内置 **MCP Server + MaxKB + DataEase + 可接 WorkBuddy**。概念最接近"工作台"，且同处 WorkBuddy 生态。2.2k★ |
| **QRev** | https://github.com/qrev-ai/qrev | 围绕 agent 构建的开源销售平台（React+Node+Python） | 旗舰代理 Qai 做潜客调研、邮件序列、管道管理，AGPL-3.0 |
| **Salesforce Agentforce** | https://www.salesforce.com | 商业 #1 Agentic CRM | AgentExchange 生态、16+ 行业 agent、Slackbot 入口 |

### 2. 国内商业产品（其他平台/报道）
- **销售易 NeoAgent / NeoAgent 2.0**（腾讯旗下，重点，见第二节）
- **纷享销客 ShareHive AgentOS（蜂巢）** — https://www.fxiaoke.com/crm/blog-92556.html
  - 三层语义体系（通用/行业/企业个性化）+ 权限继承 + 三层记忆(Memory/Know-How)
  - 核心理念：**真原生（非外挂）**，Agent 继承 CRM 权限、进入流程、沉淀记忆
- **来鼓Pro / 米多客 / 实在智能** — 小红书/抖音**私信 AI 客服 + 留资工作台**
  - 与我们的「线索经营 / 留资 CPL」高度相关：咨询→识别意向→打标签→自动发卡→推送企微/CRM 形成线索秒级流转
  - 来鼓：https://laigu.com/blog/ ；米多客：https://miduoke.net/info/consultation/3550.html ；实在智能达人运营：https://www.ai-indeed.com/encyclopedia/20356.html
- **Coze / 影刀RPA 多 Agent 内容工作室**（小红书代运营）：选题/文案/数字人/发布/复盘 5 agent 组队 — https://www.toutiao.com/article/7663146502218383913/

---

## 二、销售易 NeoAgent 产品设计与搭建（含链接 / 文字 / 图片 / 视频说明）

### 2.1 定位与演进
- 2025-03 发布「中国首款 AI CRM」NeoAgent（6 大智能体）；2026-03 升级 **NeoAgent 2.0「智慧销售工作台」**；2026-04 发布「销售专用龙虾」。
- 核心命题：CRM 从 **"记录系统" → "执行系统"**；从"工具" → "数字员工"。
- 来源：https://www.xiaoshouyi.com/?p=95772 、https://www.xiaoshouyi.com?p=95800/

### 2.2 六大智能体（场景化 Agents）
营销 / 销售助理 / 销售经理 / 销售教练 / 分析师 / 客服。
- 销售助理：查资料、语音录入、自动写纪要/日报周报/邮件
- 销售经理：评估商机健康度、匹配赢单案例、给下一步行动
- 销售教练：基于销冠话术库的 AI 角色扮演陪练
- 分析师：自然语言查数、实时生成可视化视图、归因分析
- 来源：https://cloud.tencent.cn/developer/article/2679546

### 2.3 四层架构（拆解 NeoAgent 2.0）
1. **业务语义本体**（让 AI 懂业务）：统一沉淀业务数据/指标/关系/规则/动作，听懂自然语言并映射到业务实体；自动发现未定义术语提示补充（越用越聪明）
2. **Data for AI**（Customer Data Cloud，湖仓一体）：把结构化(订单/商机) + 非结构化(邮件/企微/录音) 统一加工成 AI 友好语义数据；流批一体、Schema Evolution
3. **Agent 平台（Neo Platform）**：Agent Builder / Prompt Builder / Agentic RAG；融合 aPaaS；MCP 接入第三方工具
4. **腾讯混元大模型**：turbo/large/standard-256k + 行业大模型 + DeepSeek；信任层(数据屏蔽/审计/毒性检测/私有化)
- 来源：https://www.ccidnet.com/cpfwyjs/1101219.jhtml 、https://www.xiaoshouyi.com/about-us/100566.html

### 2.4 交互范式（图片/界面说明）
- 首页「**目标驾驶舱**」：不同角色进入看到定制界面——最醒目位置是当前**业绩目标与实际差距**、**Agent 给出的下一步行动**、**待确认审批的流程**。前台是"目标驾驶舱"，底层连复杂业务系统。
- 「对话即操作」：用自然语言/语音替代表单点选；对话框内联动展示文档/报表/日程/会议/名片。
- 多智能体协同：销售问报价→教练 Agent 切身份陪练→问预测→分析师 Agent 出视图。
- 来源（含界面截图描述）：https://www.xiaoshouyi.com?p=99736/ 、https://xiaoshouyi.com/about-us/newnew/95755.html

### 2.5 双入口（视频/演示说明）
- **智慧销售工作台** = 大本营（复杂客户分析、商机推进）
- **销售专用龙虾** = 随身小助手（企微 + WorkBuddy）：企微作指令入口，WorkBuddy 解析串联流程，销售易 CRM 执行回写，构建"自动感知→智能判断→主动触达→自动执行→自动回写"闭环。
- 场景演示：每日 8 点推送客户情报；名片拍照→自动建线索；超期商机预警并回写 CRM。
- 来源：https://www.xiaoshouyi.com?p=99592/ 、https://www.xiaoshouyi.com/about-us/99504.html 、https://www.xiaoshouyi.com?p=99948/

### 2.6 客户成效数据（文字/视频案例）
- 米其林：拜访规划 0.5h→1min；100% 销售用 AI 推荐，75% 拜访直接采用 AI 内容
- 捷豹路虎：客服响应效率 +70%，技术转接 -60%
- 奇瑞(泰国)：线索重复率 20-25%→<5%，24h 跟进率 95%
- 易格斯：清洗 20 万条主数据做交叉销售；伊顿：客服准确率 95%，成本降 20-30%
- 来源：https://www.cio360.net/show-599-104401-1.html 、https://i.ifeng.com/c/8t9BQN8VeZn

### 2.7 商业模式
从"按坐席"转向"按结果"（Agent as a Service）。

### 2.8 关键链接汇总
- 产品发布：https://www.xiaoshouyi.com/?p=95772
- NeoAgent 2.0 重构逻辑：https://www.ccidnet.com/cpfwyjs/1101219.jhtml
- 智慧销售工作台：https://www.xiaoshouyi.com?p=99592/
- 销售专用龙虾：https://www.xiaoshouyi.com/about-us/99504.html
- 销售易+WorkBuddy：https://www.xiaoshouyi.com?p=99948/
- AI CRM 深度分析：https://i.ifeng.com/c/8t9BQN8VeZn
- 腾讯云开发者社区拆解：https://cloud.tencent.cn/developer/article/2679546
- 演示 demo 入口：https://www.xiaoshouyi.com/neoai

---

## 三、销售易产品设计分析（要点）

1. **三层技术支撑**：业务语义本体（听得懂业务）+ Data for AI（数据主动喂给 AI）+ 腾讯生态深度融合（企微/会议/电子签/WorkBuddy）。
2. **范式跃迁**：人找功能 → Agent 主动服务；表单录入 → 自然语言+Skill；记录系统 → 结果交付。
3. **Agentic CRM 三要素**（对比纷享销客同口径）：真原生（长在业务系统内，非外挂）、权限继承（不越权）、记忆/Know-How 沉淀（越用越懂企业）。
4. **可信优先**：审计日志、安全沙箱、私有化、数据不用于训练——企业级落地的"安全带"。
5. **从工具到数字员工**：Agent 不只建议，还在授权范围内执行动作、等待确认。

---

## 四、我们（AdPilot）vs 销售易：体系对比与可借鉴点

| 维度 | 销售易 NeoAgent 2.0 | 我们 AdPilot | 可借鉴 |
|---|---|---|---|
| 定位 | 企业级 AI CRM（营销服一体化） | 作品集原型：商业化销售周报/工作台 | 坚持"轻量可演示"差异化 |
| 架构 | 业务语义本体+Data Cloud+Agent平台+混元 | 最小公共 schema+adapter+规则引擎派生 | 补一层「业务语义层/ontology」 |
| 数据 | 全域多模态实时湖仓 | 9 张表（6 基础+3 派生），规则生成 | 已具备，可加实时流 |
| AI 交互 | 自然语言对话、目标驾驶舱、主动推送 | 点选导航 + 一键生成报告 | 加「对话式入口」(可用 WorkBuddy 连接器) |
| 主动执行 | Agent 自主执行+待确认闭环 | 预警/待办派发(未执行闭环) | 加"下一步行动→一键确认执行" |
| 多入口 | 工作台 + 龙虾(企微+WorkBuddy) | 仅网页 | 可补 WorkBuddy 龙虾式入口(销售易同源生态) |
| 可观测 | 智能体运营看板、全量日志 | 有 eval，缺运行期日志 | 加 agent 运行/效果评测看板 |
| 记忆 | 角色/会话/业务三层记忆+Know-How | 单次复盘，无跨周记忆 | 加经验库/跨周记忆 |
| 安全 | 权限继承/审计/沙箱/私有化 | 演示级 | 简化为"演示角色"即可 |
| 商业模式 | 按结果收费 | 作品集 | 把 CPL 改善做成可量化结果交付 |

**我们相对销售易的优势（作品集要强调）**：
- 全开源、零依赖、可一键复现；销售易闭源且需企业资质。
- **可解释性强**：每条诊断/预警/待办都源自 DB 真实数字 + 规则引擎，防幻觉；销售易的"语义本体"对用户是黑盒。
- 业务扎根深：真实线索经营口径（CPL/留资/加微/私信漏斗），非泛泛 BI。
- 9 模块覆盖"盯盘-复盘-归因-跟进"全链路。

**最值得借鉴的 5 点（按优先级）**：
1. **业务语义层**：建一个 domain ontology（客户/商机/阶段/CPL 口径/动作），让 AI 真"懂业务"——这是销售易与泛大模型最大的差异点，也是我们可升级的护城河。
2. **意图驱动入口 + WorkBuddy 连接器**：既然销售易都接了 WorkBuddy，我们更应把 AdPilot 做成 WorkBuddy 连接器（"一句口令出复盘/查风险"），技术叙事直接对齐头部。
3. **主动执行闭环**：预警/待办当前只"派发"，应加"建议→确认→回写"的轻量执行闭环。
4. **目标驾驶舱首页**：把"业绩目标差距 + 下一步行动 + 待确认"做成首页，比当前"总览指标卡"更贴近销售日常。
5. **可观测与版本管理**：加 agent 运行日志 + 报告/prompt 版本管理，体现工程成熟度。

---

## 五、xhslink 分享解读（https://xhslink.cn/o/1hiEFZB0KUz）

### 5.1 作者做了什么
一个 **B 端「AI Prompt 优化 Agent」**（元-agent）：
- 让「客服 AI」和「访客 AI」自动对跑，产生对话记录；
- 用**评估器**给客服 AI 的回复打分；
- 找出低分 case，分析"怎么改 prompt 能提分"；
- 用 **3 个子 agent** 协作：**诊断 agent**（识别低分原因）→ **编辑 agent**（优化 prompt）→ **回测 agent**（验证效果）；
- 带 system prompt **版本管理** + 全量**日志回溯**。

### 5.2 怎么搭的（工具链）
1. HuggingFace 找 dataset → 用 **codex** 下载到本地（含写提示词）；
2. 搭「客服 AI + 访客 AI」；
3. 自动对话脚本产生记录；
4. 评估器对客服 AI 输出评分（作者简化版）；
5. 低分 case 交给 诊断/编辑/回测 三 agent；
6. **codex** 搭可视化页面；
7. 接 API key（默认 GPT，建议改 **qwen3.5-plus / 百炼**，性价比高）；
8. 功能：创建对跑任务 → 评估 → 低分优化+人工审核 → prompt 版本管理 → 全日志。

> 核心方法论：**非纯前端 vibe coding**（接后端/数据库/API/workflow/system prompt），用 codex 辅助但自己判断合理性并调试迭代。

### 5.3 思想价值
- **评估-优化闭环（eval loop）**：不是"生成一次就完"，而是持续打分→诊断→改→回测。
- **多 agent 编排**：把复杂任务拆给多个专职 agent。
- **版本 + 日志**：所有改动可追溯。

---

## 六、对标我们项目：我们的缺点（来自该分享的启示）

1. **缺「评估-优化」闭环**：我们 MockLLM 生成周报后即结束，没有对报告质量做自动评估/回测/迭代。→ 应加一个 **evaluator**（如：诊断是否命中真实异常、行动建议是否可执行）并形成报告质量分。
2. **缺多 agent 编排**：我们是一个"周报生成"单点；对方用 诊断/编辑/回测 多 agent 协作。→ 我们可把"复盘→归因→行动建议→验证"拆成多 agent（如 诊断 agent / 话术 agent / 验证 agent）。
3. **缺系统化运行日志与版本管理**：对方强调"所有任务运行和操作记录写日志方便回溯"；我们有 eval 但缺运行期可观测 + prompt/报告版本。
4. **缺主动迭代机制**：我们的规则/阈值是写死的，没有"低分→自动调整"的进化能力。
5. **工具方法论启发**：对方用 codex 做"非纯前端"vibe coding 把原型产品化；我们也可借 **WorkBuddy/codex** 把 AdPilot 从 Streamlit 升级为更"产品化"的形态（如接连接器、加对话入口）。

**我们的相对优势（要守住并放大）**：
- 对方是"调 prompt 的元工具"，**业务理解浅**；我们扎根真实线索经营（CPL/留资/加微/漏斗/预算花完率），业务深度是作品集核心差异化。
- 我们的**规则引擎 + 真实数据派生**比"黑盒大模型调 prompt"更可解释、更可信，正契合销售易强调的"听得懂业务 + 可审计"。

---

## 七、行动建议（落到 AdPilot 下一步）
1. 加一层「业务语义层 / domain ontology」（短平快，强化"懂业务"叙事）。
2. 把 AdPilot 做成 **WorkBuddy 连接器**（一句口令出复盘/查风险），对齐销售易同源生态。
3. 报告生成后接 **evaluator + 版本管理 + 日志**（借鉴 xhslink 分享）。
4. 首页升级为「目标驾驶舱」样式（业绩差距 + 下一步行动 + 待确认）。
5. 预警/待办加「建议→确认→回写」轻量执行闭环。

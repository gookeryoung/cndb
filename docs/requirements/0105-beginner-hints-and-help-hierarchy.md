# 需求卡片：面向初级用户的界面提示易读性与帮助文档层级下沉

- 编号：0105（与 ADR `docs/adr/0105-beginner-hints-and-help-hierarchy.md` 同号）
- 来源 / 提出人：用户（2026-11-05）
- 日期：2026-11-05
- 关联 ADR：`docs/adr/0105-beginner-hints-and-help-hierarchy.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对初级使用者，完善界面提示内容的易读性，并完善帮助文档的完善和层级下沉，制定ADR。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 针对初级使用者 | 提示与帮助文案以「未读过文档的初级用户」为基准读者：短句白话、术语首次出现即就地解释、操作类提示含下一步动作；口径写成可对照检查的文案规范 | frontend 全局 | 文案规范落入 ADR §2，评审对照 |
| C2 | 完善界面提示内容的易读性 | 散落的 placeholder / Tooltip / 空态文案按统一口径改写，优先初级用户高频路径（登录注册、全局搜索、导入预览、数据同步、大模型配置）；技术参数类提示保留示例但补白话说明 | `frontend/src/pages/**`、`frontend/src/layouts/**`、`frontend/src/components/**` | 组件单测断言关键文案；e2e 校验帮助跳转 |
| C3 | 并完善帮助文档的完善 | 补全帮助文档对新功能的覆盖缺口：工作区模板（ADR 0094）、数据流程（ADR 0095/0097）、派生字段（ADR 0100）、数据推送（ADR 0099）在帮助内容中无落点，须按四级层级补齐 | `frontend/src/pages/help/content/**`、`helpNav.tsx` | helpNav 单测校验层级完整性；内容评审 |
| C4 | 和层级下沉 | 帮助文档导航层级下沉：侧栏在选中主题下就地展开其 L3 小节（当前仅 L1→L2 可导航，L3 只在页内目录可达），初学者进入页面前即可预览主题覆盖维度；不改变既有路由与锚点 | `frontend/src/pages/help/HelpDocsPage.tsx`、`helpNav.tsx` | HelpDocsPage 单测 + help-docs e2e |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | placeholder 文案约 260 处散落各组件，无统一文案层 | `frontend/src/**/*.tsx`（grep `placeholder=` 计 260） | 技术术语直出，如「updated_at / day；留空每次全量」 |
| 2 | 帮助文档四级模型已建（L1 部分 5 / L2 主题 22 / L3 小节 / L4 条目），侧栏只导航到 L2 | `frontend/src/pages/help/helpNav.tsx:73`、`HelpDocsPage.tsx:93` | L3 定义在懒加载的 content 模块内，元数据层不可见 |
| 3 | 新功能帮助缺口：模板 / 数据流程 / 派生字段 / 推送在 content 目录无匹配 | `frontend/src/pages/help/content/*.tsx` | grep「工作区模板 / 数据流程 / 派生字段 / 推送」零命中 |
| 4 | 新手引导底座已存在（OnboardingTour + onboarding store） | `frontend/src/components/onboarding/OnboardingTour.tsx`、`frontend/src/store/onboarding.ts` | 引导与帮助文档已有重放入口，本次不重建 |
| 5 | 权限不足提示已有独立口径（角色 + 联系指引） | `docs/adr/0047-permission-denied-message.md` | 易读性改写不得破坏 0047 口径 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 「层级下沉」的落点：理解为「侧栏导航下沉到 L3 小节（就地目录）+ 过长主题内容拆分下沉」，其余候选（新建第五层级、全量 L3 进侧栏）见 ADR 决策记录 D4 否决理由 —— **待需求方在 ADR 评审时确认**
- [x] 界面提示改写范围：按「初级高频路径优先」分期推进，不做一次性全量 260 处改写（P0 高频路径 + P1 剩余按域收尾）—— **待需求方在 ADR 评审时确认**
- [x] 是否引入 i18n / 文案常量层：否，系统单语（中文），不为此引入常量层重构（见 ADR D2）—— **待需求方在 ADR 评审时确认**

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（结论列于上表，均待 ADR 评审一并拍板）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

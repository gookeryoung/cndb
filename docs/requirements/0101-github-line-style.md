# 需求卡片：全主题 GitHub 式 1px 线条系统

- 编号：0101
- 来源 / 提出人：用户（会话 2026-11-05）
- 日期：2026-11-05
- 关联 ADR：无（S1，纯视觉 / token 调整；不改组件行为与数据）
- 关联硬约束：H25（`docs/CONSTRAINTS.md`）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 所有主题，边界线、按钮边框、搜索框等UI设计，线条风格按现代风格的线条风格来，类似GITHUB

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「所有主题」 | 10 套主题统一使用 1px 描边；默认线色统一为 GitHub 中性线（浅色 `#6e7781` / 深色 `#8b949e`），`--cn-border` 与 `--cn-border-soft` 同值；active / hover 才用品牌色 | `theme.ts`、`index.css`、主题预设 | 单测：所有主题 `colorBorder` / `colorBorderSecondary` / `colorSplit` 归一为统一中性线、`lineWidth=1` |
| C2 | 「边界线」 | 消除 `1.5px` 粗描边；卡片 / 列表 / 表格 / 方盒 / 分割线统一 1px 中性线 | `index.css` | 视觉人工确认 + `make check-fast` |
| C3 | 「按钮边框」 | 默认按钮 1px 次级线；hover 加深一级；primary 品牌色 1px；text / link 无框；按钮去掉静态投影 | `index.css`、antd Button token | 前端全量测试 + 视觉确认 |
| C4 | 「搜索框」 | 输入框 / 选择器 / 日期 / 数字 / 顶栏搜索统一 1px 次级线；聚焦只保留 1px 品牌色线 + 1px ring，不叠厚光晕 | `index.css` | 视觉确认 / 既有搜索测试通过 |
| C5 | （现代风格） | 静态卡片 / 表格 / 方盒不靠重投影表达层级；浮层（Modal / Drawer / Popover / Dropdown）保留轻投影但收细描边 | `index.css` | 视觉人工确认 |
| C6 | （工程口径） | 只改 token / CSS，不改组件结构、接口与数据；CHANGELOG / DESIGN_SYSTEM 同步；前端全量测试通过 | 文档 | `make check-fast` / `pnpm test` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 主题 antd token | `frontend/src/theme/theme.ts` | 归一 `colorBorder` / `colorSplit` / `lineWidth` |
| 2 | 全站手写边框 | `frontend/src/index.css` | `1.5px` → 1px；旧强描边 → 次级线 |
| 3 | 按钮 / 输入 / 选择 | `index.css` 全局 antd 覆盖 | 1px 中性线 + 品牌色聚焦 |
| 4 | 表格 / 卡片 / 浮层 | `index.css` | 细描边；浮层保留轻投影 |
| 5 | 设计文档 | `docs/DESIGN_SYSTEM.md` | 增加线条系统口径 |

## 未决问题（已确认）

- [x] ① 线条粗细：**结论**统一 1px；focus ring 亦为 1px（不做 3px 光晕）。
- [x] ② 默认线色：**结论**不再按主题色相派生，统一 GitHub 中性线（浅色 `#6e7781` / 深色 `#8b949e`），保证所有主题边界线一致且更清晰。
- [x] ③ 浮层是否去投影：**结论**保留轻投影，只收细描边；静态面不靠投影。
- [x] ④ 方案分级：**结论**S1（纯视觉 / token，无行为变更）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-05 用户口述）

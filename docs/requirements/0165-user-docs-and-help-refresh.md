# 0165 项目文档入口、帮助内容与普通用户指路更新（S1）

Status: 已确认（2026-11-26；方案已评审，按 P0→P2 实施）
Related: `README.md`、`CONTEXT.md`、`docs/USER_DOC_MAP.md`、`frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/content/*.tsx`、ADR 0029、ADR 0036、ADR 0105

## 需求原句

> 请针对项目文档和帮助文档更新，以及面向普通用户的改进建议给出方案。

## 用户确认选项（2026-11-26）

| 议题 | 结论 |
|---|---|
| 仓库用户文档载体 | 新建 `docs/USER_DOC_MAP.md`，只做「功能 → 帮助深链 → ADR/需求」映射，不复制帮助正文 |
| 帮助新增主题优先级 | 先做 `tutorials/teams-and-access` 与 `tutorials/workspace-links`，再做记录生命周期、表组织、文档文件等补全 |
| 是否进入实现 | 是；P0 文档纠偏 → P1 帮助内容 → P2 上下文指路；P3 交互改进逐项另立卡片/ADR |

## 约束（C1..C8）

| # | 约束 | 涉及模块 | 验收 |
|---|---|---|---|
| C1 | README 提供普通用户入口（应用内帮助 / 快速入门 / 示例工作区 / 部署文档），特性列表补齐 0130–0164 已落地能力 | `README.md` | 人工核对 + `make check-docs` |
| C2 | `docs/USER_DOC_MAP.md` 为唯一映射表；仓库文档不复制帮助正文，README 与 CONTEXT 各加一行入口 | `README.md`、`CONTEXT.md`、`docs/USER_DOC_MAP.md` | 人工核对 + `make check-docs` |
| C3 | 不触碰 WIP 文件：`docs/adr/README.md`、`docs/adr/0164-*.md`、`docs/requirements/0164-*.md` 及前端 WIP 文件 | 全仓 | `git status` 比对 |
| C4 | 新增帮助主题遵循 ADR 0036 四层模型：每 L2 ≥2 个 L3，不允许空层；L4 为单一实例；同一事实只在一处写全 | `helpNav.tsx`、`content/*.tsx` | `helpNav.test.tsx` 层级完整性 |
| C5 | 路由与锚点兼容：只新增主题/小节/条目 key，不改 `topicPath` / `subsectionAnchor` / `itemAnchor` 签名，存量深链有效 | `helpNav.tsx` | `HelpDocsPage.test.tsx` + e2e 深链 |
| C6 | 正文仍按 L1 section 懒加载，`helpNav.tsx` 只含元数据，不静态 import content；不拆 per-topic chunk | `helpNav.tsx`、`content/*.tsx` | 现有体积/懒加载门禁 |
| C7 | 导语按 ADR 0105 D7「本页你能学到什么 + 适合谁」；提示文案按 R1–R6；新增术语与 CONTEXT.md 一致 | `content/*.tsx`、目标组件 | 单测抽查 + 人工评审 |
| C8 | P2 指路复用 `helpLink` 指向新增 L3/L4 锚点，不引入帮助内搜索，不改权限判定与数据口径 | 目标页面组件 | 单测/e2e 跳转可达 |

## 现状影响面

| # | 现状 | 位置 | 备注 |
|---|---|---|---|
| 1 | README 纯开发视角，无用户文档入口；特性未含团队 / 工作区链接 / 行回收站 / 并发 / 导出模板 / 旋转 | `README.md:15-31, 208-286` | P0 修正 |
| 2 | CONTEXT.md 术语已更新到 0161，但面向维护者，普通用户不可达 | `CONTEXT.md:15-23, 115` | P0 加入口行 |
| 3 | 帮助文档 24 个 L2，内容更新停在 11/23–11/25；0130+ 新功能无落点 | `frontend/src/pages/help/helpNav.tsx:73-133`、`content/*.tsx` | P1 补齐 |
| 4 | 帮助页无站内搜索（0105 D4 明确不做），深链稳定 | `frontend/src/pages/help/HelpDocsPage.tsx:83-140` | P2 用上下文 `helpLink` 指路 |
| 5 | 工作区有未提交 WIP（0164 文档旋转、主页导航、团队授权等） | `git status` | C3 全程避开 |

## 不做

- 不新增后端接口、表、列、迁移或备份口径（沿用 ADR 0036 I5 / 0105 I1）。
- 不改 ADR 0012 全局搜索、0105 D4「帮助内不做跨主题搜索」的口径。
- P3 交互改进（权限归因按钮、危险操作确认、异步状态、空态引导等）不在本卡片落地，逐项另立 S1/S2 卡片。
- 不改 0153 / 0159 等 ADR 的 `Status`（需人工确认后单独处理）。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论（用户已确认三个选型点）
- [x] 门禁按 L2：`make check-fast` → `make test`；纯 `.md` 阶段用 `make check-docs`

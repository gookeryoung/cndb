# 需求卡片：前端迁移 React 19 + antd 6

- 编号：0074（与 ADR `docs/adr/0074-react19-antd6-upgrade.md` 同号）
- 来源 / 提出人：用户（2026-10-30 会话）
- 日期：2026-10-30
- 关联 ADR：`docs/adr/0074-react19-antd6-upgrade.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对项目迁移到REACT19+ANTD6，制定方案。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「迁移到 REACT19」 | `react` / `react-dom` 升级到 19，`@types/react` / `@types/react-dom` 同步升 19；React 18→19 破坏点（移除的 API、类型收紧）全部修复且不改业务语义 | `frontend/package.json`、`frontend/src/**` | `pnpm typecheck` / `pnpm test` / `make e2e` |
| C2 | 「迁移到 ANTD6」 | `antd@6` + `@ant-design/icons@6` + `@ant-design/cssinjs@2` 同批升级（icons@6 与 antd@5 不兼容，必须原子切换）；不引入 `@ant-design/v5-patch-for-react-19` 过渡包 | `frontend/package.json` | 依赖树检查 + 全量门禁 |
| C3 | 「制定方案」 | S2 重大项：先出 ADR 并人工评审，`Proposed` → `Accepted` 后才进入实现；分期落地、每期回填落地状态 | `docs/adr/0074-*.md` | `make adr-check` |
| C4 | （隐含，与卡片 0026 的关系） | 浏览器基线口径必须明确：Chrome 81 基线保留或变更，由人拍板；`check-browser-compat.mjs`、`.browserslistrc`、`chrome81-smoke.mjs`、README 基线声明同步收口 | `frontend/scripts/`、`frontend/.browserslistrc`、`README.md` | 静态门禁退出码 + Chromium 81 冒烟 |
| C5 | （隐含，不回归） | 现有功能与视觉不回归：前端单测、前端覆盖率双门槛、Playwright e2e 全绿；10 套主题视觉一致；关键 chunk 不超 bundle budget（超限走既有流程记录理由） | `frontend/src/**`、`frontend/tests/**` | `pnpm test:coverage`、`make e2e`、`pnpm bundle:budget` |
| C6 | （隐含，存量资产处置） | 兼容层与补丁的去留有结论：`rc-field-form` / `rc-util` 两个 pnpm patch、`StyleProvider` 降级链、flex-gap shim、`themeMix` 兜底，逐项给出沿用 / 迁移 / 删除结论 | `frontend/patches/`、`frontend/src/compat/`、`frontend/src/theme/` | ADR 决策记录逐项落点 |
| C7 | 「迁移到 ANTD6」 | antd v6 弃用 API（将在 v7 移除）在仓库内清零：升级后控制台无 legacy 弃用告警，存量命中点全部改用新 API | `frontend/src/**/*.tsx` | 控制台告警断言（e2e）+ 源码扫描 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | React 18.3.1 + @types 18 | `frontend/package.json:59-60,77-78` | 已用 `createRoot`；React 18 遗留 API（`findDOMNode` / `ReactDOM.render` / `test-utils` / 函数组件 `defaultProps`）全仓 0 命中 |
| 2 | antd 5.29.3 + icons 5.6.1 + cssinjs 1.24 直接依赖 | `frontend/package.json:33-35,50` | antd 6 要求 icons >= 6 且 icons@6 与 antd@5 不兼容 |
| 3 | antd v6 弃用 API 存量 | `frontend/src/pages/**`（约 16 处） | `destroyOnClose`×2、`size="middle"`×8、`tabPosition`×1、`maskClosable`×1、`Tag bordered`×3 |
| 4 | 250 处 `.ant-*` 自定义覆盖 | `frontend/src/index.css` | antd 6 调整大量组件 DOM 结构，覆盖选择器可能失配 |
| 5 | pnpm patch 指向旧包名 | `frontend/patches/rc-field-form@2.7.1.patch`、`frontend/patches/rc-util.patch` | antd 6 依赖已迁移到 `@rc-component/*`，补丁目标消失 |
| 6 | Chrome 81 兼容层 | `frontend/src/compat/`、`frontend/src/theme/themeMix.ts`、`frontend/scripts/check-browser-compat.mjs` | 与 ADR 0026 的基线承诺冲突与否待决策 |
| 7 | 主题体系 | `frontend/src/theme/ThemeProvider.tsx:161-194` | 已开 `cssVar: true`，与 antd 6 默认 CSS variables 同向；`StyleProvider` 降级链需适配 cssinjs v2 |
| 8 | 测试链路 | `frontend/src/**/*.test.tsx` | `@testing-library/react` 16.3.3 已兼容 React 19；React 19 类型收紧可能引发 TS 报错 |

## 未决问题

- [ ] 浏览器基线：Chrome 81 基线（卡片 0026「重大需求」）保留还是提升到现代浏览器？ADR 0074 D1 给出推荐结论（保留并扩展降级白名单），**须人工拍板**后 ADR 方可转 `Accepted`。
- [x] 升级路径：一步到位（同批升 React 19 + antd 6），不分两次全量回归（2026-10-30 ADR D2）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认（浏览器基线一项待人工拍板）

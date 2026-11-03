# 需求卡片：bundle 预算门禁可持续化（帮助正文拆分 + 预算语义改造）

- 编号：0090
- 来源 / 提出人：用户（CI 中 bundle-budget 反复超限）
- 日期：2026-11-03
- 关联 ADR：无（S1，方案并入本卡片）

## 需求原句（逐字）

> CICD，bundle-budget经常超，能否一劳永逸解决此问题避免每次重构后出现。

## 可实施约束（C1..Cn）

| # | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|
| C1 | 帮助正文与页面壳拆分：`helpNav.tsx` 只保留纯元数据（key / label / icon）与工具函数，不再静态 import 5 个 content 模块；正文按 L1 section 经动态 `import()` 懒加载，每个 section 独立 chunk | `frontend/src/pages/help/` | `pnpm build` 后 `dist/assets` 出现 5 个 section chunk，`HelpDocsPage` chunk 体积显著下降 |
| C2 | 拆分后帮助页行为不回归：默认落点、深链、回落纠正、页内目录、锚点滚动、窄屏抽屉、引导重放均保持 | `frontend/src/pages/help/` | `HelpDocsPage.test.tsx` / `helpNav.test.tsx` 全绿；`help-docs.spec.ts` e2e 通过 |
| C3 | 预算语义改造：`bundle-budget.json` 每 chunk 新增可选 `budget`（gzip 字节硬上限），校验判据 `actual > budget` 才 FAIL；`baseline` 只作 warn 参照与偏差展示，不再兼任上限 | `frontend/scripts/bundle-budget.mjs` | 脚本输出含基线与上限两值；超出 baseline 未超 budget 时仅 warn |
| C4 | `--update` 行为收窄：只刷新 `baseline`（及 reason/updatedAt/commit），不得改动 `budget`；上限调整走显式 `--set-budget`（须 `--only` + `--reason`，理由落盘并进 history） | `frontend/scripts/bundle-budget.mjs` | 手工验证：`--update` 后 JSON 中 `budget` 字段不变 |
| C5 | 全部既有 chunk 与新增 help section chunk 都有 `budget`：主入口留紧余量（约 3%），按需 chunk 留 15–25% | `frontend/scripts/bundle-budget.json` | `pnpm build && pnpm bundle:budget` 全绿，且无「0.07 KiB 超限」级别的脆弱判定 |
| C6 | 文档同步：`docs/BUNDLE_BUDGET.md` 更新基线 / 上限双语义与 `--set-budget` 用法；CHANGELOG 增条目 | `docs/` | 文档与脚本行为一致 |
| C7 | 不放宽防膨胀意图：静态引入重型依赖（echarts / jspdf 等）进任何受控 chunk 仍会 FAIL；「慢涨」仍产生 warn | `frontend/scripts/bundle-budget.mjs` | 归因输出与 warn 汇总保留 |

## 未决问题

- 无（粒度取 P0：按 section 拆分；单 section chunk 触达 budget 时再升级按 topic 拆）。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论，需求方确认（用户已确认方案 A）

# 需求卡片 0016：认证页 JS 动态背景（Perlin 流场粒子 · 青紫渐变 · 深色底）

- 编号：0016（与 ADR `docs/adr/0016-*.md` 同号）
- 来源 / 提出人：用户口述需求（2026-10-21 两次变更）
- 日期：2026-10-21
- 关联 ADR：[0016](../adr/0016-auth-background-animation.md)
- Status：Accepted（需求方 2026-10-21 确认最终方案）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 登录背景动图，在白色底色下科技感不足，请考虑是否改为黑色。动画种类太多，请移除多余项，仅保留一个数论动画方案。

> 改回之前的数字雨方案。

> 动图改为采取Perlin 流场粒子 + 青紫渐变方案。

> 三条按时间顺序记录，第三条为最终口径（前两条均被其覆盖）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「仅保留一个…方案」+「Perlin 流场粒子」 | 删除星座 / 星云 / 极光 / 数字雨 / 光点 5 个旧变体，只保留一个动效：固定种子 Perlin 噪声方向场驱动粒子漂移，每颗粒子保留一段环形尾迹（桌面 40 / 移动 26 个历史点）并每帧连成流线；粒子数桌面 800 / 移动 320 | `frontend/src/components/auth-background/flowfield.ts` | `flowfield.test.ts` + 视觉走查 |
| C2 | 「请考虑是否改为黑色」 | 认证页页面底色固定近黑（`--cn-auth-bg`）；登录卡片继续跟随 10 套主题，不强制深色卡片 | `frontend/src/index.css`、`frontend/src/layouts/AuthLayout.tsx` | `AuthLayout.test.tsx`、login / register e2e；视觉走查 |
| C3 | 「科技感」+「青紫渐变」 | 深色舞台 + 青紫渐变流线（`--cn-auth-accent` 青 → `--cn-auth-accent-alt` 紫 → 青）+ 页面双色径向光晕；不引入第三方动画库 | `frontend/src/index.css`、`frontend/src/components/auth-background/palette.ts`、`frontend/src/components/auth-background/flowfield.ts` | `flowfield.test.ts` 渐变色标断言 + 视觉走查 |
| C4 | 「移除多余项」 | 删除右下角切换器、`localStorage['cndb_auth_bg']` 偏好与变体元数据；`AuthLayout` 不再持有变体状态 | `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/components/auth-background/` | 单测断言无切换器；login / register e2e 不回归 |
| C5 | 性能与资源（仓库既有约定） | 单 rAF；桌面 DPR ≤ 2，移动端 DPR ≤ 1.5 且 30fps；`document.hidden` 暂停；resize 150ms 节流；桌面指针轻微扰动流场，移动端关闭 | `frontend/src/components/auth-background/engine.ts` | `engine.test.ts` |
| C6 | 可访问性（仓库既有约定） | `prefers-reduced-motion: reduce` 只画一次预热流线静帧；画布 / 容器 `aria-hidden`；背景层 `pointer-events: none` | `frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/index.css` | 单测 + login / register e2e |
| C7 | 降级（仓库既有约定） | `getContext('2d')` 为空或 auth token（bg / ink / accent / accent-alt）缺失时保留 `.auth-shell` 固定深色 CSS 背景，不抛错、不白屏 | `frontend/src/components/auth-background/engine.ts` | `engine.test.ts` |
| C8 | 体积与测试（仓库既有约定） | 背景仍走 lazy chunk，不进入主入口；gzip ≤ 8 KiB；单测覆盖动效 / 引擎 / 色板 / 组件 / 布局；login / register e2e 不回归 | `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/components/auth-background/*.test.ts(x)`、`frontend/tests/e2e/smoke/` | `pnpm build` + `bundle:budget`、`pnpm test`、e2e |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 认证页 5 个背景变体 + 右下角切换器 | `frontend/src/components/auth-background/`、`frontend/src/layouts/AuthLayout.tsx` | 本次删除全部旧变体与切换器，收敛为单一 Perlin 流场动效 |
| 2 | 旧数字雨实现 | `frontend/src/components/auth-background/variants/rain.ts`（已删除） | 用户先要求「改回数字雨」，随后改为 Perlin 流场粒子；不恢复旧实现 |
| 3 | 认证页浅色 CSS 氛围背景 | `frontend/src/index.css` | 改为固定深色舞台 + 青紫双色光晕 + `--cn-auth-*` token |
| 4 | 10 套主题体系 | `frontend/src/theme/meta.ts`、`frontend/src/theme/ThemeProvider.tsx` | 页面背景不再跟主题；卡片仍跟主题 |
| 5 | 认证页单测 / e2e | `frontend/src/layouts/AuthLayout.test.tsx`、`frontend/tests/e2e/smoke/{login,register}.spec.ts` | 同步移除切换器断言并补 `data-effect="flowfield"` |
| 6 | 首屏体积基线 | `frontend/scripts/bundle-budget.json` | 背景 chunk 变小；主入口去掉偏好 / 切换器 |

## 已确认问题

- [x] Q1 动画形态：「数论动画」先定为模乘万花筒（2026-10-21），同日被「Perlin 流场粒子」取代，旧 5 变体全部删除（→ C1）
- [x] Q2 黑色范围：仅页面背景固定近黑，登录卡片继续跟随主题（→ C2）
- [x] Q3 配色：青紫渐变，固定 token 不跟随主题品牌色（→ C3）
- [x] Q4 切换与持久化：单一方案后不再需要切换器与 `cndb_auth_bg`（→ C4）
- [x] Q5 覆盖范围：`/login` + `/register` 共用 `AuthLayout`，同步生效（→ C2）
- [x] Q6 「改回数字雨」：同日被「Perlin 流场粒子 + 青紫渐变」覆盖，以最新口径为准（→ C1 / C3）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-21）

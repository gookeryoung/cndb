# 需求卡片 0016：认证页静态晶格背景（JS 一次生成，固定深色舞台，青紫配色）

- 编号：0016（与 ADR `docs/adr/0016-auth-background-animation.md` 同号）
- 来源 / 提出人：用户口述需求（2026-10-21 首次提出；2026-11-07 改为静态晶格）
- 日期：2026-11-07
- 关联 ADR：[0016](../adr/0016-auth-background-animation.md)
- Status：Accepted（需求方 2026-11-07 确认替换方案）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 登陆页的流畅粒子和宇宙星辰，更换为固定的晶格背景图（js生成）是否性能更好，且适配chrome81

> 好的，按这个方案更新 ADR 0016 并实现静态晶格版本

> 第一条为本次变更诉求：把流场粒子与宇宙星系替换为 JS 生成的固定晶格背景，并确认性能与 Chrome 81 兼容性；第二条为需求方确认按该方案落地。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「更换为固定的晶格背景图（js生成）」 | 认证页背景改为静态六边形晶格：JS 在挂载时绘制一次后常驻，不启动 rAF、不随指针 / 时间变化；每 3 行 / 3 列交点放一颗青紫交替结点 | `frontend/src/components/auth-background/lattice.ts`、`engine.ts` | `lattice.test.ts`、`engine.test.ts` + 视觉走查 |
| C2 | 「是否性能更好」 | 静态绘制只在挂载与 resize 时各发生一次：resize 150ms 节流重绘；桌面 DPR ≤ 2、移动端 ≤ 1.5；移除 rAF / visibilitychange / pointermove 等持续开销 | `frontend/src/components/auth-background/engine.ts` | `engine.test.ts`（断言不调用 rAF、不随指针重绘） |
| C3 | 「适配chrome81」 | 只用 Chrome 81 已支持的 Canvas 2D 基础 API（`clearRect` / `beginPath` / `moveTo` / `lineTo` / `arc` / `fill` / `stroke` / `setTransform`）；不使用 `roundRect` / `ctx.reset()` / `structuredClone` 等新 API；构建基线仍为 chrome81 | `frontend/src/components/auth-background/lattice.ts`、`frontend/scripts/browser-baseline.mjs` | `pnpm build` 的 `check-browser-compat --strict` + `pnpm e2e:chrome81` |
| C4 | 替换旧背景 | 删除 `flowfield` / `galaxy` 两个动效、右下角切换器、`preference.ts` 与 `localStorage['cndb_auth_bg']`；认证页不再有背景切换入口 | `frontend/src/components/auth-background/` | 删除对应单测；login / register e2e 断言无切换器 |
| C5 | 视觉口径不变 | 保留固定近黑舞台与青紫 `--cn-auth-*` token：晶格线用 ink 低透明度，结点用 accent / accent-alt；登录卡片继续跟随 10 套主题 | `frontend/src/index.css`、`palette.ts` | `palette.test.ts`、`AuthLayout.test.tsx` + 视觉走查 |
| C6 | 可访问性与降级 | 背景层 `aria-hidden` + `pointer-events: none`；`getContext('2d')` 为空或 auth token 缺失时保留 `.auth-shell` 固定深色 CSS 背景；静态背景天然满足 `prefers-reduced-motion` | `AuthBackground.tsx`、`engine.ts`、`index.css` | `AuthBackground.test.tsx`、`engine.test.ts`、e2e |
| C7 | 体积与测试 | 晶格与引擎同属背景 lazy chunk，不进入主入口；chunk 继续满足 `bundle-budget` 上限；单测覆盖晶格绘制 / 引擎 / 组件 / 布局，e2e 覆盖背景可见且不拦截表单 | `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/components/auth-background/*.test.ts(x)`、`frontend/tests/e2e/smoke/` | `pnpm build` + `bundle:budget`、`pnpm test`、e2e |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 流场粒子 / 宇宙星系双动效 | `frontend/src/components/auth-background/` | 整体删除，替换为单一静态晶格 |
| 2 | 右下角效果切换器 | `AuthBackgroundSwitcher.tsx`、`index.css` | 删除按钮、定位与 `[data-effect]` 样式 |
| 3 | 本地效果偏好 | `preference.ts` | 删除 `cndb_auth_bg` 读写，旧值不再读取 |
| 4 | 背景引擎生命周期 | `engine.ts` | 从单 rAF 循环改为一次绘制 + resize 重绘 |
| 5 | 认证页单测 / e2e | `frontend/src/components/auth-background/`、`frontend/tests/e2e/smoke/{login,register}.spec.ts` | 移除 `data-effect` / 切换 / 刷新保持断言 |
| 6 | 固定舞台 token 与 `--cn-mix-*` 注册表 | `frontend/src/index.css`、`frontend/src/theme/themeMix.ts` | 仅删除切换器专用的混色 token |

## 已确认问题

- [x] Q1 背景形态：改为 JS 生成、固定不动的晶格背景（→ C1）
- [x] Q2 性能口径：去掉持续 rAF，只在挂载 / resize 时绘制（→ C2）
- [x] Q3 兼容口径：Chrome 81 基线不变，只用基础 Canvas 2D API（→ C3）
- [x] Q4 旧动效去留：流场粒子、宇宙星系、切换器与偏好全部移除（→ C4）
- [x] Q5 视觉与可访问性：保留近黑舞台 + 青紫配色与 `aria-hidden` / `pointer-events:none`（→ C5 / C6）
- [x] Q6 覆盖范围：`/login` + `/register` 共用 `AuthLayout`，同步生效（→ C2）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-07）

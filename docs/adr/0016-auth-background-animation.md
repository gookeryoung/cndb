# ADR 0016: 认证页静态晶格背景（JS 一次生成，固定深色舞台，青紫渐变）

Status: Implemented
Date: 2026-10-21（2026-11-07 由「流场粒子 / 宇宙星系双动效」改为静态晶格）
Related: `frontend/src/components/auth-background/lattice.ts`、`frontend/src/components/auth-background/engine.ts`、`frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/layouts/AuthLayout.tsx`、`frontend/src/index.css`、`frontend/scripts/bundle-budget.json`
需求卡片: `docs/requirements/0016-auth-background-animation.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「更换为固定的晶格背景图（js生成）」 | 新增 `lattice.ts`：尖顶六边形铺满画布，奇数行横向错开半个步长；每 3 行 / 3 列交点放一颗结点，青（accent）紫（accent-alt）按行列奇偶交替。挂载时绘制一次，之后不随时间 / 指针变化（D1） |
| C2 | 「是否性能更好」 | 引擎只做一次静态绘制；删掉 rAF、`visibilitychange`、`pointermove`；仅保留 resize 150ms 节流后的重绘。桌面 DPR ≤ 2、移动端 ≤ 1.5（D2） |
| C3 | 「适配chrome81」 | 绘制只用 `clearRect` / `beginPath` / `moveTo` / `lineTo` / `closePath` / `stroke` / `arc` / `fill` / `setTransform` 等 Chrome 81 已支持的 Canvas 2D API；不引入 `roundRect`、`ctx.reset()`、`structuredClone` 等新 API；构建基线仍为 chrome81（D5） |
| C4 | 替换旧背景 | 删除 `flowfield.ts`、`galaxy.ts`、`AuthBackgroundSwitcher.tsx`、`preference.ts` 及其单测；`AuthBackground` 不再有 `data-effect`、切换器与 `localStorage['cndb_auth_bg']`（D3） |
| C5 | 视觉口径不变 | `.auth-shell` 仍为近黑舞台 + 双色径向光晕 + 低透明度 CSS 网格；画布晶格线用 `--cn-auth-ink`（alpha 0.085），结点用 `--cn-auth-accent` / `--cn-auth-accent-alt`（alpha 0.34）；登录卡片继续跟随 10 套主题（D4 / D7） |
| C6 | 可访问性与降级 | 背景层 `aria-hidden` + `pointer-events: none`；`getContext('2d')` 为空或 auth token 缺失时返回 noop，保留 `.auth-shell` 固定深色 CSS 背景；静态背景无动画，天然满足 `prefers-reduced-motion`（D6） |
| C7 | 体积与测试 | `AuthBackground` 继续 `lazy` 引入，晶格 / 引擎 / 色板同属背景 chunk；单测覆盖晶格绘制、引擎、组件与布局；login / register e2e 断言画布可见、`aria-hidden`、`pointer-events:none` 且无切换器（D6） |

决策结论只在「决策记录」写一次。

## Context

变更前现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 认证页背景为 `flowfield` 与 `galaxy` 两种动效 | `frontend/src/components/auth-background/flowfield.ts`、`galaxy.ts` | 桌面流场约 800 粒子 × 40 点尾迹、星系 1600 星点，每帧持续重绘 | 本次要替换的对象 |
| 2 | 引擎持有一个持续 rAF 循环 | `engine.ts` | 登录页停留期间持续占用 CPU / GPU 与电量，低端机掉帧 | 性能诉求的直接原因 |
| 3 | 右下角切换器 + 本地偏好 | `AuthBackgroundSwitcher.tsx`、`preference.ts` | 两种效果与持久化在静态方案下没有意义 | 需要随旧动效一起移除 |
| 4 | 背景层已 `aria-hidden` + `pointer-events:none` | `AuthBackground.tsx`、`index.css` | 可访问性契约可原样保留 | 约束新方案 |
| 5 | 固定舞台 token `--cn-auth-*` 与卡片主题解耦 | `frontend/src/index.css`、`theme/meta.ts` | 晶格可以继续复用同一套颜色 | 约束配色 |
| 6 | `AuthLayout` 被 `App.tsx` 静态 import，背景必须 lazy | `frontend/src/App.tsx` | 防止晶格代码进入主入口 | 约束体积 |
| 7 | 浏览器基线 Chromium 81，构建由 esbuild 降级 | `frontend/scripts/browser-baseline.mjs`、`vite.config.ts` | 新绘制代码必须落在基线 API 内 | 约束兼容性 |

**核心缺陷（需求要补的）**：背景是持续动画，登录页空闲时仍不断重绘；需求方要求换成由 JS 一次生成、之后静止的晶格背景图。

设计目标（不变量）：

- **I1 不干扰**：背景层 `aria-hidden` + `pointer-events: none`，不新增任何可聚焦元素，不改变表单焦点顺序。
- **I2 无持续循环**：任一时刻都不存在 rAF 或定时器驱动的重绘；只有挂载与 resize 节流后的各一次静态绘制。
- **I3 颜色单源**：画布颜色只来自 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink`，不在 JS 写死色值。
- **I4 静态优先**：`prefers-reduced-motion` 与普通模式看到同一张静帧；没有需要降级的动画。
- **I5 优雅降级**：无 Canvas / auth token 缺失 / 0 尺寸时保持固定深色 CSS 背景，不抛错、不白屏。
- **I6 体积与兼容隔离**：晶格模块留在背景 lazy chunk；绘制只用 Chrome 81 基线 API。

## Decision

### 1. 数据模型

无后端模型。前端只有 3 个纯数据概念：

| 概念 | 形态 | 说明 |
|---|---|---|
| `Palette` | `{ accent, accentAlt, ink }` | 固定舞台 token 的运行期快照 |
| `LatticeFrame` | `{ ctx, width, height, dpr, palette, isMobile }` | 一次静态绘制所需的上下文；`width/height` 为设备像素 |
| 尺寸常量 | `latticeCell(isMobile)` | 六边形外接圆半径：桌面 46px / 移动端 34px |

晶格不保存跨帧状态，也不使用全局单例；每次绘制都由 `drawLattice(frame)` 从头生成。

### 2. 判定算法（唯一入口）

```ts
// mountAuthBackground(canvas, { isMobile }): () => void
```

生命周期（唯一入口）：

1. `canvas.getContext('2d')` 为空 → 返回 `noop`（I5）。
2. `readPalette()` 读取 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink`；失败 → 返回 `noop`，CSS 背景兜底（I5）。
3. `layout()`：按 `getBoundingClientRect()` 取得 CSS 尺寸，`dpr = min(devicePixelRatio, isMobile ? 1.5 : 2)`；设置 `canvas.width/height` 后 `clearRect` 并调用 `drawLattice`。
4. 0 尺寸 → 跳过绘制，等待下一次 resize。
5. 监听 `resize`（passive），150ms 节流后重跑 `layout()`。
6. dispose：清定时器、移除 resize 监听，可重复调用（I2）。

绘制算法（`drawLattice`）：

1. 尖顶六边形：宽 `√3·s`、高 `2s`；行距 `1.5s`，奇数行横向错开 `√3·s/2`。
2. 覆盖范围为画布外加一行一列，边缘六边形自然被裁切。
3. 六边形线宽 `max(1, dpr × 0.75)`，颜色 `withAlpha(ink, 0.085)`，整批 `beginPath` 后一次 `stroke`。
4. 每 3 行 / 3 列交点取一颗结点，半径 `1.7 × dpr`；按 `(row + col) % 2` 分青 / 紫两组，各批量设置一次 `fillStyle` 后 `arc + fill`。

### 3. API 变更清单

无。不新增 / 修改任何后端端点；删除 `localStorage['cndb_auth_bg']` 的读写（旧值不再读取，也不做迁移）。

### 4. 边界与例外

1. **深色范围**：仅 `.auth-shell` 页面背景固定近黑；登录卡片仍由 antd token / 主题决定（D4）。
2. **主题切换**：晶格颜色来自固定 auth token，主题切换不重绘；主题只影响卡片。
3. **颜色解析**：auth token 为 `#rgb` / `#rrggbb` / `rgb()`；`withAlpha` 统一转 `rgba()`。
4. **叠加方式**：黑底与页面光晕由 CSS 提供；画布保持透明，只画低透明度晶格线与结点。
5. **移动端**：晶格更密（34px），DPR 封顶 1.5；无指针 / 视差。
6. **窗口极小 / 0 尺寸**：不绘制，等待下一次 resize；不抛异常。
7. **首帧闪烁**：背景 chunk 未就绪时显示固定深色 CSS 背景，加载完成后 canvas 淡入（≤ 240ms，reduced-motion 无过渡）。
8. **旧偏好**：`cndb_auth_bg` 不再读取；历史值保留在用户本地存储中，不做清理。
9. **Chrome 81**：不使用 `CanvasRenderingContext2D.roundRect`、`ctx.reset()`、`structuredClone`、`Array.prototype.at` 等基线外 API；CSS 侧沿用现有 `check-browser-compat` 门禁。固定深色舞台的 `color-mix()` 声明含 `var()`，Chrome 81 会把整个 `background` 计算为 `none`（页面变白、浅色晶格不可见），因此 `.auth-shell` / `::before` 的现代写法已移入 `@supports`（ADR 0026 边界 9）；`reportWebVitals` 在缺少 `visibility-state` / `event` 条目的内核上跳过 CLS / INP，避免 `Deprecated API for given entry type` 控制台噪音。

### 5. 迁移

无（不涉及数据库、备份格式或存量数据）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 组件入口 | `frontend/src/components/auth-background/AuthBackground.tsx` | 去掉效果状态与切换器；只渲染 `aria-hidden` 背景层 + canvas；按 `isMobile` 挂载引擎 |
| 类型 | `frontend/src/components/auth-background/types.ts` | 保留 `Palette`；`FrameContext` / `BackgroundVariant` 改为 `LatticeFrame` |
| 晶格 | `frontend/src/components/auth-background/lattice.ts` | 新增：六边形晶格与青紫结点的静态绘制 |
| 引擎 | `frontend/src/components/auth-background/engine.ts` | 改为一次绘制 + resize 节流重绘；移除 rAF / visibility / pointer |
| 色板 | `frontend/src/components/auth-background/palette.ts` | 逻辑不变，仅更新注释引用 |
| 删除 | `flowfield.ts`、`galaxy.ts`、`AuthBackgroundSwitcher.tsx`、`preference.ts` 及对应测试 | 动效、切换器与本地偏好整体移除 |
| 布局 | `frontend/src/layouts/AuthLayout.tsx` | 无结构变化：仍 `lazy` 引入 `AuthBackground` |
| 样式 | `frontend/src/index.css` | 删除 `.auth-bg-switch*`、`[data-effect]` 与移动端切换器规则；更新背景层注释 |
| 混色注册表 | `frontend/src/theme/themeMix.ts` | 删除仅切换器使用的 `auth-*` 混色条目 |

### 7. 测试清单

**判定层（单测）**

- `lattice.test.ts`：六边形数量与 `moveTo`/`lineTo` 比例正确；线宽与结点半径随 DPR 放大；坐标有限且在边缘裁切范围内；0 尺寸不绘制；同参数两次绘制完全一致；移动端晶格更密；颜色来自色板 token。
- `engine.test.ts`：挂载只绘制一次且不调用 `requestAnimationFrame`；无 context / token 缺失返回 noop；桌面 DPR 封顶 2、移动端封顶 1.5；resize 150ms 节流后重绘一次；dispose 后不再重绘且可重复调用；0 尺寸跳过绘制。
- `palette.test.ts`：三个 auth token 正常读取、任一缺失返回 `null`；`withAlpha` 覆盖 hex / rgb / 非法值。

**组件层（单测）**

- `AuthBackground.test.tsx`：背景层 `aria-hidden`；渲染 canvas 且无切换器 / `data-effect`；挂载时把 canvas 与 `{ isMobile }` 交给引擎；卸载调用 dispose。
- `AuthLayout.test.tsx`：children 仍渲染；背景层懒加载后存在且 `aria-hidden`；无切换器。

**e2e（前端）**

- `frontend/tests/e2e/smoke/login.spec.ts`、`smoke/register.spec.ts`：认证页背景 canvas 可见、`aria-hidden`、`pointer-events: none`，无切换器，且不拦截表单点击。

**体积与兼容**

- `pnpm build` 后 `bundle:budget` 通过；背景 chunk gzip 不超过既有上限。
- `check-browser-compat --strict` 通过；`pnpm e2e:chrome81` 冒烟可用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 静态晶格绘制 + 引擎简化为一次绘制 + 组件 / CSS 接入 + 单测 | 低 |
| **P1** | 删除双动效 / 切换器 / 偏好，更新 e2e、体积与兼容收尾 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 背景形态 | JS 生成的固定六边形晶格，挂载时绘制一次后常驻 | 满足「固定晶格背景图」诉求；一次绘制即可稳定呈现 | 继续流场粒子 / 星系动画（持续占用）；纯 CSS 网格（已有 `.auth-shell::before`，缺乏结点层次）；图片资源（增加请求与主题耦合） | `lattice.ts` |
| D2 | 生命周期 | 删除 rAF、visibilitychange、pointermove；仅 resize 150ms 节流重绘 | 静态图不需要逐帧循环，空闲时零持续开销是本方案的主要收益 | 保留低频 rAF 做微动（仍有功耗且违背「固定」）；用 CSS 动画平移晶格（同样持续合成） | `engine.ts` |
| D3 | 旧动效与偏好 | 删除 `flowfield` / `galaxy` / 切换器 / `preference.ts` / `cndb_auth_bg` | 静态方案只有一种背景，切换与持久化没有语义 | 保留切换器作为「静态 / 动画」开关（需求方明确替换） | `AuthBackground.tsx`、`index.css` |
| D4 | 深色范围 | 仅页面背景固定近黑；登录卡片继续跟随 10 套主题 | 沿用既有已确认口径，改动面最小 | 整页强制深色卡片（与主题体系冲突） | `index.css`、`AuthLayout.tsx` |
| D5 | 兼容口径 | 只用 Chrome 81 基线 Canvas 2D API；不新增 polyfill | 现有构建 / 静态门禁与老内核冒烟均以 chrome81 为基线 | 使用 `roundRect` / `ctx.reset()` 等新 API（81 不支持）；引入图形库（超体积预算） | `lattice.ts`、`browser-baseline.mjs` |
| D6 | 体积与可访问性 | 晶格 / 引擎 / 色板留在背景 lazy chunk；背景层 `aria-hidden` + `pointer-events:none`，不新增可聚焦元素 | 不抬主入口体积；静态背景不干扰表单 | 静态图直接内联到主入口（破坏隔离）；把背景做成可交互（无必要） | `AuthBackground.tsx`、`AuthLayout.tsx` |
| D7 | 配色与纹理 | 晶格线用 ink（alpha 0.085），结点用 accent / accent-alt（alpha 0.34），青紫交替 | 延续「科技感 + 青紫渐变」品牌语言，对比度稳定 | 纯单色晶格（层次不足）；跟随主题品牌色（部分主题在近黑底上偏暗） | `palette.ts`、`index.css` |
| D8 | 降级策略 | 无 Canvas / token 缺失 / 0 尺寸时不挂画布，保留 `.auth-shell` 固定深色 CSS 背景 | 登录页永不因背景失败 | 失败时报错或白屏 | `engine.ts` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：登录页背景从持续 rAF 改为一次绘制，空闲期不再占用 CPU / GPU；删除两套动效、切换器与偏好后代码与测试面显著收缩；Chrome 81 兼容风险低于原动画方案。
- **负向**：背景失去动态氛围，视觉效果固定；用户不再能切换背景；旧的 `cndb_auth_bg` 本地值成为无主数据（不做清理）。
- **风险与缓解**：晶格在超宽屏铺满 → 一次绘制的六边形数量随面积增长，但只在挂载 / resize 时发生；高 DPR 内存 → DPR 封顶 2 / 1.5；token 解析失败 → CSS 背景兜底；懒加载失败 → Suspense `null` + 固定深色背景。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/components/auth-background/lattice.ts`、`frontend/src/components/auth-background/types.ts`、`frontend/src/components/auth-background/engine.ts`、`frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/index.css` | `frontend/src/components/auth-background/lattice.test.ts`、`frontend/src/components/auth-background/engine.test.ts`、`frontend/src/components/auth-background/AuthBackground.test.tsx`、`frontend/src/layouts/AuthLayout.test.tsx` | 29f52579 |
| P1 | 已落地 | `frontend/src/components/auth-background/`（删除双动效 / 切换器 / 偏好）、`frontend/src/theme/themeMix.ts` | `frontend/tests/e2e/smoke/login.spec.ts`、`frontend/tests/e2e/smoke/register.spec.ts` | 29f52579 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P1 已落地并提交（29f52579）；Chrome 81 兼容修复已完成并通过前端门禁，已提交（5ee4ac80）
- 已完成：新增 `lattice.ts` 一次性绘制六边形晶格与青紫结点；`engine.ts` 去掉 rAF / 可见性 / 指针监听，只保留 resize 150ms 节流重绘；`AuthBackground` 去掉效果状态、切换器与本地偏好；删除 `flowfield` / `galaxy` / `AuthBackgroundSwitcher` / `preference` 及对应单测；同步更新 CSS、混色注册表、e2e 与需求卡片 / ADR / CHANGELOG。Chrome 81 修复：`.auth-shell` / `::before` 的 `color-mix` 现代写法移入 `@supports`（否则深色舞台变白、晶格不可见）；`reportWebVitals` 按条目能力跳过 CLS / INP，并在 `polyfills.ts` 对缺失的 `visibility-state` 条目短路 `getEntriesByType`（web-vitals 的 FCP / LCP 也会查询它），消除 `Deprecated API for given entry type`；`check-browser-compat.mjs` 统计兜底时跳过 `@supports (... color-mix ...)` 块
- 下一步：无（Chrome 81 修复已随 `5ee4ac80` 提交）
- 已知坑：`AuthLayout` 被 `App.tsx` 静态引入，背景必须保持 lazy；jsdom 无 `getContext`，单测需 mock；晶格尺寸按设备像素计算，DPR 已封顶；`cndb_auth_bg` 旧偏好不再读取；e2e 登录按钮定位必须保持 `/^登\s*录$/` 首尾锚定；Chrome 81 下含 `var()` 的 `color-mix()` 声明会让整个属性变初始值，认证页已用 `@supports` 隔离，新增 auth 样式时不要再用「前兜底 + 后 color-mix」双层写法；静态门禁对 `@supports (... color-mix ...)` 块内的 `color-mix` 不计兜底缺口，因此现代写法必须放进该块而不是裸写
- 最近一次全绿：2026-11-07 `pnpm check` / `pnpm test`（3119 例）/ `pnpm test:coverage` / `pnpm build`（含 `check-browser-compat --strict`）/ `pnpm bundle:budget` / `make flow`（check-fast + pytest 6704 例）；Chromium 737027 实测登录页无控制台报错、`.auth-shell` 为深色舞台、晶格 canvas 有像素输出

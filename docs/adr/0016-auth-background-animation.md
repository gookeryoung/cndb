# ADR 0016: 认证页 JS 动态背景（Perlin 流场粒子，青紫渐变，固定深色舞台）

Status: Implemented（2026-10-21 评审通过；同日按新需求改为 Perlin 流场粒子 + 青紫渐变）
Date: 2026-10-21
Related: `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/components/auth-background/`、`frontend/src/index.css`、`frontend/src/theme/meta.ts`、`frontend/scripts/bundle-budget.json`
需求卡片: `docs/requirements/0016-auth-background-animation.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 仅保留一个动画方案 + Perlin 流场粒子 | 唯一动效 `flowfield`：固定种子 Perlin 噪声方向场驱动粒子漂移，每颗粒子的环形尾迹连成流线；删除全部 5 个旧变体（D2） |
| C2 | 白色底色科技感不足，考虑改为黑色 | `.auth-shell` 页面底色固定近黑 `--cn-auth-bg`；登录卡片继续跟随 10 套主题，不强制深色卡片（D11） |
| C3 | 科技感 + 青紫渐变 | 深色舞台 + 青紫渐变流线（`--cn-auth-accent` 青 → `--cn-auth-accent-alt` 紫 → 青）+ 页面双色径向光晕；零新增依赖（D7 / D12） |
| C4 | 移除多余项 | 删除右下角切换器、`localStorage['cndb_auth_bg']`、变体元数据与偏好模块；`AuthLayout` 无变体状态（D3） |
| C5 | 性能与资源 | 单 rAF；桌面 DPR ≤ 2，移动端 DPR ≤ 1.5 且 30fps；`document.hidden` 暂停；resize 150ms 节流；桌面指针轻微扰动流场（D6） |
| C6 | 可访问性 | `prefers-reduced-motion: reduce` 只画一次预热流线静帧、不启动 rAF；画布与容器 `aria-hidden`；背景层 `pointer-events: none`（D5 / D8） |
| C7 | 降级 | `getContext('2d')` 为空或 auth token（accent / accent-alt / ink）缺失时不挂载画布，保留 `.auth-shell` 固定深色 CSS 背景（D9） |
| C8 | 体积与测试 | 背景走 lazy chunk，不进入主入口；背景 chunk gzip ≤ 8 KiB，不抬 `bundle-budget.json` 基线；单测 + login / register e2e 不回归（D10） |

决策结论只在「决策记录」写一次。

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 原实现有 5 个背景变体（星座 / 星云 / 极光 / 数字雨 / 光点）+ 右下角切换器 + localStorage 偏好 | `frontend/src/components/auth-background/`、`frontend/src/layouts/AuthLayout.tsx` | 方案过多、视觉语言被稀释；单方案后切换器与偏好成为无效复杂度 | 需求变更的直接原因 |
| 2 | `.auth-shell` 背景由 `--cn-bg-page` + 主题品牌色双径向光晕派生 | `frontend/src/index.css` | 浅色主题下整体偏白，科技感不足 | 改为固定深色舞台 |
| 3 | 10 套主题通过 `body.theme-*` 与 `--cn-*` 变量切换；`useTheme()` 暴露 `mode` / `isDark` | `frontend/src/theme/meta.ts`、`frontend/src/theme/ThemeProvider.tsx` | 页面底色不再跟主题；卡片仍需跟主题，不能全局改暗 | 约束深色范围（D11） |
| 4 | `AuthLayout` 被 `App.tsx` 静态 import，页面级才是 lazy | `frontend/src/App.tsx` | 背景实现必须继续走独立 lazy chunk | 约束体积（D10） |
| 5 | jsdom 未实现 `HTMLCanvasElement#getContext` | `frontend/src/test/setup.ts` | 单测需显式 mock canvas | 约束测试 |
| 6 | 主入口体积基线 175.22 KiB（gzip） | `frontend/scripts/bundle-budget.json` | 删除偏好 / 切换器后主入口应更小 | 约束体积 |

**核心缺陷（需求要补的）**：原方案在浅色底上科技感不足，且 5 个变体让视觉语言发散；单一 Perlin 流场粒子 + 青紫渐变 + 固定深色舞台才能稳定表达“科技感”。

设计目标（不变量）：

- **I1 不干扰**：背景层 `aria-hidden` + `pointer-events: none`，不改变 Tab 顺序、不遮挡卡片交互。
- **I2 单循环**：任一时刻至多一个 rAF；StrictMode 双挂载、resize、可见性切换都不产生双循环。
- **I3 颜色单源**：画布颜色只来自 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink`（固定舞台 token），不在 JS 写色值。
- **I4 静态优先**：`prefers-reduced-motion: reduce` 下无持续 rAF，只出现一次预热流线静帧。
- **I5 优雅降级**：无 Canvas / auth token 缺失 / 0 尺寸时保持固定深色 CSS 背景，不抛错、不白屏。
- **I6 体积隔离**：引擎与流场不进入主入口 chunk。
- **I7 卸载干净**：dispose 幂等，移除 resize / visibility / pointer 监听与定时器。
- **I8 单一动效**：只保留 `flowfield`，无切换器、无本地偏好、无变体元数据。

## Decision

### 1. 数据模型

无后端模型。前端只有 3 个纯数据概念：

| 概念 | 形态 | 说明 |
|---|---|---|
| `Palette` | `{ accent, accentAlt, ink }` | 固定舞台 token 的运行期快照；accent = 青紫渐变两端（青），accentAlt = 中段（紫），ink = 中性网格 / 卡片描边 |
| `FrameContext` | `{ ctx, width, height, palette, isMobile, pointer }` | 单帧绘制上下文 |
| `BackgroundVariant` | `resize` + `frame` | 唯一实现 `createFlowField`；没有变体 ID / 元数据 / 本地存储键 |

绘制状态（粒子数组、渐变缓存）只存在于动效实例内部，组件卸载即丢弃；Perlin 置换表是模块级固定种子常量（只读）；不使用全局单例。

### 2. 判定算法（唯一入口）

```ts
// mountAuthBackground(canvas, options): () => void
type MountOptions = {
  isMobile: boolean
  reducedMotion: boolean
}
```

生命周期（唯一入口）：

1. `canvas.getContext('2d')` 为空 → 返回 `noop`（I5）。
2. `readPalette()` 读取 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink`；失败 → 返回 `noop`，CSS 背景兜底（I5）。
3. 按 `clientWidth/Height × dpr` 设置位图尺寸，`ctx.setTransform(dpr, 0, 0, dpr, 0, 0)`；0 尺寸时跳过绘制等待 resize。
4. `reducedMotion` 为真 → 绘制一帧 `frame(ctx, 0)` 后不启动 rAF（I4）。
5. 否则启动唯一 rAF 循环；移动端以 `1000 / 30` 为最小帧间隔跳帧。
6. `visibilitychange`：隐藏时 `cancelAnimationFrame`，恢复且非 reduced 时重启（I2）。
7. `resize`：150ms 节流后重新测量并调用 `variant.resize`。
8. 桌面非 reduced：`pointermove`（passive）更新归一化指针，流场方向叠加 ≤ 0.36 rad 偏转（x 0.24 + y 0.12）。
9. dispose：取消 rAF、移除全部监听、清空定时器，可重复调用（I7）。

动效接口：

```ts
interface BackgroundVariant {
  resize(c: FrameContext): void
  frame(c: FrameContext, timeMs: number): void
}
```

### 3. API 变更清单

无。不新增 / 修改任何后端端点，不写用户偏好表；`localStorage['cndb_auth_bg']` 不再读写。

### 4. 边界与例外

1. **深色范围**：仅 `.auth-shell` 页面背景固定近黑；登录卡片仍由 antd token / 主题决定，浅色主题下就是白卡片浮在黑底上（D11）。
2. **主题切换**：画布颜色来自固定 auth token，主题切换不再重建引擎；主题只影响卡片。
3. **颜色解析**：auth token 为 `#rgb` / `#rrggbb` / `rgb()`；`withAlpha` 统一转 `rgba()`，不可解析时原样返回（渐变仍可建）。
4. **叠加方式**：黑底由 CSS 提供；画布保持透明，流线用 `lighter` 合成让交叉处自然增亮，绘制结束还原 `source-over`；每帧先 `clearRect`，尾迹由每颗粒子的环形缓冲提供，不依赖画布残影（只画单帧位移会因 0.x px 线段几乎不可见）。
5. **移动端**：DPR 1.5、目标 30fps、粒子 320（桌面 800）、尾迹 26 点（桌面 40）、关闭指针扰动；粒子密度仍覆盖全屏，卡片四周均有流线。
6. **窗口极小 / 0 尺寸**：不绘制，等待下一次 resize；不抛异常。
7. **首帧闪烁**：背景 chunk 未就绪时显示固定深色 CSS 背景，加载完成后 canvas 淡入（≤ 240ms，reduced-motion 无过渡）。
8. **旧偏好**：历史 `cndb_auth_bg` 键忽略，不做迁移或清理。

### 5. 迁移

无（不涉及数据库、备份格式或存量数据）；旧 localStorage 键不读不写。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 组件入口 | `frontend/src/components/auth-background/AuthBackground.tsx` | 无 props；读 `useResponsive` + reduced-motion；`aria-hidden`；`data-effect="flowfield"` |
| 类型 | `frontend/src/components/auth-background/types.ts` | `Palette { accent, accentAlt, ink }` / `FrameContext` / `BackgroundVariant` |
| 色板 | `frontend/src/components/auth-background/palette.ts` | 读 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink` + `withAlpha` |
| 引擎 | `frontend/src/components/auth-background/engine.ts` | `mountAuthBackground`：DPR、rAF、可见性、resize、指针扰动、dispose |
| 动效 | `frontend/src/components/auth-background/flowfield.ts` | Perlin 流场粒子：固定种子噪声、粒子漂移、预热静帧、青紫渐变描边 |
| 布局 | `frontend/src/layouts/AuthLayout.tsx` | `lazy` 引入 `AuthBackground`；背景层 + 内容层 z-index；无切换器 |
| 样式 | `frontend/src/index.css` | `--cn-auth-*` 固定舞台 token（含 accent-alt 紫）；`.auth-shell` 黑底 + 青紫双色光晕 + ink 网格；删除 `.auth-bg-switch*` |
| 删除 | `frontend/src/components/auth-background/variants/`、`AuthBackgroundSwitcher.tsx`、`preference.ts` | 旧 5 变体与偏好清理 |

### 7. 测试清单

**判定层（单测）**

- `flowfield.test.ts`：resize 后 frame 有一次流线描边、坐标有限；每颗粒子输出多段 `lineTo`（尾迹折线，`lineTo ≥ moveTo × 10`，守住「单帧亚像素线段不可见」的回归）；0 尺寸不绘制；移动端可绘制；首帧预热后每帧只描边一次；青紫渐变三个色标；固定种子下两次实例流线一致；噪声在 -1..1 且确定。
- `palette.test.ts`：三个 auth token 正常读取、任一缺失返回 `null`、空字符串视为失败；`withAlpha` 覆盖 hex / rgb / 非法值。
- `engine.test.ts`：无 canvas context 返回 noop；token 缺失返回 noop；reduced-motion 不调用 rAF；可见性隐藏暂停 / 恢复重启；resize 节流；dispose 幂等；移动端 30fps 跳帧。

**组件层（单测）**

- `AuthBackground.test.tsx`：canvas 存在且 `aria-hidden`；`data-effect="flowfield"`；卸载后引擎 dispose。
- `AuthLayout.test.tsx`：children 仍渲染；背景层存在；420px 容器不变；无切换器。

**e2e（前端）**

- `frontend/tests/e2e/smoke/login.spec.ts`、`smoke/register.spec.ts`：认证页背景 canvas 可见、`aria-hidden`、`pointer-events: none`、`data-effect="flowfield"`，且不拦截表单点击。

**体积**

- `pnpm build` 后 `bundle:budget` 通过；背景 chunk gzip ≤ 8 KiB。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 引擎 + Perlin 流场粒子 + `AuthLayout` 接入 + 删除旧 5 变体 / 切换器 / 偏好 + 单测 | 低 |
| **P1** | 固定深色舞台 + 青紫 auth token + 移动端 / reduced-motion 调优 + 体积与 e2e 收尾 + 文档回填 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 动效实现选型 | 原生 Canvas 2D + rAF，无第三方库 | 体积可控、可读固定舞台 token、Perlin 流场用 2D noise 可表达 | CSS keyframes（无法做逐帧噪声驱动的粒子尾迹）；three.js（~150KB gzip，超 C8）；GIF / 视频（体积大、无法随卡片主题共存） | `components/auth-background/engine.ts` |
| D2 | 唯一动效 | Perlin 流场粒子：固定种子 improved Perlin 2D 方向场驱动粒子漂移，每颗粒子维护环形尾迹（桌面 40 / 移动 26 个历史点）并每帧连成流线；粒子数桌面 800 / 移动 320，速度 0.06 px/ms × 0.55..1.45；首帧预热「尾迹点数 + 8」步（×8ms）灌满缓冲 | 需求方确认最终方案；流线贴合“科技感”；每帧一次批处理描边（桌面 800 条折线 / 60fps，移动 320 / 30fps）；整段尾迹描边才可见（单帧位移仅 0.x px） | 保留旧 5 变体（视觉稀释）；数字雨（用户同日放弃）；模乘万花筒（上一版，被本次需求覆盖） | `flowfield.ts` |
| D3 | 切换与持久化 | 删除切换器与 `localStorage['cndb_auth_bg']`；单一方案无需选择 | 减少主入口代码与交互噪音；无非法值回落分支 | 保留切换器（单方案下无意义）；后端用户偏好（更重） | `AuthLayout.tsx` |
| D4 | 覆盖范围 | 仅 `/login`、`/register` | 两页共用 `AuthLayout`，改动面最小 | 覆盖 `/public`（公开页样式与权限语境不同） | `AuthLayout.tsx` |
| D5 | 减少动态偏好 | `prefers-reduced-motion: reduce` 只画一次预热流线静帧 | 与现有 CSS 约定一致 | 直接隐藏背景（丢失氛围且主题色块突兀） | `AuthBackground.tsx` |
| D6 | 移动端与交互档位 | 移动端 DPR 1.5 / 30fps / 320 粒子 / 26 点尾迹 / 无视口扰动；桌面 800 粒子 / 40 点尾迹 + 指针偏转 ≤ 0.36 rad | 移动端 GPU 与电池成本高；关闭指针扰动避免触屏滑动改变流场 | 全端同档（耗电）；移动端保留指针扰动（无鼠标语义） | `flowfield.ts`、`engine.ts` |
| D7 | 颜色来源与叠加 | 运行期读固定 `--cn-auth-*`；青紫渐变 = accent 青 → accent-alt 紫 → accent，`createLinearGradient` 三色标；黑底 + `lighter` 流线发光 | 黑底对比度稳定；与浅色主题品牌色解耦；渐变由画布坐标决定，无需逐粒子算色 | 跟随 `--cn-brand-color`（minimal / sepia 品牌色在黑底上偏暗）；在 JS 硬编码 10 套色板（维护成本） | `palette.ts`、`flowfield.ts`、`index.css` |
| D8 | 可访问性 | 背景层 `aria-hidden` + `pointer-events:none`；无新增可聚焦元素 | 不干扰表单焦点与读屏 | 画布可聚焦 / 可点击（会抢走表单操作） | `AuthBackground.tsx` |
| D9 | 降级策略 | 保留 `.auth-shell` 固定深色 CSS 背景作为兜底，失败即不挂画布 | 现有视觉已可用，避免白屏 | 移除 CSS 背景（失败时白屏） | `index.css`、`AuthBackground.tsx` |
| D10 | 体积边界 | `AuthBackground` 用 `lazy(() => import())` 独立 chunk，背景 gzip ≤ 8 KiB，主入口基线不抬 | `AuthLayout` 静态进主入口（`App.tsx`），必须切断静态链；删除偏好 / 切换器后主入口更小 | 静态 import（撑大主入口）；把 `AuthLayout` 整体改 lazy（改动扩散到路由骨架） | `AuthLayout.tsx`、`bundle-budget.json` |
| D11 | 深色范围 | 仅页面背景固定近黑；登录卡片继续跟随 10 套主题 | 需求方确认；改动面最小；卡片可读性由主题保证 | 整页强制深色卡片（改动大、与主题体系冲突） | `index.css`、`AuthLayout.tsx` |
| D12 | 配色 token | accent `#22d3ee`（青）、accent-alt `#a855f7`（紫）、ink `#dbe4f3`、底色 `#05070c` | 需求方确认青紫渐变；黑底对比度高；浅色主题品牌色不作画布色 | 跟随主题品牌色（部分主题在黑底上偏暗）；纯单色（层次不足） | `index.css` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：认证页获得单一、可解释的流场动效；固定黑底 + 青紫渐变让科技感稳定；删除切换器 / 偏好后代码更小、交互更干净。
- **负向**：认证页页面底色不再随 10 套主题变化；固定青紫与卡片主题品牌色可能不同色相（已由需求方确认接受）。
- **风险与缓解**：低端设备掉帧 → 粒子数 800 / 320 + 移动端 30fps；首帧预热耗时 → 预热只推进粒子灌满缓冲，首帧与后续帧共用同一次整批描边；token 解析失败 → CSS 背景兜底；懒加载失败 → Suspense `null` + 固定深色背景。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/components/auth-background/flowfield.ts`、`frontend/src/components/auth-background/engine.ts`、`frontend/src/components/auth-background/types.ts`、`frontend/src/components/auth-background/palette.ts`、`frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/layouts/AuthLayout.tsx` | `frontend/src/components/auth-background/flowfield.test.ts`、`frontend/src/components/auth-background/engine.test.ts`、`frontend/src/components/auth-background/palette.test.ts`、`frontend/src/components/auth-background/AuthBackground.test.tsx`、`frontend/src/layouts/AuthLayout.test.tsx` | 待提交 |
| P1 | 已落地 | `frontend/src/index.css` | `frontend/tests/e2e/smoke/login.spec.ts`、`frontend/tests/e2e/smoke/register.spec.ts` | 待提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P1 已落地（代码 / 测试 / 文档就绪，待用户确认提交后回填提交列 sha）
- 已完成：单一 Perlin 流场粒子、青紫渐变 token 与双色光晕、删除 5 个旧变体 / 切换器 / `cndb_auth_bg` 偏好、单测与 e2e 断言同步；每颗粒子改用环形尾迹整段描边（修复「画了但几乎不可见」：单帧位移仅 0.x px），实测画布 alpha>0 像素占比 3.85%
- 下一步：无（本 ADR 范围内交付完毕）；如需视觉微调，改 `flowfield.ts` 的粒子数 / `FIELD_SCALE` / 速度 / 预热步数，或调 `--cn-auth-*` token
- 已知坑：`AuthLayout` 被 `App.tsx` 静态引入，背景必须 lazy 才能守住主入口体积；jsdom 无 `getContext`，单测需 mock；首帧预热是「粒子数 × (尾迹点数 + 8)」次粒子推进后一次性描边（桌面 800 × 40 段），上调粒子数或尾迹长度需同步评估首帧耗时；Perlin 置换表必须保持固定种子（去掉后单测的确定性断言会失败）
- 最近一次全绿：`make check-fast` + `make test`（5136 passed / 8 skipped）+ `pnpm test`（152 文件 / 1927 用例）+ `pnpm build` + `bundle:budget`（主入口 175.50 KiB ≤ 183.98；背景 chunk gzip 2.72 KiB ≤ 8 KiB）+ e2e smoke login/register（9 passed / 1 skipped）@ 2026-10-21

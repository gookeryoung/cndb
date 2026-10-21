# ADR 0014: 认证页 JS 动态背景（5 组风格，可切换）

Status: Accepted（2026-10-21 评审通过）
Date: 2026-10-21
Related: `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/App.tsx`、`frontend/src/theme/ThemeProvider.tsx`、`frontend/src/theme/meta.ts`、`frontend/src/index.css`、`frontend/scripts/bundle-budget.json`
需求卡片: `docs/requirements/0014-auth-background-animation.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 5 组可独立挂载的背景变体 | 固定变体集合 `constellation / nebula / aurora / rain / orbs`，每个变体实现 `BackgroundVariant`（`resize` + `frame`），由同一 `mountAuthBackground` 引擎驱动；模块级无可变状态（D1 / D2） |
| C2 | JS 驱动的动图 | Canvas 2D + `requestAnimationFrame`；零新增依赖；每帧一次 `clearRect` + 变体绘制（D1） |
| C3 | 星座等 5 种风格 | 星座连线（默认）、星云漩涡、极光流光、数字雨、光点流体；参数与几何形态按变体分文件，互不共享状态（D2） |
| C4 | 用作登录界面背景 | `AuthLayout` 内新增背景层与切换器；仅 `/login`、`/register` 复用；卡片保持 420px 居中并置顶（D4） |
| C5 | 主题一致性 | 取色走 `getComputedStyle(document.body)` 的 `--cn-brand-color` / `--cn-bg-page` / `--cn-text-primary`；`useTheme().mode` 变化时重建效果；`isDark` 决定叠加模式（D7） |
| C6 | 性能与资源 | 单 rAF；桌面 DPR ≤ 2，移动端 DPR ≤ 1.5 且 30fps；`document.hidden` 暂停；resize 150ms 节流；粒子数按面积与设备降档；桌面鼠标视差（D6） |
| C7 | 可访问性 | `prefers-reduced-motion: reduce` 只画静态首帧、不启动 rAF；画布与容器 `aria-hidden`；背景层 `pointer-events: none`（D5 / D8） |
| C8 | 降级 | `getContext('2d')` 为空或取色失败时直接不挂载画布，保留 `.auth-shell` 既有 CSS 渐变；切换器仍可用（D9） |
| C9 | 切换与持久化 | 右下角循环切换按钮；`localStorage['cndb_auth_bg']` 单键持久化；非法值回落 `constellation`；不新增后端接口（D3） |
| C10 | 体积边界 | `AuthBackground` 由 `AuthLayout` 动态 `import()` 成独立 chunk；主入口只增加切换器与偏好模块的少量代码；背景 chunk gzip ≤ 8 KiB，不抬 `bundle-budget.json` 基线（D10） |
| C11 | 测试 | 变体绘制 / 引擎生命周期 / 取色 / 偏好 / 切换器 / AuthLayout 集成单测；保留 login / register e2e（见 §7） |

决策结论只在「决策记录」写一次。

## Context

现状逐条核对（以代码为准，沿用卡片「现状影响面」编号）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `.auth-shell` 已有静态氛围背景：双径向品牌光晕 + 细网格纹理，2 个伪元素 | `frontend/src/index.css:2994-3017` | 可继续作为画布降级底色，不删除 | 确认 |
| 2 | `.auth-card` 有 `cn-rise-in` 入场动画与顶部品牌饰线 | `frontend/src/index.css:3020-3077` | 背景层必须位于卡片下方，且不得触发卡片重绘抖动 | 确认 |
| 3 | `AuthLayout` 只有居中容器，无背景层 | `frontend/src/layouts/AuthLayout.tsx:5-17` | 新增挂载点；容器需 `position: relative` + `z-index` | 确认 |
| 4 | `/login`、`/register` 共用 `AuthLayout` | `frontend/src/App.tsx:73-74` | 一处接入覆盖两页 | 确认 |
| 5 | 10 套主题通过 `body.theme-*` 与 `--cn-*` 变量切换；`useTheme()` 暴露 `mode` / `isDark` | `frontend/src/theme/meta.ts:8-19`、`frontend/src/theme/ThemeProvider.tsx:92-96`、`122-126` | 颜色必须运行期取，不能写死 | 确认 |
| 6 | 现有 reduced-motion 只覆盖 CSS 入场动画 | `frontend/src/index.css:3074-3078` | JS 动效需独立判断并停 rAF | 确认 |
| 7 | 主入口体积基线 179,424 B（gzip），由 `bundle-budget` 卡口 | `frontend/scripts/bundle-budget.json:14-20` | 背景实现不能静态进主入口 | 确认 |
| 8 | `AuthLayout` 单测只有「children 渲染」；smoke 覆盖 login / register | `frontend/src/layouts/AuthLayout.test.tsx:12-21`、`frontend/tests/e2e/smoke/login.spec.ts`、`frontend/tests/e2e/smoke/register.spec.ts` | 需扩测试且不回归 | 确认 |
| 9 | `AuthLayout` 被 `App.tsx` **静态 import**（页面级才是 lazy） | `frontend/src/App.tsx:12-19` | 若在 `AuthLayout` 内静态引入画布与 5 个变体，会整体进主入口、撑爆 C10 | 新增 |
| 10 | jsdom 未实现 `HTMLCanvasElement#getContext`，`matchMedia` 由 setup 统一 polyfill 为 `matches: false` | `frontend/src/test/setup.ts:15-29`、`52-64` | 单测需显式 mock canvas 与 reduced-motion，否则画布路径不可测 | 新增 |

**核心缺陷（需求要补的）**：认证页目前只有静态 CSS 渐变，没有任何 JS 绘制层，也没有背景风格选择与持久化；且 `AuthLayout` 位于主入口 chunk，新增动效必须解决 chunk 边界。

设计目标（不变量）：

- **I1 不干扰**：背景层 `aria-hidden` + `pointer-events: none`，不改变 Tab 顺序、不遮挡卡片交互。
- **I2 单循环**：任一时刻至多一个 rAF；变体切换、主题切换、StrictMode 双挂载都不产生双循环。
- **I3 颜色单源**：所有绘制颜色来自 `--cn-*` 主题变量，切换主题后一帧内使用新色板。
- **I4 静态优先**：`prefers-reduced-motion: reduce` 下无持续 rAF，只出现静态首帧。
- **I5 优雅降级**：无 Canvas / 取色失败 / 0 尺寸时保持现有 CSS 背景，不抛错、不白屏。
- **I6 体积隔离**：背景实现（引擎 + 5 变体）不进入主入口 chunk。
- **I7 卸载干净**：dispose 幂等，移除 resize / visibility / pointer / matchMedia 监听与定时器。

## Decision

### 1. 数据模型

无后端模型。前端新增 3 个纯数据概念：

| 概念 | 形态 | 说明 |
|---|---|---|
| `AuthBackgroundVariant` | 字符串联合：`constellation \| nebula \| aurora \| rain \| orbs` | 变体 ID，同时作为本地存储值 |
| `AUTH_BACKGROUND_META` | `{ id, label, description }[]` | 切换器展示用的轻量元数据，与绘制实现分离 |
| `cndb_auth_bg` | `localStorage` 单键 | 唯一持久化位置；非法 / 缺失回落 `constellation` |

绘制状态（粒子、相位、轨迹）只存在于变体实例内部，组件卸载即丢弃；不使用全局单例。

### 2. 判定算法（唯一入口）

```ts
// mountAuthBackground(canvas, options): () => void
type MountOptions = {
  variant: AuthBackgroundVariant
  isDark: boolean
  isMobile: boolean
  reducedMotion: boolean
}
```

生命周期（所有变体共用，唯一入口）：

1. `canvas.getContext('2d')` 为空 → 返回 `noop`（I5）。
2. `readPalette()` 读取 CSS 变量；失败 → 返回 `noop`，CSS 背景兜底（I5）。
3. 按 `clientWidth/Height × dpr` 设置位图尺寸，`ctx.setTransform(dpr, 0, 0, dpr, 0, 0)`；0 尺寸时跳过绘制等待 resize。
4. `reducedMotion` 为真 → 绘制一帧 `frame(ctx, 0)` 后不启动 rAF（I4）。
5. 否则启动唯一 rAF 循环；移动端以 `1000 / 30` 为最小帧间隔跳帧。
6. `visibilitychange`：隐藏时 `cancelAnimationFrame`，恢复且非 reduced 时重启（I2）。
7. `resize`：150ms 节流后重新测量并调用 `variant.resize`。
8. 桌面非 reduced：`pointermove`（passive）更新归一化视差，变体按 ≤12px 偏移绘制。
9. dispose：取消 rAF、移除全部监听、清空定时器，可重复调用（I7）。

变体接口：

```ts
interface BackgroundVariant {
  resize(c: FrameContext): void
  frame(c: FrameContext, timeMs: number): void
}
```

### 3. API 变更清单

无。不新增 / 修改任何后端端点，不写用户偏好表。

### 4. 边界与例外

1. **主题切换**：`useTheme().mode` 作为 effect 依赖，切换时 dispose 旧引擎并以新色板重建；不做 Canvas 内部渐变缓存。
2. **严格模式**：effect cleanup 必须幂等；双挂载后只保留最后一份画布循环。
3. **颜色解析**：`--cn-*` 可能是 `#rgb` / `#rrggbb` / `rgb()`；提供 `withAlpha(color, alpha)` 统一转 `rgba()`，不可解析时退回 `globalAlpha`。
4. **深浅色叠加**：深色主题使用 `lighter` 合成增强发光；浅色主题用 `source-over` 低透明度，避免泛白（D7）。
5. **移动端**：DPR 1.5、目标 30fps、粒子数 ×0.45、关闭指针视差；仍保留动画。
6. **窗口极小 / 0 尺寸**：不绘制，等待下一次 resize；不抛异常。
7. **切换器可见性**：固定在右下角，不占卡片布局；小屏仍可见但缩小内边距。
8. **首帧闪烁**：背景 chunk 未就绪时显示既有 CSS 渐变，加载完成后 canvas 淡入（CSS 过渡 ≤ 240ms，reduced-motion 下无过渡）。

### 5. 迁移

无（不涉及数据库、备份格式或存量数据）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 组件入口 | `frontend/src/components/auth-background/AuthBackground.tsx` | 默认导出画布容器；读 `useTheme` / `useResponsive` / reduced-motion；调用挂载引擎；`aria-hidden` |
| 类型与元数据 | `frontend/src/components/auth-background/types.ts` | 变体 ID、标签、`FrameContext`、`BackgroundVariant` |
| 偏好 | `frontend/src/components/auth-background/preference.ts` | `load / save / next`，键 `cndb_auth_bg`，非法值回落 |
| 色板 | `frontend/src/components/auth-background/palette.ts` | 读 CSS 变量 + `withAlpha` + 种子随机 |
| 引擎 | `frontend/src/components/auth-background/engine.ts` | `mountAuthBackground`：DPR、rAF、可见性、resize、视差、dispose |
| 变体 | `frontend/src/components/auth-background/variants/{constellation,nebula,aurora,rain,orbs}.ts` | 5 个 `BackgroundVariant` 实现 |
| 切换器 | `frontend/src/components/auth-background/AuthBackgroundSwitcher.tsx` | 原生 `<button>`，显示当前风格名，循环切换并持久化 |
| 布局 | `frontend/src/layouts/AuthLayout.tsx` | `lazy` 引入 `AuthBackground`；背景层 + 内容层 z-index；挂载切换器 |
| 样式 | `frontend/src/index.css` | `.auth-bg-layer` / `.auth-bg-canvas` / `.auth-bg-switch` / 内容层层级；全部用 `--cn-*` 变量与标尺 |
| 文档 | `CONTEXT.md` | 新增术语「认证页动态背景（AuthBackground）」与 `cndb_auth_bg` |

### 7. 测试清单

**判定层（单测）**

- `palette.test.ts`：CSS 变量正常读取、空值返回 `null`、`withAlpha` 覆盖 hex / rgb / 非法值。
- `preference.test.ts`：默认 `constellation`；合法值读取；非法值回落；`next` 循环 5→1；localStorage 抛错不崩溃。
- `engine.test.ts`：无 canvas context 返回 noop；reduced-motion 不调用 rAF；可见性隐藏暂停 / 恢复重启；resize 节流；dispose 幂等且移除监听；移动端 30fps 跳帧。
- `variants/*.test.ts`：每个变体 `resize` 后 `frame` 至少产生一次 fill / stroke；0 尺寸不抛错；粒子坐标在有限范围内（无 NaN）。

**组件层（单测）**

- `AuthBackground.test.tsx`：canvas 存在且 `aria-hidden`；主题切换后重建；卸载后 rAF 取消。
- `AuthBackgroundSwitcher.test.tsx`：点击切换标签、写入 localStorage、键盘可达。
- `AuthLayout.test.tsx`：children 仍渲染；背景层存在；切换器改变 `data-variant`；420px 容器不变。

**e2e（前端）**

- 既有 `smoke/login.spec.ts`、`smoke/register.spec.ts` 全绿；补一条断言：认证页背景 canvas 可见且不拦截表单点击。

**体积**

- `pnpm build` 后 `bundle:budget` 通过；背景 chunk gzip ≤ 8 KiB。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 引擎 + 色板 + 偏好 + 星座变体 + `AuthLayout` 接入 + reduced-motion / 降级 + 单测 | 低 |
| **P1** | 其余 4 个变体 + 切换器 UI + 持久化 + 组件测试 | 低 |
| **P2** | 移动端档位 / 视差 / 主题叠加模式调优 + chunk 预算校验 + e2e 收尾 + 文档回填 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 动效实现选型 | 原生 Canvas 2D + rAF，无第三方库 | 体积可控、可读主题变量、5 种风格都可用 2D 表达 | CSS keyframes（无法做星点连线 / 字符轨迹）；three.js（~150KB gzip，超出 C10）；GIF / 视频（体积大、无法跟随主题） | `components/auth-background/engine.ts` |
| D2 | 5 组变体与默认值 | 星座连线（默认）/ 星云漩涡 / 极光流光 / 数字雨 / 光点流体，全部保留 | 需求方确认；形态差异足够大 | 只留星座（丢失可选性）；全部按主题自动选（用户无法选择） | `variants/`、`types.ts` |
| D3 | 切换与持久化 | 右下角循环按钮 + `localStorage['cndb_auth_bg']` | 零后端改动、跨刷新保持；需求方确认 | 后端用户偏好（需迁移与接口）；跟随主题自动（不可选）；无切换入口（不满足「5 组」） | `preference.ts`、`AuthBackgroundSwitcher.tsx` |
| D4 | 覆盖范围 | 仅 `/login`、`/register` | 两页共用 `AuthLayout`，改动面最小 | 覆盖 `/public`（公开页样式与权限语境不同） | `AuthLayout.tsx` |
| D5 | 减少动态偏好 | `prefers-reduced-motion: reduce` 只画静态首帧 | 与现有 CSS 约定一致（`index.css:3074-3078`） | 直接隐藏背景（丢失氛围且主题色块突兀） | `AuthBackground.tsx` |
| D6 | 移动端与交互档位 | 移动端 DPR 1.5 / 30fps / 粒子减半 / 无视差；桌面轻微鼠标视差 | 移动端 GPU 与电池成本高；视差只作点缀 | 全端同档（耗电）；移动端完全静态（与「动图」诉求冲突） | `engine.ts` |
| D7 | 主题取色与叠加 | 运行期读 `--cn-*`，深色 `lighter`、浅色 `source-over` | 10 套主题 + `theme-dark` 兼容标记已有单一来源 | 写死色值（违反 DESIGN_SYSTEM 硬规则）；按主题硬编码 10 套色板（维护成本） | `palette.ts`、`AuthBackground.tsx` |
| D8 | 可访问性 | 背景层 `aria-hidden` + `pointer-events:none`，切换器为原生按钮 | 不干扰表单焦点与读屏 | 画布可聚焦 / 可点击（会抢走表单操作） | `AuthBackground.tsx`、`AuthBackgroundSwitcher.tsx` |
| D9 | 降级策略 | 保留 `.auth-shell` CSS 渐变作为兜底，失败即不挂画布 | 现有视觉已可用，避免白屏 | 移除 CSS 背景（失败时白屏） | `index.css:2994-3017`、`AuthBackground.tsx` |
| D10 | 体积边界 | `AuthBackground` 用 `lazy(() => import())` 独立 chunk，背景 gzip ≤ 8 KiB | `AuthLayout` 静态进主入口（`App.tsx:12`），必须切断静态链；主入口基线 179,424 B 不抬 | 静态 import（撑大主入口）；把 `AuthLayout` 整体改 lazy（改动扩散到路由骨架） | `AuthLayout.tsx`、`bundle-budget.json` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：认证页获得 5 种可切换的动效氛围；主题 / 深浅色自动适配；实现零依赖、可测试、可降级。
- **负向**：多一个独立 chunk 与约 5-8 KiB gzip；rAF 常驻带来少量 CPU / 电量开销（已用可见性暂停、移动端 30fps 与 reduced-motion 收敛）。
- **风险与缓解**：低端设备掉帧 → 粒子上限 + 帧率档位；主题变量解析失败 → CSS 背景兜底；懒加载失败 → Suspense `null` + 静态背景。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/components/auth-background/types.ts`、`frontend/src/components/auth-background/preference.ts`、`frontend/src/components/auth-background/palette.ts`、`frontend/src/components/auth-background/engine.ts`、`frontend/src/components/auth-background/variants/constellation.ts` | `frontend/src/components/auth-background/engine.test.ts`、`frontend/src/components/auth-background/palette.test.ts`、`frontend/src/components/auth-background/preference.test.ts` | 未提交 |
| P1 | 已落地 | `frontend/src/components/auth-background/variants/nebula.ts`、`frontend/src/components/auth-background/variants/aurora.ts`、`frontend/src/components/auth-background/variants/rain.ts`、`frontend/src/components/auth-background/variants/orbs.ts`、`frontend/src/components/auth-background/AuthBackgroundSwitcher.tsx` | `frontend/src/components/auth-background/variants.test.ts`、`frontend/src/components/auth-background/AuthBackgroundSwitcher.test.tsx` | 未提交 |
| P2 | 已落地 | `frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/layouts/AuthLayout.tsx`、`frontend/src/index.css` | `frontend/src/components/auth-background/AuthBackground.test.tsx`、`frontend/src/layouts/AuthLayout.test.tsx`、`frontend/tests/e2e/smoke/login.spec.ts`、`frontend/tests/e2e/smoke/register.spec.ts` | 未提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地；`Status` 仍为 `Accepted`，是否改 `Implemented` 待人工确认
- 已完成：需求卡片 0014、ADR 0014、5 个变体 + 引擎 + 偏好 + 切换器 + `AuthLayout` 接入 + 单测 + e2e 断言
- 下一步：人工评审代码与视觉走查，确认后提交 / 发版；`Status` 改写后跑 `make check-docs`
- 已知坑：`AuthLayout` 被 `App.tsx:12` 静态引入，背景必须 lazy 才能守住主入口体积；jsdom 无 `getContext`，单测需 mock；e2e 首次运行需 `pnpm exec playwright install --with-deps chromium`
- 最近一次全绿：`make check-fast` + `make test` + `pnpm test`（152 文件 / 1938 例）+ `pnpm build` + `bundle:budget` + `e2e:smoke` + `chromium-anon` login/register @ 2026-10-21

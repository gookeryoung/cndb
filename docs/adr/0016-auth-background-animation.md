# ADR 0016: 认证页 JS 动态背景（Perlin 流场粒子 / 多星系宇宙星系，可切换，青紫渐变，固定深色舞台）

Status: Implemented（2026-10-21 评审通过；同日改为 Perlin 流场粒子，并新增可切换的多座宇宙星系）
Date: 2026-10-21
Related: `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/components/auth-background/`、`frontend/src/index.css`、`frontend/src/theme/meta.ts`、`frontend/scripts/bundle-budget.json`
需求卡片: `docs/requirements/0016-auth-background-animation.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | Perlin 流场粒子 + 新增宇宙星系 + 更多星系与多轴旋转 | 两种动效共用同一引擎与色板：`flowfield`（固定种子 Perlin 噪声方向场驱动粒子漂移，每颗粒子环形尾迹连成流线）与 `galaxy`（固定种子多座旋臂星系：桌面 3 座共 1600 星点 / 移动 2 座共 700 星点，每座核球 + 两条对数螺线星臂 + 弥散星尘，大小 / 倾角 / 色相 / 自转方向各异，pitch / yaw / roll 三轴不同相位缓慢进动）；默认 `flowfield`（D2） |
| C2 | 白色底色科技感不足，考虑改为黑色 | `.auth-shell` 页面底色固定近黑 `--cn-auth-bg`；登录卡片继续跟随 10 套主题，不强制深色卡片（D11） |
| C3 | 科技感 + 青紫渐变 | 深色舞台 + 青紫渐变：流线用 `--cn-auth-accent` 青 → `--cn-auth-accent-alt` 紫 → 青；星系用青 / 紫星点 + 紫色星云；页面双色径向光晕；零新增依赖（D7 / D12） |
| C4 | 可切换的背景动图 | 右下角原生按钮循环切换 `flowfield` ↔ `galaxy`，即时生效；偏好写 `localStorage['cndb_auth_bg']`，刷新保持；非法值 / 存储不可用回落 `flowfield`（D3） |
| C5 | 性能与资源 | 单 rAF；桌面 DPR ≤ 2，移动端 DPR ≤ 1.5 且 30fps；`document.hidden` 暂停；resize 150ms 节流；桌面指针扰动（流场偏转 / 星系视差）；切换先 dispose 旧实例再挂载新实例（D6） |
| C6 | 可访问性 | `prefers-reduced-motion: reduce` 只画一次静态帧；画布与背景容器 `aria-hidden` + `pointer-events: none`；切换器独立于背景层，`type="button"` + 明确 `aria-label`，可键盘操作（D5 / D8） |
| C7 | 降级 | `getContext('2d')` 为空或 auth token（accent / accent-alt / ink）缺失时不挂载画布，保留 `.auth-shell` 固定深色 CSS 背景（D9） |
| C8 | 体积与测试 | 双动效 / 切换器 / 偏好同属背景 lazy chunk，不进入主入口；chunk gzip ≤ 8 KiB，不抬 `bundle-budget.json` 基线；单测 + login / register e2e 覆盖切换与刷新保持（D10） |

决策结论只在「决策记录」写一次。

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 认证页只有单一 `flowfield` 动效，无第二个变体 | `frontend/src/components/auth-background/flowfield.ts`、`engine.ts` | 引擎写死 `createFlowField`，无法按偏好切换 | 需求变更的直接原因 |
| 2 | 背景层 `aria-hidden` + `pointer-events: none`，层内无交互元素 | `AuthBackground.tsx`、`index.css` | 切换器不能放进背景层，需独立定位层 | 约束切换器结构 |
| 3 | 无效果偏好模块 | `frontend/src/components/auth-background/` | 切换结果刷新即丢 | 恢复单键偏好 |
| 4 | 10 套主题通过 `body.theme-*` 与 `--cn-*` 变量切换；登录卡片跟随主题 | `frontend/src/theme/meta.ts`、`ThemeProvider.tsx` | 页面底色不跟主题；卡片仍需跟主题 | 约束深色范围（D11） |
| 5 | `AuthLayout` 被 `App.tsx` 静态 import，页面级才是 lazy | `frontend/src/App.tsx` | 背景实现必须继续走独立 lazy chunk | 约束体积（D10） |
| 6 | jsdom 未实现 `HTMLCanvasElement#getContext` | `frontend/src/test/setup.ts` | 单测需显式 mock canvas | 约束测试 |
| 7 | 主入口体积基线 175.22 KiB（gzip） | `frontend/scripts/bundle-budget.json` | 切换器与偏好必须留在背景 chunk 内 | 约束体积 |

**核心缺陷（需求要补的）**：只有一种动效，无法按偏好切换；需求方要保留流场粒子并新增宇宙星系，两者共享深色舞台与青紫色板。

设计目标（不变量）：

- **I1 不干扰**：背景层 `aria-hidden` + `pointer-events: none`，切换器只在右下角占一个小按钮，不改变表单 Tab 顺序起点、不遮挡卡片。
- **I2 单循环**：任一时刻至多一个 rAF；切换效果先 dispose 旧实例再挂载；StrictMode 双挂载、resize、可见性切换都不产生双循环。
- **I3 颜色单源**：画布颜色只来自 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink`，不在 JS 写色值。
- **I4 静态优先**：`prefers-reduced-motion: reduce` 下无持续 rAF，两种动效都只画一次完整静态帧（流场预热流线 / 星系星点）。
- **I5 优雅降级**：无 Canvas / auth token 缺失 / 0 尺寸时保持固定深色 CSS 背景，不抛错、不白屏；偏好非法时回落 `flowfield`。
- **I6 体积隔离**：引擎、两种动效、切换器与偏好模块都不进入主入口 chunk。
- **I7 卸载干净**：dispose 幂等，移除 resize / visibility / pointer 监听与定时器。
- **I8 双动效可切换**：只保留 `flowfield` 与 `galaxy` 两个效果；`galaxy` 为多座星系（桌面 3 / 移动 2）且每座各自多轴进动；默认 `flowfield`；切换即时生效并持久化。

## Decision

### 1. 数据模型

无后端模型。前端只有 4 个纯数据概念：

| 概念 | 形态 | 说明 |
|---|---|---|
| `AuthEffect` | `'flowfield' \| 'galaxy'` | 效果 id；同时是 `localStorage['cndb_auth_bg']` 的合法取值 |
| `AuthEffectMeta` | `{ id, label }` | 切换器文案；`AUTH_EFFECTS` 固定顺序 = 循环顺序 |
| `Palette` | `{ accent, accentAlt, ink }` | 固定舞台 token 的运行期快照；accent = 青紫渐变两端（青），accentAlt = 中段（紫），ink = 中性星点 / 网格 |
| `FrameContext` | `{ ctx, width, height, palette, isMobile, pointer }` | 单帧绘制上下文 |
| `BackgroundVariant` | `resize` + `frame` | 两个实现：`createFlowField` / `createGalaxy` |

绘制状态（粒子数组、星点数组、渐变缓存）只存在于动效实例内部，切换或卸载即丢弃；Perlin 置换表是模块级固定种子常量（只读）；不使用全局单例。

### 2. 判定算法（唯一入口）

```ts
// mountAuthBackground(canvas, options): () => void
type MountOptions = {
  isMobile: boolean
  reducedMotion: boolean
  effect: AuthEffect
}
```

生命周期（唯一入口）：

1. `canvas.getContext('2d')` 为空 → 返回 `noop`（I5）。
2. `readPalette()` 读取 `--cn-auth-accent` / `--cn-auth-accent-alt` / `--cn-auth-ink`；失败 → 返回 `noop`，CSS 背景兜底（I5）。
3. `effect === 'galaxy' ? createGalaxy(isMobile) : createFlowField(isMobile)`。
4. 按 `clientWidth/Height × dpr` 设置位图尺寸，`ctx.setTransform(dpr, 0, 0, dpr, 0, 0)`；0 尺寸时跳过绘制等待 resize。
5. `reducedMotion` 为真 → 绘制一帧 `frame(ctx, 0)` 后不启动 rAF（I4）。
6. 否则启动唯一 rAF 循环；移动端以 `1000 / 30` 为最小帧间隔跳帧。
7. `visibilitychange`：隐藏时 `cancelAnimationFrame`，恢复且非 reduced 时重启（I2）。
8. `resize`：150ms 节流后重新测量并调用 `variant.resize`。
9. 桌面非 reduced：`pointermove`（passive）更新归一化指针；流场叠加 ≤ 0.36 rad 方向偏转，星系作为 ≤ 22px 视差偏移。
10. dispose：取消 rAF、移除全部监听、清空定时器，可重复调用（I7）。

偏好（`preference.ts`）：

```ts
const AUTH_EFFECT_STORAGE_KEY = 'cndb_auth_bg'
loadAuthEffect(): AuthEffect     // 缺失 / 非法 / 读失败 → 'flowfield'
saveAuthEffect(effect: AuthEffect): void  // 写失败静默忽略
nextAuthEffect(effect: AuthEffect): AuthEffect // 按 AUTH_EFFECTS 顺序循环
```

组件层（`AuthBackground.tsx`）：`useState(loadAuthEffect)` 持有当前效果；点击切换器 → `saveAuthEffect(next)` + `setEffect(next)`；`effect` 进入引擎 effect 依赖，变化时先 dispose 旧实例再挂载新实例（I2）。

动效接口：

```ts
interface BackgroundVariant {
  resize(c: FrameContext): void
  frame(c: FrameContext, timeMs: number): void
}
```

### 3. API 变更清单

无。不新增 / 修改任何后端端点，不写用户偏好表；仅恢复前端 `localStorage['cndb_auth_bg']` 读写（合法值只有两个效果 id）。

### 4. 边界与例外

1. **深色范围**：仅 `.auth-shell` 页面背景固定近黑；登录卡片仍由 antd token / 主题决定（D11）。
2. **主题切换**：画布颜色来自固定 auth token，主题切换不重建引擎；主题只影响卡片。
3. **颜色解析**：auth token 为 `#rgb` / `#rrggbb` / `rgb()`；`withAlpha` 统一转 `rgba()`，不可解析时原样返回（渐变仍可建）。
4. **叠加方式**：黑底由 CSS 提供；画布保持透明。流场用环形尾迹整段描边（单帧位移仅 0.x px，只画单帧线段不可见）并以 `lighter` 让交叉处增亮；星系逐座先铺缓存的外晕 + 核球两层径向渐变（按包围盒裁剪到画布内），再用 `lighter` 批量 `fillRect` 星点；绘制结束还原 `source-over` 与 `globalAlpha = 1`，每帧先 `clearRect`。
5. **切换语义**：循环顺序固定 `flowfield → galaxy → flowfield`；切换立即重建画布，不做交叉淡入（避免两实例并行违反 I2）；按钮文案随当前效果更新。
6. **移动端**：DPR 1.5、目标 30fps；流场粒子 320 / 尾迹 26 点，星系 2 座共 700 星点；关闭指针扰动；桌面流场 800 粒子 / 40 点尾迹，星系 3 座共 1600 星点与每座 ≤ 22px 视差。
7. **窗口极小 / 0 尺寸**：不绘制，等待下一次 resize；不抛异常。
8. **首帧闪烁**：背景 chunk 未就绪时显示固定深色 CSS 背景，加载完成后 canvas 淡入（≤ 240ms，reduced-motion 无过渡）。
9. **偏好**：历史版本可能写入过已删除的 5 个旧变体 id；凡不在 `AUTH_EFFECTS` 内的值一律按 `flowfield` 处理，不做迁移或清理。
10. **切换器定位**：绝对定位右下角（桌面 24px、移动端 12px），`z-index: 2`（高于卡片层 1）；仅按钮接收指针事件与键盘焦点，`aria-label` 含「切换登录背景动效」；不进入 `aria-hidden` 背景层。

### 5. 迁移

无（不涉及数据库、备份格式或存量数据）；`cndb_auth_bg` 旧值按非法值回落默认。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 组件入口 | `frontend/src/components/auth-background/AuthBackground.tsx` | 效果状态 + `loadAuthEffect` / `saveAuthEffect`；背景层 + 切换器兄弟节点；`data-effect` 跟随效果 |
| 类型与元数据 | `frontend/src/components/auth-background/types.ts` | 新增 `AuthEffect` / `AuthEffectMeta` / `AUTH_EFFECTS`；保留 `Palette` / `FrameContext` / `BackgroundVariant` |
| 偏好 | `frontend/src/components/auth-background/preference.ts` | 读 / 写 / 循环 / 文案；非法值与存储异常回落 `flowfield` |
| 切换器 | `frontend/src/components/auth-background/AuthBackgroundSwitcher.tsx` | 原生按钮 + 效果圆点 + 文案；`aria-label` / `title` |
| 引擎 | `frontend/src/components/auth-background/engine.ts` | `MountOptions.effect`；按效果创建 `flowfield` 或 `galaxy` |
| 动效 | `frontend/src/components/auth-background/flowfield.ts` | 保留 Perlin 流场粒子实现 |
| 动效 | `frontend/src/components/auth-background/galaxy.ts` | 宇宙星系：多座星系的固定种子旋臂采样、差分自转、三轴倾斜矩阵与多轴进动、闪烁、每座外晕 / 核球渐变、指针视差 |
| 布局 | `frontend/src/layouts/AuthLayout.tsx` | 无结构变化：仍 `lazy` 引入 `AuthBackground` |
| 样式 | `frontend/src/index.css` | 新增 `.auth-bg-switch` 胶囊按钮（固定舞台 token、hover / focus-visible、移动端内缩、reduced-motion 去过渡） |

### 7. 测试清单

**判定层（单测）**

- `flowfield.test.ts`：resize 后 frame 有一次流线描边、坐标有限；每颗粒子输出多段 `lineTo`；0 尺寸不绘制；移动端可绘制；首帧预热后每帧只描边一次；青紫渐变三个色标；固定种子下两次实例流线一致；噪声在 -1..1 且确定。
- `galaxy.test.ts`：resize 后 frame 清屏一次、3 座星系各自外晕 / 核球渐变与星点 `fillRect` 数量正确、裁剪在画布内、坐标有限；每座按色相换主色且三组星点批量着色；0 尺寸不绘制；移动端 2 座星系；渐变跨帧复用；固定种子下两次实例星点一致；指针改变星系中心形成视差。
- `preference.test.ts`：无值 / 非法值 / 读失败回落 `flowfield`；写入后读回；循环顺序；文案。
- `palette.test.ts`：三个 auth token 正常读取、任一缺失返回 `null`、空字符串视为失败；`withAlpha` 覆盖 hex / rgb / 非法值。
- `engine.test.ts`：无 canvas context 返回 noop；token 缺失返回 noop；reduced-motion 不调用 rAF；可见性隐藏暂停 / 恢复重启；resize 节流；dispose 幂等；移动端 30fps 跳帧；`effect=galaxy` 时使用星系构建器（可绘制）。

**组件层（单测）**

- `AuthBackground.test.tsx`：默认 `data-effect="flowfield"`；挂载时把 `effect` 交给引擎；点击切换器后 `data-effect="galaxy"` 并写入 `cndb_auth_bg`；卸载后 dispose。
- `AuthBackgroundSwitcher.test.tsx`：渲染当前文案 / `data-effect` / `aria-label`；点击调用切换。
- `AuthLayout.test.tsx`：children 仍渲染；背景层与切换器存在；420px 容器不变。

**e2e（前端）**

- `frontend/tests/e2e/smoke/login.spec.ts`、`smoke/register.spec.ts`：认证页背景 canvas 可见、`aria-hidden`、`pointer-events: none`、默认 `data-effect="flowfield"`，且不拦截表单点击；点击切换器后 `data-effect="galaxy"`，刷新后仍为 `galaxy`。

**体积**

- `pnpm build` 后 `bundle:budget` 通过；背景 chunk gzip ≤ 8 KiB。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 引擎 + Perlin 流场粒子 + `AuthLayout` 接入 + 单测 | 低 |
| **P1** | 固定深色舞台 + 青紫 auth token + 移动端 / reduced-motion 调优 + 体积与 e2e 收尾 | 中 |
| **P2** | 宇宙星系动效 + 效果元数据 / 偏好 + 右下角切换器 + 单测与 e2e 切换断言 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 动效实现选型 | 原生 Canvas 2D + rAF，无第三方库 | 体积可控、可读固定舞台 token、两种动效都能用 2D 表达 | CSS keyframes（无法做逐帧噪声 / 差分自转）；three.js（~150KB gzip，超 C8）；GIF / 视频（体积大、无法随卡片主题共存） | `engine.ts` |
| D2 | 动效集合 | `flowfield`：固定种子 improved Perlin 2D 方向场 + 环形尾迹（桌面 800 / 移动 320 粒子，40 / 26 点尾迹）；`galaxy`：固定种子多座旋臂星系（桌面 3 座共 1600 星点 / 移动 2 座共 700 星点，每座核球 18% / 星臂 36% / 星尘 46%，内快外慢差分自转，三轴倾斜 + 多轴进动 + 闪烁 + 外晕 / 核球渐变 + 视差）；默认 `flowfield` | 保留已交付的流场基线，多座星系满足更多星系与多轴旋转；两个实现共用 `BackgroundVariant` 与色板，切换成本最低 | 用星系替换流场（用户要求再增加而非替换）；单座星系（不满足更多星系与相互旋转感）；再恢复旧 5 变体（视觉语言发散） | `flowfield.ts`、`galaxy.ts` |
| D3 | 切换与持久化 | 右下角原生按钮循环切换；偏好写 `localStorage['cndb_auth_bg']`；默认 `flowfield`；非法值 / 存储不可用回落默认 | 用户要求可切换；两选项下循环按钮比下拉更轻；刷新保持符合预期 | 下拉选择器（两选项过重）；只切换不持久化（刷新丢失）；后端用户偏好（更重） | `AuthBackgroundSwitcher.tsx`、`preference.ts`、`AuthBackground.tsx` |
| D4 | 覆盖范围 | 仅 `/login`、`/register` | 两页共用 `AuthLayout`，改动面最小 | 覆盖 `/public`（公开页样式与权限语境不同） | `AuthLayout.tsx` |
| D5 | 减少动态偏好 | `prefers-reduced-motion: reduce` 只画一次完整静态帧 | 与现有 CSS 约定一致；两种动效首帧都完整可见 | 直接隐藏背景（丢失氛围）；只对其中一种降级（口径分裂） | `AuthBackground.tsx`、`flowfield.ts`、`galaxy.ts` |
| D6 | 移动端与交互档位 | 移动端 DPR 1.5 / 30fps / 流场 320 粒子 / 26 点尾迹 / 星系 2 座共 700 星点 / 无视口扰动；桌面流场 800 粒子 / 40 点尾迹 + 指针偏转 ≤ 0.36 rad，星系 3 座共 1600 星点 + 每座视差 ≤ 22px | 移动端 GPU 与电池成本高；关闭指针扰动避免触屏滑动改变画面 | 全端同档（耗电）；移动端保留指针扰动（无鼠标语义） | `flowfield.ts`、`galaxy.ts`、`engine.ts` |
| D7 | 颜色来源与叠加 | 运行期读固定 `--cn-auth-*`；流场青紫渐变三色标；星系星点按 accent / accent-alt / ink 分三组批量绘制，每座星系用外晕 5 色标 + 核球 3 色标径向渐变（按色相权重决定青 / 紫主色），均以 `lighter` 叠加 | 黑底对比度稳定；与浅色主题品牌色解耦；分组批量设置样式减少状态切换 | 跟随 `--cn-brand-color`（部分主题在黑底上偏暗）；逐星写独立色值（状态切换成本高、体积大） | `palette.ts`、`flowfield.ts`、`galaxy.ts` |
| D8 | 可访问性 | 背景层 `aria-hidden` + `pointer-events:none`；切换器独立于背景层，是唯一新增可聚焦元素，`type="button"` + `aria-label` + `title`，可见 focus 环 | 切换需要交互入口；不能把按钮藏进 `aria-hidden` 层；不干扰表单焦点与读屏 | 画布可聚焦 / 可点击；把切换器放进背景层（读屏失效） | `AuthBackground.tsx`、`AuthBackgroundSwitcher.tsx`、`index.css` |
| D9 | 降级策略 | 保留 `.auth-shell` 固定深色 CSS 背景作为兜底，失败即不挂画布；偏好非法回落 `flowfield` | 现有视觉已可用，避免白屏 | 移除 CSS 背景（失败时白屏）；偏好非法时报错（登录页不可用） | `index.css`、`engine.ts`、`preference.ts` |
| D10 | 体积边界 | `AuthBackground` 用 `lazy(() => import())` 独立 chunk；两种动效 / 切换器 / 偏好都留在 chunk 内；背景 gzip ≤ 8 KiB，主入口基线不抬 | `AuthLayout` 静态进主入口（`App.tsx`），必须切断静态链；切换器放组件内可随 chunk 懒加载 | 静态 import（撑大主入口）；把切换器单独做成主入口组件（破坏隔离） | `AuthLayout.tsx`、`bundle-budget.json` |
| D11 | 深色范围 | 仅页面背景固定近黑；登录卡片继续跟随 10 套主题 | 需求方确认；改动面最小；卡片可读性由主题保证 | 整页强制深色卡片（改动大、与主题体系冲突） | `index.css`、`AuthLayout.tsx` |
| D12 | 配色 token | accent `#22d3ee`（青）、accent-alt `#a855f7`（紫）、ink `#dbe4f3`、底色 `#05070c` | 需求方确认青紫渐变；黑底对比度高；两种动效共用一套 token | 跟随主题品牌色（部分主题在黑底上偏暗）；纯单色（层次不足） | `index.css` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：认证页可在“流场粒子 / 宇宙星系”之间切换，偏好刷新保持；两种动效共用固定黑底 + 青紫色板与同一引擎，代码与视觉语言保持收敛。
- **负向**：切换器新增一个可聚焦元素；背景 chunk 体积与首帧绘制成本随第二种动效上升；切换会重建画布，切换瞬间动画从首帧开始。
- **风险与缓解**：低端设备掉帧 → 流场 800 / 320 粒子、星系 3 座 1600 / 2 座 700 星点（桌面 / 移动），移动端 30fps；星系多层渐变填充 → 每座外晕 / 核球渐变缓存、按包围盒裁剪到画布内、移动端降低星点；切换双循环风险 → 由 effect 依赖的 dispose / remount 保证；token 解析失败 → CSS 背景兜底；懒加载失败 → Suspense `null` + 固定深色背景。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/components/auth-background/flowfield.ts`、`frontend/src/components/auth-background/engine.ts`、`frontend/src/components/auth-background/types.ts`、`frontend/src/components/auth-background/palette.ts`、`frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/layouts/AuthLayout.tsx` | `frontend/src/components/auth-background/flowfield.test.ts`、`frontend/src/components/auth-background/engine.test.ts`、`frontend/src/components/auth-background/palette.test.ts`、`frontend/src/components/auth-background/AuthBackground.test.tsx`、`frontend/src/layouts/AuthLayout.test.tsx` | `6d8adbe0` |
| P1 | 已落地 | `frontend/src/index.css` | `frontend/tests/e2e/smoke/login.spec.ts`、`frontend/tests/e2e/smoke/register.spec.ts` | `6d8adbe0` |
| P2 | 已落地 | `frontend/src/components/auth-background/galaxy.ts`、`frontend/src/components/auth-background/preference.ts`、`frontend/src/components/auth-background/AuthBackgroundSwitcher.tsx`、`frontend/src/components/auth-background/AuthBackground.tsx`、`frontend/src/components/auth-background/engine.ts`、`frontend/src/components/auth-background/types.ts`、`frontend/src/index.css` | `frontend/src/components/auth-background/galaxy.test.ts`、`frontend/src/components/auth-background/preference.test.ts`、`frontend/src/components/auth-background/AuthBackgroundSwitcher.test.tsx`、`frontend/src/components/auth-background/AuthBackground.test.tsx`、`frontend/src/components/auth-background/engine.test.ts`、`frontend/tests/e2e/smoke/login.spec.ts`、`frontend/tests/e2e/smoke/register.spec.ts` | `b06362c7` |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（双动效 + 多座星系 + 切换器 + 偏好；代码 / 测试 / 文档已提交 `b06362c7`）
- 已完成：新增 `galaxy` 多座宇宙星系（桌面 3 座 / 移动 2 座，每座独立倾角 / 色相 / 自转方向，pitch / yaw / roll 多轴进动）、效果元数据 / `cndb_auth_bg` 偏好 / 右下角循环切换器；引擎按 `effect` 选择实现，切换时先 dispose 再挂载；单测与 login / register e2e 覆盖默认流场、切换星系与刷新保持
- 下一步：无（本 ADR 范围内交付完毕）；如需视觉微调，改 `flowfield.ts` 的粒子数 / `FIELD_SCALE` / 速度，或 `galaxy.ts` 的 `DESKTOP_GALAXIES` / `MOBILE_GALAXIES` 位置 / 星点数 / 倾角 / 进动速度，或调 `--cn-auth-*` token
- 已知坑：`AuthLayout` 被 `App.tsx` 静态引入，背景必须 lazy 才能守住主入口体积；jsdom 无 `getContext`，单测需 mock；切换器是唯一可聚焦的背景元素，不能移入 `aria-hidden` 层；星系每座每帧两层径向渐变（外晕 + 核球）并按包围盒裁剪，桌面 3 座共 1600 星点 / 移动 2 座共 700 星点；两种动效都必须保持固定种子（去掉后单测的确定性断言会失败）；e2e 登录按钮定位必须保持 `/^登\s*录$/` 首尾锚定，避免被「切换登录背景动效」按钮污染
- 最近一次全绿：2026-10-21 —— 前端 `pnpm check` / `pnpm test`（155 文件 / 1949 用例）/ `pnpm build` + `bundle:budget`（AuthBackground chunk gzip 4.69 KiB ≤ 8 KiB）全绿；根目录 `make check-docs`（adr-check 0 error / 0 warning）与 `make flow`（ruff / pyrefly 0 error；pytest 5136 passed / 8 skipped）全绿；e2e smoke：authed 10 passed、anon 11 passed（含切换 galaxy 与刷新保持）

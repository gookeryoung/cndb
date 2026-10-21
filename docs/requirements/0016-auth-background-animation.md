# 需求卡片 0016：认证页 JS 动态背景（5 组风格）

- 编号：0016（与 ADR `docs/adr/0016-*.md` 同号）
- 来源 / 提出人：用户口述需求
- 日期：2026-10-21
- 关联 ADR：[0016](../adr/0016-auth-background-animation.md)
- Status：Accepted（需求方 2026-10-21 确认）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 设计 5 组不同风格的炫酷的背景 js 动图，如星座等风格。用作登录界面背景。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「设计 5 组不同风格的炫酷的背景」 | 提供 5 个可独立挂载的背景变体，统一实现同一套 `AuthBackground` 接口（`mount(container, options) => dispose`），彼此不共享可变状态；5 组全部保留可选，默认星座 | `frontend/src/components/auth-background/` | 逐一挂载的单测 + 视觉走查 |
| C2 | 「js 动图」 | 动效由 JS 驱动（Canvas 2D + `requestAnimationFrame`），不使用 GIF/视频/第三方动画库；每帧只做一次绘制提交 | 同上 | 单测断言 rAF 启动；bundle 中无新增动画依赖 |
| C3 | 「如星座等风格」 | 5 组定稿为星座连线（默认）/ 星云漩涡 / 极光流光 / 数字雨 / 光点流体，视觉语言互不重复：星座 = 星点 + 近邻连线 + 缓慢漂移；星云 = 螺旋粒子云；极光 = 噪声带状光幕；数字雨 = 字符列下落；光点流体 = 大尺寸柔光圆斑 | 同上 | 视觉走查 + 快照式配置断言 |
| C4 | 「用作登录界面背景」 | 仅接入 `AuthLayout`，覆盖 `/login` 与 `/register`，不接 `/public`；背景层 `position: absolute; inset: 0`，位于 `auth-card` 之下，`pointer-events: none`，不得改变 420px 卡片居中布局 | `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/App.tsx:73-74` | `AuthLayout.test.tsx` 断言卡片仍可交互；登录 / 注册 e2e 通过 |
| C5 | 主题一致性（仓库硬规则） | 所有颜色从 `var(--cn-brand-color)` / `--cn-bg-page` / `--cn-text-primary` 运行时读取（`getComputedStyle`），10 套主题（含深色）自动适配；JS / CSS 中不出现颜色字面量 | `frontend/src/index.css`、`frontend/src/theme/meta.ts:8-19` | 静态检索无新增色值；切换主题后画布重取色 |
| C6 | 性能与资源 | 单 rAF 循环；桌面 DPR 上限 2、移动端 1.5 且目标 30fps；`document.hidden` 时暂停；`resize` 节流；粒子数按视口面积设上限，移动端再降一档且关闭视差；桌面允许轻微鼠标视差；卸载 / StrictMode 双挂载时取消 rAF、移除监听 | 同上 | 单测断言 cleanup 可重复调用；e2e 无卡顿告警 |
| C7 | 可访问性 | 尊重 `prefers-reduced-motion: reduce`：不启动 rAF，仅绘制静态帧；画布 `aria-hidden="true"`；不改变焦点顺序 | `frontend/src/index.css:3074-3078`、背景组件 | 单测 mock `matchMedia` 为 reduce 后断言无 rAF |
| C8 | 降级 | Canvas 不可用或取色失败时保留现有 `.auth-shell` CSS 渐变背景，不抛错、不白屏 | `frontend/src/index.css:2994-3017` | jsdom 无 canvas 环境测试 |
| C9 | 切换机制 | 登录 / 注册页右下角提供一个低调的循环切换入口（5 组依次切换，显示当前组名），选择写入 `localStorage['cndb_auth_bg']`；非法值回落星座；不新增后端接口 | `AuthLayout`、`components/auth-background/preference.ts` | 切换 / 持久化 / 非法值回落单测 |
| C10 | 体积 | 背景代码只随认证页 chunk 加载，不进入主入口；新增 gzip 体积 ≤ 8 KiB；不得为体积抬高 `bundle-budget.json` 基线 | `frontend/src/App.tsx:17-19`、`frontend/scripts/bundle-budget.json:12-41` | `pnpm build` + `bundle:budget` 通过 |
| C11 | 测试 | 单测覆盖 5 组变体的挂载 / 卸载、reduced-motion、无 canvas 降级、切换持久化；更新 `AuthLayout.test.tsx`；`login` / `register` e2e 不回归 | `frontend/src/**/*.test.ts(x)`、`frontend/tests/e2e/smoke/` | `make frontend-coverage`、`make e2e` |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 认证页静态氛围背景（双径向光晕 + 细网格） | `frontend/src/index.css:2994-3017` | 新画布与其共存或替换，需保留降级 |
| 2 | 认证卡片入场动画与顶部饰线 | `frontend/src/index.css:3020-3077` | 画布层级 / 重绘不得影响 `cn-rise-in` |
| 3 | AuthLayout 容器与 420px 居中 | `frontend/src/layouts/AuthLayout.tsx:5-17` | 背景层挂载点 |
| 4 | 登录 / 注册路由 | `frontend/src/App.tsx:73-74` | 只覆盖这两条路由 |
| 5 | 主题体系（10 套 + `theme-dark` 兼容标记） | `frontend/src/theme/meta.ts:8-19`、`frontend/src/theme/ThemeProvider.tsx:34-35` | 运行时取色 + 主题切换重绘 |
| 6 | Reduced-motion 既有约定 | `frontend/src/index.css:3074-3078` | 需扩展到 JS 动效 |
| 7 | 首屏体积基线 | `frontend/scripts/bundle-budget.json:12-41` | 主入口 179,424 B 基线不可抬高 |
| 8 | 认证页单测 / e2e | `frontend/src/layouts/AuthLayout.test.tsx`、`frontend/tests/e2e/smoke/{login,register}.spec.ts` | 需扩展且不回归 |

## 已确认问题

- [x] Q1 五组风格：按「星座连线 / 星云漩涡 / 极光流光 / 数字雨 / 光点流体」定稿，5 组全部保留可选（→ C1 / C3）
- [x] Q2 切换与持久化：登录页提供切换器，选择存 `localStorage['cndb_auth_bg']`（→ C9）
- [x] Q3 覆盖范围：仅 `/login` + `/register`，不改 `/public`（→ C4）
- [x] Q4 移动端：降粒子数、DPR 1.5、目标 30fps，关闭触摸视差；桌面保留轻微鼠标视差；reduced-motion 静态帧（→ C6 / C7）
- [x] Q5 视觉基调：严格单色系，仅品牌色 + 中性色，全部经主题变量派生，不引入额外色相（→ C5）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-21）

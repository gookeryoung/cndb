# 需求卡片 0016：认证页 JS 动态背景（Perlin 流场粒子 + 多星系宇宙星系，可切换）

- 编号：0016（与 ADR `docs/adr/0016-*.md` 同号）
- 来源 / 提出人：用户口述需求（2026-10-21 六次变更）
- 日期：2026-10-21
- 关联 ADR：[0016](../adr/0016-auth-background-animation.md)
- Status：Accepted（需求方 2026-10-21 确认最终方案）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 登录背景动图，在白色底色下科技感不足，请考虑是否改为黑色。动画种类太多，请移除多余项，仅保留一个数论动画方案。

> 改回之前的数字雨方案。

> 动图改为采取Perlin 流场粒子 + 青紫渐变方案。

> 登录背景再增加可切换的背景动图：宇宙星系效果。

> 转速太快，并且缺乏星系朦胧感。

> 需要看到更多的星系，并且绕多个轴相互旋转

> 六条按时间顺序记录，第三条确定流场粒子基线，第四条在其上新增宇宙星系并要求可切换，第五、六条为星系视觉调优（降速 + 朦胧）与多星系多轴旋转。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「Perlin 流场粒子」+「再增加…宇宙星系效果」+「更多的星系，并且绕多个轴相互旋转」 | 两种动效并存：`flowfield`（固定种子 Perlin 噪声方向场驱动粒子漂移，每颗粒子保留一段环形尾迹并每帧连成流线；桌面 800 / 移动 320）与 `galaxy`（固定种子多座旋臂星系：桌面 3 座共 1600 星点 / 移动 2 座共 700 星点，每座由中心核球 + 两条对数螺线星臂 + 弥散星尘组成，大小 / 倾角 / 色相 / 自转方向各异；星点按盘面极坐标自转，再经每座独立的三轴倾斜矩阵投影，pitch / yaw / roll 以不同相位与方向缓慢进动）；默认 `flowfield` | `frontend/src/components/auth-background/flowfield.ts`、`frontend/src/components/auth-background/galaxy.ts` | `flowfield.test.ts`、`galaxy.test.ts` + 视觉走查 |
| C2 | 「请考虑是否改为黑色」 | 认证页页面底色固定近黑（`--cn-auth-bg`）；登录卡片继续跟随 10 套主题，不强制深色卡片 | `frontend/src/index.css`、`frontend/src/layouts/AuthLayout.tsx` | `AuthLayout.test.tsx`、login / register e2e；视觉走查 |
| C3 | 「科技感」+「青紫渐变」 | 深色舞台 + 青紫渐变：流线用青 → 紫 → 青三色标；星系用青 / 紫星点 + 紫色星云 + 页面双色径向光晕；不引入第三方动画库 | `frontend/src/index.css`、`frontend/src/components/auth-background/palette.ts`、`flowfield.ts`、`galaxy.ts` | `flowfield.test.ts` / `galaxy.test.ts` 色彩断言 + 视觉走查 |
| C4 | 「可切换的背景动图」 | 恢复右下角切换器：原生按钮循环切换 `flowfield` ↔ `galaxy`，即时生效；偏好写入 `localStorage['cndb_auth_bg']`，刷新后保持；非法值 / 存储不可用回落 `flowfield` | `frontend/src/components/auth-background/AuthBackgroundSwitcher.tsx`、`preference.ts`、`AuthBackground.tsx` | `preference.test.ts`、`AuthBackgroundSwitcher.test.tsx`、`AuthBackground.test.tsx`、login / register e2e |
| C5 | 性能与资源（仓库既有约定） | 单 rAF；桌面 DPR ≤ 2，移动端 DPR ≤ 1.5 且 30fps；`document.hidden` 暂停；resize 150ms 节流；桌面指针轻微扰动（流场偏转 / 星系视差），移动端关闭；切换时先 dispose 旧实例再挂新实例，不产生双循环 | `frontend/src/components/auth-background/engine.ts` | `engine.test.ts` |
| C6 | 可访问性（仓库既有约定） | `prefers-reduced-motion: reduce` 只画一次静态帧（流场预热流线 / 星系完整静帧）；画布与背景容器 `aria-hidden` + `pointer-events: none`；切换器是唯一新增可聚焦元素，`type="button"` + 明确 `aria-label` | `AuthBackground.tsx`、`AuthBackgroundSwitcher.tsx`、`index.css` | 单测 + login / register e2e |
| C7 | 降级（仓库既有约定） | `getContext('2d')` 为空或 auth token（accent / accent-alt / ink）缺失时保留 `.auth-shell` 固定深色 CSS 背景，不抛错、不白屏 | `frontend/src/components/auth-background/engine.ts` | `engine.test.ts` |
| C8 | 体积与测试（仓库既有约定） | 双动效、切换器与偏好模块同属背景 lazy chunk，不进入主入口；chunk gzip ≤ 8 KiB；单测覆盖两种动效 / 引擎 / 色板 / 偏好 / 切换器 / 组件 / 布局；login / register e2e 覆盖切换与刷新保持 | `frontend/src/layouts/AuthLayout.tsx`、`frontend/src/components/auth-background/*.test.ts(x)`、`frontend/tests/e2e/smoke/` | `pnpm build` + `bundle:budget`、`pnpm test`、e2e |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 认证页单一 Perlin 流场动效 | `frontend/src/components/auth-background/` | 新增多座星系的 `galaxy` 变体与效果元数据，引擎按 `effect` 选择实现 |
| 2 | 背景层无交互元素 | `frontend/src/components/auth-background/AuthBackground.tsx` | 恢复切换器，不能放进 `aria-hidden` 的背景层 |
| 3 | 无本地偏好 | `frontend/src/components/auth-background/preference.ts`（已删除） | 恢复 `cndb_auth_bg` 单键偏好，仅接受两个合法效果 id |
| 4 | 10 套主题体系 | `frontend/src/theme/meta.ts`、`frontend/src/theme/ThemeProvider.tsx` | 页面背景仍不跟主题；卡片仍跟主题 |
| 5 | 认证页单测 / e2e | `frontend/src/components/auth-background/`、`frontend/tests/e2e/smoke/{login,register}.spec.ts` | 补切换与持久化断言，保留 `data-effect` 契约 |
| 6 | 首屏体积基线 | `frontend/scripts/bundle-budget.json` | 背景 chunk 变大；主入口仍不变（背景整体 lazy） |

## 已确认问题

- [x] Q1 动画形态：第三条确定为 Perlin 流场粒子；第四条在其上新增宇宙星系，两者并存（→ C1）
- [x] Q2 黑色范围：仅页面背景固定近黑，登录卡片继续跟随主题（→ C2）
- [x] Q3 配色：青紫渐变，固定 token 不跟随主题品牌色（→ C3）
- [x] Q4 切换与持久化：恢复右下角切换器与 `cndb_auth_bg`，默认 `flowfield`，非法值回落（→ C4）
- [x] Q5 覆盖范围：`/login` + `/register` 共用 `AuthLayout`，同步生效（→ C2）
- [x] Q6 「改回数字雨」：同日被「Perlin 流场粒子 + 青紫渐变」覆盖，以最新口径为准（→ C1 / C3）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-21）

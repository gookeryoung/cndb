# 需求卡片：低版本浏览器性能专项（Chrome 81 等）

- 编号：0117（与 ADR `docs/adr/0117-legacy-browser-performance.md` 同号）
- 来源 / 提出人：用户（2026-11-07）
- 日期：2026-11-07
- 关联 ADR：`docs/adr/0117-legacy-browser-performance.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请针对CHROME81等低版本浏览器的性能优化提升，制定可行方案

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「针对 CHROME81 等低版本浏览器」 | 硬基线固定为 Chromium 81 / Edge 81（含内嵌 WebView），沿用 ADR 0026 的 `BROWSER_BASELINE`；其他低版本只承诺「可打开、无异常」，不承诺交互时延 | `frontend/scripts/browser-baseline.mjs`、`docs/adr/0026-chrome81-compat.md` | 基线常量唯一存在，无第二处版本号判断 |
| C2 | 「性能优化提升」 | 在参考数据集（5000 行 × 20 列）上采集并落表三项基线：首屏可交互、主题切换、视图 / 页面切换；采集口径固定为 `PerformanceObserver('longtask')` 的「最长任务」与「点击→下一帧」时延 | `frontend/scripts/chrome81-smoke.mjs`、ADR 0117「落地状态」 | 基线表写入 ADR，可复跑 |
| C3 | 「性能优化提升」 | 旧内核一次主题切换触发的同步 `getComputedStyle` 次数为常数（≤ 1 次快照读），`--cn-mix-*` 写入批量完成；重复切回同一主题时命中缓存、不重复写值 | `frontend/src/theme/themeMix.ts`、`frontend/src/index.css` | 单测统计读取次数 + Chromium 81 冒烟 |
| C4 | 「性能优化提升」 | 兼容垫片的常驻开销可度量、可切片、可熔断：flex-gap 扫描按空闲切片执行（单次 ≤ 8ms）、待扫描根去重、非 flex 子树不做全量子树扫描；现有 `__CNDB_DISABLE_FLEX_GAP_SHIM__` 保留并在冒烟中验证「熔断后布局不崩」 | `frontend/src/compat/flexGap.ts` | 单测（节点规模 + 预算）+ 冒烟 |
| C5 | 「性能优化提升」 | 长列表沿用现有虚拟化：主表、看板、甘特在参考规模下只挂载可视窗口；低版本不另建渲染路径 | `frontend/src/pages/grid/gridTableSection.tsx`、`frontend/src/pages/grid/views/{kanban,gantt}/` | e2e 断言可见行数与 DOM 节点数上限 |
| C6 | 「制定可行方案」 | 性能门禁可判定：`chrome81-smoke.mjs` 增加性能断言，超阈值以非 0 退出；阈值集中在单一常量文件，禁止散落数字 | `frontend/scripts/chrome81-smoke.mjs`、`frontend/scripts/perf-budget.mjs` | 定时 CI 红 / 绿可判定 |
| C7 | 「CHROME81 等低版本」 | 降级只按能力探测，不按 UA 版本号；能力探测收敛到单一模块，新增低版本分支必须复用 | `frontend/src/compat/` | 代码检查：`navigator.userAgent` 只允许出现在基线脚本 |
| C8 | 「性能优化提升」（不回归） | 现代内核不新增降级：原生 `color-mix()`、原生 flex gap、主题平滑过渡保持；既有 Playwright e2e 全绿 | `frontend/src/theme/`、`frontend/src/index.css`、`frontend/tests/e2e/` | `make flow` + 前端 e2e |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | flex-gap 垫片常驻扫描 | `frontend/src/compat/flexGap.ts:153-158`、`:196-214` | 监听 `body` 子树 `childList` + `class/style`；新增节点整棵 `querySelectorAll('*')`，每元素多次 `getComputedStyle`（`:91-129`） |
| 2 | 主题 `--cn-mix-*` 兜底重算 | `frontend/src/theme/themeMix.ts:259-270` | 旧实现边读边写，旧内核读写交替触发多次全量样式重算（本次已改快照） |
| 3 | 全页主题过渡规则 | `frontend/src/index.css:44` | 旧实现给全树（含伪元素）挂 transition，旧内核一次切换建立大量过渡（本次已按能力门控） |
| 4 | 旧内核冒烟无性能断言 | `frontend/scripts/chrome81-smoke.mjs`、`frontend/tests/e2e/critical/browser-compat.spec.ts` | 只断言功能 / 视觉，时延与长任务不可判定 |
| 5 | 大表渲染 | `frontend/src/pages/grid/gridTableSection.tsx:224` | 主表已 `virtual={true}`，可排除「整表重挂」作为主因 |
| 6 | 兼容层装载入口 | `frontend/src/main.tsx:101-102`、`frontend/src/compat/index.ts:10-15` | 首次渲染后按能力动态加载，现代内核不下载垫片 |
| 7 | 图表 / Dashboard 主题切换重建 | `frontend/src/pages/grid/views/dashboard/` | 是否 `key` 强制重建图表实例待 ADR 核实 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题（已结论，2026-11-07 需求方确认）

- [x] 覆盖范围：仅 Chromium 81 / Edge 81 为硬基线；Firefox ESR / Safari 只保「可打开」。
- [x] 降级授权：允许旧内核关闭装饰性效果（全页过渡、阴影、模糊），保留颜色瞬时切换与可读性对比度。
- [x] flex-gap 垫片：保留运行时垫片，增加去重 / 非 flex 短路 / 空闲切片预算 / 熔断；不做构建期 CSS 后处理。
- [x] 参考数据集与阈值：5000 行 × 20 列；初值「主题切换 ≤ 200ms、视图切换 ≤ 800ms、首屏可交互 ≤ 3000ms、单次长任务 ≤ 250ms」，P0 实测后只收紧不放松。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-07）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

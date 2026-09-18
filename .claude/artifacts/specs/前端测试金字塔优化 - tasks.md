# 前端测试金字塔优化 - 实施计划

> 派生自同目录 `spec.md`（AC-1~AC-10）。任务为依赖有序的垂直切片；每个任务完成须附 Completion Evidence（rule 给出命令输出/产物，rubric 给出分数+理由+证据）。

## Task 1: Vitest 测试基础设施
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 安装 devDependencies：`vitest`（选与 Vite 6 peer 兼容的稳定线）、`@vitest/coverage-v8`、`jsdom`、`@testing-library/react`、`@testing-library/user-event`、`@testing-library/jest-dom`、`msw@^2`
  - `frontend/vite.config.ts` 改用 `vitest/config` 的 `defineConfig`（向后兼容既有 Vite 字段，syncStaticPlugin/build 行为不变），新增 `test` 字段：environment=jsdom、globals、setupFiles、复用 `@` alias、coverage（provider=v8，include=src，exclude 测试与生成物）
  - 新建 `frontend/src/test/setup.ts`：jest-dom 匹配器、antd 所需 polyfill（matchMedia/ResizeObserver/getBoundingClientRect/scrollTo）、RTL 自动 cleanup、每个用例后清空 localStorage/sessionStorage
  - `package.json` 增加 scripts：`test`（vitest run）、`test:watch`、`test:coverage`
  - 先落 1 个冒烟测试验证链路；确认 `pnpm build` / `pnpm typecheck` / `pnpm lint` 无回归
- **Acceptance Criteria Addressed**: AC-1（基建部分）、AC-10
- **Test Requirements**:
  - `rule` TR-1.1: `pnpm test` 运行冒烟测试退出码 0（证据：命令输出）
  - `rule` TR-1.2: `pnpm build`、`pnpm typecheck`、`pnpm lint` 全部退出码 0（证据：输出）
  - `rubric` TR-1.3: 配置最小化与复用度；scale 1-5；anchors 1=大量重复/另起炉灶，3=可读可维护，5=完全复用既有 alias/插件且 test 配置独立成段清晰；threshold >= 4（证据：vite.config.ts diff）

## Task 2: grid 领域纯逻辑单元测试
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `fieldOps.test.ts`：操作符映射按类型、别名解析（long_text/decimal/multi_select/rich_text/link_to_table）、`extractSelectOptions` 双格式（string[] / {label,value,color}[]）、空 config、过滤空 value
  - `fieldValueFormat.test.ts`：formatLinkValue（数组/单对象/裸值/空）、formatMultiSelectValue（数组/逗号串/空）、getSelectLabel（命中/未命中/无 options）、extractImageUrl（string/对象/数组/非法）、formatFieldDisplayValue 各 field_type 分支（boolean 是/否、空值短路）
  - `dateUtils.test.ts`：parseDate（date/datetime/非法/null）、fmtDate 补零、daysFromToday 正负零
  - `viewOptionSchema.test.ts`：getOptionSchema 五种视图 + 未知类型空、`_fieldMatchesSchema`（`__all__` 排除 hidden、is_primary、别名）、`resolveFieldOptions`、`resolveOpts`（undefined→defaultValue、switch false 不回退、schema 外字段保留）、`resolveAutoField`（优先级顺序、includePrimary、literalFallback）
- **Acceptance Criteria Addressed**: AC-3、AC-2（前置数据）
- **Test Requirements**:
  - `rule` TR-2.1: 四个测试文件存在且 `pnpm test` 全部通过（证据：输出）
  - `rule` TR-2.2: 上述边界/异常路径均有显式断言（证据：用例清单核对）
  - `rubric` TR-2.3: 用例质量；scale 1-5；anchors 1=测实现细节/共享状态，3=基本 AAA 可读，5=行为导向+describe 分组清晰+数据表驱动；threshold >= 4（证据：代码抽查）

## Task 3: 通用工具单元测试
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `tagColors.test.ts`：getTagColorName 同值同色（hash 稳定）、空值回退 blue、resolveTagColor 三路径（options 已存 color 优先 → 语义推荐 → 调色板 index fallback）、suggestColorForLabel 典型语义（紧急/已完成/低风险/数字等级/字母等级）与无匹配 null、`__resetTagColorCache` 生效、ANTD_COLOR_NAMES 导出完整（31 项）
  - `useResponsive.test.ts`：getDeviceType 边界（767/768/1023/1024/1279/1280）、SSR 安全（window undefined 分支）、hook resize 防抖 100ms（fake timers）
  - `jinja2Highlight.test.ts`：`{{}}`/`{%%}`/`{##}` 三类 token 识别与 class 命名、混排文本、无 token 时空 DecorationSet（经 EditorState.create 构建验证）
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-3.1: 三个测试文件存在且全部通过（证据：输出）
  - `rule` TR-3.2: 缓存重置、fake timers、SSR 分支均有验证（证据：用例清单）
  - `rubric` TR-3.3: 用例质量；同 TR-2.3 锚点；threshold >= 4（证据：代码抽查）

## Task 4: 数据层单元测试
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `api/client.test.ts`：getToken/setToken/clearToken（含 localStorage 异常 try/catch 分支）、请求拦截器注入 Authorization、multipart 删除 Content-Type、响应拦截器 detail 三种形态归一化（string/数组/对象）、401 → clearToken + `/login?return_to=` 重定向（含 /login、/public 路径排除）
  - `store/auth.test.ts`：login 成功置 token+user、register 成功自动登录、logout 清理、refresh 无 token/loading/失败清理三分支、persist partialize 仅 token
  - `store/gridView.test.ts`：全部 setters、updateViewFilters/updateViewSortings 函数式更新、patch 批量、reset 回初值
  - `store/tableSettings.test.ts`：按既有 actions 覆盖（实施时先读该 store 定用例）
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-4.1: 四个测试文件存在且全部通过（证据：输出）
  - `rule` TR-4.2: 401 重定向、detail 归一化、persist 边界、reset 等关键行为有断言（证据：用例清单）
  - `rubric` TR-4.3: 用例质量；同 TR-2.3 锚点；threshold >= 4（证据：代码抽查）

## Task 5: 覆盖率双门槛校验
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2, 3, 4
- **Description**:
  - 新建 `frontend/scripts/check-coverage.mjs`：读取 coverage/coverage-summary.json；核心集合（FR-2/FR-3 全部模块 glob，含 Task 11 抽取产物）断言 lines>=90 且 branches>=85；全局 src 断言 lines>= 水位常量（首版 30 起步，按首跑实际校准为 30~实际值间的 5 的整数倍并回写常量）；不达标列出明细并以非 0 退出
  - `test:coverage` 串联 `vitest run --coverage` + 校验脚本；用达标/不达标两份 fixture JSON 验证脚本逻辑
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `rule` TR-5.1: 校验脚本对 fixture（达标/不达标各一）输出正确退出码与明细（证据：命令输出）
  - `rule` TR-5.2: `pnpm test:coverage` 实跑通过，报告可见核心集合与全局实际值均达标（证据：输出）
  - `rubric` TR-5.3: 报告可读性；scale 1-5；anchors 1=只有退出码，3=列出差距，5=按模块列出阈值/实际/差距；threshold >= 4（证据：脚本输出样例）

## Task 6: 组件测试设施（renderProviders + MSW）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `src/test/render-providers.tsx`：统一 render（QueryClientProvider retry=false + MemoryRouter + antd ConfigProvider/ThemeProvider），导出可传入初始 route/store 状态的选项
  - `src/test/msw.ts`：setupServer + handlers（登录、me、workspaces、tables、fields、records 等组件测试所需端点），`onUnhandledRequest: 'error'`；setup.ts 中 beforeAll/afterEach/afterAll 接入（resetHandlers/重置 storage/store）
  - 冒烟：1 个经 MSW 的小型组件测试验证设施
- **Acceptance Criteria Addressed**: AC-4（前置）
- **Test Requirements**:
  - `rule` TR-6.1: MSW 冒烟测试通过，且人为制造未命中请求时报错（证据：输出）
  - `rubric` TR-6.2: 设施易用性；scale 1-5；anchors 1=每个测试重复搭 provider，3=可复用但选项少，5=一行 render + 按需注入；threshold >= 4（证据：Task 7 使用效果）

## Task 7: ProtectedRoute 组件测试
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 6
- **Description**:
  - 三态：loading → Spin；未登录 → 重定向 `/login?return_to=<encodeURIComponent(当前路径+query)>`；已登录 → 渲染 children
  - auth store 状态注入用 renderProviders 选项，MSW 仅用于 /me 响应
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-7.1: 三态断言全部通过（证据：输出）
  - `rubric` TR-7.2: 行为导向（断言 URL/可见元素而非 store 内部）；同 TR-2.3 锚点；threshold >= 4（证据：代码）

## Task 8: GridCell 组件测试
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 6
- **Description**:
  - 按字段类型渲染：text/number 直接显示、boolean 是/否、select 显示 label、multiselect 逗号连接、link 取 value、空值空白
  - 行内编辑（InlineEditCellProps）：编辑控件渲染、onFieldChange 更新草稿、onFieldCommit/回车提交触发保存回调（mock 回调断言参数）
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-8.1: 类型渲染与编辑回调断言全部通过（证据：输出）
  - `rubric` TR-8.2: 用例质量；同 TR-2.3 锚点；threshold >= 4（证据：代码抽查）

## Task 9: ColumnFilterDropdown 组件测试
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 6
- **Description**:
  - 操作符列表随 field.field_type 联动（getOpsForField 驱动）；needValue=true 的操作符无值输入控件；值类操作符出现对应 valueKind 输入；选择操作符+填值 → 应用回调带 (fieldName, op, value)；重置 → onFilterReset
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-9.1: 联动/needValue/应用/重置断言全部通过（证据：输出）
  - `rubric` TR-9.2: 用例质量；同 TR-2.3 锚点；threshold >= 4（证据：代码抽查）

## Task 10: 视图配置表单组件测试
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 6
- **Description**:
  - 目标：`CreateEditViewForm`（备选 `ViewConfigDialog`，实施时取依赖更轻者，证据中说明）
  - 断言：kanban schema 驱动渲染全部字段项、required 项（group_field）缺失被校验阻止、defaultValue 回填（card_sort_direction=desc、urgent_threshold_days=3）、fieldTypes 过滤后下拉仅含匹配字段
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-10.1: 渲染/校验/默认值/过滤断言全部通过（证据：输出）
  - `rubric` TR-10.2: 用例质量；同 TR-2.3 锚点；threshold >= 4（证据：代码抽查）

## Task 11: 大组件纯函数抽取 + 单测
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - 候选清单（实施时逐个判定 UI 耦合度，不强抽的记录取舍理由）：
    1. `views[] → 可用视图模式集合`推导（GridPage 内联，view-mode-switch 矩阵的行为核心）
    2. 看板卡片排序与分组键（KanbanView，含紧急置顶逻辑）
    3. 甘特日期区间/刻度计算（GanttView）
  - 抽取为独立模块（如 `src/pages/grid/components/viewModes.ts` 等），GridPage 等改为引用；行为零变更；每模块配单测（对照原逻辑断言等价）
- **Acceptance Criteria Addressed**: AC-3（FR-3）、AC-5（前置）
- **Test Requirements**:
  - `rule` TR-11.1: 抽取模块有单测且与原行为等价（证据：单测 + 引用点 diff）
  - `rule` TR-11.2: 抽取后 `pnpm typecheck`/`pnpm lint` 通过，E2E 不在此阶段运行（由 Task 12 统一验证）（证据：输出）
  - `rubric` TR-11.3: 抽取取舍说明完备（抽/不抽均有理由）；scale 1-5；anchors 1=无说明，3=部分说明，5=逐候选说明；threshold >= 4（证据：任务证据文本）

## Task 12: E2E 下沉精简
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2, 3, 4, 11
- **Description**:
  - `view-mode-switch.spec.ts`：5 行"表→按钮数"矩阵收敛为代表性 1 例（如科研项目 3 按钮）+ 跨表导航 1 例 + 点击切换 1 例；矩阵全量断言下沉为 Task 11 推导函数的单测
  - `navigation.spec.ts`：owner 筛选断言若已由组件/集成层等价覆盖则移除该条（映射表记录）；Header 可达性等链路断言保留
  - `row-crud.spec.ts`：必填校验两条合并保留链路断言（"新增→校验→填写→保存→清理"）
  - 产出下沉映射表（E2E 移除断言 ↔ 下层用例 ID，记录于任务证据）；确保用例总数 ≤ 26
  - 运行 `make e2e` 全绿（webServer 自动隔离后端）
- **Acceptance Criteria Addressed**: AC-5、AC-9
- **Test Requirements**:
  - `rule` TR-12.1: `make e2e` 退出码 0 且用例计数 ≤ 26（证据：输出）
  - `rule` TR-12.2: 下沉映射表逐条对应下层等价覆盖（证据：映射表）
  - `rubric` TR-12.3: 精简后 E2E 仅含端到端链路断言；scale 1-5；anchors 1=仍含大量逻辑断言，3=少量残留，5=纯链路；threshold >= 4（证据：spec diff 审查）

## Task 13: 门禁接入（Makefile + CI）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5
- **Description**:
  - `Makefile`：`frontend-check` 在 typecheck+lint 后追加 `pnpm test:coverage`（若耗时超预期可先 `pnpm test` + 单独 coverage 目标，以实测为准）
  - `.github/workflows/ci.yml`：`frontend-check` job 增加"Frontend tests + coverage"步骤（强制门禁，不设 continue-on-error）；e2e job 维持观察期策略不变
- **Acceptance Criteria Addressed**: AC-6
- **Test Requirements**:
  - `rule` TR-13.1: 本地 `make check` 全绿（含前端测试阶段）（证据：输出）
  - `rule` TR-13.2: CI YAML 审查：frontend-check job 含测试步骤且无 continue-on-error（证据：diff）

## Task 14: 测试约定落地 + 全量验收
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 7, 8, 9, 10, 12, 13
- **Description**:
  - FR-7 约定落地执行核对：就近 `*.test.ts(x)`、AAA、中文 describe/test、隔离设施统一走 setup.ts（不新建 md 文件，约定以 spec.md FR-7 + setup.ts/eslint 注释承载）
  - AC-7：`pnpm test` 连续 3 次计时取中位数（目标 ≤ 15s）
  - AC-8/AC-9：对照锚点自评并附证据（三层用例计数：单元/组件/E2E）
  - AC-10 + AC-1/2/6：最终 `make check` 全绿复核
- **Acceptance Criteria Addressed**: AC-1、AC-2、AC-6、AC-7、AC-8、AC-9、AC-10
- **Test Requirements**:
  - `rule` TR-14.1: 三层用例计数产出且 E2E ≤ 26（证据：计数清单）
  - `rule` TR-14.2: `make check` 最终全绿（证据：输出）
  - `rubric` TR-14.3: AC-7 速度；scale 1-5；anchors 1=>45s，3=≤25s，5=≤10s；threshold >= 4 即 ≤15s（证据：3 次计时记录）
  - `rubric` TR-14.4: AC-8 质量综合；scale 1-5；同 spec AC-8 锚点；threshold >= 4（证据：抽查 + 隔离设施审查）

## 完成定义（队列排空标准）

- 全部任务 `completed` 或经用户批准 `cancelled`；
- spec.md 全部 AC 在任务证据中可追溯；
- 最终 `make check` 全绿、`make e2e` 全绿；
- 独立 Review 通过（review.md 在 Review 阶段创建）。

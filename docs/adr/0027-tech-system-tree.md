# ADR 0027: 科研项目管理新增技术体系表与「技术脉络」树形视图

Status: Accepted（已评审；P0-P1 已落地）
Date: 2026-10-24
Related: `docs/requirements/0027-research-tech-system-tree.md`、`src/cndb/cli/seed/datasets.py`、`src/cndb/cli/seed/fields.py`、`src/cndb/cli/seed/views.py`、`frontend/src/pages/grid/views/TreeView.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`examples/datasets/工作区-科研项目管理/views.json`、`examples/datasets/工作区-科研项目管理/fields.json`
需求卡片: `docs/requirements/0027-research-tech-system-tree.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C7），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 科研项目管理，数据表，增加技术体系数据 | 新增 `examples/datasets/工作区-科研项目管理/技术体系.csv`；seed 按文件名自动建表，无需注册表或写代码 |
| C2 | 增加技术体系数据 | 列固定为 `技术编号,父技术编号,技术名称,技术方向,技术层级,成熟度`；`技术方向 / 技术层级 / 成熟度` 为低基数列，由 CSV 推断提升为 select |
| C3 | 增加技术体系数据 | 种子 43 行：6 个技术方向、4 层（领域 / 方向 / 技术 / 专项）；根节点 `父技术编号=ROOT`，其余父引用必须是已存在的 `技术编号`，无环、无孤儿 |
| C4 | 增加技术体系数据 | `fields.json` 的 `技术体系.settings`：`技术编号` required + unique，`技术名称` required；不新增 `link_lookups` / `backfills` |
| C5 | 树形视图标识技术脉络 | `views.json` 的 `技术体系`：`grid`「全部」（默认，按 `技术编号` 升序）+ `tree`「技术脉络」（`parent_field=父技术编号`、`title_field=技术名称`、`status_field=成熟度`、`show_numbering=false`、`expand_all=true`） |
| C6 | 树形视图标识技术脉络 | 复用已注册的 `tree` 模式与 `TREE_OPTIONS`；不改前端组件、视图 schema、路由与后端接口 |
| C7 | （交付约束） | 不补文档、不建项目表字段、不加跨表关联；既有 7 张表的结构与关联保持不变 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 示例工作区按目录下 `*.csv` 自动建表，文件名即表名，无白名单 | `src/cndb/cli/seed/datasets.py:192-203` | 新增 CSV 即生效，无需改 seed 编排 | 确认 |
| 2 | `fields.json` 的 `settings` 按「表名 → 字段名 → required/unique」改写字段标志，缺失仅打印跳过 | `src/cndb/cli/seed/fields.py:222-238` | 新表可直接声明约束，不影响既有表 | 确认 |
| 3 | CSV 建表对低基数 text 列自动提升 select（小样本 ≤20 行允许 ≤15 唯一值、比例 ≤0.80；<100 行 ≤25 唯一值、比例 ≤0.60） | `src/cndb/plugins/tables/services/transfer/normalize/promote.py:21-79` | 4 档成熟度、4 层层级、6 个方向均会提升为 select，供树视图状态徽章使用 | 确认 |
| 4 | 视图种子保存前校验 `parent_field` / `title_field` / `status_field` 等引用字段存在 | `src/cndb/cli/seed/views.py:34-87` | 视图配置字段名必须与 CSV 表头逐字一致，否则整条视图被跳过 | 确认 |
| 5 | 视图种子按表名写入；同名「全部」更新自动生成的默认视图；`scope=global` → `ViewVisibility.TABLE` | `src/cndb/cli/seed/views.py:210-293` | 新表默认视图与树视图均走表内共享，不新增权限面 | 确认 |
| 6 | Tree 视图把 `parent_field` 业务值反查到父行；`ROOT` 等无法命中的值按根节点处理；含循环检测 | `frontend/src/pages/grid/views/TreeView.tsx:95-195` | 文本父编号方案可用，无需 link 自关联 | 确认 |
| 7 | `tree` 模式已在 `ViewMode` / `VALID_MODES` 注册，配置项由 `TREE_OPTIONS` 定义 | `frontend/src/pages/grid/views/viewModes.ts:11-14`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts:229-253` | 零前端改动即可打开树视图 | 确认 |
| 8 | 既有 tree 种子范例为「科研任务分解 / 任务层级树」，同为文本父编号 | `examples/datasets/工作区-科研项目管理/views.json:799-816` | 本次配置形态可对齐，降低校验风险 | 确认 |
| 9 | 真实数据集完整性测试会静态解析 CSV 表头 + `views.json` 引用，并校验视图类型与字段可达 | `tests/test_backup_seed_roundtrip.py:335-562`、`tests/test_seed_project_todo.py:252-298` | 新表 / 新视图自动纳入，另需专属父子完整性测试 | 新增 |
| 10 | 现有科研项目管理工作区共 7 张表（科研项目 / 课题负责人 / 科研经费 / 项目进展 / 科研任务分解 / 科研待办事项 / 科研资源排期），无跨项目技术对象 | `examples/datasets/工作区-科研项目管理/`、`src/cndb/cli/seed/fields.py:20-27` | 任务分解树只表达单项目 WBS，不能表达跨项目技术脉络 | 新增 |

**核心缺陷（需求要补的）**：现有示例工作区只有「项目 / 任务 / 经费 / 进展」等管理对象，缺少可跨项目复用的技术能力对象及其层级关系；`科研任务分解` 树是单项目 WBS，父节点语义是任务拆分，无法用来标识技术演进脉络。

设计目标（不变量）：

- **I1 零 DDL / 零迁移**：只新增 seed CSV 与视图配置，不产生数据库结构变更。
- **I2 父子完整性**：每行 `父技术编号` 必须命中同表 `技术编号` 或 `ROOT`；从根可达、无环、无孤儿。
- **I3 能力边界不变**：不新增端点、权限档位、前端视图类型；树视图沿用既有 `tree` 模式与表档可见性。
- **I4 既有数据不变**：现有 7 张表的表头、字段设置、关联规则与视图均不改动。

## Decision

### 1. 数据模型

无迁移。新增 seed 表 `技术体系`，由 CSV 建表；列与推断类型：

| 列 | 含义 | 推断类型 | 约束 |
|---|---|---|---|
| `技术编号` | 技术节点唯一标识（`T...` 编码） | text | required + unique，seed 视图按此升序 |
| `父技术编号` | 父节点 `技术编号`；根节点填 `ROOT` | text | 非必填；必须命中同表编号或 `ROOT` |
| `技术名称` | 节点显示名 | text | required |
| `技术方向` | 所属一级方向（根节点同名） | select | 6 个取值，随 CSV 提升 |
| `技术层级` | 领域 / 方向 / 技术 / 专项 | select | 4 个取值，随 CSV 提升 |
| `成熟度` | 探索期 / 培育期 / 成长期 / 成熟期 | select | 4 个取值，树视图状态徽章 |

数据规模：43 个节点，6 个根（人工智能 / 先进制造 / 新能源 / 新材料 / 生物医药 / 信息技术），最深 4 层。父子关系使用文本业务编号而非 link 自关联，理由见 D2。

### 2. 判定算法（唯一入口）

无新增判定入口。层级构建完全复用 `frontend/src/pages/grid/views/TreeView.tsx` 的 `buildTree`：`父技术编号` 业务值经反查映射到父行；`ROOT` 未命中任何行，按根节点处理；循环引用由 `visited` 防御。数据侧保证不出现无效父引用，前端防御仅作兜底。

### 3. API 变更清单

无。不新增 / 修改任何端点；视图通过既有 `GET /api/v1/workspaces/{wid}/tables/{tid}/views` 与行查询接口读取。

### 4. 边界与例外

1. 根节点统一写 `ROOT`（与既有 `科研任务分解.父任务ID` 口径一致），不写空串，便于 CSV 与看板复用。
2. `技术方向` 在根节点与后代节点重复填写，保证按方向筛选 / 分组时无需回溯祖先。
3. 不建立 `技术体系` 与 `科研项目` 的 link 关联；项目归属技术脉络不在本需求范围（D5）。
4. 树视图不显示层级编号（`show_numbering=false`），节点右侧以 `成熟度` 徽章与子项数量表达状态。
5. 任何父引用失效时，前端按根节点展示（既有行为），但 seed 数据测试必须拦截该类数据进入仓库。

### 5. 迁移

无。`技术体系` 由 seed 在全新库建表；已部署实例不跑 seed 则不受影响，也不产生空表。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 树视图组件 | `frontend/src/pages/grid/views/TreeView.tsx` | 无 |
| 视图配置 schema | `frontend/src/pages/grid/view-config/viewOptionSchema.ts` | 无（复用 `TREE_OPTIONS`） |
| 视图模式注册 | `frontend/src/pages/grid/views/viewModes.ts` | 无（`tree` 已注册） |

### 7. 测试清单

**判定层（单测）**：无新增前端逻辑。以下数据侧校验放在新增的 `tests/test_seed_tech_system.py`：

- CSV 表头逐字匹配、行数 43、`技术编号` 唯一；
- 每个 `父技术编号` ∈ 同表编号 ∪ `{ROOT}`；
- 从根可达全部节点、无环、无孤儿；
- 覆盖 ≥4 个技术方向、≥3 层；
- `fields.json` 的 `技术体系.settings` 断言；
- `views.json` 的 `技术体系` 视图数量、默认视图、tree 的 5 项 `view_options` 断言。

**接口层**：无新增用例（无接口变更）。

**迁移 / 备份**：`tests/test_backup_seed_roundtrip.py` 的真实数据集完整性用例自动覆盖新表：`view_type` 合法、视图名 / order 唯一、`parent_field` 等引用可在 CSV 表头解析。

**seed 集成（DB）**：在临时 datasets 目录放 `技术体系.csv` + `fields.json` + `views.json`，按 `test_seed_project_todo.py` 的既有模式跑 `_seed_datasets` → `_apply_field_settings` → `_seed_views`，断言：

- 表建成且行数一致，`技术方向 / 技术层级 / 成熟度` 字段类型为 `select`；
- `技术编号` 的 required / unique 标志生效；
- `全部` 为默认 grid、`技术脉络` 为 tree 且 `view_options` 落库正确。

**e2e（前端）**：不新增。无前端改动，树组件行为由 `frontend/src/pages/grid/views/TreeView.test.tsx` 既有用例覆盖；`make e2e` 仍按硬门禁执行全量。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `技术体系.csv` 数据、`fields.json` 设置、`views.json` 两个视图、静态完整性测试 | 低（纯 seed 数据，失败只跳过单表 / 单视图） |
| **P1** | seed 集成（DB）测试、真实数据集完整性回归、文档与门禁收尾 | 低（零迁移、零接口、零前端改动） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 技术体系数据的载体 | 新建独立 `技术体系` 表 | 「技术脉络」是独立于项目的技术能力图谱，需多层级、可复用；独立表可直接用 tree 视图 | 只在 `科研项目` 加分类字段（单值、无法表达层级）；并入 `科研任务分解`（任务拆分与长期技术脉络语义混叠） | `examples/datasets/工作区-科研项目管理/技术体系.csv` |
| D2 | 父子关系的表达 | 文本业务编号 `父技术编号` + `ROOT` | 与既有 WBS 树同口径；CSV 建表即用，TreeView 支持业务值反查，无需 link 结构与回填 | link 自关联（需 `fields.json` link_lookups + 行关联回填，seed 步骤更多、失败面更大）；物化路径 / 层级编码（需额外维护，收益仅排序） | `技术体系.csv`、`cli/seed/views.py` |
| D3 | 树视图形态 | `tree`「技术脉络」：标题=技术名称、状态=成熟度、默认展开、不显示编号 | 通用层级浏览语义，不引入任务进度 / 负责人等 WBS 语义；成熟度是技术脉络最有信息量的状态 | `wbs`（带进度汇总与编号，语义偏任务）；`leader_line` 类新视图（需新前端类型，超出需求） | `views.json`、`viewOptionSchema.ts:229-253` |
| D4 | 数据口径 | 6 个技术方向、4 层（领域 / 方向 / 技术 / 专项）、43 个节点；成熟度 4 档 | 覆盖多领域与多层演进，满足「标识脉络」；低基数列可稳定推断 select | 只放 1-2 个方向（看不出跨领域脉络）；每列自由文本（无法提升 select、状态徽章失效） | `技术体系.csv` |
| D5 | 与 `科研项目` 的关系 | 不建关联 | 需求只要求技术体系数据与树形视图；建 link 会牵动 fields.json 回填与项目表结构 | 在项目表加 `技术体系` 关联字段（改动既有表，违反 C7）；新建项目-技术映射表（超出需求） | `examples/datasets/工作区-科研项目管理/科研项目.csv`（不改） |
| D6 | 代码改动范围 | 零后端接口、零前端代码、零迁移 | 现有 seed 机制与 tree 模式已能承载；最小改动降低回归面 | 为新表写专用 seed 代码或新视图类型（重复既有能力） | `cli/seed/datasets.py`、`views/TreeView.tsx`（不改） |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：科研示例工作区补上跨项目的技术能力图谱；技术脉络一眼可读（方向 → 技术 → 专项）；纯 seed 数据落地，零迁移、零接口、零前端回归面；新表自动进入备份 / 完整性测试。
- **负向**：`技术体系` 与 `科研项目` 暂无关联，用户需自行按名称对照；技术数据是静态示例，不随项目进展自动更新。
- **风险与缓解**：父引用写错会导致节点被前端当作根节点静默展示，故用数据测试强制校验父子完整性与无环；低基数推断若因行数变化失效，select 徽章退化为文本展示，不影响树结构。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 视图可见性 | `DataView.visibility` / `scope_key` | seed `scope=global` → 表档，工作区成员均可见 | ADR 0003 |
| 视图配置 schema | `viewOptionSchema.ts` | 复用 `TREE_OPTIONS`，不新增配置项 | ADR 0022（schema 单一真相源约定） |
| 层级视图 | `TreeView.tsx` / `viewModes.ts` | 不新视图类型，沿用 tree | 本 ADR D3 / D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `examples/datasets/工作区-科研项目管理/技术体系.csv`、`examples/datasets/工作区-科研项目管理/fields.json`、`examples/datasets/工作区-科研项目管理/views.json` | `tests/test_seed_tech_system.py` | 0dc2e12f |
| P1 | 已落地 | `examples/datasets/工作区-科研项目管理/技术体系.csv`、`examples/datasets/工作区-科研项目管理/fields.json`、`examples/datasets/工作区-科研项目管理/views.json` | `tests/test_seed_tech_system.py`、`tests/test_backup_seed_roundtrip.py` | 0dc2e12f |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P1 已落地（Status 已定 Accepted）
- 已完成：`技术体系.csv`（43 行 / 6 方向 / 4 层）、`fields.json` 设置、`views.json` 双视图、`tests/test_seed_tech_system.py` 9 例；真实数据集完整性回归随 `make flow` 全量通过
- 下一步：无（落地表「提交」列已回填 `0dc2e12f`）；如需 `Status=Implemented` 由人确认
- 已知坑：视图种子对字段名逐字校验，CSV 表头与 `views.json` 必须完全一致；`ROOT` 不是合法技术编号，仅作为根标记；低基数 select 推断依赖行数与唯一值比例，新增行时勿让 `技术方向 / 技术层级 / 成熟度` 变成高基数列
- 最近一次全绿：`make flow`（2026-10-24，5329 passed / 3 skipped）

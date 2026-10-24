# 需求卡片：科研项目管理新增技术体系数据与「技术脉络」树形视图

- 编号：0027（与 ADR `docs/adr/0027-*.md` 同号）
- 来源 / 提出人：用户口述需求
- 日期：2026-10-24
- 关联 ADR：`docs/adr/0027-tech-system-tree.md`（Proposed，待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 科研项目管理，数据表，增加技术体系数据和树形视图标识技术脉络。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 科研项目管理，数据表，增加技术体系数据 | 在「科研项目管理」示例工作区新增数据表 `技术体系`，以 `examples/datasets/工作区-科研项目管理/技术体系.csv` 为种子；seed 的 CSV 自动发现机制负责建表。 | `examples/datasets/工作区-科研项目管理/`、`src/cndb/cli/seed/datasets.py` | seed 后该工作区存在 `技术体系` 表且行数等于 CSV 数据行数 |
| C2 | 增加技术体系数据 | 表结构固定为：`技术编号`（唯一标识）、`父技术编号`（指向同表父节点，根节点填 `ROOT`）、`技术名称`、`技术方向`、`技术层级`、`成熟度`。低基数列（技术方向 / 技术层级 / 成熟度）随 CSV 推断为 select，供树视图状态徽章使用。 | CSV 建表推断 | 字段名与类型断言：`技术方向` / `技术层级` / `成熟度` 为 select |
| C3 | 增加技术体系数据 | 数据覆盖不少于 4 个技术方向、不少于 3 层父子层级；每个 `父技术编号` 必须是同表已存在的 `技术编号` 或 `ROOT`，禁止孤儿节点与循环引用。 | `技术体系.csv` | 测试校验唯一性、父子存在性、从根可达性与无环 |
| C4 | 增加技术体系数据 | `fields.json` 的 `settings` 为 `技术体系` 声明：`技术编号` required + unique，`技术名称` required；不新增 `link_lookups` / `backfills`，不改动现有表字段。 | `examples/datasets/工作区-科研项目管理/fields.json` | 解析 fields.json 并断言设置项；seed 后字段标志生效 |
| C5 | 树形视图标识技术脉络 | `views.json` 的 `技术体系` 键下配置 2 个视图：默认 `grid`「全部」（按 `技术编号` 升序）+ `tree`「技术脉络」；tree 的 `view_options` 为 `parent_field=父技术编号`、`title_field=技术名称`、`status_field=成熟度`、`show_numbering=false`、`expand_all=true`。 | `examples/datasets/工作区-科研项目管理/views.json`、`src/cndb/cli/seed/views.py` | 解析 views.json 并断言；seed 后视图落库且 `view_type` / `view_options` 正确 |
| C6 | 树形视图标识技术脉络 | 树视图完全复用现有 `tree` 视图能力，不改动前端树组件、视图 schema、路由或后端视图接口。 | `frontend/src/pages/grid/views/TreeView.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts` | 变更文件清单不含前端源码与后端接口源码 |
| C7 | （交付约束） | 本需求不补示例文档，不新增跨表关联，不新建项目表字段。 | `documents/`、`科研项目.csv` | 变更文件清单不含 docs 与既有 CSV |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 示例工作区 CSV 自动建表：目录下新增 `*.csv` 即建表，无需注册 | `src/cndb/cli/seed/datasets.py:192-203` | 新增 CSV 自动生效；无白名单 |
| 2 | 字段设置种子：`settings` 按表名/字段名改写 required / unique | `src/cndb/cli/seed/fields.py:222-238` | 表或字段缺失时仅打印跳过 |
| 3 | 视图种子字段校验：`parent_field` / `title_field` / `status_field` 已在白名单 | `src/cndb/cli/seed/views.py:34-87` | 字段名必须与 CSV 表头逐字一致 |
| 4 | 视图种子落库与默认视图替换语义 | `src/cndb/cli/seed/views.py:210-293` | 同名「全部」会更新自动生成的默认视图 |
| 5 | Tree 视图构建：业务值反查父行、孤儿归根、循环检测 | `frontend/src/pages/grid/views/TreeView.tsx:95-195` | `ROOT` 不是有效技术编号时按根节点处理 |
| 6 | Tree 视图配置项定义 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts:229-253` | 6 项，含 status_field / expand_all |
| 7 | 现有 tree 配置范例（科研任务分解「任务层级树」） | `examples/datasets/工作区-科研项目管理/views.json:799-816` | 本次 `技术脉络` 沿用同一形态 |
| 8 | 真实数据集断言范例（views.json / fields.json 解析 + seed 后校验） | `tests/test_seed_project_todo.py:252-298`、`tests/test_seed_project_todo.py:329-351` | 新测试按此结构组织 |
| 9 | 既有表清单与关联规则（本次不触碰） | `examples/datasets/工作区-科研项目管理/科研项目.csv:1`、`src/cndb/cli/seed/fields.py:20-27` | 不改表结构、不加 link/backfill |

## 未决问题

- [x] 「技术体系数据」载体 → **新建独立 `技术体系` 表**（不在 `科研项目` 表加字段）。
- [x] 树视图形态 → **`tree` 视图「技术脉络」，默认全部展开，不显示层级编号**，状态徽章显示 `成熟度`。
- [x] 是否同步补技术体系示例文档 → **不补**。
- [x] 是否与 `科研项目` 表建立关联 → **不建立**（本需求范围内保持独立表）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

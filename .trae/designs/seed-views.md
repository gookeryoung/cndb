# seed 视图种子（views.json）设计与完整性校验

## 范围

seed 命令的视图注入：`examples/datasets/<工作区>/views.json`（CSV/fields.json 工作区）与 `api_config.json` 内嵌 views（API 建表工作区）。实现位于 `src/cndb/cli/seed.py`（`_seed_views` / `_validate_view_fields` / `FIELD_IMPORT_RULES`）。

## 接口定义

- `_get_workspace_view_configs(datasets_dir) -> dict[str, dict[str, list]]`：扫描 `工作区-*/views.json`，utf-8-sig 读取，工作区名剥离「工作区-」前缀。
- `_validate_view_fields(vc, valid_fields, ws_name, table_name) -> bool`：校验 filters/sortings/view_options 字段引用与 charts[] 逐条目（错误打印定位到 `charts[i].<key>`）；失败视图跳过不阻断。
- `_seed_views(db, user, tables_map, datasets_dir) -> int`：同名视图存在则整配置更新（覆盖自动生成的「全部」默认 grid），否则新建；单视图异常回滚并跳过。
- `FIELD_IMPORT_RULES: dict[str, list[tuple[str, str, list[str]]]]`：同工作区字段克隆规则（目标表, 源表, 字段列表），模块级常量，`_apply_field_import_rules` 与测试共用。

## 数据模型（view_options 键约定）

- grid/kanban/calendar/gantt/wbs/matrix/chart 共 7 种 `view_type`；后端 views.py 与 seed.py 各持一份字段白名单，新增视图模式需同步两处。
- matrix：`row_field`/`column_field` 必填，column 为日期字段时配 `date_granularity`（默认 month），`title_field` 可选。
- chart：单图扁平键或 `charts[]` 数组（元素=扁平键集），双形态不并存；`show_stats_panel` 默认开。
- kanban：`card_sort_field`/`card_sort_direction`/`group_order`/`ungrouped_label`/`pin_urgent`。

## 算法与流程

1. seed 主流程步骤 3（所有表就绪后）调用 `_seed_views`：建表自动生成「全部」grid 默认视图 → views.json 同名配置整体更新。
2. 字段解析来源（建表顺序决定可用字段全集）：
   - CSV 表头（`create_table_from_csv`）；
   - `fields.json` `link_lookups`：引入 link 字段（`link_name`）与 lookup 字段（`fields`）；
   - `FIELD_IMPORT_RULES` 克隆的物理列；
   - 硬编码业务表（部门表/员工表）；
   - API 建表：`tencent_stock` 处理器字段为 `TENCENT_STOCK_FIELDS` 常量产出，可静态解析；`json` 等数据驱动 handler 字段取决于响应内容，无法静态解析（仅查 view_type）。

## 异常处理

- 视图引用不存在字段/表：打印 `[seed-视图] 跳过` 并继续其余视图；工作区/表缺失同理。
- 单视图落库异常：rollback 该视图，不阻断其它。

## 完整性校验契约（tests/test_backup_seed_roundtrip.py::TestSeedViewsIntegrity）

- view_type ∈ 7 种合法模式（全部工作区全量）。
- 同表视图名唯一、order 唯一。
- filters/sortings/view_options/charts[] 引用字段 ∈ 解析来源全集；仅 `json` 数据驱动 API 建表跳过字段校验（tencent_stock 经常量通道纳入校验）。
- 7 种视图模式在全部 views.json 中均有至少一个示例。
- 新增/改名数据集字段后未同步 views.json 会在该测试失败并定位到 工作区/表/视图/字段。

## 视图覆盖矩阵（seed 现状，2026-10）

| 工作区 | 表 | 视图模式 |
|---|---|---|
| 某企业销售管理 | 产品开发 | grid/kanban/calendar/gantt/chart |
| 某企业销售管理 | 员工表 | grid/kanban/calendar/matrix/chart |
| 某企业销售管理 | 电商销售 | grid/kanban/calendar/matrix/chart |
| 某企业销售管理 | 客户流失 | grid/kanban/chart |
| 某企业销售管理 | 日常待办 | grid/kanban/calendar/chart |
| 某企业销售管理 | 出差统计 | grid/kanban/calendar |
| 某企业销售管理 | 营销活动 | grid/kanban/gantt/calendar/chart |
| 某企业销售管理 | 部门表 | grid |
| 某地区数据 | 气温天气 | grid/kanban/calendar/matrix/chart |
| 某地区数据 | 房价预测 | grid/kanban/chart |
| 科研项目管理 | 科研项目 | grid/kanban/calendar/chart |
| 科研项目管理 | 科研经费 | grid/kanban/calendar/matrix/chart |
| 科研项目管理 | 课题负责人 | grid/kanban/chart |
| 科研项目管理 | 项目进展 | grid/kanban/calendar/chart |
| 项目管理 | WBS任务分解 | grid/kanban/calendar/gantt/wbs/chart |
| 项目管理 | 资源排期 | grid/matrix/chart |
| 项目管理 | 待办事项 | grid/kanban/calendar/chart |
| 低质量数据 | 16-日期格式大全 | grid/chart/calendar |
| 低质量数据 | 17-数字格式大全 | grid/chart（极端数据健壮性专用） |
| 低质量数据 | 18-布尔与百分比 | grid/chart/matrix |
| 低质量数据 | 19-特殊值杂项 | grid/chart/kanban |
| 股票信息管理 | A股典型个股行情 | grid×3（api_config）/chart 多图（字段经 TENCENT_STOCK_FIELDS 通道校验） |

注：低质量数据工作区的 15 个 xlsx 为手动导入样例（seed 仅建 CSV 表），不配 views.json 视图。

## e2e 锚点

- `critical/matrix-view.spec.ts`：气温天气月份列头（YYYY-MM）、员工表 link 归桶；testid：matrix-view/matrix-corner/matrix-col-header/matrix-row-header/matrix-cell。
- `critical/view-mode-switch.spec.ts`：按钮数与 seed 视图 1:1（部门表 0/科研项目 4/产品开发 5/客户流失 3/电商销售 5）；电商销售 chart 卡片头数量 5（chart-card-title-{i}）与 views.json charts 数量联动。
- 前端单测 `viewModes.test.ts` deriveModeSwitch 矩阵与 seed 同步维护。

# seed 数据集字段回填设计

## 背景与问题

数据集 CSV 天然带外键文本列（如科研工作区各子表的"课题编号"），但 seed 流程建立关联与克隆字段时只建结构不落数据，导致界面显示异常：

- `fields.json` 的 `link_lookups` 建立 link + lookup 字段后，link 关联表无行映射，lookup 列全部显示为空；
- `_apply_field_import_rules` 克隆源表字段（"项目状态"等）到子表后，物理列无数据，列值全部为空。

## 机制设计

回填由 `fields.json` 声明驱动，统一在 `_apply_field_settings` 中执行（主流程步骤 2b 之后）。

### 配置格式

- `link_lookups[].match`：`{"local": "目标表匹配列", "source": "源表匹配列"}`，声明后回填 link 行关联；
- `backfills[]`：`{"table", "source_table", "fields": ["源字段名"], "match"}`，按匹配列把源表字段值写入目标表同名物理列。

### 匹配与回填算法

核心函数 `_backfill_rows_by_match`（[seed.py](../../../src/cndb/cli/seed.py)）：

1. 校验匹配列存在，任一缺失打印告警返回 0；
2. 读取源表行（id + 匹配列 + 值字段物理列），按匹配值（`str(v).strip()`，None/空串不入映射）建立 `值 -> 源行` 映射；
3. 逐行读目标表匹配列，命中则：
   - `link_field` 提供时调用 `set_links` 写关联表（替换语义，multiple=False 场景单目标）；
   - 值字段对目标表物理列执行 UPDATE（仅取源表有物理列的字段，lookup/link 虚拟字段自动跳过）；
4. 返回成功回填的行数。

### 幂等性

- link 回填：`set_links` 为先清后写替换语义，重复执行结果一致；
- 值回填：重复覆写同值；
- 匹配不上的行（无对应源行）不触碰，保持原值。

### 执行位置与顺序

- `_apply_field_import_rules`（建表后）：克隆字段结构，不改；
- `_apply_field_settings` 步骤 2：settings 必填/唯一 → link_lookups 建 link/lookup → match 行关联回填 → backfills 物理列数据回填；
- link 字段查找按 `link_name` 在目标表 active_fields 中定位（import_fields_as_lookup 的 created/skipped 均可能包含 link）。

## 科研工作区配置（examples/datasets/工作区-科研项目管理/fields.json）

- 三条 `link_lookups`（课题负责人/项目进展/科研经费 ← 科研项目）均声明 `match: {local: 课题编号, source: 课题编号}`；
- `backfills` 三条：课题负责人←项目状态、项目进展←项目状态+立项年份、科研经费←项目状态+项目类别。

## 已知边界

- 匹配值应为可字符串化且去空格后稳定的文本（课题编号类）；重复匹配值以后出现的源行为准（源表匹配列重复时）；
- 回填不校验目标列类型兼容性——值来自同库源列，类型由建表推断保证一致；
- "关联课题" link 无 match 时行关联保持为空（如销售工作区"日常待办"，CSV 无外键列属正常）。

## 验收

- [x] seed 后科研经费/课题负责人/项目进展三表的"关联课题" link 关联非空，lookup 列实时解析正确
- [x] 克隆物理列（项目状态/项目类别/立项年份）行数据回填正确
- [x] 重复执行 seed 幂等，字段数与行数据不变
- [x] 单元测试：test_seed_field_settings.py 覆盖 match 回填、backfills 值回填、幂等、匹配列缺失优雅跳过、真实数据集配置断言

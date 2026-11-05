# ADR 0100: 数据表派生字段（公式 / 函数生成）

Status: Implemented
Date: 2026-11-05
Related: `src/cndb/plugins/tables/field_types/formula.py`、`src/cndb/plugins/tables/services/core/formulas.py`、`src/cndb/plugins/analytics/services/formula.py`、`frontend/src/pages/fields/FieldManager/`
需求卡片: `docs/requirements/0100-formula-derived-fields.md`

## 口径（需求 → 设计落点）

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 新建派生字段 | 新字段类型 `formula`（派生字段）+ 公式 / 小数位配置；新建下拉可选 |
| C2 | 按公式 / 函数生成 | 复用 analytics 公式引擎；保存时校验语法与字段引用 |
| C3 | 生成字段内容 | 读取行时计算并附加到行响应；列表 / 单行同口径 |
| C4 | 只读 | `has_physical_column=False`，写入忽略；网格 / 行详情只读 |
| C5 | 错误容忍 | 公式异常该字段回退 None，不拖垮读取 |
| C6 | 前端 | 字段管理器公式配置区 + 类型元数据 + 只读展示 |
| C7 | 工程口径 | 无迁移；文档与测试同步 |

## Context

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 字段类型支持文本 / 数字 / 日期 / 选择 / 关联 / 附件等物理或引用字段 | `tables/field_types/` | 无法按已有字段生成只读结果 | 新增 C1/C3 |
| 2 | 已有 analytics 受限公式引擎 | `plugins/analytics/services/formula.py` | 可复用安全解析 / 求值，无需 eval | 确认 C2 |
| 3 | lookup / link 已有「无物理列」虚拟字段先例 | `field_types/lookup.py`、`lookups.py` | 派生字段可沿用虚拟字段读取期附加模式 | 确认 C3/C4 |
| 4 | 行读取列表 / 单行两个出口 | `services/core/records.py` | 必须在两个出口都附加公式值 | 新增 C3 |
| 5 | 物理 DDL 对非物理字段会误建关联表（通用 add_column） | `services/core/ddl.py` | 需只对 link 建关联表，formula/lookup 跳过 | 新增边界 |

核心缺陷：**字段只能存储用户输入，不能表达「由其它字段计算得到」的只读结果。**

设计目标（不变量）：

- **I1 不落库**：formula 无物理列，读取时计算，避免数据漂移。
- **I2 安全**：复用受限公式引擎，禁止 eval / 任意代码。
- **I3 只读**：写入丢弃，不参与必填 / 唯一物理约束。
- **I4 单点附加**：列表与单行共用 `attach_formula_values`。
- **I5 失败隔离**：单个公式异常只回退该列 None。

## Decision

### 1. 数据模型

无数据库迁移。字段元数据新增 `field_type="formula"`，`config = {formula, decimals}`。

### 2. 判定算法（唯一入口）

- `_validate_field_config`：保存时公式语法与字段引用校验（延迟导入 analytics 引擎）。
- `attach_formula_values`：读取时唯一计算入口；lookup 先、formula 后，按字段顺序。
- 公式引擎：`analytics.services.formula.evaluate_column`（白名单 AST）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /tables/{tid}/fields` | 支持 `field_type=formula` + config |
| `PATCH /tables/{tid}/fields/{fid}` | 支持修改公式 / 小数位；禁止普通字段 ↔ formula 切换 |
| `GET /records`、`GET /records/{rid}` | 响应行附加 formula 字段计算值 |

### 4. 边界与例外

- 公式只能引用本表字段；未知字段保存 400。
- 普通字段改 formula / formula 改普通字段：400，要求新建。
- 公式无物理列：不参与必填 / 唯一物理索引；`required/is_unique` 对 formula 无实际约束。
- link / lookup 字段不进入公式引擎的物理读取？公式可引用 lookup（lookup 先 attach），link 值可能是摘要对象，参与数值计算时通常为 None。
- 运行期公式异常 → 该字段全列 None，不抛错影响其它列。
- 隐藏字段仍计算，但最终按字段隐藏规则裁剪响应。

### 5. 迁移

无。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 字段管理器 | `typeConfigPanel.tsx` | formula 配置区（公式 / 小数位 / 可用字段提示） |
| 类型元数据 | `fieldTypeMeta.ts` | 「派生字段」标签与选项 |
| 单元格 / 行详情 | `cellValueUtils.ts`、`RowDetailDrawer.tsx`、`FieldEditor` | formula 只读展示，不进入提交 |
| API 类型 | `api/types/tables.ts` | `FieldType` 增加 formula |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_formula_fields.py`：创建 / 读取计算 / 只读回传 / 非法公式与字段 / 类型切换拦截。
- `frontend/src/pages/fields/FieldManager/FieldManager.test.tsx`：新建派生字段提交 formula config。

**接口层**：字段创建 / 记录读取附加 formula。

**迁移 / 备份**：无迁移；字段元数据随表备份（config JSON）自动往返。

**e2e（前端）**：本期未新增。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | formula 字段类型 / 校验 / 读取期计算 | 低 |
| **P1** | 列表与单行附加 / 只读边界 / DDL 跳过虚拟列 | 中 |
| **P2** | 字段管理器配置区 / 网格只读 / 测试 | 中 |

## 决策记录

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 计算字段形态 | 虚拟字段，读取时计算 | 不引入物化 / 回填复杂度，源字段变化即时反映 | 物化列 + 重算任务（同步成本 / 漂移） | `formulas.py` |
| D2 | 公式引擎 | 复用 analytics 受限引擎 | 已有白名单 AST、函数与测试；无 eval | 新写表达式引擎（重复且安全风险） | `field_types/formula.py` |
| D3 | 类型切换 | 禁止普通 ↔ formula 互转 | 互转会涉及物理列删除 / 数据丢失，新建更安全 | 自动重建列（SQLite 风险 / 语义不清） | `routers/fields.py` |
| D4 | 公式引用 | `[字段名]`，仅本表 | 与 analytics 公式一致；字段改名可见 | 跨表引用（权限 / 依赖复杂） | `formulas.py` |
| D5 | 失败口径 | 单列回退 None | 一个坏公式不拖垮整表读取 | 抛错致整行失败（影响列表） | `formulas.py` |
| D6 | DDL | 非物理字段只对 link 建关联表 | 避免 lookup / formula 被误建关联表 | 沿用通用非物理分支（错误建表） | `ddl.py` |

## Consequences

- **正向**：无需物化即可在表格 / 详情中看到公式结果；安全复用既有公式引擎。
- **负向**：公式字段不可排序 / 筛选下推（当前读取期附加），大表计算有内存 / CPU 成本。
- **风险与缓解**：公式引用字段改名后失效 → 保存期校验新公式；已有公式不改名提醒可在后续版本补。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 公式引擎 | `analytics/services/formula.py` | 复用白名单 AST / 函数 | ADR 0006 M4 / analytics 模板 |
| 虚拟字段 | lookup / link 先例 | formula 同样无物理列，读取期附加 | ADR 0006 |
| 字段 DDL | `ddl.add_column` | 非物理字段跳过 DDL，仅 link 建关联表 | ADR 0038 |
| 表备份 | 字段 config JSON | 公式随字段元数据往返，无需额外结构 | ADR 0075 |

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/field_types/formula.py`、`src/cndb/plugins/tables/services/core/formulas.py` | `tests/test_formula_fields.py` | b6685f20 |
| P1 | 已落地 | `src/cndb/plugins/tables/services/core/records.py`、`src/cndb/plugins/tables/services/core/ddl.py` | `tests/test_formula_fields.py` | b6685f20 |
| P2 | 已落地 | `frontend/src/pages/fields/FieldManager/`、`frontend/src/pages/grid/` | `frontend/src/pages/fields/FieldManager/FieldManager.test.tsx` | b6685f20 |

## 交接

- 当前阶段：全期已落地（P0 / P1 / P2）。
- 已完成：formula 字段类型、保存校验、读取期计算、只读边界、字段管理器配置。
- 下一步：可补公式字段排序 / 筛选下推、字段改名自动重写引用。
- 已知坑：formula 是读取期虚拟列，不参与物理排序 / 筛选下推；引用字段改名后旧公式需手工更新。
- 最近一次全绿：`make flow`（本次提交前，2026-11-05）。

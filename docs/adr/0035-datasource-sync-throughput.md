# ADR 0035: 数据同步吞吐优化（选项校验缓存 + 轻量落表）

Status: Implemented（2026-10-27 人工确认 P0-P2 全期落地）
Date: 2026-10-25
Related: `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/runner.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/tables/field_types/select.py`、`src/cndb/plugins/tables/services/fields/select_options.py`、ADR 0006、ADR 0034、ADR 0104
需求卡片: `docs/requirements/0035-datasource-sync-throughput.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

> 本 ADR 保留的决策：选项值集合缓存（D1）、同步轻量落表（D2）、流式批大小（D4）、更新路径与非唯一索引（D5）、请求根数自适应不做（D6）。
> 并发 `workers` 与示例任务限速取值（原 D3）已由 ADR 0104 删除；本节与正文只描述现行口径。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 日线数据同步数据时间太长 | 同步链路单批落表从 16.5s / 34.9s（新增 / 更新，实测）降到 1.3s / 2.3s，并随 D2 再降一档 |
| C2 | 时间太长（日常增量） | 选项校验按 config 缓存（D1）+ 轻量落表（D2）让每批固定成本下降 12~15 倍；见 Context#1 与 Consequences |
| C3 | 请参考 ~/stock-strategy 的实现方式 | 采纳：批量落表、跳过与同步无关的分析；否决：复合唯一键 + `ON CONFLICT`（D5）、换存储引擎（ADR 0034 D7 已否决，本 ADR 沿用） |
| C4 | 参考实现方式 | 幂等键、行级写权限、校验语义、批大小与游标断点全部不变；轻量模式只跳过「报告类」计算，不跳过校验与 upsert 匹配（D2） |
| C5 | 优化 | 零新增依赖、零迁移、零 API / 前端变动；引擎侧优化对旧配置直接生效 |

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。需求卡片「现状影响面」编号 1..5 沿用。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `SelectFieldType.validate_value` 每行每字段调用 `_allowed_values_from_config`，每次重建大选项集合 | `src/cndb/plugins/tables/field_types/select.py` | 实测 7,286 行落表：新增 16.5s、更新 34.9s（表 13.5 万行）；缓存后 1.3s / 2.3s（12~15 倍） | 确认（C1/C2） |
| 2 | 同步落表复用完整导入分析链：批内 prefill → RowValidator → 两次 `DiffReporter` → `profile_columns` → `recommend_match_keys`（查库） → execute 末尾 `sync_select_options_from_table`（全表 distinct） | `src/cndb/plugins/tables/services/importing/importer.py` | 每批固定开销（画像 / 推荐 / 全表 distinct）随批数线性累积；实测跳过画像后更新 2.31s→1.92s | 确认（C1/C2） |
| 3 | 更新路径逐行 `UPDATE`（`bulk_update_rows` 循环） | `src/cndb/plugins/tables/services/core/records.py` | 7,286 行更新中约 1.5s 属逐行语句开销；缓存后占比可接受 | 新增（评估后不做，见 D5） |
| 4 | 大表写入缺少轮末 WAL 收尾 | `src/cndb/plugins/datasource/services/runner.py`、`src/cndb/core/database.py` | WAL 持续膨胀影响前台读与备份体积 | 转 ADR 0043 D4 处理 |

**核心缺陷（需求要补的）**：同步链路的「单批固定成本」被按导入语义付满了 —— 面向人工导入的质量画像、参考列推荐与全表选项同步，在一条要跑上千批、数百万行的同步任务上变成主要耗时；同时选项校验按行重建大集合，使单批成本再放大一个数量级。

设计目标（不变量）：

- **I1 语义不变**：字段校验（类型 / 必填 / 选项）、幂等键匹配、未知列策略、行级写权限与既有导入链路一致；跳过的是「报告类产物」，不是校验。
- **I2 结果一致**：同一输入批次，优化前后写入的数据行集合与 `inserted/updated/skipped` 计数一致。
- **I3 限速语义不变**：`rate_limit_ms` 仍是相邻请求最小出发间隔（ADR 0104 D6 的串行实现），本 ADR 不改语义。
- **I4 零迁移**：不新增表 / 列 / 索引，不做数据迁移；旧任务配置无需改写即可享受 D1/D2。

## Decision

### 1. 数据模型

无。

### 2. 判定算法（唯一入口）

**(a) 选项值集合缓存**（`src/cndb/plugins/tables/field_types/select.py`）

- 新增模块级有界缓存：键 = `id(config)` + `len(options)`，值 = `(config 引用, frozenset)`；命中前校验 `config is 缓存里的 config`，避免 `id` 复用误命中。
- `_allowed_values_from_config` 改为「查缓存 → 未命中才构建」，`select` / `multiselect` 两处调用共用。
- 失效口径：options 列表被原地 append（batch prefill / 全表同步）时长度变化即换键；上限 256 条，超出整表清空（配置对象通常个数量级少于该值）。

**(b) 同步轻量落表**（`src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/datasource/services/write.py`）

- `Importer.analyze(..., light=True)`：保留 `prefill_select_options_from_rows`、`RowValidator`、upsert 匹配、`_plan_unknown_columns` 与一次 `DiffReporter.build`（执行阶段要读 `skipped_columns`）；跳过 `profile_columns`、`recommend_match_keys`、`generate_cleaning_suggestions`、第二次报告组装。
- `Importer.execute(..., sync_options=False)`：跳过末尾 `sync_select_options_from_table`（全表 distinct）。批内 prefill 已把本批新选项写入 config，覆盖「新选项入选」场景；存量行选项由人工导入链路的全表同步继续兜底。
- `write.upsert_rows` 增加 `light: bool = False` 参数，数据同步路径（`services/runner.py:_persist_rows`）传 `light=True`；导入 API / 前端导入保持默认 `False`（行为不变）。
- 保留 `partial=True`、`_drop_missing_required`、`bulk_create` / `bulk_update_rows` 调用顺序不变。

### 3. API 变更清单

无。

### 4. 边界与例外

1. `light=True` 时若目标表存在需要「新增未知列」的配置（`unknown_cols_strategy="add_text_field"`），同步链路本就不开启该策略（`write.py` 只有 `auto_add_fields` 为 llm_prompt 专属），因此不涉及 DDL 分支。
2. 选项缓存对「同一 dict 被深拷贝成新对象」不会命中，退化为原行为（正确性不受影响）。
3. 批次内出现新选项值时，prefill 会向 `config.options` 追加，缓存因长度变化重建；下次批次的校验直接受益。

### 5. 迁移

无。

### 6. 前端

无。

### 7. 测试清单

**判定层（单测）**：

- `tests/test_sync_select_options.py` 增补：同一 config 重复校验只构建一次集合（用计数器桩断言）；options 追加后新值立即生效；`id` 复用保护（构造两个 dict 先后进缓存）。
- `tests/test_import_pipeline.py`：`Importer.analyze(light=True)` 的报告不含 `column_profiles` / `recommend_match_keys` / `cleaning_suggestions`，但 `skipped_columns`、`upsert_result` 与默认模式一致。
- 新增 `tests/test_import_light_mode_equivalence.py`：同一批行分别走默认与 light 落表，断言写入行集合与 `inserted/updated/skipped` 完全一致（I2）。
- `tests/test_datasource_runner_streaming.py`：`_persist_rows` 走 light 路径且跨批计数不变。

**接口层**：既有 `tests/test_datasource_api.py`、`tests/test_datasource_cli.py` 全绿（默认模式未变）。

**迁移 / 备份**：`tests/test_datasource_migration.py` 与 `tests/test_datasource_backup.py` 全绿（无迁移）。

**e2e（前端）**：无新增（前端零改动）；发布前跑现有 datasource e2e 套件回归。

**性能验收（人工）**：在同一份 13.5 万行库上复测「7,286 行新增 / 更新」落表耗时，目标 ≤3s。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 选项值集合缓存（判定层）+ 单测 | 低（纯函数级优化，语义不变） |
| **P1** | 轻量落表模式（analyze/execute/write/runner 接入）+ 等价性用例 | 中（触及导入器公共签名，需保证默认路径不变） |
| **P2** | 同机基准复测 + 文档收尾 | 低（仅测量与文档） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 单行选项校验成本 | 按 config 标识缓存 frozenset（有界 + 身份校验） | 实测 7,286 行落表 16.5s→1.3s；34.9s→2.3s | ① 改 `SelectFieldConfig` 结构（迁移与前端风险）；② 校验层绕过选项检查（破坏 C4/I1） | `src/cndb/plugins/tables/field_types/select.py` |
| D2 | 同步是否复用完整导入分析 | 新增 `light=True`：跳过画像 / 推荐 / 清洗建议 / 全表选项同步，保留校验与 upsert | 单批固定开销 × 上千批；报告类产物对同步无人消费 | ① 另写一套专用写入器（重复校验 / 权限 / 必填逻辑，维护双份）；② 全关校验（静默写入脏数据） | `services/importing/importer.py`、`services/write.py`、`services/runner.py` |
| D4 | 流式批大小 | 维持 10,000（ADR 0039 D3 调整后的当前值） | 缓存后单批成本已降到 1~2s；调大会改动既有流式断点粒度与用例语义 | 调大到 20,000（收益 <10%，改动面扩大） | `services/pipeline.py` |
| D5 | 更新路径逐行 UPDATE / 唯一键 | 维持 `bulk_update_rows` 逐行 + 非唯一复合索引 | 缓存后更新 7,286 行 2.3s 可接受；逐行 WHERE 才能保持行级权限判定 | ① `executemany` 合批（削弱逐行权限与软删过滤）；② 复合唯一键 + `ON CONFLICT`（ADR 0006 明确否决，改幂等口径） | `services/core/records.py`（不改） |
| D6 | 请求根数自适应 | 不做 | 分页 / 时间窗口的请求数由声明决定，无自适应收益空间 | 按缺口算请求数（多一层日期推断，配置与测试成本换不来时间） | — |

## Consequences

- **正向**：
  - 落表单批成本下降 12~15 倍（16.5s→1.3s 新增，34.9s→2.3s 更新），叠加 D2 后更新再降至约 1.9s；
  - 大表同步的每批固定开销与批数解耦，任务越长收益越稳定；
  - 优化对旧任务配置零迁移（D1/D2 直接生效）。
- **负向**：
  - 导入器新增 `light` / `sync_options` 两个开关，公共签名变宽；靠默认 `False` 保证导入路径不变；
  - 模块级缓存引入「配置对象身份」隐式契约，需要单测锁定失效语义。
- **风险与缓解**：
  - `light` 路径漏掉某个校验分支 → 用「默认 vs light」等价性用例锁死写入结果与计数；
  - 缓存误命中导致新选项校验失败 → 键含 `len(options)` 且校验对象身份，prefill 追加后必重建。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 幂等口径 | `match_keys` 应用层先查后写 | 不引入唯一约束 / `ON CONFLICT` | ADR 0006（本 ADR D5 沿用） |
| 串行限速 | `rate_limit_ms` | 相邻请求最小出发间隔语义不变（ADR 0104 已删除并发实现） | ADR 0104 D6 |
| 大规模任务形态 | 流式落表 / 动态标的 | 不变 | ADR 0034 D1/D3 |
| 导入报告能力 | `DiffReporter` / 画像 / 推荐 | 人工导入保持全量，同步走轻量 | 本 ADR D2 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/tables/field_types/select.py` | `tests/test_sync_select_options.py` | 5bdf927c |
| P1 | 已落地 | `src/cndb/plugins/tables/services/importing/importer.py`、`src/cndb/plugins/datasource/services/write.py`、`src/cndb/plugins/datasource/services/runner.py` | `tests/test_import_light_mode_equivalence.py`、`tests/test_datasource_runner_streaming.py` | 5bdf927c |
| P2 | 已落地 | `src/cndb/plugins/datasource/services/pipeline.py`、`src/cndb/plugins/datasource/services/write.py` | `tests/test_datasource_write_throughput.py` | 5bdf927c |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已全部落地，门禁全绿（`make check`）
- 已完成：选项值集合有界缓存；轻量落表模式（同步链路默认启用、人工导入不变）；基准复测（13.5 万行库、7,286 行单批：默认 1.33s 新增 / 2.26s 更新，同步链路 0.95s / 1.92s，基线 16.5s / 34.9s）
- 下一步：无（功能完结）；后续吞吐项（WAL 收尾 / 行拷贝收敛）由 ADR 0043 承接
- 已知坑：① 选项缓存的键必须带 `len(options)`，否则 batch prefill 追加新选项后仍用旧集合；② `light` 模式仍要走 `_plan_unknown_columns`（执行阶段读 `skipped_columns`）；③ 单批基准须在与生产同规模的库上测，空库测不出选项校验成本；④ 缓存是模块级全局的，同进程内导入与同步互相受益（基准须用独立进程分别测）
- 最近一次全绿：`make check`（含 `make cov` 97.02%、前端 static）@ 5bdf927c

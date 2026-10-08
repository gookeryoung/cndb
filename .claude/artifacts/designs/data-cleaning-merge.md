# 数据清洗与重复合并（Data Cleaning & Merge）Spec

> Status: ALIGNED
> Author: user
> Last updated: 2026-10-08

## Background

cndb 的清洗与去重能力目前仅存在于导入流程（analyze → cleaning_suggestions → cleaning_actions），对已存表缺少重复检测、合并与 in-place 清洗能力。海量数据治理场景需要：对已存表做重复检测 → 人工确认 → 合并（字段级融合 + link 引用迁移）、批量清洗，并配套专门的权限控制，防止批量破坏性操作被随意执行。

## In scope

- 已存表重复检测：用户指定判重字段组合，精确匹配分组（可选忽略大小写/首尾空格），异步任务 + 进度轮询
- 重复组预览确认：分组浏览（每组含成员行 id、判重字段值、行数据对比），逐组指定保留行与字段保留策略
- 合并执行：字段级融合（保留策略：非空优先/最新/最早/手动指定）→ 被合并行进回收站（可逐行恢复）→ 入向 link 引用自动迁移到保留行 → AuditLog 记录
- 已存表 in-place 清洗：复用导入侧动作库（trim_whitespace / fill_null / coerce_type / drop_outliers），清洗前生成 before/after 预览，确认后异步执行
- 权限配置：新增表级动作 `MANAGE_DATA`（数据治理），纳入 TableAction 枚举、TablePermission 角色阈值字段、自定义 Role 权限位（ACTION_KEYS）、表成员授权体系，默认工作区角色阈值 ADMIN
- 前端：表详情工具栏"数据治理"入口（检测配置 → 组确认/清洗配置 → 执行进度），权限设置面板新增数据治理项
- 所有治理操作必须人工确认后执行，不提供免确认自动模式

## Out of scope

- 模糊匹配判重（相似度/编辑距离）——仅在检测策略层预留扩展接口，不实现
- 导入流程既有清洗/去重链路的任何变更
- 跨表清洗/合并（单表内操作，不含工作区级批量治理）
- 一键撤销整个合并/清洗任务（依赖既有行级回收站逐行恢复，不建任务级快照回滚）
- 定时/调度自动清洗
- 新增清洗动作类型（大小写统一、日期归一化等"标准化"动作，见 Open questions）

## Assumptions

- 单表规模目标 ≤ 50 万行；分批扫描 + 流式分组，不在内存持有全量行【待用户复核】
- 新建治理任务表（复用 ImportTask 的状态机与进度模式，但字段独立：kind=detect/merge/clean），不改造 ImportTask 本身
- `MANAGE_DATA` 默认阈值 = 工作区 ADMIN；表拥有者与工作区 OWNER/ADMIN 天然放行（沿用 check_action 优先级链 1/2）
- link 迁移语义：被合并行的**入向**引用（其他表或本表 link 字段指向被合并行）全部改指保留行；保留行自身的 link 字段值按字段保留策略参与融合；组内互引不迁移
- 检测报告以 JSON 存储于任务记录（类似 validation_report 模式），重复组分页读取
- 清洗动作 v1 仅复用现有 4 动作，coerce_type 在已存表语境下语义为"修正不符合字段类型的违规值"【待用户复核】

## Solution

新增治理服务层（`services/governance/`），三块核心能力 + 一条权限链路：

1. **检测**：按判重字段组合分批扫描（主键分页，SQL 分组聚合为主），产出重复组报告（组列表 + 每组成员行 id + 判重键值）存任务表；检测策略接口 `DuplicateDetector` 预留模糊扩展。
2. **合并**：逐组按确认配置执行——保留行字段按策略融合（non_empty_first / latest / oldest / manual）→ 被合并行 trash（复用行级回收站）→ link 引用批量迁移（复用 links 服务扩展）→ AuditLog（action=merge，detail 记录组配置）。执行时做行版本校验，检测后被外部修改的行跳过并在结果报告中标记。
3. **清洗**：从导入侧 cleaning.py 抽出动作实现公共层（导入与治理共用），对已存表按动作生成 before/after 样例预览，确认后分批 UPDATE；fill_null 的 mean/median、outliers 的 IQR 阈值改为对已存数据实时计算。
4. **权限**：`TableAction` 新增 `MANAGE_DATA` → TablePermission 加 `manage_data_role` 字段 + Alembic 迁移 → ACTION_KEYS/ACTION_LABELS 同步（自定义 Role 自动补位）→ `check_action` 优先级链不变 → 治理 API 全部经 `get_table_or_404(action=MANAGE_DATA)` 校验。

API 骨架（`/api/v1/workspaces/{wid}/tables/{tid}/governance/*`）：
`POST detect`（match_fields + 选项）→ `GET tasks/{id}`（状态/进度/结果分页）→ `POST merge`（group 配置）→ `POST clean`（actions）。

前端：表工具栏"数据治理"入口 → 三步向导（检测/清洗配置 → 组确认与策略 → 进度与结果报告）；权限面板新增"数据治理"角色阈值项；治理任务进度复用导入任务轮询模式。

## Edge cases & risks

| Category | Notes |
|---|---|
| Boundary conditions | 组内自引用 link（表自关联且组内互引）不迁移，避免环；空表/无重复返回空报告而非报错；判重字段含隐藏字段时按配置拒绝或提示 |
| Failure modes | 任务执行期间行被并发修改 → 行版本校验跳过冲突组并在报告标记；合并到一半失败 → 单组事务原子性（组内要么全成功要么回滚），任务级可重试 |
| Risks | 大表检测内存 → 分批扫描流式分组；回收站膨胀 → 复用既有回收站清理机制；权限迁移遗漏 → MANAGE_DATA 为新增动作不改变现有权限行为，仅增不改 |
| Mitigation | 治理操作全部异步任务化（不阻塞请求）；AuditLog 记录完整配置快照；执行前强制预览确认 |

## Acceptance criteria

- AC-1 对含重复行的已存表，指定判重字段组合发起检测，任务完成后返回重复组列表（每组含成员行 id 与判重字段值）；忽略大小写选项生效
- AC-2 对一组 3 行重复，确认保留行与字段策略后执行合并：保留行字段按策略融合、其余 2 行进回收站且可恢复、指向被合并行的入向 link 引用全部改指保留行、AuditLog 记录 action=merge
- AC-3 对含空值/首尾空格的已存表，选择 fill_null(mean) 与 trim_whitespace 执行清洗：预览样例与实际结果一致、任务进度达 100%、AuditLog 记录 action=clean
- AC-4 EDITOR 用户（未获 MANAGE_DATA 授权）调用检测/合并/清洗 API 返回 403；ADMIN 用户通过；表拥有者通过
- AC-5 自定义 Role 授予 MANAGE_DATA 权限位后，持有该 Role 的表成员可执行治理操作
- AC-6 10 万行规模表（PostgreSQL）检测任务完成时间 < 60s，进程内存无 OOM
- AC-7 `make check`（lint + typecheck + cov ≥ 95%）通过；新增接口补齐 Pydantic schema + 前端 `src/types/` 类型 + API 测试

## Open questions

- 单表规模目标是否确认为 50 万行（影响分批参数与 AC-6 性能基准的档位）——待用户复核
- 清洗动作 v1 是否需要补充"标准化"类动作（大小写统一、日期格式归一化）——默认 v1 仅复用现有 4 动作，待用户复核

## Core entities (ontology)

| Entity | Type | Key fields | Relationship |
|---|---|---|---|
| GovernanceTask | ORM 任务表 | kind(detect/merge/clean), status, progress, report(JSON) | 属于 DataTable，复用 ImportTask 状态机模式 |
| DuplicateGroup | 检测报告内聚合单元 | member_row_ids, match_key_values, survivor_row_id(确认后) | GovernanceTask.report 的组成单元 |
| SurvivorshipRule | 枚举 | non_empty_first / latest / oldest / manual | 合并配置项，按字段指定 |
| TableAction.MANAGE_DATA | 权限动作 | 默认阈值 ADMIN | 进入 ACTION_KEYS / TablePermission / Role 权限位 |
| CleaningAction | 动作枚举（复用） | trim_whitespace / fill_null / coerce_type / drop_outliers | 与导入侧共享实现公共层 |

## Interview metadata

- Mode: default
- Waves: 3
- Final ambiguity: 21.8%
- Status: PASSED

### Clarity breakdown

| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.9 | 0.40 | 0.36 |
| Scope | 0.75 | 0.25 | 0.19 |
| AC | 0.6 | 0.25 | 0.15 |
| Context | 0.85 | 0.10 | 0.085 |

### 确认记录

- Wave 1（Goal）：作用对象 = 已存表数据治理（非导入流程增强）
- Wave 2（合并语义）：合并深度 = 字段级融合 + link 引用迁移
- Wave 3（判重标准）：v1 精确匹配 + 检测策略预留模糊扩展

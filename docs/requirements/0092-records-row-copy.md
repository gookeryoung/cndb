# 需求卡片：复制行与被复制行完全一致（不套用字段自动填充规则）

- 编号：0092
- 来源 / 提出人：用户（会话 2026-11-04）
- 日期：2026-11-04
- 关联 ADR：无（S1，方案并入本卡片）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 数据表，复制行的信息应当与被复制行一致，不应因为字段存在自动填入规则而自动填入

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「复制行的信息应当与被复制行一致」 | 复制行走**服务端**按源行原值复制：新增 `POST /{wid}/tables/{tid}/records/copy`（`row_ids[]`），读取源行全部物理列原值（含字段隐藏列）与关联字段目标 id，再以 exact 模式批量写入；响应返回新行 id | `tables/services/core/records.py`、`tables/routers/records.py`、`tables/schemas/models.py` | 后端单测：源行值（编号 / 状态 / 日期 / 备注）逐字段一致 |
| C2 | 「不应因为字段存在自动填入规则而自动填入」 | exact 复制路径跳过 `_apply_auto_increment_defaults`（自动编号）、`date.auto_fill`（on_create / on_update）与 `DataField.default_value`；源行空值显式写 NULL（不走「未提供 → 补默认」分支） | 同上（`_normalize_values(exact=True)`、`bulk_create(exact_copy=True)`） | 判定层：自动编号不重新取号、空状态不被默认值补、历史日期不被 auto_fill 改成今天；对照用例证明普通建行会覆盖 |
| C3 | （权限与边界） | 复制属「新增行」：要求表级 `EDIT_RECORDS`（与批量建行一致，viewer 403）；源行读范围与 `GET /{id}` 同源（行级权限 / 软删过滤），范围外或不存在返回 404；单次最多 200 行 | `tables/routers/records.py` | 接口层：viewer 403、缺失行 404、越权行 404 |
| C4 | （前端接线） | 网格「复制行」改为调用 copy 端点，不再由前端拼行值走 `bulk-create`（避免当前视图缺列 / 隐藏字段导致漏字段被自动填充）；成功提示与列表刷新口径不变 | `frontend/src/pages/grid/GridPage.tsx`、`frontend/src/api/records.ts` | 前端类型检查 + 既有网格用例回归 |
| C5 | （文档口径） | CONTEXT 增「复制行」术语；CHANGELOG 记修复条目；说明隐藏字段的服务端口径（复制但不回显） | `CONTEXT.md`、`CHANGELOG.md` | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 网格复制行由前端拼值后批量建行 | `frontend/src/pages/grid/GridPage.tsx`（`copyRow`） | C4 改调 copy 端点；前端行数据可能缺当前视图未加载 / 隐藏字段 |
| 2 | 创建路径自动填充规则 | `tables/services/core/records.py`（`_normalize_values` / `_apply_auto_increment_defaults`） | C2 需要 exact 分支 |
| 3 | 批量建行端点 | `tables/routers/bulk_crud.py` | 复制不走该端点（自动填充口径保留给人工新增 / 导入） |
| 4 | 行读取（含行级权限 / 字段隐藏） | `tables/services/core/records.py`（`get_row` / `_build_row_read_scope_where`） | C3 复用读范围，服务端复制全部物理列 |

## 未决问题（已确认）

- [x] ① 复制的语义：**结论**「完全一致的副本」，自动编号等也沿用源行值（用户原话）；需要新编号时用手工新增而不是复制。
- [x] ② 隐藏字段是否复制：**结论**复制（服务端写原值、响应不回显，不构成越权读取）；源行必须在调用者的行读范围内。
- [x] ③ 权限：**结论**复制 = 新增行，要求可编辑该表（viewer / 关闭直编的 editor 走既有批量建行口径即 403），不引入新的修改申请形态。
- [x] ④ 方案分级：**结论**S1（新增只读源 + 精确写入端点，无数据模型 / 权限模型变化）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-04 用户口述）

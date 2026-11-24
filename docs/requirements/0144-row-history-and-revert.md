# 需求卡片：行级历史与撤销

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0144（规划卡 `0141` 的 P1 项；**S2**）
- 来源 / 提出人：用户（会话 2026-11-24，「P1+P2」）
- 日期：2026-11-24
- 关联 ADR：`docs/adr/0144-row-history-and-revert.md`

## 需求原句（逐字）

> P1+P2

对应 `docs/requirements/0141-table-robustness-roadmap.md` P1 表项：「行级历史与撤销」。
需求方在 0141 二次评审时批准了 P1 范围，本次指示直接实施。

## 可实施约束（C1..C8）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「行级历史」 | 一次用户写操作（create / update / trash / restore / revert）= 一条版本记录，`version` 从 1 严格递增，`(row_id, version)` 唯一 | `models.py`、迁移 `ea1b2c3d4e5f` | 单测：建行 v1、更新 v2、软删 v3… |
| C2 | 「只记变化」 | `diff` 只存变化字段 `{字段: {old, new}}`；`_` 开头的系统 / 派生键（`_etag` / `_rev` / 软删元数据）不进 diff；无变化的 update 不产生版本 | `services/core/row_history.py` | 单测：diff 精确等于预期；空更新不新增版本 |
| C3 | 「可撤销」 | 撤销 = 按目标版本的 `old` 值生成**新版本**（不删历史、不回退版本号），可反复撤销 / 撤销撤销 | 同上、`records.update_row` | 单测：revert 后版本 +1、值回退；两次 revert 往返 |
| C4 | 「写放大可控」 | 导入 / 数据同步等批量链路默认 `record_history=False`（`bulk_update` / `bulk_update_rows` 本身不写历史） | `records.py` | 单测：`record_history=False` 不产生版本 |
| C5 | 「可审计」 | 记录操作人快照（`actor_id` + `actor_name`），用户删号后历史仍可读；行物理删除（purge）后历史保留（`row_id` 无外键） | 同 C1 | 单测：actor_name 落库；purge 后历史行仍在 |
| C6 | （接口） | `GET /records/{id}/history?limit=`（版本倒序）、`POST /records/{id}/revert/{version}`；可见性沿用行读口径（范围外 404），撤销沿用写范围 / 修改申请双轨 | `routers/records.py` | 接口测试：历史列表、撤销、404 三种 |
| C7 | （前端） | 本期只交付后端与接口；行详情「历史」时间线 UI 列为后续（复用 `RecordRevision`，不需再改模型） | — | 记入 ADR「已知限制」 |
| C8 | （兼容） | 新增元数据表，无存量迁移；历史写入失败不影响主写路径（尽力而为 + 日志） | 迁移、`record_revision` | 单测：历史不可用时主写仍成功 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 行写路径 | `records.py::update_row` / `trash_rows` / `restore_rows` / `create_row` | 统一在此挂历史 |
| 2 | 审计 | `services/core/audit.py` | 审计存整行快照（`detail`），与历史分工：审计=谁做了什么，历史=字段级前后值 |
| 3 | 修改申请 | `change_requests` | 撤销走申请轨道时复用 `revert_values` 计算差量 |
| 4 | 备份 | `workspace_backup` | 历史是流水（ADR 0075），**不进备份** |

## 未决问题

- [x] ① 存整行快照还是只存 diff：**只存 diff**（大字段重复落库不可接受）。
- [x] ② 撤销是否回退版本号：**不回退**，生成新版本（可反复撤销、可审计）。
- [x] ③ 批量 / 导入是否记历史：**不记**（写放大），需要时显式打开。
- [x] ④ 前端时间线 UI：本期不做，记入 ADR 已知限制。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题全部有结论

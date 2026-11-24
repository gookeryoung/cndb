# 需求卡片：批量编辑增强（查找替换）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0149（规划卡 `0141` 的 P2 项；S1）
- 来源 / 提出人：用户（会话 2026-11-24，「按建议」）
- 日期：2026-11-24
- 关联 ADR：无独立 ADR（S1）

## 需求原句（逐字）

> 按建议

对应 `docs/requirements/0141-table-robustness-roadmap.md` P2 表项：「批量编辑增强（查找替换 / 粘贴校验预览 / 跨页全选）」。

## 可实施约束（C1..C8）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「查找替换」 | `POST /records/bulk-replace`：`field` + `find` + `replace` + `match`（`contains` / `exact` / `regex`），支持 `filters` / `filter_logic` 限定范围 | `services/core/bulk_replace.py`、`routers/records.py` | 接口测试：三种模式各自命中与落库 |
| C2 | 「先预览」 | 默认 `dry_run=true`：只返回 `matched / skipped / preview`（最多 20 条前后值），不写库；`dry_run=false` 才落库 | 同上 | 接口测试：预览后库内数据未变 |
| C3 | 「范围与权限」 | 复用列表 WHERE（行级权限 + 软删 + 业务过滤），因此"替换的就是用户看到的"；要求 `EDIT_RECORDS` | 同上 | 接口测试：viewer 403、范围外行不动 |
| C4 | 「只改文本物理列」 | 只允许 `text / email / url / phone` 且有物理列的字段；lookup / formula / link / 数字 → 400 | 同上 | 单测：四类拒绝 |
| C5 | 「规则一致」 | 替换后的值必须仍通过字段规则（需求 0146）；不通过的行跳过并计入 `skipped`（不整批失败） | 同上 | 单测：坏值被跳过且原值保留 |
| C6 | 「有界」 | 匹配范围超过 `REPLACE_MAX_ROWS`（2 万）→ 400 要求收窄；非法正则 / 空查找串 / 未知匹配模式 → 400 | 同上 | 单测：上限与三类非法输入 |
| C7 | 「不记历史」 | 批量链路不写行历史（ADR 0144 D4，避免写放大），改动仍进审计与事件流 | 同上 | 与 ADR 0144 一致（沿用既有 bulk 路径） |
| C8 | （前端） | 网格「更多 → 批量替换」对话框：字段候选只列文本字段、预览表格展示前后值、未预览时禁止确认、确认后刷新列表 | `pages/grid/BulkReplaceDialog.tsx`、`gridToolbar.tsx` | 前端单测 6 例 |

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 批量写 | `records.bulk_update_rows` | 替换复用；逐行各有 values |
| 2 | 字段规则 | `field_rules.validate_row_constraints` | 替换后逐行校验 |
| 3 | 列表筛选 | `records.list_rows` | 预览与落库共用同一 WHERE |
| 4 | 网格工具栏 | `gridToolbar.tsx` | 「更多」菜单新增入口（按 `EDIT_RECORDS` 门控） |

## 未决问题

- [x] ① 粘贴校验预览 / 跨页全选：本期未做（前端体量较大），列为后续；本卡片只交付「查找替换」。
- [x] ② 替换是否记行历史：不记（与批量写同口径）。
- [x] ③ 上限：单次 2 万行（超出要求收窄筛选）。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [ ] 粘贴校验预览 / 跨页全选：未开始（④ 已登记为后续）

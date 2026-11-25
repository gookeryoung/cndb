# ADR 0156: 跨工作区移动后的引用修复（诊断 + 三策略 + 版本化改写）

Status: Accepted
Date: 2026-11-25
Related: `src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/documents/services/parse.py`、`src/cndb/plugins/documents/services/export/table_refs.py`、`src/cndb/plugins/documents/services/move.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/models.py`、`frontend/src/pages/documents/MoveDocumentModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`
需求卡片: `docs/requirements/0156-cross-workspace-reference-repair.md`（需求原文与约束编号的唯一副本）
上位: ADR 0155（文档跨工作区移动，P2 条目由本 ADR 承接）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；C1..C10 引用卡片编号。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「引用」「修复」 | 新服务 `services/references.py::diagnose_move_references`：两方向扫描（被移动文档内 → 源工作区目标；源工作区文档 → 被移动文档标题），返回 `ReferenceIssue[]`（doc/raw/kind/reason/target_workspace） |
| C2 | 「自动修复」 | `RepairStrategy ∈ {none, annotate, snapshot}`；`annotate` 把 `[[x]]` → `x（已移至「WS」）`、`{{table:id…}}` → `（数据表引用已失效：原表在「WS」）`；`snapshot` 额外把 `{{table:id}}` 替换为静态 GFM 表格（复用 `table_refs`） |
| C3 | （可预览） | `POST …/documents/references/preview`（默认 dry-run）→ 每条 `{document_id, raw, next, kind}` + `affected_documents`；不落库 |
| C4 | （接在移动上） | `move-to-workspace` 增 `repair_strategy`（默认 `none`）；非 `none` 时在移动完成后、同一请求内对**被移动文档**执行修复（各自新版本） |
| C5 | （反向引用） | 目标工作区外的文档（源工作区残留文档）只 `annotate`；需源 `WRITE`；只替换匹配到的 `[[旧标题]]` 片段，其余字节不动 |
| C6 | （可追溯） | `CHANGE_TYPES` 增 `move_repair`；版本 `change_summary="跨工作区移动引用修复"`；`core_event("documents.references_repaired")` 两侧各一条（含统计，不含正文） |
| C7 | （幂等 / 不覆盖） | 无残留 → 200 `{changed: 0}` 不生成版本；版本冲突按 D6 处理 |
| C8 | （不静默） | 文档页「文档链接」抽屉对 `broken` 且能判定「目标已移至其它工作区」的条目给出提示；导出侧沿用现有降级文案 |
| C9 | （有界） | 单次 ≤200 篇；`snapshot` 单表行数沿用导出上限；扫描只读正文，不引新依赖 |
| C10 | （存量不变） | 默认 `none`；不触发修复时正文与版本零变化 |

## Context

现状逐条核对（以代码为准）。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 双链按**当前工作区标题**解析，返回 `exists/broken` | `documents/services/content.py:831` | 跨区必断，且无法表达「目标在别的工作区」 | 确认（C1/C8） |
| 2 | 已有同工作区断链改指端点 `POST /{doc_id}/links/repair` | `content.py:893`、`routers/documents.py` | 只支持改指本工作区现存文档，跨区无出口 | 确认（C5） |
| 3 | 反链扫描按标题在**当前工作区**匹配 | `content.py:784` | 源工作区文档的反链在移动后指向不存在的标题 | 确认（C1/C5） |
| 4 | 双链词法 `iter_wikilinks` 忽略代码围栏、支持锚点/别名 | `documents/services/parse.py:139` | 修复必须复用同一词法，否则会误改围栏内文本 | 确认（C5/C9） |
| 5 | 数据表引用有解析与**快照改写**能力（导出用） | `export/table_refs.py:83`、`:226` | `snapshot` 策略可直接复用 | 确认（C2） |
| 6 | 正文写入唯一入口 `save_version` + `sync_fts` | `content.py` | 修复 = 生成新版本（可回滚、可审计） | 确认（C6） |
| 7 | 移动链路唯一入口 `move_nodes_to_workspace` | `documents/services/move.py` | 需要接入策略参数与修复调用 | 确认（C4） |
| 8 | 变更类型枚举 `CHANGE_TYPES` 是纯字符串常量（无 DB 约束） | `documents/models.py` | 新增 `move_repair` 不需要迁移 | 确认（C6） |
| 9 | 文档页「文档链接」抽屉只展示本工作区断链 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 需要展示「已移至其它工作区」的原因 | 确认（C8） |

**核心缺陷（需求要补的）**：ADR 0155 让文档能跨工作区搬迁，但**引用仍是工作区局部语义**——`[[标题]]` 与 `{{table:id}}` 都只能在本工作区内解析，移动后必断，而系统既不能诊断、也没有任何修复通道（用户只能自己在正文里改，且不知道改哪些）。

设计目标（不变量）：

- **R1 显式**：正文改写必须由用户显式选择策略；默认 `none`，绝不静默改内容。
- **R2 可预览**：任何修复都能先看到「原文 → 新文」清单，确认后才落库（与 AI 动作同一范式）。
- **R3 可追溯**：修复生成新版本（`change_type=move_repair`），可回滚；事件留痕不含正文。
- **R4 不误改**：只替换诊断命中的引用片段（复用 `iter_wikilinks` / `parse_table_ref_line`），代码围栏内文本与其余字节一律不动。
- **R5 幂等**：无残留引用时不生成版本；重复执行不累积改写。
- **R6 存量不变**：默认策略下正文 / 版本 / 导出与升级前逐条一致。

> R1 / R3 若评审要求登记，按 `ADR 0156 R1/R3` 补 CONSTRAINTS（H27）；当前未登记。

## Decision

### 1. 数据模型

**无新表、无新列、无迁移**。仅：

- `documents/models.py` 的 `CHANGE_TYPES` 追加 `CHANGE_TYPE_MOVE_REPAIR = "move_repair"`（纯字符串枚举，无 DB 约束）。
- 版本正文由既有 `save_version` 写入；外存大正文沿用现有分级存储。

### 2. 判定算法（唯一入口）

新服务 `src/cndb/plugins/documents/services/references.py`：

```python
RepairStrategy = Literal["none", "annotate", "snapshot"]

@dataclass
class ReferenceIssue:
    document_id: int          # 引用所在的文档
    workspace_id: int         # 引用所在工作区
    kind: str                 # wikilink | table_ref
    raw: str                  # 正文原文（如 [[旧标题]] 或 {{table:12|width=75}}）
    target_title: str | None  # 双链目标标题
    target_table_id: int | None
    reason: str               # target_moved | target_left_behind | table_in_other_workspace | target_deleted | not_found
    target_workspace_id: int | None
    target_workspace_name: str | None

def diagnose_move_references(db, *, source_workspace_id, target_workspace_id, moved_doc_ids) -> list[ReferenceIssue]
def preview_repair(db, issues, strategy) -> list[RepairPreview]      # {document_id, raw, next}
def apply_repair(db, *, issues, strategy, actor) -> RepairResult      # 生成版本 + 事件
```

诊断顺序（唯一实现）：

1. 取被移动文档（`moved_doc_ids`，即 ADR 0155 的子树集合）的最新版本正文，抽出 `[[…]]` 与 `{{table:…}}`；
2. 双链：目标标题若**已随子树移动**（在 `moved_doc_ids` 内）→ 不断链（同一个新工作区，仍可解析），跳过；否则若在源工作区仍存在 → `target_left_behind`；不存在 → `not_found`；
3. 表格引用：`table.workspace_id == target_workspace_id` → 正常；`== source_workspace_id` → `table_in_other_workspace`（修复候选）；不存在 → `target_deleted`；
4. 反向引用：在**源工作区**扫描 `[[被移动文档标题]]`（`content.backlinks` 的 SQL 反向使用），命中 → `target_moved`（引用方在源工作区，只能 annotate）；
5. 去重（同文档 + 同 `raw` 只报一条），按 `workspace_id, document_id, raw` 排序，最多返回 2000 条。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `POST /api/v1/workspaces/{wid}/documents/references/preview` | 新增：body `{document_ids, target_workspace_id, strategy}` → `{issues, previews, affected_documents}`（**不落库**） |
| `POST /api/v1/workspaces/{wid}/documents/references/repair` | 新增：同 body + 可选 `confirm=true` → 执行（生成版本 + 事件） |
| `POST /api/v1/workspaces/{wid}/documents/move-to-workspace` | 修改：新增可选 `repair_strategy`（默认 `none`），非空时移动完成后对**被移动文档**执行修复 |

静态段路由（`references/*`）与 ADR 0155 的 `move-*` 一样**注册在 `/{doc_id}` 之前**。

### 4. 边界与例外

1. **代码围栏内的 `[[…]]`**：`iter_wikilinks` 不解析 → 修复不改 → 保持字面文本。
2. **锚点 / 别名**：`[[标题#锚点|别名]]` 修复时保留锚点与别名（沿用 `parse.format_wikilink`）。
3. **表格引用的参数**：`{{table:12|view=3|width=75}}` 在 `annotate` 时整体替换为说明文本；`snapshot` 时按 `view/limit/width` 生成静态表格（`width` 对静态表格无效，直接丢弃）。
4. **快照失败**（表已删 / 权限变更 / 行数超限）：该条降级为 `annotate` 文案，不中断整批。
5. **反向引用**：只 annotate（跨区无法解析）；需源工作区 `WRITE`，否则该部分跳过并在结果 `skipped` 中说明。
6. **草稿**：不参与修复（只改已提交版本）；若用户有个人草稿，草稿内容原样保留（保存时会基于新版本再次分派）。
7. **已修复**：诊断为空 → `{changed: 0}`，不生成版本（R5）。
8. **版本推进**：预览后正文被他人推进 → 按 D6 口径处理（默认 **重新诊断后修复最新版本**，并在响应里返回 `recomputed: true`；如评审要求严格，可改为 409 `stale_version`）。
9. **上限**：单次修复 ≤200 篇文档（与移动同口径）；`issues > 2000` 时只返回前 2000 条并在响应标记 `truncated`。
10. **跨工作区活引用**：本期不做（依赖 ADR 0154 的链接获批 + 只读表读取），`{{table:}}` 一律按「失效引用」处理。

### 5. 迁移

无（无 schema 变更；`CHANGE_TYPES` 是纯字符串枚举）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API | `frontend/src/api/documents.ts` | 新增 `previewReferenceRepair` / `repairReferences`；`moveToWorkspace` payload 增 `repair_strategy` |
| 移动弹窗 | `frontend/src/pages/documents/MoveDocumentModal.tsx` | 新增「引用修复」选项（不处理 / 注释说明 / 表格快照），默认不处理；选择后移动成功提示「已修复 N 条引用」 |
| 文档页 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | 「文档链接」抽屉：断链条目补充「目标已移至『工作区名』」提示与「一键修复引用」入口（走预览 → 确认） |
| 预览弹窗 | `frontend/src/pages/documents/ReferenceRepairModal.tsx`（新增） | 列出「原文 → 新文」与受影响文档，确认后执行 |

样式遵循 H24 / H25 / H29；弹窗随文档页 lazy chunk（H31）。

### 7. 测试清单

**判定层（单测）**
- `diagnose_move_references`：两方向、`target_left_behind` / `target_moved` / `table_in_other_workspace` / `target_deleted`、去重与排序、代码围栏不命中。
- `preview_repair`：`annotate` 与 `snapshot` 的「原文 → 新文」逐条断言（含锚点/别名与 `view/width` 参数）。
- 幂等：二次诊断为空。

**接口层**
- 预览不落库（版本数不变）；执行生成新版本（`change_type=move_repair`、`version +1`、正文按策略改写）。
- 带 `repair_strategy=snapshot` 的移动：移动 + 快照一次完成，目标侧正文为静态表格，源侧文档被 annotate。
- 反向引用：源工作区文档只 annotate，其余字节不变；源 `WRITE` 缺失时跳过并说明。
- 快照失败（目标表已删）降级 annotate。
- 超限 400（>200 文档）；`issues` 截断标记。
- 存量：不带策略的移动与原用例逐条一致。

**迁移 / 备份**
- 无迁移；`make test` 存量用例全绿。
- 备份往返：修复产生的新版本随备份往返（既有版本路径不变）。

**前端单测**
- 移动弹窗策略选项与提交载荷；预览弹窗渲染「原文 → 新文」与受影响文档；执行后提示计数；失败展示后端 detail。

**e2e**
- 含 `[[双链]]` 与 `{{table:…}}` 的文档移动到目标工作区并选「表格快照」→ 目标工作区正文显示静态表格与注释文案，文档页不再提示失效。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P2-1** | `services/references.py` 诊断 + 预览 + 两策略执行 + 单测/接口测试（不含前端） | 中（正文改写必须精确，靠复用既有词法 + 逐条断言兜底） |
| **P2-2** | 移动链路接入 `repair_strategy` + 反向引用 annotate + 事件/版本类型 | 中（与 ADR 0155 的原子顺序耦合） |
| **P2-3** | 前端：移动弹窗策略项、预览弹窗、文档链接抽屉入口 + 单测 + e2e | 低 |
| **P2-4（评估）** | 跨工作区**活引用**：ADR 0154 链接获批后，`{{table:}}` 只读解析到源表 | 高（依赖 0154 落地与授权面） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 默认是否自动修复 | **默认 `none`**，修复必须显式选择 | 正文改写是内容变更，静默改用户文字不可接受 | 移动时默认 annotate（用户正文被改却不知情） | `move.py`、`MoveDocumentModal.tsx` |
| D2 | 修复策略集合 | `none` / `annotate` / `snapshot` 三档 | annotate 保信息不保内容；snapshot 保内容但会失真（静态快照） | 只做 annotate（用户仍看不到数据）；只做 snapshot（表格失真且无法再更新） | `references.py` |
| D3 | `{{table:…}}` 是否保留「活引用」 | 本期一律按失效引用处理；活引用依赖 ADR 0154，放 P2-4 评估 | 跨区读表需要授权面（H15 天花板），不属于移动修复本体 | 直接把表复制/重建到目标工作区（数据双份、后续漂移） | `references.py`、`P2-4` |
| D4 | 改写粒度 | 只替换诊断命中的 `raw` 片段（复用 `iter_wikilinks` / `parse_table_ref_line`） | 保证「其余字节不动」（R4），避免整体重排正文 | 正则全局替换（易误伤围栏内文本与相似写法） | `references.py` |
| D5 | 版本与审计 | 修复生成新版本（`change_type=move_repair`）+ `core_event` | 可回滚、可审计；与既有保存语义一致 | 原地改正文不生成版本（不可回溯，违反 H35 精神） | `content.save_version`、`references.py` |
| D6 | 并发冲突口径 | **重新诊断后修复最新版本**（默认），响应带 `recomputed` 标记 | 修复是幂等「让引用可用」目标，不是覆盖用户内容；重算更符合意图 | 409 `stale_version`（用户要重新预览一次，体验差）；盲目覆盖（丢用户改动） | `references.py` |
| D7 | 反向引用处理 | 只 `annotate`（跨区无法解析标题）；需源工作区 `WRITE` | 源工作区文档可能属于别人，改写需要授权 | 自动改成「已移出」并删除链接（丢信息）；不做反向（断链永久存在） | `references.py` |
| D8 | 预览形态 | 服务端返回 `{document_id, raw, next}` 清单（不回传全文） | 与 AI 动作「建议 → 预览 → 确认」同范式；正文体积大不回传 | 前端本地改写预览（可能与服务端口径漂移） | `references.py`、`ReferenceRepairModal.tsx` |

## Consequences

- **正向**：跨工作区移动后引用不再「静默失效」——可诊断、可预览、可按策略修复（注释或静态快照），修复可回滚、可审计。
- **负向**：新增一条「改写正文」的写路径（与保存、回滚同级），必须严格控制替换粒度；快照会失真（表格数据固定在修复时刻）。
- **风险与缓解**：误改 → 只替换命中片段 + 逐条断言 + 版本可回滚；用户误解快照语义 → 弹窗文案明确「快照为修复时刻的数据，不会随后更新」。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 文档跨工作区移动 | ADR 0155 | 真移动；引用不自动修复（本 ADR 补齐） | ADR 0155 |
| 跨工作区只读引用 | ADR 0154 | `workspace_link` 提供只读表访问；P2-4 才可能支撑「活引用」 | ADR 0154 |
| 同工作区断链改指 | 既有 `/links/repair` 端点 | 本 ADR 不改该端点，跨区修复走新端点 | 既有实现 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P2-1 | 已落地 | `src/cndb/plugins/documents/services/references.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/schemas/__init__.py` | `tests/test_document_reference_repair.py` | 见「交接」回填 |
| P2-2 | 已落地 | `src/cndb/plugins/documents/services/move.py`、`src/cndb/plugins/documents/models.py` | `tests/test_document_reference_repair.py` | 见「交接」回填 |
| P2-3 | 已落地 | `frontend/src/pages/documents/MoveDocumentModal.tsx`、`frontend/src/pages/documents/ReferenceRepairModal.tsx`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/api/documents.ts` | `frontend/src/pages/documents/ReferenceRepairModal.test.tsx`、`frontend/tests/e2e/critical/document-move-workspace.spec.ts` | 见「交接」回填 |

## 交接（会话结束更新）

- 当前阶段：P2-1 / P2-2 / P2-3 全部落地（2026-11-25；D6 采用「重新诊断修复最新版本」，D7 反向引用同批 annotate）
- 已完成：需求卡片 0156、本 ADR、现状核对（双链解析 / 断链改指 / 反链 / 词法 / 数据表引用快照 / 版本写入 / 移动链路 / 变更类型枚举 / 文档页断链抽屉）
- 下一步：人工验收后 `make push`（H4 / H6）；P2-4（跨工作区活引用）待 ADR 0154 链接能力就绪后单独立项
- 已知坑：① 必须复用 `iter_wikilinks` / `parse_table_ref_line`，否则代码围栏内文本会被误改；② `snapshot` 的 `width` 参数对静态表格无效，替换时要丢弃；③ 反向引用改写源工作区他人文档需要源 `WRITE`，缺失时只能跳过并说明；④ 与 ADR 0155 的原子顺序耦合：修复发生在移动提交之后，若修复失败不回滚移动（用户可再次执行修复，幂等）
- 最近一次全绿：后端 7559 passed（新增 12 例引用修复 + 20 例移动回归）、前端 `ReferenceRepairModal` 6 例 + `MoveDocumentModal` 8 例 + `DocumentsPage`/`DocumentEditorPage` 回归 144 passed、e2e `document-move-workspace.spec.ts` 4 passed、`bundle-budget` 在预算内 @ 本地 2026-11-25

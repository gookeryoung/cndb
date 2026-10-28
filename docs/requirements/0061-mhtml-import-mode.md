# 需求卡片：MHTML 导入可选转换（转 Markdown 或原样存档，默认不转换）

- 编号：0061（与 ADR `docs/adr/0061-*.md` 同号，卡片存 `docs/requirements/0061-mhtml-import-mode.md`）
- 来源 / 提出人：需求方（会话）
- 日期：2026-10-28
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 导入的MTHML能否选择转MD或者不转换，默认不转换。

方案口径（需求方已确认的讨论结论）：批次级开关、默认原样存档、保留 ADR 0049 转换链路、预览随模式联动、默认值变更需文档说明。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 能否选择转MD或者不转换 | `POST /import/files/analyze` 与 `POST /import/files` 新增可选表单参数 `mhtml_mode: 'convert' \| 'archive'`；缺省 `archive`（向后兼容调用方不传参） | documents plugin `routers/file_import.py` | 接口单测：缺省 / convert / archive 三种取值 |
| C2 | 默认不转换 | 缺省（`archive`）时 `.mhtml` / `.mht` 走原样存档 assets 通道（与 PDF 同口径：`is_asset`、不转 Markdown、不参与编辑、可下载原件） | `services/importers/reader.py`、`importer.py` | 后端单测：默认导入后生成素材文档而非 Markdown 文档 |
| C3 | 选择转MD | `mhtml_mode='convert'` 时沿用 ADR 0049 转换链路（`convert_mhtml` → Markdown + 素材展开），行为与现状一致 | `services/importers/mhtml.py` | 后端单测：convert 模式产物与现状快照一致 |
| C4 | （性能口径） | `_expand_mhtml_resources` 仅在 convert 模式执行，archive 模式不解包素材索引 | `services/importers/importer.py:130` | 后端单测：archive 模式不触发素材展开 |
| C5 | （预览一致性） | analyze 预览随 `mhtml_mode` 联动：archive 时 mhtml 项标记原样存档（`is_asset` / format 正确），convert 时为可导入文档；预览计数与落库结果一致 | `services/importers/reader.py`、`importer.py` | 后端单测：同一批次两种模式的 analyze 断言 |
| C6 | （前端开关） | 通用导入弹窗确认区新增「MHTML 转 Markdown」开关，默认关；开关状态随 analyze / import 提交传递；archive（开关关）时「导入内嵌图片」开关禁用并提示不适用 | frontend `DocumentImportModal.tsx`、`api/documents.ts` | 前端单测：默认值、开关切换后提交参数、禁用态 |
| C7 | （阅读体验，best effort） | DocumentAssetView 对 `content_type=mhtml` 尝试 `<iframe>` 内嵌预览；若现有白名单机制不支持则退化为仅下载（不阻塞验收） | frontend `DocumentAssetView.tsx` | 前端单测或人工验证 |
| C8 | （行为变更说明） | 默认值从「转换」变为「不转换」属行为变更：CHANGELOG 记录，帮助教程文案同步（含两种模式差异） | `CHANGELOG`、`frontend/src/pages/help/content/tutorials.tsx` | `make check-docs` |
| C9 | （回归口径） | Obsidian 库导入（vault）不受影响：vault 链路不新增 `mhtml_mode`，行为不变 | `services/importers/` vault 相关 | 后端 vault 导入单测回归通过 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | MHTML 无条件转 Markdown | `src/cndb/plugins/documents/services/importers/reader.py:146` | 转换入口，需按模式分流 |
| 2 | MHTML 素材解包 | `src/cndb/plugins/documents/services/importers/importer.py:130`（`_expand_mhtml_resources`） | C4：仅 convert 执行 |
| 3 | analyze / import 接口参数 | `src/cndb/plugins/documents/routers/file_import.py:62,80` | C1：新增 `mhtml_mode` 表单参数 |
| 4 | 转换链路（ADR 0049） | `src/cndb/plugins/documents/services/importers/mhtml.py:151`（`convert_mhtml`） | C3：保留不动 |
| 5 | 前端提交参数 | `frontend/src/api/documents.ts:321,771,798` | C6：payload / form 增加 `mhtml_mode` |
| 6 | 前端弹窗确认区 | `frontend/src/pages/documents/DocumentImportModal.tsx` | C6：开关与禁用联动 |
| 7 | 素材预览白名单 | `frontend/src/pages/documents/DocumentAssetView.tsx:107` | C7：目前仅 pdf 内嵌预览 |
| 8 | 教程文案 | `frontend/src/pages/help/content/tutorials.tsx` | C8：导入说明更新 |
| 9 | Obsidian 库导入 | `services/importers/`（vault 链路） | C9：确认不受影响 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 开关粒度：批次级开关（不做每文件勾选）——需求方已确认
- [x] 默认值：`archive`（不转换）——需求方已确认；行为变更经 C8 说明
- [x] mhtml 原样存档后的阅读体验：优先尝试 iframe 内嵌预览，不支持则退化为仅下载，不阻塞验收（C7 为 best effort）——待需求方确认
- [x] 方案分级：S1（跨前后端 + 默认值口径变化，无架构分叉），写卡片不强制 ADR；若实现中预览字段联动扩散再升级 S2——待需求方确认

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

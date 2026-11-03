# 需求卡片：Word（docx）/ Excel（xlsx）原件在线预览

- 编号：0087
- 来源 / 提出人：用户（会话）
- 日期：2026-11-03
- 关联 ADR：0087（S2：新增原件族 `word` 内容类型 + 导入模式 + 只读预览端点契约）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档，增加docx，xlsx文件在线预览功能

需求澄清（2026-11-03 需求方确认）：按「B 方案」——导入 .docx 时可选「转换 Markdown / 原件存档」，**默认仍转 Markdown**（向后兼容），原件存档时在线阅读原件；本次范围**仅文档模块**（表格附件字段不在本期）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「xlsx 文件在线预览」 | `content_type=xlsx` 的原件在阅读器内直接渲染为表格（**多工作表按标签页分页切换**、首行作表头、数值 / 日期格式化为文本），不再给「不支持在线预览」下载卡 | `documents/services/preview/`、`documents/routers/documents.py`、`frontend/src/pages/documents/DocumentAssetView.tsx` | 判定层单测（渲染 / 多表 / 截断）+ 接口层预览端点 + 前端单测分派 |
| C2 | 「docx 文件在线预览」 | 导入链路新增 `docx_mode`：`convert`（默认，沿用 ADR 0010 转 Markdown）/ `archive`（原件存档，`content_type=word`）；archive 存档的原件在阅读器内渲染为 HTML（标题 / 段落 / 加粗斜体 / 列表 / 表格 / 内嵌图片） | `documents/services/importers/`、`documents/routers/file_import.py`、`frontend/src/pages/documents/DocumentImportModal.tsx` | 判定层单测（模式分派 / 渲染）+ 接口层导入 + 前端单测（开关切换重解析） |
| C3 | （安全口径） | 预览 HTML 一律在 `sandbox` 禁脚本 iframe 渲染；后端输出全部文本转义、加 `Content-Security-Policy: sandbox` + `X-Content-Type-Options: nosniff`；预览读权限与 `/asset` 同源（工作区成员 + 文档可见性） | `documents/services/preview/`、`documents/routers/documents.py`、`frontend/src/pages/documents/DocumentAssetView.tsx` | 接口层断言响应头与 404；前端单测断言 sandbox 属性 |
| C4 | （有界口径） | 解析与渲染有硬上限：工作表数 / 单表行列 / 总单元格 / 单元格文本长度 / 内嵌图片数量与总字节 / 输出 HTML 体积；超限截断并在页面提示，不随原件体积线性膨胀内存 | `documents/services/preview/office.py` | 判定层单测：超限截断标记、空文档、损坏原件报错 |
| C5 | （兼容口径） | 默认导入行为不变：`.docx` 仍转 Markdown、`xlsx/xls/pptx/ppt/pdf/图片` 仍原样存档；旧版二进制 `.xls` / `.doc` 无预览能力时保持下载卡；未 archive 的普通 Markdown 文档不受影响；备份 / 恢复无需协议变更 | `documents/services/importers/`、`workspaces/services/` | 既有导入 / 备份单测回归通过 |
| C6 | （展示口径） | 格式映射新增 `word` → 原件族（Word 图标 / 蓝色 / 只读标记），文档树 / 列表 / 搜索统一取用；导入弹窗新增「Word 原样存档」开关，切换后重新解析预览 | `frontend/src/components/Document/docFormat.ts`、`frontend/src/pages/documents/DocumentImportModal.tsx` | 前端单测：格式映射 / 开关切换触发重解析 |
| C7 | （文档口径） | 帮助教程「文档导入」条目补充 Word 原样存档与在线预览说明；CHANGELOG 记录新增能力；CONTEXT.md 术语补 `word` 原件族与预览口径 | `frontend/src/pages/help/content/tutorials.tsx`、`CHANGELOG.md`、`CONTEXT.md` | `make check-docs` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `.xlsx` 原件族只有下载卡 | `frontend/src/pages/documents/DocumentAssetView.tsx:186` | C1 改造点 |
| 2 | `.docx` 导入即转 Markdown、不保留原件 | `src/cndb/plugins/documents/services/importers/formats.py:27`、`reader.py:176` | C2 需新增 archive 模式 |
| 3 | 原件族 `content_type` 枚举无 `word` | `src/cndb/plugins/documents/models.py:48-52` | C2 / C6 需扩展枚举 |
| 4 | 预览端点只接受 `mhtml` | `src/cndb/plugins/documents/routers/documents.py:782` | C1 / C2 / C3 扩为 Office 预览 |
| 5 | 导入端点 / 编排无 `docx_mode` | `src/cndb/plugins/documents/routers/file_import.py:66`、`importers/importer.py:169` | C2 |
| 6 | 前端格式映射 `word` 标记非原件族 | `frontend/src/components/Document/docFormat.ts:46` | C6 |
| 7 | 导入弹窗只有 MHTML 模式开关 | `frontend/src/pages/documents/DocumentImportModal.tsx:101` | C6 |
| 8 | 原型解析能力已在依赖中（`python-docx` / `openpyxl`） | `src/cndb/plugins/documents/services/importers/docx.py`、`tables/services/transfer/xlsx_rows.py` | 复用，无新增依赖 |

## 未决问题（已确认）

- [x] ① docx 原件如何取得：**结论**按 B 方案新增 `docx_mode`（默认 `convert`，可选 `archive`），archive 落 `content_type=word` 原件；不改默认行为。
- [x] ② 预览渲染位置：**结论**后端生成自包含 HTML + 前端沙箱 iframe（与 0064 MHTML 同构），不引入前端表格 / Word 解析大库（避免破 `bundle-budget`）。
- [x] ③ 本期范围：**结论**仅文档模块；表格附件字段的 docx / xlsx 预览不在本期。
- [x] ④ 方案分级：**结论**S2（新增原件族内容类型、导入模式与端点契约），补 ADR 0087。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（①B 方案 / ②后端 HTML / ③仅文档模块 / ④S2）

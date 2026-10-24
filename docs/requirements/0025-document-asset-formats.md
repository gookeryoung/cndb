# 需求卡片：文档多格式上传（PDF / Office / 图片原样存档）与按格式区分图标

- 编号：0025（与 ADR `docs/adr/0025-*.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-24
- 关联 ADR：`docs/adr/0025-document-asset-formats.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档功能增强，需支持PDF等格式文件上传，并在文档树等地方为不同格式配置不同的图标。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 文档功能增强，需支持 PDF 等格式文件上传 | 明确要求 PDF 可上传；按需求方确认的范围，本次新增 **PDF / Office（xlsx、xls、pptx、ppt）/ 图片（png、jpg、jpeg、gif、webp、svg、bmp）**；md / docx / html 沿用 ADR 0010 的转换通道 | `plugins/documents/services/importers/`、`routers/file_import.py` | 接口测试：各格式各一例导入成功 |
| C2 | …等格式文件上传 | 无法可靠转成 Markdown 的格式**原样存档**：原件存工作区上传目录，文档节点记录格式与原件信息；正文区以阅读器方式呈现，不进入 Markdown 编辑器 | `plugins/documents/models.py`、`services/importers/importer.py`、`frontend/src/pages/documents/` | 测试：原件字节可原样取回（长度 + 前缀一致） |
| C3 | 在文档树等地方… | 树上按格式渲染图标；同时覆盖文档列表、回收站、工作区搜索等出现文档条目的地方（同一份映射，不各写一套） | `frontend/src/pages/documents/docFormat.ts` 及各调用点 | 前端单测：同一 `content_type` 在各处取到同一图标与配色 |
| C4 | 为不同格式配置不同的图标 | 图标**形状 + 配色**双区分（PDF 红、Word 蓝、Excel 绿、PPT 橙、图片紫、Markdown 蓝灰、未知灰），不只靠颜色区分（色弱可辨） | 同上 | 前端单测：格式 → (图标, 颜色) 映射唯一且非空 |
| C5 | 功能增强…（健壮性） | 沿用既有边界：额度校验、逐条隔离（单文件失败只跳过该条）、冲突三策略、权限 editor+；原件读取走文档可见性校验，不做「拿到键即可读」的裸链接 | `importers/`、`routers/documents.py` | 测试：非成员 / 看不到的草稿读原件 404；超限只跳过该条 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 导入白名单只有 md / docx / html，其余扩展名直接 skip | `importers/reader.py:26-30` | PDF / 图片 / Office 会被判「不支持的格式」 |
| 2 | `content_type` 只有 `markdown` / `folder`，创建时硬编码 | `models.py:43-44`、`services/content.py:254` | 无法表达「这是一份 PDF」 |
| 3 | 正文一律是 `DocumentVersion.content`（文本），分级存储也按文本 gzip | `services/content.py:211-240` | 二进制原件不能塞进版本正文 |
| 4 | 附件落盘 + 归属校验已有（file_key → 表/行/文档） | `plugins/files/services.py`、`plugins/tables/routers/files.py` | 原件可复用同一套落盘与权限校验 |
| 5 | 树 / 列表文档图标恒为 `FileTextOutlined` | `DocumentTree.tsx:376`、`DocumentsPage.tsx:729` | 需要格式映射 |
| 6 | 编辑器页对任何文档都渲染 Markdown 编辑 / 预览 | `DocumentEditorPage.tsx:1106-1174` | 原件文档需要阅读器形态 |

## 未决问题

- [x] **PDF 等格式的处理方式**：原样存档 + 内置预览（不可编辑），不抽文本转 Markdown（用户 2026-10-24 确认）。
- [x] **格式范围**：PDF、Office 其它（xlsx / xls / pptx / ppt）、图片（png / jpg / jpeg / gif / webp / svg / bmp）；纯文本类（txt / csv）本次不纳入（用户 2026-10-24 确认）。
- [x] **图标配色**：格式专属色（PDF 红 / Word 蓝 / Excel 绿 / PPT 橙 / 图片紫 / Markdown 蓝灰），形状同时不同（用户 2026-10-24 确认）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-24）

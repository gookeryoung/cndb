# 需求卡片：MHTML 导入（内嵌素材一并入库，避免引用图片丢失）

- 编号：0049（与 ADR `docs/adr/0049-*.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-27
- 关联 ADR：`docs/adr/0049-mhtml-import.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 需要支持包含素材的MHTML格式的导入，那样就能避免引用图片丢失的问题。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 需要支持…MHTML格式的导入 | 通用文件导入通道接受 `.mhtml` / `.mht`：单个 MHTML → 1 篇 Markdown 文档（解析 MIME multipart 根 HTML 部分并走既有 html → Markdown 转换管线，标题识别 / 空白规整与 HTML 同口径）；不支持或损坏的按「单条跳过」计入 `skipped`，不中断整批 | `plugins/documents/services/importers/formats.py`、`reader.py`、新增 `mhtml` 解析、`routers/file_import.py` | 接口测试：样例 MHTML 导入后生成 1 篇文档，标题 / 正文 / 结构正确 |
| C2 | 包含素材的 | MHTML 内嵌素材（MIME 各 part）解包：图片类素材按 `Content-Location` / `Content-ID` 建立「URL → 字节」索引，正文中的引用改写为站内附件（`file:` 引用），经 `image_sink` 落盘 + 文档归属登记；传输编码（base64 / quoted-printable）先解码；非图片素材（CSS 等）丢弃 | `importers/mhtml` 解析、`importers/html.py`（本地图片索引层）、`importers/importer.py`（附件落盘） | 测试：含 2 张内嵌图片的 MHTML 导入后正文出现 `file:` 引用，附件字节与原素材一致（长度 + 前缀） |
| C3 | 避免引用图片丢失的问题 | 正文引用与素材的匹配口径：MHTML 内素材**全部内联**（相对 / 绝对 / fragment `cid:` 均按 Content-Location 匹配），匹配不到时降级为占位符并记 warning（与 HTML 本地图片同款，不静默吞图）；未被包进 MHTML 的外部 http(s) 图片保留原 URL（与现行 HTML 口径一致，不联网抓取） | `importers/mhtml` 解析 + `html.py` 图片分派 | 测试：素材齐全时正文无「图片未导入」占位与告警；缺素材时出现占位 + warning；外链保留原 URL |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 导入白名单只有 `.md/.markdown/.docx/.html/.htm` + 原件族，`.mhtml` / `.mht` 被判「不支持的格式」 | `src/cndb/plugins/documents/services/importers/formats.py:26` | 需把 MHTML 纳入可转换族 |
| 2 | `convert_file` 按 `MARKDOWN/DOCX/HTML` 三分支分派，无 MHTML 分支 | `src/cndb/plugins/documents/services/importers/reader.py:35-45,137-145` | 需新增分派（解包后复用 html 转换器） |
| 3 | HTML 转换器的本地图片按「批次相对路径」索引，MHTML 素材键是 `Content-Location` URL，两者口径不同 | `src/cndb/plugins/documents/services/importers/html.py:27,176-219,395-406`（`LocalImages` / `_resolve_local_src` / `convert_html`） | 需在 MHTML 解包层做 URL → 字节映射（候选：把素材以归一路径喂给 `local_images`） |
| 4 | 附件落盘 / 归属登记 / `import_attachments` 开关已有 | `src/cndb/plugins/documents/services/importers/importer.py:41-97,256-264` | MHTML 素材复用 `image_sink`（含开关关闭时的降级告警） |
| 5 | 单文件上限：可转换格式 8MB，MHTML 含内嵌图片普遍偏大 | `src/cndb/plugins/documents/services/importers/reader.py:42-43`（`MAX_FILE_BYTES`） | 上限口径待定（见未决问题 3） |
| 6 | 前端上传 `accept` 与格式文案未含 MHTML | `frontend/src/api/documents.ts:329-330`（`FILE_IMPORT_ACCEPT`）、`frontend/src/pages/documents/DocumentImportModal.tsx:59-60,120,326` | 需补 `.mhtml,.mht` 与标签 / 提示文案 |
| 7 | 转换层与接口层测试基座已有 | `tests/test_documents_file_import_convert.py`、`tests/test_documents_file_import_api.py` | 新增 MHTML 用例挂在同一基座 |
| 8 | 标准库 `email` 解析器可解析 MIME multipart（边界 / 传输编码 / Content-Location） | Python 标准库（无第三方依赖候选） | 是否引第三方库待 ADR 定夺 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] **扩展名范围**：`.mhtml` 与 `.mht` 都支持（用户 2026-10-27 确认）。
- [x] **导入产物形态**：只产出转换后的 Markdown 文档，不保留 MHTML 原件（用户 2026-10-27 确认）。
- [x] **单文件体积上限**：MHTML 放宽到 32MB（其余可转换格式维持 8MB；超限口径仍为「单条跳过」）（用户 2026-10-27 确认）。
- [x] **非图片素材**：CSS / 字体等一律丢弃（用户 2026-10-27 确认）。
- [x] **`import_attachments` 关闭时**：素材不丢——展开为 md 同级 `_assets/` 相对路径下的图片文档管理，正文保留相对引用（用户 2026-10-27 确认）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-27）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

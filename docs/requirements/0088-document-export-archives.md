# 需求卡片：文档树导出（压缩文档 / Obsidian 库两种压缩包，原件原样导出）

- 编号：0088
- 来源 / 提出人：用户（会话 2026-11-03）
- 日期：2026-11-03
- 关联 ADR：无（S1，方案并入本卡片；上游需求 0072）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。
> 本需求修订 0072：导出方式改为「压缩文档 / Obsidian 库」两种（均为 `.zip`），并修「原件被转成空 Markdown」的缺陷。

## 需求原句（逐字）

> 文档导出存在严重问题，1.应提供两个选项，一是压缩文档，二是obsidian库；2.文件应原样导出而不是转成空MD再导出

前一版需求（已作废）：~~导出文档，应当首先支持压缩包文件，默认.zip格式；移除文件夹选项。~~

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「应提供两个选项，一是压缩文档，二是obsidian库」 | 导出弹窗提供两种方式，均为 `.zip`：① **压缩文档**（默认）——纯文档树，不含 front-matter 与 `.obsidian/`；② **Obsidian 库**——文档树 + front-matter + 最小 `.obsidian/` 配置；两种方式的文件名分别为 `{工作区名}-documents-{YYYYMMDD-HHMM}.zip` / `{工作区名}-obsidian-{YYYYMMDD-HHMM}.zip` | `documents/services/obsidian.py`、`documents/routers/vault.py`、`frontend/src/pages/documents/DocumentsPage.tsx`、`frontend/src/api/documents.ts` | 后端单测：两种方式的 front-matter / `.obsidian` 有无 + 文件名；前端单测：默认「压缩文档」、切换后带 `style=obsidian` |
| C2 | 「文件应原样导出而不是转成空MD再导出」 | 原件族文档（`asset_file_key` 非空：PDF / Excel / Word 存档 / PPT / 图片 / MHTML）按**原件字节 + 原始扩展名**写入压缩包，不再渲染为空 `.md`；缺失原件的条目跳过；扩展名参与同名去重（同名 `报告.md` 与 `报告.pdf` 并存不互相覆盖） | `documents/services/obsidian.py`（`export_vault`） | 后端单测：pdf / xlsx / docx 原字节回读、无空 `.md`、同名共存 |
| C3 | （结构口径） | Markdown 文档仍导出正文：压缩文档不带 front-matter，Obsidian 库带；站内图片按既有规则改写为 `attachments/` 并随包导出；文件夹层级保留；可见性裁剪与正文一致（未发布草稿按规则裁剪） | `documents/services/obsidian.py` | 既有导出用例回归（结构 / 图片改写 / 命名冲突 / 空工作区 400） |
| C4 | （兼容与文档） | 非法 `style` 400；`GET /export/vault` 不带 `style` 时默认 `archive`；需求 0072 卡片、CONTEXT 术语与 CHANGELOG 同步；前端 `VaultExportStyle` 类型 + 下载命名解析 | `docs/requirements/0072-document-export-dialog.md`、`CONTEXT.md`、`CHANGELOG.md`、前后端测试 | `make check-docs` / `make flow` / `make frontend-coverage` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 导出弹窗（上一版被删） | `frontend/src/pages/documents/DocumentsPage.tsx` | C1 恢复为两项（压缩文档 / Obsidian 库） |
| 2 | 导出 API 封装 | `frontend/src/api/documents.ts`（`vaultExport`） | C1 带 `style`，默认 `archive` |
| 3 | 导出实现只按正文渲染 | `src/cndb/plugins/documents/services/obsidian.py`（`export_vault`） | C2 核心缺陷：原件族被写成空 `.md` |
| 4 | 导出路由 | `src/cndb/plugins/documents/routers/vault.py` | C1/C4 恢复 `style` 参数 |
| 5 | 需求 0072 卡片 / 用例 | `docs/requirements/0072-document-export-dialog.md`、`tests/test_documents_obsidian_vault.py`、`tests/test_documents_asset_import.py`、`frontend/src/**/*.test.*` | C4 同步 |

## 未决问题（已确认）

- [x] ① 两种方式内容差异：**结论**压缩文档 = 纯文档树（无 front-matter / 无 `.obsidian/`）；Obsidian 库 = 追加 front-matter 与最小 `.obsidian/` 配置。
- [x] ② 默认方式：**结论**压缩文档（`archive`），符合「首先支持压缩包」。
- [x] ③ 原件族导出形态：**结论**保留原始字节与原有扩展名（如 `.pdf` / `.xlsx` / `.docx`），不做转换。
- [x] ④ 缺失原件：**结论**跳过该条，不生成空文件。
- [x] ⑤ 方案分级：**结论**S1（跨前后端行为修复 + 出口恢复，无数据 / 权限口径变化）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-03 需求方口述）

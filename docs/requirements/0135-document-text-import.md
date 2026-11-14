# 需求卡片：文档导入支持纯文本族（txt 等）

- 编号：0135
- 来源 / 提出人：用户（会话 2026-11-14）
- 日期：2026-11-14
- 关联 ADR：`docs/adr/0010-document-file-import.md`（S1，方案沿用既有导入管线，增量并入本卡片）

> 本卡片是**需求原文与约束编号的唯一副本**：需求澄清后先改这里，再改代码。

## 需求原句（逐字）

> 文档导入增加txt等文本格式支持

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「增加 txt 等文本格式」 | **文本族清单**：`.txt` / `.text` / `.log` / `.csv` / `.tsv` / `.json` / `.yaml` / `.yml` / `.xml` / `.ini` / `.conf` / `.properties` / `.rst` 纳入可导入格式（与 md / docx / html / mhtml 并列），单文件导入与压缩包导入同时生效；其它扩展名仍按「不支持」跳过、不中断整批 | `plugins/documents/services/text_formats.py`、`importers/formats.py`、`importers/reader.py`、`services/obsidian.py` | 后端单测：各后缀均可导入；未知后缀仍进 skipped |
| C2 | （文本转换口径） | 文本族按**原文入库**为 Markdown 正文：统一换行为 `\n`、去首尾空行；**不解析 front-matter**（`.yaml` 开头的 `---` 是内容）、**不剥离一级标题**（`#` 可能是注释）、**不转义、不重排空白**（保留缩进 / 对齐 / 连续空行，日志与配置的结构信息在空白里）；标题取文件名（去扩展名，`clean_title` 清洗），不产生「标题取自文件名」告警 | `importers/text.py`、`importers/reader.py` | 单测：连续空行 / 行内空格 / 缩进原样保留；`---` 与 `#` 不当元数据与标题 |
| C3 | （压缩包通道） | zip 压缩包导入时，文本族条目按文档导入（标题取文件名、正文原文），不再计入「不支持文件类型」告警；`attachments/` 下的附件、原件族（PDF / Office / 图片 / MHTML）与 Markdown 的既有口径不变 | `services/obsidian.py` | 接口测试：zip 内 `.txt` / `.yaml` 生成文档且正文原文；未知后缀 zip 仍 400 |
| C4 | （编码与边界） | 编码沿用 `decode_text` 兜底（utf-8-sig → utf-8 → gb18030 → big5 → chardet → latin-1）；沿用 8MB 单文件上限、批次条目 / 总体积上限；空文件按单条跳过；逐条失败不影响整批 | `importers/normalize.py`、`importers/reader.py` | 单测：GB18030 文本可读、CRLF 统一；空 `.txt` 被跳过 |
| C5 | （前端与文档） | 导入弹窗的文件选择 `accept`、格式标签（文本 / CSV / JSON / YAML / XML）与说明文案覆盖文本族；帮助教程「导入文档库」补说明；CONTEXT 术语更新；CHANGELOG 记录 | `frontend/src/api/documents.ts`、`frontend/src/pages/documents/DocumentImportModal.tsx`、帮助教程、`CONTEXT.md`、`CHANGELOG.md` | 前端单测：accept 含 `.txt` / `.json`、说明含文本族；`make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 可转换格式白名单（md / docx / html / mhtml） | `plugins/documents/services/importers/formats.py` | C1 追加文本族 |
| 2 | 单文件导入分派与正文规整 | `plugins/documents/services/importers/reader.py` | C2 文本走独立分支，不套 Markdown 空白规整 |
| 3 | 压缩包导入（`style=archive`）笔记解析 | `plugins/documents/services/obsidian.py`（`_parse_notes` / `markdown_paths`） | C3 文本族按文档导入 |
| 4 | 前端文件选择与格式标签 | `frontend/src/api/documents.ts`、`DocumentImportModal.tsx` | C5 accept / FORMAT_LABEL / 文案 |
| 5 | 「不支持文件类型」告警 | `services/obsidian.py`（`_analyze_warnings`） | C3 文本族不再计入 |

## 未决问题（已确认）

- [x] ① 范围：**结论** txt / log / csv / tsv / json / yaml / xml / ini / conf / properties / rst / text（按原文入库，不做语法转换）。
- [x] ② 转换口径：**结论**保守原文——只统一换行与去首尾空行，不解析 front-matter、不剥标题、不重排空白。
- [x] ③ 压缩包是否同步支持：**结论**同步支持（用户按文件夹打包导入是主场景）。
- [x] ④ 标题来源：**结论**文件名（去扩展名）。
- [x] ⑤ 方案分级：**结论**S1（格式白名单 + 导入管线增分支，无数据 / 权限口径变化）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-14 用户口述 + 既有导入口径）

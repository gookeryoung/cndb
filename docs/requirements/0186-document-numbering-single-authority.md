# 0186 文档编号单一权威（编号归导出模板，正文与内容模板不写序号）（S2）

- 编号：0186
- 来源 / 提出人：用户（会话 2026-11-27，反馈「导出的文档编号重复且不统一」）
- 日期：2026-11-27
- 关联 ADR：`docs/adr/0186-document-numbering-single-authority.md`
- 关联前序：`docs/adr/0152-document-export-templates.md`（标题编号 `NumberingConfig` + `heading_prefix`）、`docs/adr/0177-document-template-integration.md`（内容模板 / 导出模板双轨与文档级绑定）、`docs/adr/0185-content-template-builtin-library.md`（内置内容模板库，正文手写序号）
- 状态：**已评审，P0–P3 已落地**（2026-11-27 人工确认「均按照建议」；ADR 0186 同步置 `Accepted`）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再同步 ADR 与代码（H26）。

## 需求原句（逐字）

> 文档，内容模板和导出模板均存在编号，导致导出的文档编号重复且不统一，请结合最佳实践给出方案，是否能够整合或者将二者协调统一。

> 均按照建议

对应的三项决策（会话内确认，落在 C1 / C5 / C7）：

1. **编号权威归排版层**（导出模板）——正文与内容模板只写层级，不写序号；
2. **内置内容模板去号**——6 套骨架改为无序号标题，由各自绑定的导出模板各显其能；
3. **导出 Markdown 不带编号**——自动编号只发生在 docx / pdf 渲染期，源文保持纯层级。

## 复现事实（立项依据，非推测）

内置内容模板 `research-pm.project-proposal`（绑定 `builtin:official`）经导出渲染，标题实际输出：

```
（一） 一、项目基本信息        ← 导出模板「（一）」+ 正文「一、」叠加
1. 3.1 总体目标               ← 导出模板「1.」+ 正文「3.1」叠加
```

三处编号来源并存：正文手写序号、内容模板骨架固化的序号、导出模板 `NumberingConfig.heading` 生成的前缀；且同一篇内 H2 用「一、」、H3 用「3.1」，本身就不自洽。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「编号重复」（均按照建议） | **单一权威**：一次导出的标题序号只能由一个层产生，导出渲染器必须检测正文是否已含显式序号，检出即**不叠加**模板编号（不报错、不阻断） | `documents/services/export/`（检测器 + docx / pdf 渲染器） | 单测：手写序号正文 + 编号模板 → 输出无重复前缀；无序号正文 → 正常生成 |
| C2 | 「编号不统一」 | 文档级判定为 **all-or-nothing**：同一篇文档内不得出现「H2 自动 + H3 手写」的半自动状态；判定结果只依赖正文块，不依赖模板配置 | `documents/services/export/numbering.py`（新增） | 单测：仅 H3 手写 → 全篇不编号；仅 H2 手写 → 全篇不编号 |
| C3 | 「结合最佳实践」 | 导出模板 `numbering` 增加 `mode` 三档：`auto`（默认，检出则让位）/ `force`（旧行为，始终叠加）/ `off`（从不编号）；缺键按 `auto` | `documents/services/export/templates.py`、前端模板面板 | 单测：三档各一例；存量 `config` JSON 缺键解析为 `auto` |
| C4 | 「协调统一」 | 图 / 表题注同样检测：题注文本已自带「图 N」「表 N」「图 N-M」前缀时不再叠加模板题注编号 | `documents/services/export/{docx,pdf}.py` | 单测：`图 1 系统架构` 不变成 `图 1 图 1 系统架构` |
| C5 | 「均按照建议」 | **内置内容模板去号**：`content_builtins.py` 6 套骨架的 `##` / `###` 标题去掉手写序号；正文内的序号式交叉引用改为语义化指代；列表 / 表格内的序号（如会议纪要「1. 」）不属标题编号，保持不变 | `documents/services/content_builtins.py` | 单测：内置正文不含标题行序号；渲染 `official` / `research` 各出一套规范编号 |
| C6 | 「均按照建议」 | 自定义内容模板（DB 行）**不强制迁移**：导出检测兜住；面板提供「去除标题序号」工具（只改标题行，动手前给出预览式确认，可撤销） | `frontend/src/pages/documents/ContentTemplatePanel.tsx`、前端纯函数 | 前端单测：工具只剥标题行序号、不动正文与列表 |
| C7 | 「均按照建议」 | `format=md` 与工作区压缩包导出**不带自动编号**（源文保持纯层级）；自动编号只在 docx / pdf 渲染期发生 | `documents/services/export/__init__.py` | 单测：`export?format=md` 输出与最新正文逐字一致 |
| C8 | （能力保全） | 既有导出能力零回归：内置 6 套导出模板的字体 / 字号 / 间距 / 表格 / 题注 / 页眉页脚配置不动；`force` 保留旧行为供显式选择；`resolve_export_template` 解析链（显式 → 文档绑定 → 工作区默认 → `research`）与 H68 静默回落口径不变 | 导出全链路 | 既有 `tests/test_export_templates.py` / `tests/test_documents_template_binding.py` 除新增用例外零改动通过 |
| C9 | （文档与订阅） | 同轮补后端单测 + 前端单测 + e2e；`CONTEXT.md`、`docs/USER_DOC_MAP.md`、帮助教程、`CHANGELOG.md` 回填；ADR 0185 的「中文序号按业务习惯排列，避免与导出模板自动编号叠加」表述按本卡修订为「正文不写序号」 | 文档、测试 | `make check-fast` / `make flow` / `make check-frontend` / `make check-docs` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 标题前缀生成 | `src/cndb/plugins/documents/services/export/templates.py:805 heading_prefix` | 无条件按层级加前缀，不感知正文 |
| 2 | docx 标题渲染 | `src/cndb/plugins/documents/services/export/docx.py:598` | 每级标题都拼 `prefix` |
| 3 | pdf 标题渲染 | `src/cndb/plugins/documents/services/export/pdf.py:618` | 同上 |
| 4 | 题注编号 | `docx.py:576-591`、`pdf.py:507-529` | 无条件 `图 N` / `表 N` / `图 N-M` |
| 5 | 编号配置模型 | `templates.py:112 NumberingConfig`（`extra="forbid"`） | 加字段需同步前端类型与面板 |
| 6 | 内置内容模板正文 | `content_builtins.py:77/138/178/216/238/267` | 6 套骨架全部手写「一、」「3.1」 |
| 7 | 内置正文口径文档 | `docs/requirements/0185-content-template-builtin-library.md:66` | 「中文序号按业务习惯排列」需修订 |
| 8 | 内置正文断言 | `tests/test_documents_content_templates.py:243,281` | 断言里带序号，随去号更新 |
| 9 | 编号参数断言 | `tests/test_export_templates.py:516`（`official` 出「一、」） | 输入是无序号正文，行为不变；新增手写序号用例 |
| 10 | 前端编号选项 | `frontend/src/pages/documents/templateOptions.ts:49 NUMBERING_OPTIONS`、`api/exportTemplates.ts:21/122` | 需加 `mode` 三档 |
| 11 | 模板面板预览 | `frontend/src/pages/documents/ExportTemplatePanel.tsx:963` | 预览按 `numberingPrefix` 生成，需能表达让位 |

## 未决问题

- [x] 编号权威放哪一层？→ **排版层**（导出模板）。理由：同一份正文可按 `official` 出「一、/（一）/1./（1）」、按 `research` 出「1/1.1/1.1.1」，内容与样式分离，插入章节自动重排（与 pandoc `--number-sections`、Sphinx `sectnum`、MkDocs 同思路）。
- [x] 内置内容模板是否去号？→ **去号**。它们已声明 `export_template_ref`，保留手写序号会把绑定模板的编号能力锁死。
- [x] 导出 Markdown / 压缩包是否带号？→ **不带**。带号会让 md 变成一次性快照，且与「编号只属于排版」冲突。
- [x] 存量手写序号文档怎么处理？→ **检测让位**，不改用户正文；需要规范化时由用户主动用「去除标题序号」工具。
- [x] 是否逐层判定？→ **不**，整篇 all-or-nothing，避免半自动半手写。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-27「均按照建议」）

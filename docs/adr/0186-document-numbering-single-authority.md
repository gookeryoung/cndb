# ADR 0186: 文档编号单一权威（导出模板 `mode` + 显式序号让位 + 内置内容模板去号）

Status: Accepted（2026-11-27 人工确认「均按照建议」，含 H72 登记；P0–P3 已落地）
Date: 2026-11-27
Related: `src/cndb/plugins/documents/services/export/templates.py`、`src/cndb/plugins/documents/services/export/numbering.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py`、`src/cndb/plugins/documents/services/export/markdown_blocks.py`、`src/cndb/plugins/documents/services/content_builtins.py`、`frontend/src/pages/documents/templateOptions.ts`、`frontend/src/pages/documents/ExportTemplatePanel.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/api/exportTemplates.ts`
需求卡片: `docs/requirements/0186-document-numbering-single-authority.md`（需求原文与约束编号的唯一副本）
上游：ADR 0152（导出模板与标题编号）、ADR 0177（模板整合与文档级绑定）、ADR 0185（内置内容模板库）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字）；约束编号 C1..C9 一律引用卡片，本表只写落地方式。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「编号重复」 | 新增检测器 `export/numbering.py::has_explicit_heading_numbers`，docx / pdf 渲染前判定；检出则本次导出跳过模板编号前缀（D1 / D2 / D5） |
| C2 | 「编号不统一」 | 判定为全篇 all-or-nothing，只看 `HeadingBlock` 序列，不看模板配置（D2） |
| C3 | 「结合最佳实践」 | `NumberingConfig.mode: auto \| force \| off`，缺键即 `auto`；`force` 保留旧行为（D3 / D8） |
| C4 | 「协调统一」 | 题注同样检测：文本已带「图 N」「表 N」「图 N-M」前缀则不叠加（D4） |
| C5 | 「均按照建议」 | `content_builtins.py` 6 套骨架标题去号；列表 / 表格序号保留（D6） |
| C6 | 「均按照建议」 | 自定义模板不迁移；面板提供「去除标题序号」工具（纯函数 + 预览式确认）（D7） |
| C7 | 「均按照建议」 | `format=md` / 压缩包导出不参与编号（自动编号只在 docx / pdf 渲染期）（D9） |
| C8 | （能力保全） | 六套内置导出模板配置零改动、解析链零改动、H68 口径不变（D7 / D8） |
| C9 | （文档与订阅） | 分期见 §8，测试清单见 §7，文档回填见 §落地状态 |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号并逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `heading_prefix()` 按层级无条件生成前缀，不读取正文内容 | `services/export/templates.py:805` | 正文自带序号时叠加 | 确认（C1 / C3） |
| 2 | docx 每级标题都拼 `prefix` 并单独加 run | `services/export/docx.py:598` | 同上 | 确认 |
| 3 | pdf 同样每级拼前缀 | `services/export/pdf.py:618` | 同上 | 确认 |
| 4 | 题注无条件写 `图 N` / `表 N` / `图 N-M` | `docx.py:576-591`、`pdf.py:507-529` | 手写「图 1 系统架构」变「图 1 图 1 系统架构」 | 确认（C4） |
| 5 | `NumberingConfig` 只有 `heading` 且 `extra="forbid"` | `templates.py:112` | 无法表达「让位 / 强制」 | 确认（C3） |
| 6 | 内置 6 套内容模板骨架全部手写「一、」「3.1」 | `content_builtins.py:77/138/178/216/238/267` | 与绑定模板（`official` / `research`）叠加 | 确认（C5） |
| 7 | 内置正文口径写「中文序号按业务习惯排列，避免与导出模板自动编号叠加」 | `docs/requirements/0185-content-template-builtin-library.md:66` | 该口径把叠加当成常态去规避，方向反了 | 确认（修订） |
| 8 | 内置正文测试断言带序号 | `tests/test_documents_content_templates.py:243,281` | 去号后需同步 | 确认（C9） |
| 9 | `official` 编号用例输入是无序号正文 `# 一` / `## 二` | `tests/test_export_templates.py:516` | 该类用例前提是「正文就是序号本身」，去号后语义变（输入改为语义标题） | 确认（C9） |
| 10 | 前端 `NUMBERING_OPTIONS` 四档 + `TemplateHeadingNumbering` 联合类型 | `frontend/src/pages/documents/templateOptions.ts:49`、`api/exportTemplates.ts:21,122` | 加 `mode` 需同步类型与面板 | 确认（C3） |
| 11 | 面板 CSS 预览按 `numberingPrefix` 硬生成前缀 | `frontend/src/pages/documents/ExportTemplatePanel.tsx:963` | 预览会展示实际不生效的编号 | 确认（C3 / §6） |
| 12 | 编辑器 / 已有文档正文由用户自由撰写 | `services/content/` | 大量存量文档已含手写序号 | 新增（C1 让位兜住） |
| 13 | `format=md` 直接返回最新正文 | `documents/services/export/__init__.py` | 若在此加编号会让 md 成为快照 | 新增（C7 明确排除） |

**核心缺陷（需求要补的）**：编号此前被认为可以由「正文」「内容模板」「导出模板」三处各自提供，但没有任何一处声明权威；三者叠加后既不统一（同篇 H2 用「一、」H3 用「3.1」），也重复（`（一） 一、`）。

设计目标（不变量）：

- **I1 单一权威**：一次导出的标题序号只能由一个层产生。正文（含内容模板骨架）出现显式序号时，模板编号必须让位；不得叠加、不得报错、不得改动用户正文。
- **I2 判定只看正文**：是否让位只由正文标题块决定（全篇 all-or-nothing），与模板配置、文档状态、权限无关；同一份正文在任何模板下判定结果一致。
- **I3 自动编号只发生在 docx / pdf 渲染期**：`format=md`、工作区压缩包导出、编辑器预览都不写序号，源文永远保持纯层级。
- **I4 静默降级**：判定 / 题注检测的任何不确定情形（例如标题文本无法解析）都按「不叠加」处理并记 debug 日志，导出主流程不得因编号判定失败而中止（与 H68 同侧）。

> I1 是跨需求长期生效的口径，已于 2026-11-27 登记为 **H72**（`docs/CONSTRAINTS.md`，来源 `ADR 0186 I1`，H27 / ADR 0119）。

## Decision

### 1. 数据模型

无新表、无新列、无迁移。

唯一变化在配置结构内部（JSON 列 `documents_exporttemplate.config`）：

```python
class NumberingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: Literal["none", "arabic_multilevel", "chapter_chinese", "cn_ordinal"] = "none"
    mode: Literal["auto", "force", "off"] = "auto"   # 新增
```

- `auto`（默认）：检出正文显式序号 → 本次导出等效 `none`，否则用 `heading`。
- `force`：始终用 `heading`（升级前行为，供显式选择）。
- `off`：从不生成编号，等价 `heading="none"` 但语义独立（用户意图不同）。
- 存量 `config` JSON 缺 `mode` 键 → pydantic 默认 `auto`（存量零迁移，H13）。

### 2. 判定算法（唯一入口）

```python
# services/export/numbering.py（新增）
EXPLICIT_HEADING_PREFIX_RE   # 第一章 / 一、/ （一）/ 3.1 / 1. / 1、
EXPLICIT_CAPTION_PREFIX_RE   # 图 1 / 图 1-1 / 表 2

def has_explicit_heading_numbers(blocks: Sequence[Block]) -> bool
def has_explicit_caption_number(text: str) -> bool
def resolve_heading_numbering(mode: str, heading: str, blocks: Sequence[Block]) -> str
    # off -> "none"; force -> heading; auto -> 检出则 "none"，否则 heading
```

判定口径：

1. 只扫描 `HeadingBlock`（`parse_blocks` 的产物），不扫段落 / 列表 / 代码块 —— 列表自带 `1.` 是列表序号，不是标题编号。
2. **全篇 all-or-nothing**：任一级标题命中显式序号即整篇让位（I2）。不做逐层判定，避免「H2 自动 + H3 手写」的半自动半手写。
3. 调用点只有两处：`docx._render_docx` 与 `pdf._render_pdf` 在拿到模板配置后、进入块循环前各算一次，结果作为本次渲染的常量传入 `_add_heading`；`heading_prefix()` 本身不改语义（仍是纯函数，`scheme="none"` 返回空串）。
4. 题注：`_caption_text` 前先过 `has_explicit_caption_number(text)`，命中则直接输出原文（不加标签与序号）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET \| POST \| PUT \| PATCH /{wid}/documents/templates*` | `config.numbering.mode` 进入请求 / 响应载荷（校验枚举，非法 422 / 400） |
| `POST /{wid}/documents/templates/preview` | 预览同样遵守 `mode`（`force` 才叠加） |
| `GET /{wid}/documents/{doc_id}/export?format=docx\|pdf` | 行为变化：正文含显式序号时不再叠加模板编号（响应结构不变） |
| `GET /{wid}/documents/{doc_id}/export?format=md` | 不变（不编号，I3） |

无新增端点、无删除端点。

### 4. 边界与例外

1. **列表序号不算标题编号**：`1. / 一、` 作为列表项出现在列表块中不触发让位。
2. **代码块内文本不参与判定**：`CodeBlock` 整体跳过（含 `# 一、` 之类的示例行）。
3. **标题里的「第一章」等跨章引用不受影响**：只有标题文本**开头**命中序号模式才算显式序号；正文段落里的「见第三章」不动（也不做自动替换）。
4. **题注让位只看文本前缀**：`表：说明` 这种模板题注源写法（`TABLE_CAPTION_RE`）不变，编号仍由模板生成；只有用户自己写成 `图 1 xxx` / `表 2 xxx` 时才让位。
5. **内置内容模板去号**：只改 `##` / `###` 标题行；表格内「序号」列、「1. （填写）」这类列表项、`- [ ]` 复选项保持原样（C5）。
6. **自定义内容模板不迁移**：DB 行原样保留，导出检测兜住；「去除标题序号」工具是**用户主动**动作（C6）。
7. **原件族文档**：不参与 docx / pdf 渲染（H19 口径），本 ADR 对其无影响。
8. **`force` 可能产生重复编号**：这是显式选择的结果，前端在选中时标注「若正文已含序号将重复」；不作为缺陷。

### 5. 迁移

无 alembic 迁移。`config` JSON 缺 `mode` 键即默认 `auto`，属新增可选字段的向后兼容扩展；备份协议（`CHUNKED_BACKUP_VERSION = 17`）不变，旧包导入后模板自动获得 `auto`（沿用 ADR 0177 D11 先例）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 类型 | `frontend/src/api/exportTemplates.ts` | `TemplateNumberingMode = 'auto' \| 'force' \| 'off'`；`numbering: { heading; mode }` |
| 选项 | `frontend/src/pages/documents/templateOptions.ts` | 新增 `NUMBERING_MODE_OPTIONS`；`numberingPrefix` 保持纯函数 |
| 面板 | `frontend/src/pages/documents/ExportTemplatePanel.tsx` | 「标题与编号」区加「编号方式」下拉（自动让位 / 总是叠加 / 不编号），选中 `force` 时给「正文已有序号将重复」提示；CSS 预览按 `mode` 决定是否画前缀（`auto` 在预览示例正文无序号时仍画出，示例正文即无序号样例） |
| 内容模板面板 | `frontend/src/pages/documents/ContentTemplatePanel.tsx` | 新增「去除标题序号」工具：调纯函数剥离标题行序号，落点前展示变更条数，可撤销（不入库直到用户保存） |
| 纯函数 | `frontend/src/pages/documents/contentTemplateFile.ts`（或就近新文件） | `stripHeadingNumbers(markdown): { text, changed }` |
| 帮助 | `frontend/src/pages/help/content/tutorials.tsx` | 「导出模板」节补「编号方式」三档与「正文不写序号」口径 |

### 7. 测试清单

**判定层（单测，`tests/test_export_numbering.py` 新增）**

- `has_explicit_heading_numbers`：`一、` / `（一）` / `3.1` / `1.` / `第一章` / `（1）` 各命中一例；纯语义标题不命中。
- 只扫标题：列表项 `1.` 与代码块 `# 一、` 不触发。
- `resolve_heading_numbering`：`off` / `force` / `auto`×（命中 / 未命中）四例。
- `has_explicit_caption_number`：`图 1 架构` / `图 1-1 架构` / `表 2 指标` 命中；`系统架构` 不命中。

**渲染层**

- docx / pdf：手写序号正文 + `auto` → 标题无模板前缀（且原文序号保留一次）；同一正文 + `force` → 两次出现（旧行为可复现）。
- docx / pdf：题注文本自带 `图 1` → 不出现「图 1 图 1」。
- `official` 无序号正文仍输出「一、/（一）」；`research` 仍输出「1/1.1」。

**接口层**

- 模板 CRUD 接受 `numbering.mode`；非法值 422/400；缺键读回为 `auto`。
- 导出端点：手写序号文档 → docx 标题不重复；`format=md` 与最新正文逐字一致（C7）。

**内容模板**

- 内置 6 套正文：任一 `^#{2,6}\s` 行不含「一、」「3.1」等序号；既有章节断言改为语义标题。
- 前端 `stripHeadingNumbers`：只剥标题行、不改列表 / 表格 / 代码块；`changed` 计数正确。

**前端**

- `ExportTemplatePanel.test.tsx`：编号方式下拉三档、`force` 提示、`mode` 进入保存载荷。
- `ContentTemplatePanel.test.tsx`：「去除标题序号」按钮的变更条数与撤销。

**e2e**：`critical/document-numbering-authority.spec.ts`——用 API 建两篇文档（正文自带序号 / 纯语义标题），改模板 `mode` 后导出 docx 并解 `word/document.xml` 断言真实字节：`auto` 让位后「一、」只出现一次、`auto` 无序号正文照常出「一、/二、」、`force` 出现「一、 一、」的显式叠加、`off` 从不编号、`md` 三档字节完全一致。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 检测器 `numbering.py` + `NumberingConfig.mode` + docx / pdf 接入 + 题注检测（含单测） | 中（渲染行为变化，靠 golden 断言兜底） |
| **P1** | 内置 6 套内容模板去号 + 既有断言同步 + 0185 卡片口径修订 | 低 |
| **P2** | 前端：类型 / 选项 / 面板 `mode` 下拉 / 内容模板「去除标题序号」工具 | 中（前端交互与预览口径） |
| **P3** | 文档回填（`CONTEXT.md`、`USER_DOC_MAP.md`、帮助、`CHANGELOG.md`）+ e2e | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 编号权威放哪一层 | **排版层**（导出模板）；正文与内容模板只写层级 | 同一份正文可按 `official` 出「一、/（一）/1./（1）」、按 `research` 出「1/1.1」，内容与样式分离；插章自动重排；与 pandoc `--number-sections` / Sphinx `sectnum` / MkDocs 同思路 | 内容层权威（编号写死在正文）：换文体要重写全文、漏号重号靠人；仅「导出时剥离」补丁：剥离会误伤以「一、」开头的正常标题，且不解决「谁负责编号」 | `export/templates.py`、`export/numbering.py` |
| D2 | 判定粒度 | **全篇 all-or-nothing**，只看标题块 | 逐层判定会产出「H2 自动 + H3 手写」的半自动状态，用户无法解释；整篇判定可一句话说明 | 逐层判定：可解释性差、规则复杂；按模板判定：与正文无关会导致同一文档在不同模板下编号跳变 | `export/numbering.py` |
| D3 | 配置表达 | `NumberingConfig.mode: auto \| force \| off`，默认 `auto` | 既要修默认可为，又要保留旧行为出口（存量自定义模板 / 显式想要双编号） | 只改默认不提供开关：无法复现旧行为，回归排查困难；用 `heading="none"` 表达让位：语义混淆（`none` 是「用户不要编号」） | `export/templates.py` |
| D4 | 题注是否同样处理 | 是，文本已带 `图 N` / `表 N` 前缀则不叠加 | 与标题同一类「内容 vs 样式」冲突；「图 1 图 1 架构」是高频真实报错形态 | 只处理标题：题注重号仍在；强制编号题注：会让手写题注文档出现双号 | `docx.py:576`、`pdf.py:507` |
| D5 | 检测结果是否影响非渲染路径 | 否，仅 docx / pdf 渲染期 | 自动编号属于「排版」；写进 md 会让源文变成一次性快照，且破坏版本 diff 语义 | md 导出也编号：源文被污染、导入回来会带死号 | `export/__init__.py` |
| D6 | 内置内容模板是否去号 | **去号**（6 套全改），列表 / 表格序号保留 | 内置模板已声明 `export_template_ref`，保留手写号等于把绑定模板的编号能力锁死；去号后 `official` / `research` 各显其能 | 保留手写号并把绑定模板设 `off`：等于放弃该模板的排序 / 重排能力，且未来插章必须手工改正文 | `content_builtins.py` |
| D7 | 存量自定义模板 / 文档是否迁移 | 不迁移；导出检测兜住；提供「去除标题序号」工具由用户主动执行 | 迁移会改写用户正文（不可逆、破坏版本历史语义）；工具 + 预览式确认把决定权交回用户 | 服务端批量剥离：误伤风险高、无法撤销 | `ContentTemplatePanel.tsx`、前端纯函数 |
| D8 | 失败 / 不确定情形 | 一律按「不叠加」并记 debug 日志，不中断导出 | 与 H68 同侧：导出主流程必须永远能出文件 | 判定失败报错：一次解析异常会让整篇导不出 | `export/numbering.py` |
| D9 | md / 压缩包导出 | 不带编号（I3） | 源文保持纯层级，往返导入不产生死号 | 带编号：md 成为快照，且再导入会变成手写序号文档 | `export/__init__.py` |
| D10 | 不变量登记 | 以 **H72** 登记（H71 已被 ADR 0185 占用）：「一次导出的标题序号只能由一个层产生；正文有显式序号时模板编号必须让位且不报错；判定只依赖正文标题块」 | I1 / I2 是跨需求长期口径（H27） | 只写在 ADR：后续容易退回「无条件叠加」 | `docs/CONSTRAINTS.md` H72 |

门禁：2026-11-27 人工确认「均按照建议」，`Status → Accepted`，D1–D10 全部定稿，无「待定」。

## Consequences

- **正向**：同一份正文换模板即换编号体系；插入章节自动重排；「（一） 一、」这类叠加从根上消失；内置内容模板不再和绑定模板打架；题注双号一并解决。
- **负向**：渲染行为默认发生变化（等价于所有「正文有手写序号」的文档导出外观改变，方向是去掉重复）；`Mode` 增加一档配置，面板与文档需同步。
- **风险与缓解**：① 用户已习惯手写序号 → 检测让位保证「最多少一次编号，绝不多一次」，且 `force` 可回到旧行为；② 检测误判（把普通标题当序号）→ 正则只认行首的确定性模式，且误判后果是「不编号」而非「错编号」；③ 内置模板去号影响存量副本 → 已有文档（从模板建出）正文是**复制值**，不随内置库更新，历史文档不受影响。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 标题编号方案 | `NumberingConfig.heading` | 四档不变，只新增 `mode` 控制叠加时机 | ADR 0152 D16（本 ADR 扩展） |
| 模板解析链 | `resolve_export_template` | 完全不变（显式 → 文档绑定 → 工作区默认 → `research`） | ADR 0177 D9 / H68 |
| 内容模板范围 | `documents_contenttemplate` | 表结构不变；仅内置库正文去号 | 需求 0169 / ADR 0185 |
| 内置内容模板正文口径 | `content_builtins.py` | 「中文序号按业务习惯排列」改为「正文不写序号，编号交给绑定模板」 | ADR 0185（本 ADR 修订其口径） |
| 内置导出模板配置 | `BUILTIN_TEMPLATES` | 六套配置零改动（`mode` 皆为默认 `auto`） | ADR 0152 I4 |
| 备份协议 | `CHUNKED_BACKUP_VERSION = 17` | 不升版本（新增可选字段） | ADR 0075 / 0177 D11 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/export/numbering.py`（新增）、`src/cndb/plugins/documents/services/export/templates.py`、`src/cndb/plugins/documents/services/export/docx.py`、`src/cndb/plugins/documents/services/export/pdf.py` | `tests/test_export_numbering.py`（新增）、`tests/test_export_templates.py` | `c570d487` |
| P1 | 已落地 | `src/cndb/plugins/documents/services/content_builtins.py`、`docs/requirements/0185-content-template-builtin-library.md` | `tests/test_documents_content_templates.py` | `c570d487` |
| P2 | 已落地 | `frontend/src/api/exportTemplates.ts`、`frontend/src/pages/documents/templateOptions.ts`、`frontend/src/pages/documents/ExportTemplatePanel.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.tsx`、`frontend/src/pages/documents/contentTemplateNumbers.ts`（新增） | `frontend/src/pages/documents/ExportTemplatePanel.test.tsx`、`frontend/src/pages/documents/ContentTemplatePanel.test.tsx`、`frontend/src/pages/documents/contentTemplateNumbers.test.ts`（新增） | `c570d487` |
| P3 | 已落地 | `CONTEXT.md`、`docs/USER_DOC_MAP.md`、`frontend/src/pages/help/content/tutorials.tsx`、`docs/CONSTRAINTS.md` | `frontend/tests/e2e/critical/document-numbering-authority.spec.ts`（新增） | `c570d487` |

## 交接（会话结束更新）

- 当前阶段：P0–P3 全部已落地并提交（`c570d487`，2026-11-27），`make adr-check` 归零
- 已完成：检测器 + `mode` 三档 + docx / pdf 让位 + 题注让位；内置 6 套内容模板去号与 0185 口径修订；前端类型 / 选项 / 面板下拉 /「去除标题序号」工具；H72 登记与文档回填
- 下一步：无（P0–P3 已落地、sha 已回填）。后续若新增编号方案，扩 `NumberingConfig.heading` 枚举并在 `heading_prefix()` 补分支，判定链不变。
- 已知坑：
  - `templates.py` 的 `NumberingConfig` 是 `extra="forbid"`，前端必须**同时**发 `heading` 与 `mode`，否则新的前端打旧后端会 422（本仓库前后端同版本发布，暂无跨版本需求）。
  - 检测器只认标题文本**开头**的序号模式；「第 3.1 节 目标」这种中间带号的写法不触发让位（有意保守，宁可多编号一次也不误判为手写）。
  - 内置内容模板去号后，`test_documents_content_templates.py` 里原先断言「一、项目基本信息」的用例改为语义标题；`official` 渲染断言（`test_export_templates.py::test_heading_numbering_and_page_footer`）的输入从 `# 一` 改为语义标题，因为旧输入本身是「正文当序号」的反例。
  - `format=md` 与压缩包导出**不**编号（I3 / D9），需要带编号的文件请导 docx / pdf。
- 最近一次全绿：`make check-fast` + `make flow` + `make check-frontend`（覆盖率双门槛）@ 2026-11-27

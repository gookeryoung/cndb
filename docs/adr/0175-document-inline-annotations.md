# ADR 0175: 正文内批注（文本锚点 + 评论线程）

Status: Proposed（待评审）
Date: 2026-11-26
Related: ADR 0036（帮助文档）、ADR 0161（权限边界）、ADR 0004（行级权限，仅作判定风格参考）、`src/cndb/plugins/documents/services/visibility.py`、`src/cndb/plugins/documents/services/content.py`、`frontend/src/pages/documents/DocumentEditorPage.tsx`
需求卡片: `docs/requirements/0175-document-inline-annotations.md`

## 口径（需求 → 设计落点）

需求原文见卡片 §需求原句；卡片约束沿用 C1..C9，本表只补设计落点。

| 卡片约束 # | 需求片段 | 本设计的落地 |
|---|---|---|
| C1 | 正文内批注 | 锚点 = TextQuote（`quote` + 前后各 32 字符 `prefix` / `suffix`）+ 位置偏移（相对纯文本投影，advisory）；落库带 `version_number`（D1 / D2） |
| C2 | 评论线程 | 单表自关联 `parent_id`：根批注有锚点，回复无锚点；`status ∈ open/resolved` 只作用于根；删根级联删回复（D2 / D4） |
| C3 | 谁可以批注 | 对文档有 READ 的成员（含 viewer）可建根批注 / 回复；根作者或 owner/editor 可解决 / 重开；作者删自己的、owner/editor 删任意（D3） |
| C4 | 可见性（H33） | 所有批注端点先走 `get_visible_document_or_404`；文档不可见 → 404，不泄露批注存在性（D3） |
| C5 | 版本变化 | 列表时按最新正文重定位：偏移命中 → 唯一 quote 命中 → prefix/suffix 邻接 → 失败标 `orphaned`，不删除（D5） |
| C6 | 游客与导出 | 分享载荷不含批注、不提供写入；导出渲染不读批注表（D6） |
| C7 | 前端 | 阅读 / 编辑态选区浮动「批注」；右侧抽屉（根 + 回复 + 解决）；头部未解决计数；移动端全屏抽屉（§6） |
| C8 | 通知边界 | 不做通知 / @（通知表已删），仅文档内计数（D7） |
| C9 | 测试与文档 | 判定 / 接口 / 重定位 / 前端用例见 §7 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 正文是整篇 Markdown，无块级模型 | `documents/models.py:78`、`services/content.py:351` | 无法按块 id 锚定，只能做文本锚点 | 确认 C1 |
| 2 | 现有评论只有文档级 issue 线程 | `documents/models.py:377`（`DocumentIssueComment`） | 与正文位置无关，不能复用为批注 | 确认 |
| 3 | 版本为全量快照，回滚创建新版本 | `services/content.py:454` | 锚点必须带版本号并支持重定位，不能只存偏移 | 确认 C5 |
| 4 | 可见性只有状态维度（published 公开，draft/archived 仅创建者与管理员） | `services/visibility.py:43,46,125` | 批注读路径必须复用同一过滤，否则会绕过 H33 | 确认 C4 |
| 5 | 游客分享是独立 token，无 user 身份 | `documents/models.py:210-221` | 游客无法归属批注作者，本期不参与 | 确认 C6 |
| 6 | 导出从正文渲染，不读评论类数据 | `documents/services/export/` | 批注天然不入导出，无需额外开关 | 确认 C6 |
| 7 | 修改申请 / 双轨写与正文解耦 | `services/change_requests.py:82` | 批注不随修改申请流转，也不阻塞保存 | 新增 |
| 8 | 通知基础设施已删除 | 迁移 `2c3d4e5f6a70` | 本期无站内通知能力 | 确认 C8 |

**核心缺陷**：文档目前只有「整篇评论」（issue），无法把讨论钉在具体一句话上；而正文是整篇
Markdown 且随版本全量变化，直接存字符偏移会在任何一次编辑后失效。

设计目标（不变量）：

- **I1 位置可恢复**：批注必须能在正文更新后重新定位，定位失败要显式降级，不得静默错位。
- **I2 可见性同源**：批注的读 / 写权限与文档可见性同一判定，不新增旁路（H33）。
- **I3 不改正文**：批注独立存储，不写入 Markdown、不产生版本文档，不影响导出与双链解析。
- **I4 游客隔离**：游客分享既不读也不写批注。

> 本 ADR 的 I1 / I2 属跨需求长期口径，`Proposed → Accepted` 前需登记入 `CONSTRAINTS.md`
> （建议 H68 / H69，来源 `ADR 0175 I1/I2`）。

## Decision

### 1. 数据模型

新表 `documents_annotation`（迁移单条，downgrade 删表）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `workspace_id` | FK workspaces CASCADE | 便于工作区级清理与备份 |
| `document_id` | FK documents CASCADE, index | |
| `parent_id` | FK self CASCADE, nullable | 空 = 根批注；非空 = 回复 |
| `author_id` | FK accounts SET NULL | 作者删除后保留批注 |
| `body` | Text | 纯文本，1..2000 字符（服务层校验） |
| `quote` | Text | 根批注必填；选区原文（纯文本投影） |
| `prefix` / `suffix` | Text | 前后各 ≤32 字符，用于歧义消解 |
| `start_offset` / `end_offset` | int nullable | 相对纯文本投影的偏移，advisory |
| `version_number` | int | 创建时的最新版本号 |
| `status` | String(16) | `open` / `resolved`（仅根批注） |
| `resolved_by_id` / `resolved_at` | FK / datetime | 解决信息 |
| `created_at` / `updated_at` | TimestampMixin | |

索引：`(document_id, status)`、`(document_id, parent_id)`。单文档根批注上限 200（服务层拒绝）。

### 2. 锚点与纯文本投影

- 前端选区通过 `window.getSelection().toString()` 取 `quote`，并取前后 32 字符作 `prefix` / `suffix`；
  偏移取选区在**纯文本投影**中的字符位置（仅作加速提示）。
- 服务端定义 `annotations/plaintext.py::plain_text(markdown)`：去掉代码围栏标记、标题 `#`、强调符号、
  链接语法只保留链接文字、图片只保留 alt、表格分隔线；与阅读态渲染文本保持同一投影口径。
- 之所以不直接对 Markdown 源文匹配：用户在阅读态看到的是渲染文本，`**粗体**` 之类的语法符号
  不应影响锚点命中；投影函数是唯一映射层，前端不做二次解析。

### 3. 判定算法（唯一入口）

`documents/services/annotations.py`：

```python
def require_annotation_read(db, workspace_id, doc_id, user) -> Document:
    """复用 visibility.get_visible_document_or_404（H33）"""

def can_annotate(db, workspace_id, user) -> bool:
    """workspace_data_role(user) is not None（READ 即可，viewer 允许）"""

def can_moderate(db, workspace_id, doc, user) -> bool:
    """workspace_data_role in {OWNER, EDITOR} 或 is_superuser"""
```

- 新建根批注 / 回复：`can_annotate`；
- 解决 / 重开：根作者 **或** `can_moderate`；
- 删除：作者本人 **或** `can_moderate`（删根级联删回复）；
- 回复不能单独解决；对回复调用解决 → 400。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/documents/{doc_id}/annotations` | 新增：返回 `items`（根批注含 `replies`、`anchor_state ∈ ok/orphaned`、`can_resolve`）、`open_count` |
| `POST /{wid}/documents/{doc_id}/annotations` | 新增：`{body, quote, prefix?, suffix?, start_offset?, end_offset?, parent_id?}`；`parent_id` 存在时按回复处理并忽略锚点 |
| `PATCH /{wid}/documents/{doc_id}/annotations/{id}` | 新增：`{body?}` 编辑自己的正文；`{status?}` 仅根批注且需作者或管理员 |
| `DELETE /{wid}/documents/{doc_id}/annotations/{id}` | 新增：作者或管理员 |

所有端点先 `require_annotation_read`；跨工作区 / 不可见文档统一 404。

### 5. 边界与例外

1. **定位失败**：返回 `anchor_state=orphaned`，前端归入「失效批注」分区，允许作者重新锚定或删除。
2. **代码块内文本**：允许批注（投影保留代码内容），但 `quote` 位于围栏内时 `prefix/suffix` 可能含标记，定位仍以 quote 唯一命中为准。
3. **超长选区**：`quote` 上限 500 字符；超出返回 400。
4. **同句多处出现**：优先偏移命中；其次 prefix/suffix 唯一匹配；仍歧义则取第一个并标记 `ambiguous`（前端提示「可能位置」）。
5. **归档文档**：可读即可批注（与文档状态无关，仅要求 READ）。
6. **并发**：不做实时同步；列表按 `updated_at` 排序，前端手动刷新。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 选区入口 | `DocumentEditorPage.tsx` / `components/Document/MarkdownPreview.tsx` | 阅读 / 编辑态监听 `selectionchange`，选中非空文本时显示浮动「批注」按钮 |
| 抽屉 | `AnnotationDrawer.tsx`（新） | 根批注列表 + 回复 + 解决 / 重开 + 删除；点击跳转并临时高亮 quote |
| 计数 | `DocumentEditorPage.tsx` 头部 | 「批注 N」入口，未解决数徽标 |
| API | `api/documents.ts` | `listAnnotations / createAnnotation / updateAnnotation / deleteAnnotation` |
| 移动端 | `AnnotationDrawer` | 复用 Drawer `placement=bottom` 全屏形态（H30 断点） |

### 7. 测试清单

**判定层（单测）**：viewer 可建 / 可回复、不可删他人；作者可解决自己的；editor 可解决任意；
回复不能解决；删除根级联回复；单文档 200 条上限。

**锚点层（单测）**：偏移命中；唯一 quote 命中；prefix/suffix 消歧；删改原文后 `orphaned`；
回滚到旧版本后重新命中；代码块内文本；超长 quote 拒绝。

**接口层**：不可见文档 404；跨工作区 404；回复挂在他人文档批注下 400；`open_count` 正确。

**游客 / 导出**：分享载荷无 `annotations` 字段；docx / pdf / md 导出正文不含批注文本。

**前端（组件 / e2e）**：选区出现入口；提交后抽屉出现；解决后计数减；orphaned 分区展示。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 表 + 投影函数 + 判定入口 + 列表 / 新建 / 删除接口 | 低 |
| **P1** | 重定位算法 + 解决 / 重开 + 锚点测试 | 中（歧义与投影口径） |
| **P2** | 前端选区入口 + 抽屉 + 计数 + 移动端 | 中（选区坐标与渲染映射） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 锚点形式 | TextQuote（quote + prefix/suffix）+ 偏移 + 版本号 | 无块模型，纯偏移会在编辑后失效 | 只存偏移（易失效）；只存 quote（歧义） | `services/annotations/plaintext.py` |
| D2 | 存储结构 | 单表自关联（根 + 回复） | 回复不需要锚点，单表查询简单 | 根 / 回复两表（多一次 join） | 表 `documents_annotation` |
| D3 | 权限 | READ 可批注；作者或 editor+ 可解决 / 删除 | 批注是讨论而非数据写入；viewer 也应能提意见 | 仅 editor+ 可批注（限制过严） | `services/annotations.py` |
| D4 | 回复解决语义 | 只有根可解决，回复不可 | 避免线程状态碎片化 | 每条都可解决（状态语义混乱） | 同上 |
| D5 | 定位失败处理 | 标 `orphaned`，保留内容 | 批注本身是信息，不应因编辑丢失 | 自动删除（丢数据）；静默取首个（错位） | 重定位算法 |
| D6 | 游客与导出 | 游客不读写；导出不含 | 游客无身份；导出是正文语义 | 游客只读展示（需新增游客身份） | 分享 / 导出路径 |
| D7 | 通知 | 本期不做，仅计数 | 通知表已删，重建成本高 | 先做通知（范围膨胀） | 无 |

## Consequences

- **正向**：讨论可钉在具体语句；编辑后仍能找回；不侵入正文与导出；权限复用现有可见性。
- **负向**：新增纯文本投影层，投影口径变化会影响历史锚点；没有通知，作者不会被动收到回复。
- **风险与缓解**：投影与渲染不一致 → 投影函数单点维护 + 锚点回归用例；大量批注拖慢列表 →
  单文档 200 条上限 + 一次读取正文后内存定位。

## 行业对照（可选）

| 维度 | Notion | 语雀 | 本设计 |
|---|---|---|---|
| 锚点 | 块 id + 文本偏移 | 文本选区 | TextQuote + 偏移 + 版本号（D1） |
| 线程 | 评论含回复 / 解决 | 评论含回复 | 单表根 + 回复 + 解决（D2 / D4） |
| 可见性 | 跟随页面权限 | 跟随文档权限 | 复用 H33（D3） |

来源：Notion Help「Comments」、语雀帮助「文档评论」（口径级参考，不复制实现）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 文档可见性 | 状态三态 | 批注只继承、不改写 | ADR 0161 / H33 |
| 评论 | `DocumentIssueComment` | issue 线程保持独立，不与批注合并 | 既有实现 |
| 块模型 | 未来 `0177` | 块模型落地后评估块级锚点，不推翻本设计 | 规划中 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | — | — | — |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |

## 交接（会话结束更新）

- 当前阶段：ADR 评审前（Proposed）
- 已完成：需求卡 0175、ADR 决策表（无待定）
- 下一步：人工评审 D1..D7；通过后登记 H68/H69 并开 P0
- 已知坑：纯文本投影必须与阅读态渲染同口径；选区偏移在编辑态与阅读态可能不同
- 最近一次全绿：`make flow` @ `e7e4720e`（2026-11-26）

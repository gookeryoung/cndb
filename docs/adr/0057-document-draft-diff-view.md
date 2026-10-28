# ADR 0057: 文档草稿 — 修改内容查看（diff）、保存与丢弃

Status: Accepted
Date: 2026-10-28
Related: `src/cndb/plugins/documents/services/drafts.py`、`src/cndb/plugins/documents/routers/documents.py`、`src/cndb/plugins/documents/services/parse.py`、`frontend/src/pages/documents/DocumentEditorPage.tsx`、`frontend/src/api/documents.ts`、ADR 0051
需求卡片: `docs/requirements/0057-document-draft-diff-view.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 修改内容查看（只看diff） | 新增端点 `GET /{doc_id}/draft/diff`（见 §3），以草稿 `base_version_number` 为基准计算 unified diff；前端编辑页顶部「查看修改」按钮 + 抽屉，复用 DiffView |
| C2 | 保存 | 既有 `PUT /{doc_id}/draft` 语义不变（只写个人草稿、不生成版本），本 ADR 零改动，仅回归验证 |
| C3 | 丢弃 | 后端既有 `DELETE /{doc_id}/draft` 不变；前端接线「丢弃草稿」按钮（确认提示），成功后载入最新版本内容并切回查看模式 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 草稿服务齐备：get / save / delete / submit；草稿为个人数据（document_id + user_id 一份），与最新版本一致时视为无修改 | `src/cndb/plugins/documents/services/drafts.py:34-141` | C2、C3 后端能力已存在 | 确认 |
| 2 | 草稿 REST 端点：GET / PUT / DELETE `/{doc_id}/draft` | `src/cndb/plugins/documents/routers/documents.py:480-527` | 后端无需新增草稿 CRUD | 确认 |
| 3 | 版本 diff 端点 `GET /{doc_id}/diff`（base/head 版本号 → unified diff） | `src/cndb/plugins/documents/routers/documents.py:948-980` | 草稿 diff 可沿同款载荷结构（diff/added/removed） | 确认 |
| 4 | diff 计算入口 `parse.unified_diff(base, head) → (text, added, removed)` | `src/cndb/plugins/documents/services/parse.py:218-228` | 直接复用，不新造 diff 算法 | 确认 |
| 5 | 修改申请 diff 载荷 `diff_payload`（基准正文 → 待审正文） | `src/cndb/plugins/documents/services/change_requests.py:152-158` | 草稿 diff 语义同构，可对齐实现 | 确认 |
| 6 | 前端 `documentsApi.discardDraft` 已定义但全仓无调用方 | `frontend/src/api/documents.ts:539-540` | 「丢弃」在后端有、前端无入口，用户无法自助丢弃草稿 | 确认 |
| 7 | DiffView 组件 + diffModel 已用于版本对比 | `frontend/src/components/DiffView/` | 草稿 diff 抽屉直接复用 | 确认 |
| 8 | 编辑页草稿态：serverDraft 状态、「草稿待提交」标签、保存/提交按钮 | `frontend/src/pages/documents/DocumentEditorPage.tsx:261-297,1044-1046` | 草稿 diff 与丢弃按钮挂在此处 | 确认 |
| 9 | `draft_payload` 返回 content / base_version_number / stale 等，不含 diff | `src/cndb/plugins/documents/services/drafts.py:50-65` | 前端有草稿全文，理论上可本地算 diff，但与版本对比 / 修改申请的口径会分叉 | 新增 |

**核心缺陷（需求要补的）**：草稿只有「全文回到编辑器」一种查看方式，没有「只看改了什么」的 diff 视图；且「丢弃草稿」后端有能力而前端无入口，草稿只能被提交或覆盖，无法一键放弃。

设计目标（不变量）：

- **I1 单一 diff 判定**：草稿 diff 与版本 diff、修改申请 diff 都必须走 `parse.unified_diff` 唯一入口，前端不得自行实现 diff 算法。
- **I2 只读不落地**：草稿 diff 是纯读路径，不得修改草稿表、不产生版本、不触发修改申请。
- **I3 草稿私有性不变**：草稿 diff / 丢弃仍只限本人（管理员也不可见他人草稿），沿用现有权限判定入口。
- **I4 丢弃不可逆但可确认**：丢弃前必须有确认提示；丢弃后编辑态完全重置为最新版本。

## Decision

### 1. 数据模型

无（不改任何表）。

### 2. 判定算法（唯一入口）

- diff 计算：复用 `parse.unified_diff(base_text, head_text)`（`parse.py:218`）。
- 草稿 diff 服务函数新增 `draft_diff(db, workspace_id, doc_id, user) -> dict | None`（放 `services/drafts.py`）：
  1. `require_member` + `get_visible_document_or_404` + `ensure_text_document`（与 `save_draft` 同款权限链，I3）；
  2. `get_draft` 无草稿 → 返回 `None`（404 语义由路由层决定，见 §4）；
  3. base 取 `draft.base_version_number` 对应版本正文（版本已被清理时回退取草稿快照语义，见 §4.2）；head 取草稿 `draft.content`；
  4. 调 `parse.unified_diff` 返回 `{base_version, diff, added, removed, stale}`，`stale = base_version_number < latest_num`（Q1：基准为编辑基准版本）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{doc_id}/draft/diff` | 新增：个人草稿 diff；无草稿返回 404（code=`no_draft`），载荷 `{base_version, diff, added, removed, stale}` |
| `PUT /{doc_id}/draft`、`DELETE /{doc_id}/draft` | 无变更（C2/C3 后端既有，回归即可） |

### 4. 边界与例外

1. **无草稿**：`GET /draft/diff` 返回 404（code=`no_draft`）；前端不显示「查看修改」按钮，正常看不到该错误。
2. **基准版本不存在**（旧草稿 base 版本被清理 / 历史数据）：以当前最新版本正文为 base 兜底并在载荷中把 `base_version` 置为最新版本号，不报错中断（stale 字段照常计算）。
3. **文件夹 / 非文本文档**：与 `save_draft` 同款拒绝（ConflictError / `ensure_text_document`）。
4. **stale 提示**：`stale=true` 时前端在 diff 抽屉顶部展示「文档已更新到 vX，你的修改基于 vY」提示，不阻断查看（Q1 决议的引导口径）。
5. **丢弃幂等**：后端 `delete_draft` 已幂等（`drafts.py:124-129`），前端重复点击无害。
6. **丢弃后跳转**（Q3）：前端成功后以最新版本内容重置编辑器状态（content、serverDraft=null、baseVersionRef 重置）并 `viewMode='view'`。

### 5. 迁移

无（零迁移）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/documents.ts` | 新增 `getDraftDiff(wid, docId)` 与 `DocumentDraftDiffPayload` 类型 |
| 编辑页 | `frontend/src/pages/documents/DocumentEditorPage.tsx` | ① `serverDraft` 存在时在顶部操作区渲染「查看修改」按钮，打开抽屉；② 抽屉内复用 DiffView 渲染草稿 diff，`stale` 时展示提示；③ 新增「丢弃」按钮（Popconfirm 确认），调用 `discardDraft`，成功后按 §4.6 重置编辑态 |
| 测试 | `frontend/src/pages/documents/DocumentEditorPage.test.tsx` | 见 §7 |

### 7. 测试清单

**判定层（单测）**（`tests/test_document_drafts.py` 扩展）：

- `draft_diff`：有草稿时返回 base→draft 的 diff / added / removed / stale；
- 无草稿返回 None；文件夹与非文本文档拒绝；
- base 版本不存在时回退最新版本（§4.2）；
- diff 为只读：调用前后草稿表与版本表无变化（I2）。

**接口层**（`tests/test_documents_plugin.py` 或既有草稿 API 测试处）：

- `GET /{doc_id}/draft/diff` 200 / 404（no_draft）/ 权限链（非成员 401/403、他人草稿互不可见，I3）；
- `PUT`/`DELETE` /draft 既有用例回归（C2/C3）。

**迁移 / 备份**：无迁移；备份往返不涉及新结构，跑既有备份测试回归即可。

**前端单测**（`DocumentEditorPage.test.tsx`）：

- 有草稿时「查看修改」按钮出现，点击打开抽屉并渲染 diff；
- stale 提示展示；
- 「丢弃」：确认后调用 discardDraft，成功后编辑态重置为最新版并切回查看模式；取消确认不调用 API。

**e2e（前端）**：并入既有文档编辑关键路径（`frontend/tests/e2e/`）——编辑 → 保存草稿 → 查看 diff → 丢弃 → 回到查看模式。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 后端 `draft_diff` 服务 + `GET /draft/diff` 端点 + 单测 / 接口测试 | 低（纯读路径） |
| **P1** | 前端「查看修改」按钮 + diff 抽屉（复用 DiffView）+ 单测 | 低 |
| **P2** | 前端「丢弃草稿」接线 + 丢弃后编辑态重置 + 单测 / e2e | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：草稿 diff 与丢弃如何补齐 | 后端新增只读 diff 端点 + 前端接线既有能力；不改数据模型与既有端点 | 保存 / 丢弃 / diff 计算均已存在，缺口只在草稿 diff 读路径与前端丢弃入口 | 本地（前端）自行 diff 草稿全文与拉取的版本内容：与 unified_diff 唯一入口冲突（I1），且版本正文未必在客户端 | `services/drafts.py`、`routers/documents.py` |
| D2 | diff 基准版本（Q1） | 以草稿 `base_version_number`（编辑基准版本）为基准；stale 时附提示不阻断 | 与 `submit_draft` 的基准校验口径一致，所见即所审 | 当前最新版本为基准：混入他人改动，看不出「自己改了什么」 | `drafts.py` `draft_diff` |
| D3 | diff 入口形态（Q2） | 编辑页顶部「查看修改」按钮 + 抽屉，复用 DiffView | 版本对比已用 DiffView，零新组件 | 编辑器切换只读 diff 视图：需在编辑/diff 间来回切换，交互成本高 | `DocumentEditorPage.tsx` |
| D4 | 丢弃行为（Q3） | Popconfirm 确认后调用既有 DELETE；成功后载入最新版本内容并切回查看模式 | 丢弃不可逆需确认；查看模式是已发布文档的默认态 | 仅清空编辑器停留编辑模式：易误以为「草稿还在，只是清空了内容」 | `DocumentEditorPage.tsx` |
| D5 | 无草稿 / 基准版本缺失的响应 | 无草稿 404（code=`no_draft`）；基准版本缺失回退最新版本为 base | 前端只在有草稿时展示入口，404 不可达即兜底；回退保证旧草稿仍可看 diff | 基准缺失直接报错中断：旧草稿彻底看不了 diff，体验断裂 | `drafts.py`、路由层 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：草稿三件套（查看 diff / 保存 / 丢弃）闭环；丢弃不再依赖「把内容改回原文再保存」的绕路操作；diff 与版本对比共用一套算法与组件，口径不分叉。
- **负向**：新增一个只读端点与其前后端测试；`DocumentEditorPage.tsx` 顶部操作区多两个按钮（窄屏需收纳，见 ADR 0044 的紧凑口径）。
- **风险与缓解**：草稿内容与最新版本一致时 `draft_payload` 视为无草稿，diff 入口随之消失，无空态歧义；大文档 diff 复用既有 unified diff 性能口径（同 `GET /diff`），无新增风险。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 草稿保存/提交解耦 | `documents_draft` 表 + /draft 端点 | 语义不变，本 ADR 只补读路径与前端入口 | ADR 0051 → 0057 |
| 顶栏操作紧凑化 | 编辑页工具栏 | 窄屏下新按钮遵循紧凑收纳 | ADR 0044、0057 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/drafts.py`（`draft_diff`）、`src/cndb/plugins/documents/routers/documents.py`（`GET /draft/diff`） | `tests/test_document_drafts.py`（TestDraftDiff 6 例） | [41465823](https://codeup.aliyun.com/cndev/python/cndb/commit/41465823) |
| P1 | 已落地 | `frontend/src/api/documents.ts`（`getDraftDiff`）、`frontend/src/pages/documents/DocumentEditorPage.tsx`（「查看修改」按钮 + diff 抽屉） | `frontend/src/pages/documents/DocumentEditorPage.test.tsx`（diff 抽屉 / stale 提示） | [41465823](https://codeup.aliyun.com/cndev/python/cndb/commit/41465823) |
| P2 | 已落地 | `frontend/src/pages/documents/DocumentEditorPage.tsx`（「丢弃草稿」+ 编辑态重置） | `frontend/src/pages/documents/DocumentEditorPage.test.tsx`（确认 / 取消）、`frontend/tests/e2e/critical/document-draft-diff-discard.spec.ts` | [41465823](https://codeup.aliyun.com/cndev/python/cndb/commit/41465823) |

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（待人工评审转 Implemented）
- 已完成：P0 后端 `draft_diff` + `GET /draft/diff`；P1 前端「查看修改」抽屉（复用 DiffView，stale 提示）；P2 「丢弃草稿」接线（Popconfirm → DELETE → 重置到最新版本并回查看模式）
- 下一步：CI e2e 分片验证新 spec；人工评审后 Status 转 `Implemented`
- 已知坑：本地 e2e 无法运行（Playwright chromium 缺系统库 libatk 且无 sudo 安装权限），新 e2e spec 未经本地浏览器执行，仅过 tsc / eslint / 单测等价验证（与 ADR 0053 会话同款环境限制）
- 最近一次全绿：`make flow` + `make cov`（96.65%）+ `make frontend-coverage`（双门槛达标）@ [41465823](https://codeup.aliyun.com/cndev/python/cndb/commit/41465823)（2026-10-28）

# ADR 0125: 设计结构保存策略改为草稿 / 版本分离（3s 草稿 + 手动里程碑 + 10 分钟检查点）

Status: Accepted（2026-11-08 人工评审通过）
Date: 2026-11-08
Related: `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/plugins/design/services/`、`src/cndb/plugins/documents/models.py`、`src/cndb/plugins/documents/services/drafts.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/api/design.ts`、`docs/adr/0113-design-version-history-and-diff.md`、`docs/adr/0057-document-draft-diff-view.md`
需求卡片: `docs/requirements/0125-design-save-strategy.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..C10），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「保存过于频繁反而不好区分版本」 | 3s 自动保存改为 `PUT /{design_id}/draft`：只写 `design_designdraft`，不编译、不落版本、不改 `design.content` / 最新版本号；版本列表与 diff 完全不受自动保存影响 |
| C2 | 「保存过于频繁反而不好区分版本」 | 新表 `design_designdraft`（`design_id + user_id` 唯一）；草稿内容与最新版本一致时删除草稿行（等价于「无修改」）；`base_version_number` 记录开始编辑所基于的版本 |
| C3 | 隐含（版本语义） | `PUT /content` 仅表示手动保存：固定 `change_type=manual`（请求体不再接受 `change_type`）；内容等于最新版不落版，最新版为 `auto` 时提升为 `manual`（沿用 ADR 0113 D7） |
| C4 | 「结合最佳实践」 | `save_design_draft` 内判定检查点：距最新版本 `created_at` ≥600s 且草稿内容不同 → 走与手动保存同一写入函数编译并落 `auto` 版本；编译失败只保留草稿、不落版、不报 4xx |
| C5 | 「结合最佳实践」 | 新增 `GET /{design_id}/draft`；编辑器打开时若草稿与最新版不同，弹出「恢复上次编辑 / 丢弃」；恢复只改编辑器内存内容，不自动落版 |
| C6 | 隐含（权限） | 草稿读取 `_require_member` 但只返回本人草稿；写入 / 丢弃 `_require_editor`；草稿不属于版本资源，viewer 无写入口 |
| C7 | 隐含（存量兼容） | 存量 `auto` 版本原样保留（历史可看可 diff）；迁移只建新表，不改存量表与数据；`downgrade` 删表 |
| C8 | 隐含（备份口径） | `workspace_backup.py` 的 `designs[]` 不增加草稿字段（`BACKUP_VERSION` 保持 `15`）；`workspace_restore.py` 在删版本 / 设计前显式清空 `design_designdraft` |
| C9 | 隐含（交互一致性） | 自动保存状态文案改为「草稿已保存 / 草稿保存失败」；手动保存、刷新、恢复前 `cancel()` pending 草稿保存；手动保存成功后本人在该设计上的草稿行删除 |
| C10 | 隐含（测试与文档） | 单测 / 接口 / 迁移 / 前端单测 / e2e 分层覆盖；ADR 0113 的 D2 / D7 与本 ADR 冲突处以本 ADR 为准，索引与 CHANGELOG 同步 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `DesignDesign.content` 是当前唯一真相源，`compiled` 为保存期快照 | `src/cndb/plugins/design/models.py:61-67` | 自动保存推进 `content` 即等于推进正式内容 | 确认 |
| 2 | `DesignDesignVersion` 已有 `change_type`（manual / auto / refresh / rollback） | `src/cndb/plugins/design/models.py:105-107` | 无需改版本表；`auto` 保留给检查点使用 | 确认 |
| 3 | 保存端点按 `payload.change_type` 落版，且对相同内容去重 / 把最新 `auto` 提升 `manual` | `src/cndb/plugins/design/routers.py:512-558` | 去重与提升逻辑保留；`change_type` 入参取消 | 确认 |
| 4 | 新建设计即落 v1 `manual` | `src/cndb/plugins/design/routers.py:355-405` | 每个设计必有最新版本，检查点区间有确定起点 | 新增 |
| 5 | 依赖刷新 / 版本恢复各自落 `refresh` / `rollback` 版本 | `src/cndb/plugins/design/routers.py:562-590,806-870` | 二者不属于「保存节奏」，不改；恢复 / 刷新后应清空草稿 | 确认 |
| 6 | 前端 3s 防抖自动保存，`change_type=auto`，每次落一版 | `frontend/src/pages/design/DesignEditorPage.tsx:324-368` | 版本噪音来源；改为写草稿 + 状态文案 | 确认 |
| 7 | 自动保存与手动保存单飞、手动前 `cancel()` | `frontend/src/pages/design/DesignEditorPage.tsx:324-381` | 单飞机制沿用，目标端点改为草稿 | 确认 |
| 8 | 文档端已有个人草稿表：`documents_draft`（`document_id + user_id` 唯一、`base_version_number`、同内容即删除） | `src/cndb/plugins/documents/models.py:233-259`、`services/drafts.py:81-122` | 直接复用该范式，不新造协议 | 确认 |
| 9 | 文档草稿未引入三方合并 / 冲突拦截时必须 409；设计端现状无并发控制 | `src/cndb/plugins/documents/services/drafts.py:81-122` | 设计端本期不引入 `stale_version` 拦截（见 D6） | 新增 |
| 10 | 备份 `designs[]` 只导出设计当前内容与 `versions[]` | `src/cndb/plugins/workspaces/services/workspace_backup.py:577-615` | 不新增草稿字段，协议不变 | 确认 |
| 11 | 覆盖恢复先删 `design_designversion` 再删 `design_design` | `src/cndb/plugins/workspaces/services/workspace_restore.py:132-136` | 需在同事务内先删草稿表，避免恢复后残留旧草稿 | 确认 |
| 12 | 迁移 head 为 `b0c1d2e3f4a5` | `src/cndb/alembic/versions/b0c1d2e3f4a5_add_workspace_project_context.py` | 新迁移以此为 `down_revision` | 新增 |
| 13 | 版本抽屉已支持类型徽标、连续 `auto` 折叠、两版 diff | `frontend/src/pages/design/DesignEditorPage.tsx:494-560,830-887` | 检查点产生的 `auto` 仍按原方式展示，不改交互 | 确认 |

**核心缺陷（需求要补的）**：现状把「持久化」等同于「历史版本」，3s 一次的高频保存全部落成 `version_number`，版本序列被过程态淹没；用户找不到「值得回看的版本」。

设计目标（不变量）：

- **I1 持久化与历史分离**：自动保存只写草稿；任何创建 `design_designversion` 的路径只允许手动保存、检查点、刷新、恢复四类，且必须经统一落版入口。
- **I2 版本语义不变**：`version_number` 单序列、版本行不可变（检查点落 `auto` 后不再修改）、diff 与恢复按版本号工作（沿用 ADR 0113 / 0086）。
- **I3 草稿私有**：草稿按用户隔离，只有本人可读写；草稿内容不进入他人响应、版本列表、diff 或备份。
- **I4 正式内容一致**：`design.content` / `compiled` / 依赖闭包 / 引用索引只在手动保存、检查点、刷新、恢复时整体更新，四处共用同一写入函数。
- **I5 失败不破坏编辑态**：草稿保存失败、检查点编译失败不删除草稿、不改正式内容、不弹打断式错误；手动保存失败仍保留当前编辑器内容。
- **I6 存量与备份兼容**：存量 `auto` 版本保留；旧备份（无草稿概念）照常导入；恢复后草稿为空。

## Decision

### 1. 数据模型

新增 `design_designdraft`（不动存量表）：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | int | PK | 草稿行主键 |
| `design_id` | int | FK `design_design.id` CASCADE，NOT NULL，索引 | 归属设计 |
| `user_id` | int | FK `accounts_user.id` CASCADE，NOT NULL，索引 | 归属用户（草稿私有） |
| `content` | `Text` | NOT NULL DEFAULT `""` | 草稿 DSL 原文（不存 `compiled`） |
| `content_size` | int | NOT NULL DEFAULT 0 | UTF-8 字节数，列表 / 校验用 |
| `content_hash` | `String(64)` | NOT NULL DEFAULT `""` | 与最新版比较、去重用 |
| `base_version_number` | int | NOT NULL DEFAULT 0 | 开始编辑所基于的版本号（仅展示 / 提示） |
| `created_at` / `updated_at` | datetime | `TimestampMixin` | 自动保存覆盖更新 |

- 唯一键 `uniq_design_draft_design_user (design_id, user_id)`；索引 `ix_design_designdraft_user (user_id)`。
- 草稿**不参与** `version_number` 序列；不新增 `change_type`（草稿不是版本）。
- 常量：`DESIGN_CHECKPOINT_INTERVAL_SECONDS = 600` 定义在 `services/drafts.py`，测试可 monkeypatch。

### 2. 判定算法（唯一入口）

新增 `src/cndb/plugins/design/services/content.py`：

```python
def persist_design_content(
    db: Session,
    design: DesignDesign,
    user: User,
    *,
    content: str,
    change_type: str,
    comment: str = "",
) -> int: ...
```

- 编译（`_compile_for_design` 下沉 / 复用）→ 写 `design.content` / `compiled` / `dependencies` / `updated_by_id` → `_add_version(...)` → `sync_refs` → `mark_referrers_stale` → 返回版本号；**不 commit**，由调用方事务提交。
- 手动保存、检查点、刷新、恢复四条写路径都必须经该函数（I1 / I4）；路由层不再各自拼写字段。

新增 `src/cndb/plugins/design/services/drafts.py`：

```python
def get_design_draft(db, design_id, user_id) -> DesignDesignDraft | None: ...
def draft_payload(db, design, user) -> dict | None: ...
def save_design_draft(db, design, user, *, content, base_version_number=None) -> dict | None: ...
def discard_design_draft(db, design, user) -> None: ...
def delete_all_drafts(db, design_id) -> None: ...
```

**草稿保存顺序**：

1. `_require_editor` + `_design_or_404`。
2. 计算 `content_hash`；与最新版本 `content` 相同 → 删除本人草稿行并返回 `None`（C2）。
3. upsert 本人草稿行：`content` / `content_size` / `content_hash` / `base_version_number`（缺省取最新版本号；大于最新版本号 → 400）。
4. 检查点判定（C4）：
   - 取最新版本 `latest`；`now - latest.created_at < 600s` → 只提交草稿；
   - 到期 → `persist_design_content(..., change_type=auto)`；成功则删除本人草稿行并提交（正式内容已等于草稿）；`CompileResult` 有诊断 / 抛 `BadRequestError` → 回滚草稿之外的落版写入，**保留草稿并提交**，响应仍为草稿载荷。
5. 返回 `draft_payload` 或 `None`。

**手动保存顺序**（改 `save_design_content`）：

1. 取最新版本；内容相同：
   - 最新为 `auto` → 提升 `manual`，可更新 `comment`；
   - 否则不落版；
   - 两种情况都删除本人草稿行，返回详情。
2. 内容不同 → `persist_design_content(..., change_type=manual)` → 删除本人草稿行 → `commit`。

**刷新 / 恢复**：写路径复用 `persist_design_content`，类型分别为 `refresh` / `rollback`；成功后删除**该设计全部用户**的草稿行（正式内容已整体换代，旧草稿无恢复意义），在既有事务内提交。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/designs/{design_id}/draft` | 新增：返回本人草稿载荷 `{content, content_size, base_version_number, current_version_number, stale, updated_at}`；无草稿 / 草稿与最新版相同 → `null` |
| `PUT .../designs/{design_id}/draft` | 新增：保存本人草稿（editor）；入参 `{content, base_version_number?}`；返回草稿载荷或 `null`（与最新版相同） |
| `DELETE .../designs/{design_id}/draft` | 新增：丢弃本人草稿（editor）；幂等，恒 204 |
| `PUT .../designs/{design_id}/content` | 修改：请求体删除 `change_type` 字段（服务端固定 `manual`）；成功后删除本人草稿行 |
| `POST .../designs/{design_id}/refresh` | 修改：成功后清空该设计全部草稿 |
| `POST .../designs/{design_id}/versions/{n}/restore` | 修改：成功后清空该设计全部草稿 |
| 版本列表 / 详情 / diff | 不变（`auto` 仍作为检查点类型展示） |

响应模型新增 `DesignDraftPayload`；`DesignContentSave` 只保留 `content` / `comment`。

### 4. 边界与例外

1. **无修改**：草稿内容与最新版一致 → 删除草稿行，`GET` 返回 `null`，前端不显示恢复提示。
2. **检查点未到期**：只写草稿；`design.content` 与版本号不变。
3. **检查点编译失败**：不落版、不改 `design.content`；草稿保留，响应仍为草稿载荷（不返回 400），前端状态显示「草稿已保存」。
4. **检查点与手动保存竞争**：前端单飞 + 手动前 `cancel()`；服务端以事务和 `unique(design_id, version_number)` 兜底（沿用 ADR 0114 的并发口径）。
5. **多用户草稿**：每人一条互不覆盖；手动保存只删本人草稿；刷新 / 恢复清空全部草稿。
6. **草稿基准漂移**：`base_version_number < current_version_number` 时载荷标 `stale=true`，前端提示「基于 vN 编辑，当前已到 vM」；**不拦截保存**（设计端无修改申请 / 直编双轨，保持现状后写覆盖）。
7. **viewer**：`PUT/DELETE /draft` 403；`GET /draft` 返回本人空草稿（viewer 本就不会产生草稿）。
8. **软删设计**：草稿端点沿用 `_design_or_404`，软删 404；设计硬删由 FK CASCADE 清理草稿。
9. **草稿体积**：沿用设计原文 256KB 编译上限的同一常量做写入校验，超限 400，不落草稿。
10. **检查点上限**：同一设计最多每 600s 一条 `auto`；连续编辑 1 小时最多 6 条，版本抽屉沿用连续 `auto` 折叠。

### 5. 迁移

单条 alembic 迁移（`down_revision = "b0c1d2e3f4a5"`，revision `c1d2e3f4a5b7_add_design_drafts.py`）：

1. `upgrade`：`inspect` 判断表不存在时 `op.create_table("design_designdraft", ...)`，同时建唯一键与索引；存在则跳过（幂等）。不写任何业务数据。
2. `downgrade`：表存在时 `op.drop_table("design_designdraft")`；不触碰 `design_design` / `design_designversion`。
3. 迁移测试：升级 → 降级 → 再升级幂等；列集合与 ORM 模型逐列一致；唯一键与索引存在。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/design.ts` | `saveContent` 去掉 `change_type`；新增 `DesignDraftPayload` 类型与 `getDraft` / `saveDraft` / `discardDraft` |
| 编辑器 | `frontend/src/pages/design/DesignEditorPage.tsx` | ① 3s 防抖改调 `saveDraft`，状态文案「草稿已保存 / 草稿保存失败」；② 打开时 `getDraft`，与最新版不同则弹「恢复上次编辑 / 丢弃」；③ 手动保存 / 刷新 / 恢复前 `cancel()`；④ 手动保存成功后清空恢复提示；⑤ 版本抽屉与 diff 交互不变，`auto` 徽标改文案为「检查点」 |
| 样式 | `frontend/src/index.css` | 复用 `cn-dsl-version-*`；恢复提示条沿用现有 `Alert` / 抽屉视觉，不新造弹窗体系 |
| 测试 | `frontend/src/pages/design/DesignEditorPage.test.tsx`、`frontend/tests/e2e/critical/design-version-history.spec.ts` | 见 §7 |

### 7. 测试清单

**判定层（单测）**：

- `save_design_draft`：新建 / 覆盖草稿；内容等于最新版 → 删除草稿；`base_version_number` 越界 400；
- 检查点：未到期只写草稿；到期且内容不同 → 落 `auto` 且 `design.content` 更新、草稿删除；编译失败 → 草稿保留、版本数不变；
- `save_design_content`：相同内容不落版；最新 `auto` 提升 `manual`；成功后删除本人草稿；
- 刷新 / 恢复：清空该设计全部草稿，版本类型分别 `refresh` / `rollback`；
- `draft_payload`：`stale` 判定、无草稿返回 `None`。

**接口层**（`tests/test_design_api.py`）：

- `PUT/GET/DELETE /draft` 正常往返；viewer 写 403、读返回空；跨工作区 404；
- 3s 自动保存等价路径（`PUT /draft`）后版本列表长度不变；
- 手动保存落 `manual` 并删除草稿；相同内容不新增版本；
- 检查点（monkeypatch `DESIGN_CHECKPOINT_INTERVAL_SECONDS=0` 或回拨版本时间）落 `auto`；
- `PUT /content` 携带旧 `change_type` 字段按 422 拒绝（契约收紧）。

**迁移 / 备份**：

- 迁移升级 / 降级 / 幂等 + 列集合；
- 备份载荷断言 `designs[]` 不含草稿字段、`BACKUP_VERSION == "15"`；
- 恢复工作区后 `design_designdraft` 计数为 0；
- 旧备份导入不受影响。

**前端单测**：

- 编辑停止 3s → 只调一次 `saveDraft`，不调 `saveContent`；连续输入只落最后一次；
- 编译有诊断 / dirty=false / viewer 时不保存草稿；
- 草稿保存失败：内容不丢、状态可见、不弹手动保存 Alert；
- 打开时有草稿 → 恢复提示；恢复后编辑器内容为草稿；丢弃后调 `discardDraft`；
- 手动保存取消 pending 草稿保存并清除提示；
- 版本抽屉：`auto` 显示「检查点」，连续 `auto` 折叠与 diff 行为不变。

**e2e（前端）**：编辑 → 等待草稿保存 → 版本历史仍只有手动版本 → 手动保存生成 `manual` → 关闭重开出现草稿恢复提示 → 恢复 / 丢弃两条分支可见。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 模型 + 迁移 + `services/content.py` / `services/drafts.py` + 草稿三端点 + 手动保存去重与草稿删除 + 刷新 / 恢复清空草稿 + 检查点 + 单测 / 接口 / 迁移测试 | 中（抽出统一写入函数，触碰四条写路径） |
| **P1** | 前端 API + 3s 草稿保存 + 恢复 / 丢弃提示 + 状态文案 + 前端单测 | 中（打开态与草稿恢复交互） |
| **P2** | 备份 / 恢复清理断言 + e2e + CHANGELOG / 文档回填 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 草稿表 + 手动版本 + 10 分钟 `auto` 检查点 | 持久化与历史分离，版本列表只留里程碑；与文档草稿、Figma / Git 心智一致 | ① 继续 3s 落 `auto` + 仅 UI 折叠：版本号仍被过程态淹没；② 仅手动保存：长时间编辑无任何历史快照 | `models.py`、`services/drafts.py` |
| D2 | 草稿粒度 | 每人一份（`design_id + user_id` 唯一） | 与 `documents_draft` 一致；多人编辑互不覆盖 | 设计表加 `draft_content` 单列：后编辑者覆盖前者的未提交草稿 | `models.py` |
| D3 | 草稿内容 | 只存 DSL 原文 + `base_version_number`，不存 `compiled` | 3s 高频写不能每次都编译；预览由现有 `/preview` 承担 | 存 `compiled`：写放大且历史 IR 与当前编译口径易漂移 | `services/drafts.py` |
| D4 | 落版时机 | 仅手动保存 / 检查点 / 刷新 / 恢复；手动保存请求不再接受 `change_type` | 客户端不能伪造来源（继承 ADR 0113 I4）；`auto` 只由检查点产生 | 保留客户端传 `auto`：等于保留旧的 3s 落版入口 | `schemas.py`、`routers.py` |
| D5 | 检查点参数 | 距最新版本 ≥600s 且内容有变化才落一条 `auto` | 1 小时连续编辑最多 6 条；与 Figma / Notion 的时间桶检查点同量级 | ① 不设检查点：长编辑无历史；② 5 分钟：版本仍偏多；③ 30 分钟：单次会话可能一条都没有 | `services/drafts.py` |
| D6 | 并发与基准漂移 | `base_version_number` 只展示 `stale`，不拦截保存 | 设计端无修改申请双轨，现状即后写覆盖；拦截会改变既有保存语义，超出本次需求 | 文档式 `stale_version` 409：用户在正常协作下被阻塞 | `services/drafts.py`、`DesignEditorPage.tsx` |
| D7 | 草稿与备份 | 草稿不进工作区备份；恢复时清空 | 草稿是个人临时恢复数据，且备份不携带用户身份映射；协议保持 v15 | 随 `designs[]` 导出当前用户草稿：身份映射失真、协议与测试面扩大 | `workspace_backup.py`、`workspace_restore.py` |
| D8 | 统一写入口 | 抽出 `persist_design_content`，四条写路径共用 | 保证 `content` / `compiled` / 依赖 / 引用索引 / `stale` 标记只在一处更新（I4） | 路由层各自拼写：检查点容易漏 `sync_refs` / `mark_referrers_stale` | `services/content.py` |
| D9 | 草稿清理范围 | 手动保存删本人草稿；刷新 / 恢复删全部草稿 | 刷新 / 恢复整体换代，保留旧草稿只会把过期内容“复活” | 手动保存也删全部：误删他人未提交编辑 | `routers.py`、`services/drafts.py` |
| D10 | 前端展示 | `auto` 徽标文案改「检查点」，其余折叠 / diff 不变 | 避免用户把检查点误读为“自动保存” | 新增第五种 `change_type`：版本表、备份、前端枚举全要扩，收益不足 | `DesignEditorPage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## 行业对照（可选）

| 维度 | Figma | Notion | 本设计 |
|---|---|---|---|
| 高频持久化 | 自动保存，无版本 | 自动保存，无版本 | 3s 写个人草稿（D1 / D3） |
| 自动历史 | 约 30 分钟检查点 | 周期性快照 | 10 分钟 `auto` 检查点（D5） |
| 命名版本 | 手动命名 | 手动保存版本 | 手动保存 `manual` + 备注（D4） |
| 草稿归属 | 个人 / 文件级 | 个人 | 每人一份（D2） |

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 版本模型与 diff | `design_designversion` / `services/diff.py` | 版本行、`change_type`、单序列、diff 与摘要不变 | ADR 0113（D2 / D7 的落版节奏由本 ADR 修订） |
| 依赖闭包与恢复 | 版本 `dependencies` + restore | 恢复仍按历史快照编译并落 `rollback` 新版本 | ADR 0086 / 0113 |
| 草稿范式 | `documents_draft` | 复用「每人一份 + `base_version_number` + 同内容即删除」 | ADR 0057 |
| 备份协议 | `designs[]` | 不增加草稿字段，协议仍 v15 | ADR 0075 / 0118 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/services/content.py`、`src/cndb/plugins/design/services/drafts.py`、`src/cndb/alembic/versions/c1d2e3f4a5b7_add_design_drafts.py` | `tests/test_design_api.py`、`tests/test_design_draft_migration.py` | 未提交 |
| P1 | 已落地 | `frontend/src/api/design.ts`、`frontend/src/api/index.ts`、`frontend/src/pages/design/DesignEditorPage.tsx` | `frontend/src/pages/design/DesignEditorPage.test.tsx` | 未提交 |
| P2 | 已落地 | `src/cndb/plugins/workspaces/services/workspace_restore.py` | `tests/test_workspace_backup_v14.py`（草稿不入备份 / 恢复清空）、`frontend/tests/e2e/critical/design-version-history.spec.ts` | 未提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 全部落地，`make check-fast` / `make flow` 全绿；待提交（未授权 commit / push）
- 已完成：需求卡 0125（Q1-Q4 已确认）；ADR 评审通过；草稿表迁移 `c1d2e3f4a5b7`；统一落版入口 `services/content.py`；草稿三端点 + 检查点；前端草稿保存 / 恢复 / 丢弃；备份排除与恢复清空；e2e 重写
- 下一步：如需发布，按 H4 / H6 由人确认后 commit / push；若后续引入多人协同冲突拦截，另立 ADR 修订 D6
- 已知坑：检查点测试用 monkeypatch `DESIGN_CHECKPOINT_INTERVAL_SECONDS`；`PUT /content` 已收紧为 `extra="forbid"`，旧客户端带 `change_type` 会 422；`design_designdraft` 依赖 FK 级联，覆盖恢复已显式先删；SQLite 读回时间为 naive，判定用 `_as_utc` 归一
- 最近一次全绿：2026-11-08 `make check-fast` + `make flow`（6769 passed / 3 skipped；前端单测 30 例通过）

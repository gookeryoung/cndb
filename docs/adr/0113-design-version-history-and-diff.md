# ADR 0113: 设计结构版本历史区分主动保存 / 自动小版本与版本 DIFF

Status: Accepted（2026-11-06 用户评审通过，进入实现）
Date: 2026-11-06
Related: `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/plugins/design/services/files.py`、`src/cndb/plugins/documents/services/parse.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/api/design.ts`、`frontend/src/hooks/useDebouncedCallback.ts`、`frontend/src/components/DiffView/DocumentDiffView.tsx`、`docs/adr/0057-document-draft-diff-view.md`、`docs/adr/0079-design-3d-dsl-module.md`、`docs/adr/0086-design-file-library-assembly-constraints-and-open-performance.md`
需求卡片: `docs/requirements/0113-design-version-history-and-diff.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 区分用户主动保存的版本和自动保存的小版本 | `design_designversion` 新增 `change_type`（`manual` / `auto` / `refresh` / `rollback`）；四个写路径各自由服务端赋值，前端只可请求 `manual` / `auto` |
| C2 | 自动保存的小版本 | 编辑器用 `useDebouncedCallback(3000)` 自动保存；仅 `dirty && !isViewer && 编译无诊断 && 无写请求在途` 时触发；失败只更新工具栏状态，不回退编辑器内容 |
| C3 | 不好进行区分 | 共用 `version_number` 单序列；自动保存推进 `design.content` 与最新版本号，类型由 `change_type` 表达；列表 / 详情 / diff 均返回该字段 |
| C4 | 不好进行区分 | 版本抽屉按类型区分徽标：`manual` 为里程碑（无徽标或「主动保存」），`auto` 弱化并把连续自动版本折叠为「N 个自动小版本」；数据全量保留 |
| C5 | 更友好的版本DIFF设计 | 新增 `GET /{design_id}/diff?base=&head=`：unified diff + `added` / `removed` + 结构变化摘要（参数 / 节点数 / 顶层装配）；文本 diff 复用 `core/textdiff.unified_diff` 唯一入口 |
| C6 | 更友好的版本DIFF设计 | 版本抽屉支持任选两版（默认本版 vs 上一版），摘要在前、文本 diff 在后，复用 `DocumentDiffView` 的统一 / 并排、双端行号与行内高亮 |
| C7 | 隐含（只读与权限） | 版本列表 / 详情 / diff 沿用 `_require_member`；保存（含自动）沿用 `_require_editor`；viewer 前端不调度自动保存 |
| C8 | 隐含（草稿不丢） | 自动保存失败或编译失败不落版、不改 `design.content`；编辑器内容与手动保存错误 Alert 均保留 |
| C9 | 隐含（存量兼容） | 迁移给存量行补 `change_type='manual'`；迁移幂等且 downgrade 可还原；存量零数据改写（仅默认值填充） |
| C10 | 隐含（备份口径） | designs 段的版本项导出 / 导入 `change_type`；旧备份缺字段按 `manual` 还原，备份协议仍为 v13（新增可选字段，不升号） |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 版本表只有 `version_number` / `content` / `compiled` / `dependencies` / `comment`，无来源类型 | `src/cndb/plugins/design/models.py:73-104` | 无法区分主动保存与自动小版本 | 确认 |
| 2 | 唯一落版入口 `_add_version`，版本号 = 最新号 + 1 | `src/cndb/plugins/design/routers.py:187-211` | 可在此统一注入 `change_type` | 确认 |
| 3 | 手动保存 `PUT /content` 编译通过即落版，无自动保存 | `src/cndb/plugins/design/routers.py:432` | 需要新增自动保存调用与类型入参 | 确认 |
| 4 | 依赖刷新 `POST /refresh` 落版，备注默认「依赖更新」 | `src/cndb/plugins/design/routers.py:468` | 应归为 `refresh`，避免与主动保存混淆 | 确认 |
| 5 | 版本恢复 `POST /versions/{n}/restore` 落新版，备注「恢复自 vN」 | `src/cndb/plugins/design/routers.py:632` | 应归为 `rollback` | 确认 |
| 6 | 版本列表按号倒序、详情返回原文 / IR / 依赖快照；无 diff 端点 | `src/cndb/plugins/design/routers.py:581,615` | 需补 `change_type` 与两版本对比端点 | 确认 |
| 7 | 版本 DTO 无类型字段 | `src/cndb/plugins/design/schemas.py:151-169` | 需补 `change_type` 与 diff 响应模型 | 确认 |
| 8 | 前端仅手动保存 / Ctrl+S；版本抽屉只做原文回看与恢复，无类型徽标、无 diff | `frontend/src/pages/design/DesignEditorPage.tsx:198-241,580-670` | 自动保存与 diff 交互均需新增 | 确认 |
| 9 | 前端设计 API 已有 list / get / restore 版本封装 | `frontend/src/api/design.ts:194-258` | 补 `changeType` 参数与 diff 方法即可 | 确认 |
| 10 | `useDebouncedCallback(fn, delayMs)` 已用于视图配置自动保存，卸载自动取消 | `frontend/src/hooks/useDebouncedCallback.ts:1-46` | 直接复用到 3s 自动保存，不新造计时器 | 确认 |
| 11 | `DocumentDiffView` + `diffModel` 已实现统一 / 并排、行内高亮、增删统计 | `frontend/src/components/DiffView/DocumentDiffView.tsx:1-126` | 设计 diff 直接复用组件 | 确认 |
| 12 | `unified_diff(base, head) → (text, added, removed)` 在 documents 插件内 | `src/cndb/plugins/documents/services/parse.py:218-232` | 设计插件不应反向依赖 documents 插件，需下沉到 core | 新增 |
| 13 | 备份 designs 段逐版本导出 `version_number` / `content` / `comment` / `dependencies`，`compiled` 不导出 | `src/cndb/plugins/workspaces/services/workspace_backup.py:547-584` | 新增字段需往返；旧备份缺字段按 manual | 确认 |
| 14 | 备份导入逐版本重建，字段缺省按代码默认 | `src/cndb/plugins/workspaces/services/backup_io.py:1113-1114,1198-1210` | 旧备份无需升级即可导入 | 确认 |
| 15 | 版本行已持久化 `compiled` IR 快照（含 `params` / `nodes` / `outline`） | `src/cndb/plugins/design/models.py:95`、`src/cndb/plugins/design/services/dsl/compile.py:165-173` | 结构变化摘要可直接读快照，无需重新编译 | 新增 |
| 16 | 迁移链当前 head 为 `2a4c6e8f0b1d` | `src/cndb/alembic/versions/2a4c6e8f0b1d_drop_datasource_entrant_cursor.py:19` | 新迁移以该 revision 为 down_revision | 新增 |

**核心缺陷（需求要补的）**：`design_designversion` 只表达「第几版 + 原文」，不表达「这一版是谁、为什么产生的」；所有保存（手动 / 刷新 / 恢复）同质化，且历史面板只能看单版原文，无法回答「这版和上一版改了什么」。

设计目标（不变量）：

- **I1 单一落版入口**：所有版本写入只经 `_add_version`，且必须显式传 `change_type`；路由层不得自行拼 `DesignDesignVersion`。
- **I2 单一 diff 判定**：设计 diff 必须走 `core/textdiff.unified_diff`；前端 / 设计插件不得另写 diff 算法。
- **I3 自动保存不破坏编辑态**：自动保存失败、编译失败或内容与最新版一致时不落版、不回写编辑器内容；手动保存失败仍保留草稿。
- **I4 类型不可伪造**：客户端只能请求 `manual` / `auto`；`refresh` / `rollback` 由服务端在对应端点强制赋值。
- **I5 历史可复现不变**：依赖闭包快照与按快照恢复的口径沿用 ADR 0086 I5，本设计不改。
- **I6 存量与旧备份兼容**：存量版本一律视为 `manual`；旧备份缺 `change_type` 时按 `manual` 还原。

## Decision

### 1. 数据模型

`design_designversion` 增加一列（无新表）：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `change_type` | `String(20)` | `NOT NULL DEFAULT 'manual'` | 版本来源：`manual` 主动保存 / `auto` 自动小版本 / `refresh` 依赖刷新 / `rollback` 版本恢复 |

- 常量定义在 `models.py`：`CHANGE_TYPE_MANUAL / AUTO / REFRESH / ROLLBACK`，并集合 `CHANGE_TYPE_VALUES`；对外 schema 用 `Literal` 校验。
- 版本号仍单序列（`version_number` 连续），不引入主 / 次双轨；`unique(design_id, version_number)` 不变。
- 自动小版本与主动版本同表同列，**数据全量保留**，折叠只是前端展示策略。
- 结构摘要不落库：diff 时读两版 `compiled` 快照现场计算（见 §2）。

### 2. 判定算法（唯一入口）

**落版**：`_add_version(db, design, user, *, content, compiled, comment, dependencies, change_type)` 增加必填 `change_type`；三个写入端点（save / refresh / restore）各自传值（`manual|auto` / `refresh` / `rollback`）。

**保存去重与主动提升**（`save_design_content` 内，`_add_version` 之前）：

1. 取最新版本行 `latest`（无则走正常落版）。
2. `payload.change_type == auto` 且 `latest.content == payload.content` → 不落版，直接返回当前详情（版本号不变）。
3. `payload.change_type == manual` 且 `latest.content == payload.content`：
   - 若 `latest.change_type == auto` → 将该行 `change_type` 改为 `manual`，`payload.comment` 非空时同时更新 `comment`，**不新增版本**（把自动小版本提升为主动里程碑）；
   - 否则不落版，返回当前详情（前端按钮本就禁用）。
4. 其余情况按现有逻辑编译、写 `design.content`、落版。

**版本差异**：新增 `services/diff.py::design_diff(db, design, base, head)`：

1. 按 `version_number` 取两版（缺任一 → `NotFoundError(code=design_version_not_found)`）；
2. `diff_text, added, removed = unified_diff(base.content, head.content)`；
3. 结构摘要 `structure_summary(base.compiled, head.compiled)`：
   - `available=false`：任一侧 `compiled` 为空 / 非 dict / 缺 `nodes`（v1 老快照或损坏）；
   - `params.added / removed / changed[{name, base, head}]`：按 `compiled["params"]` 的 `name → value` 对比；
   - `nodes`：`{"base": int, "head": int}`；
   - `assemblies.added / removed`：`compiled["outline"]["children"]` 中 `kind ∈ {system, assembly, group}` 的 `name` 集合差；
   - base 与 head 相同时返回空摘要 + 空 diff；
4. 返回 `{base_version, head_version, diff, added, removed, summary}`。

**diff 工具下沉**：把 `unified_diff` 从 `documents/services/parse.py` 移到 `src/cndb/core/textdiff.py`；`documents` 的 3 处调用（版本 diff、草稿 diff、修改申请 diff）与 2 处测试改为从 core 导入，`parse.py` 不再保留同名转发（仓库不保留兼容壳）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `PUT /api/v1/workspaces/{wid}/designs/{design_id}/content` | `DesignContentSave` 增加 `change_type: Literal["manual","auto"] = "manual"`；实现去重与主动提升（§2） |
| `POST .../designs/{design_id}/refresh` | 无入参变化；服务端强制 `change_type=refresh` |
| `POST .../designs/{design_id}/versions/{n}/restore` | 无入参变化；服务端强制 `change_type=rollback` |
| `GET .../designs/{design_id}/versions` | 列表项增加 `change_type` |
| `GET .../designs/{design_id}/versions/{n}` | 详情增加 `change_type` |
| `GET .../designs/{design_id}/diff?base=&head=` | 新增：两版本对比，返回 `{base_version, head_version, diff, added, removed, summary}`；成员可读 |

### 4. 边界与例外

1. **自动保存与手动保存竞争**：前端同一时刻只允许一个保存在途；手动保存、刷新、恢复前先 `cancel()` pending 自动保存；请求在途时不再调度新的自动保存。
2. **自动保存触发条件**：`contentReady && dirty && !isViewer && !preview.compiling && diagnostics.length === 0`；内容回到已保存态时取消防抖。
3. **自动保存失败**：只把工具栏状态置为「自动保存失败」（可重试），不弹出错误 Alert、不回写内容；手动保存失败仍走现有「保存被拒绝（草稿已保留）」Alert。
4. **自动保存成功**：不回写编辑器 `content`（用户可能已继续输入），只失效详情 / 版本查询；手动保存维持现有回写行为。
5. **编译失败**：服务端仍按现逻辑 400 拒绝且不落版（边界 #2）；前端因 `diagnostics.length === 0` 条件本就不会发起自动保存。
6. **内容相同**：按 §2 去重；主动保存可把最新 `auto` 提升为 `manual`，不产生重复内容的版本行。
7. **结构摘要不可用**：老版本 / 空 `compiled` 时 `summary.available=false`，文本 diff 照常返回，前端显示「该版本缺少结构快照，仅显示文本差异」。
8. **恢复 / 刷新仍会落版**：沿用 ADR 0086 的「恢复 = 以历史原文新建一版」，只是类型标记为 `rollback` / `refresh`，不改变历史可复现口径（I5）。
9. **版本列表规模**：不新增分页 / 保留上限（Q3 全量保留）；折叠在前端按「连续 `auto` 段」分组，段内仍可逐条展开。
10. **软删设计**：版本 / diff 端点沿用 `_design_or_404`，软删设计返回 404。

### 5. 迁移

单条 alembic 迁移（`down_revision = "2a4c6e8f0b1d"`，新 revision 例如 `3b5d7f9a1c2e_design_version_change_type.py`）：

1. `upgrade`：用 inspector 判断列是否已存在，幂等执行 `op.add_column("design_designversion", sa.Column("change_type", sa.String(20), nullable=False, server_default="manual"))`；存量行由默认值补齐，不改写原文 / 版本号。
2. `downgrade`：列存在时 `op.drop_column("design_designversion", "change_type")`；不触碰其他列与数据。
3. 迁移测试覆盖升级 → 降级 → 再升级幂等，以及存量行 `change_type == "manual"`。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/design.ts` | `DesignVersionItem` 增加 `change_type`；`saveContent` 增加可选 `change_type`；新增 `getDiff(wid, designId, base, head)` 与 `DesignVersionDiff` / `DesignVersionSummary` 类型 |
| 编辑器 | `frontend/src/pages/design/DesignEditorPage.tsx` | ① 引入 `useDebouncedCallback`，按 §4.2 调度自动保存（静默，失败只更新工具栏状态）；② 手动保存 / 刷新 / 恢复前 `cancel()`；③ 保存按钮在「有修改」或「最新版为 auto」时可用，后者文案为「标记为重要版本」；④ 版本抽屉改为类型徽标 + 连续自动版本折叠 + 任选两版对比；⑤ 摘要块在 `DocumentDiffView` 之前渲染 |
| 样式 | `frontend/src/index.css` | 版本抽屉的类型徽标、折叠分组、摘要块样式，沿用 `cn-vh-*` / `cn-diff-*` 既有视觉语言 |
| 测试 | `frontend/src/pages/design/DesignEditorPage.test.tsx`、`frontend/tests/e2e/critical/design-version-history.spec.ts` | 见 §7 |

### 7. 测试清单

**判定层（单测）**：

- `_add_version` 四类 `change_type` 落库正确；服务端强制 `refresh` / `rollback`，客户端传非法值被 schema 拒绝；
- 保存去重：`auto` 相同内容不落版；`manual` 相同内容把最新 `auto` 提升为 `manual` 且版本号不变；已为 `manual` 时不重复落版；
- `structure_summary`：参数增删改、节点数、顶层装配增删；`compiled` 缺失时 `available=false`；
- `design_diff`：正常 diff / base==head 空差异 / 版本缺失 404；
- `core.textdiff.unified_diff` 行数与增删统计（从 documents 测试迁移）。

**接口层**（`tests/test_design_api.py`）：

- `PUT /content`：默认 `manual`；`change_type=auto`；相同内容去重；主动提升；
- `POST /refresh`、`POST /versions/{n}/restore` 落对应类型；
- `GET /versions`、`GET /versions/{n}` 返回 `change_type`；
- `GET /diff`：200 载荷结构、`base/head` 缺失 404、成员可读、viewer 可读（只读）；
- 权限：viewer 调 `PUT /content` 仍 403（含自动保存路径）。

**迁移 / 备份**：

- 迁移升级 / 降级 / 幂等 + 存量行默认 `manual`；
- 备份往返：`change_type` 原样还原；旧 v13 备份缺字段按 `manual` 导入。

**前端单测**：

- 编辑停止 3s 且无诊断 → 调一次自动保存（fake timers）；连续输入只落最后一次；
- 编译有诊断 / dirty=false / viewer 时不自动保存；
- 自动保存失败：内容不丢、错误状态可见、不弹手动保存 Alert；
- 手动保存取消 pending 自动保存；
- 版本抽屉：类型徽标、连续 auto 折叠为「N 个自动小版本」、展开可回看；
- diff：默认本版 vs 上一版、切换两版、摘要先于文本 diff、空差异态。

**e2e（前端）**：编辑 → 等待自动小版本 → 手动「标记为重要版本」→ 打开版本历史 → 折叠展开 → 选择两版对比 → 摘要与文本 diff 可见。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 数据模型 + 迁移 + `_add_version` 类型参数 + save 去重 / 主动提升 + schema / 列表返回 + 单测 / 接口 / 迁移测试 | 中（涉及存量表，但仅加默认列） |
| **P1** | `core/textdiff` 下沉 + `design_diff` + `structure_summary` + `GET /diff` + 测试（含 documents 回归） | 中（跨模块移动工具函数） |
| **P2** | 前端自动保存 + 类型徽标 / 折叠 + diff 抽屉 / 摘要 + 备份字段 + 前端单测 / e2e | 中（自动保存交互与竞态） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案 | 单表加 `change_type`，自动保存复用保存端点并落同序版本，diff 读时计算 | 改动最小、与文档端 `change_type` 范式一致；版本表已有原文与 IR 快照 | ① 另建 `design_designversion_minor` 小版本表：版本序列 / 恢复 / 备份全部要双轨维护；② 自动保存只写个人草稿：无法回看历史，不能满足「小版本」 | `models.py`、`routers.py` |
| D2 | 自动保存触发（Q1） | 停止输入 3s，编译无诊断且内容有变化才落 `auto` 版本 | 与编辑器 300ms 预览防抖同链路，3s 足够区分「思考停顿」与「持续输入」 | 固定 60s 定时：连续编辑仍会切碎版本；仅离开页面兜底：崩溃丢改动 | `DesignEditorPage.tsx` |
| D3 | 编号口径（Q2） | 共用 `version_number` 单序列 + `change_type` 类型 | 恢复 / 依赖快照 / 备份均按单序列实现，双轨会破坏可复现与恢复语义 | 主 / 次双轨：`restore` 与依赖快照需同时理解两套编号 | `models.py`、`routers.py` |
| D4 | 自动版本保留（Q3） | 全量保留，前端把连续 `auto` 折叠展示 | 自动保存是不可变快照，删除会破坏「任意两版可对比」；折叠已解决列表噪音 | 只留最近 N 条 / 主动保存时清理：历史断档且删除不可逆 | `DesignEditorPage.tsx` |
| D5 | DIFF 粒度（Q4） | 文本行级 unified diff + 结构变化摘要 | DSL 行级差异定位精确；IR 快照已存在，摘要可零编译得出 | 仅文本 diff：看不出装配结构变化；仅结构 diff：丢失原文级修改 | `services/diff.py`、`DesignEditorPage.tsx` |
| D6 | diff 工具位置（Q5） | `unified_diff` 下沉到 `cndb/core/textdiff.py`，documents 与 design 共用 | 避免 design 插件反向依赖 documents 插件；保持单一 diff 入口（I2） | ① design 直接 import documents 服务：插件耦合；② design 内复制算法：双入口漂移 | `src/cndb/core/textdiff.py`、`documents/services/parse.py` |
| D7 | 自动保存与主动保存同内容 | `auto` 相同内容不落版；`manual` 相同内容把最新 `auto` 提升为 `manual`，不新增版本 | 自动保存可能抢先落版，必须保留用户「标记里程碑」的能力；提升避免重复内容行 | ① 一律不落版：用户无法标记；② 一律新建 manual 版本：产生同内容重复版本，反而更难区分 | `routers.py` `save_design_content` |
| D8 | 结构摘要来源 | 读两版 `compiled` 快照；缺失时 `available=false`，文本 diff 照常 | 版本表已存 IR；重编译历史依赖可能失败且耗时 | 每次都按依赖快照重编译：慢且受依赖缺失影响 | `services/diff.py` |
| D9 | 备份协议 | designs 版本项增加 `change_type`；保持 v13，不升协议号；旧备份缺字段按 `manual` | 新增字段是 v13 超集，导入按字段显式取值，旧客户端忽略未知字段 | 升 v14：为可选元数据牵动备份协议与全套版本断言，收益不足 | `workspace_backup.py`、`backup_io.py` |
| D10 | 类型赋值边界 | 客户端只可传 `manual` / `auto`；`refresh` / `rollback` 服务端强制 | 防止前端伪造来源，类型语义可信（I4） | 允许客户端自由传四类：来源可被篡改 | `schemas.py`、`routers.py` |
| D11 | 自动保存失败表现 | 静默失败 + 工具栏状态提示，不回写内容、不弹 Alert | 自动保存是后台行为，Alert 会打断编辑；手动保存失败仍强提示 | 复用红色 Alert：频繁打扰 | `DesignEditorPage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：版本历史能一眼区分「主动里程碑」与「过程小版本」；任意两版可对比，先看结构摘要再看行级差异；自动保存让编辑器崩溃 / 误关的损失收敛到 3 秒内；文档与设计共用一套 diff 算法。
- **负向**：`design_designversion` 行数随自动保存增长（全量保留的既定成本）；前端新增自动保存竞价与折叠逻辑，`DesignEditorPage.tsx` 复杂度上升；`unified_diff` 下沉会触碰 documents 的 3 处调用与 2 处测试。
- **风险与缓解**：自动保存与手动保存并发 —— 单飞 + cancel + 服务端去重兜底；旧版本无 `compiled` —— 摘要降级为不可用，文本 diff 不受影响；备份旧数据 —— 缺字段默认 `manual`，并有往返测试覆盖。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 版本模型与保存落版 | `design_designversion` + `_add_version` | 增加 `change_type`，版本号仍单序列；恢复 / 刷新仍落新版本 | ADR 0079 → 0113 |
| 依赖闭包与历史复现 | 版本 `dependencies` + restore | 口径不变，恢复仅补类型标记 | ADR 0086 |
| Diff 视图与 unified diff | `components/DiffView` + `parse.unified_diff` | 设计端复用同一组件与算法（工具下沉 core） | ADR 0057 → 0113 |
| 设计单一工作台 | 编辑器 / 版本抽屉入口 | 版本入口仍由 `DesignMoreMenu` 打开，不新增页面 | ADR 0109 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/alembic/versions/3b5d7f9a1c2e_design_version_change_type.py` | `tests/test_design_api.py`、`tests/test_design_version_change_type_migration.py` | 38fdd507 |
| P1 | 已落地 | `src/cndb/core/textdiff.py`、`src/cndb/plugins/design/services/diff.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`src/cndb/plugins/documents/services/parse.py` | `tests/test_design_api.py`、`tests/test_documents_plugin.py`、`tests/test_cov_documents_extra.py` | 38fdd507 |
| P2 | 已落地 | `frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/api/design.ts`、`frontend/src/index.css`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py` | `frontend/src/pages/design/DesignEditorPage.test.tsx`、`frontend/tests/e2e/critical/design-version-history.spec.ts`、`tests/test_workspace_backup_v11.py`、`tests/test_workspace_backup_v13.py` | 38fdd507 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地（2026-11-06），等待人工验收与提交
- 已完成：`change_type` 模型 / 迁移 / 四类来源赋值与保存去重提升；`core/textdiff` 下沉 + `GET /diff` + 结构摘要；前端 3s 自动保存（单飞 / 静默失败）、类型徽标与连续 auto 折叠、任选两版对比；备份 `change_type` 往返与旧备份默认 `manual`
- 下一步：人工验收 e2e 与门禁全绿后提交（`make push`），确认是否将 Status 改为 `Implemented`
- 已知坑：自动保存与手动保存竞态靠「单飞 + `cancel()` + 服务端去重」三层兜底；`structure_summary` 依赖版本 `compiled.nodes`，v1 老快照会降级为 `available=false`；`unified_diff` 已从 `documents/services/parse.py` 删除，其他分支若有新调用需改从 `cndb.core.textdiff` 导入
- 最近一次全绿：`make flow`（6685 passed）/ `make cov`（95.29%）/ `make frontend-coverage`（核心 97.79%）@ 2026-11-06；e2e 待 CI 跑 `make e2e`

# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增
- 生产部署支持**内置反向代理（含实时协作 WebSocket）**：`docker-compose.prod.yml` 新增 `nginx` 服务（`--profile proxy` 可选启用），配置位于 `deploy/nginx/`（模板 + HTTP/HTTPS 共用片段，对 `/api/v1/ws` 单独放行 `Upgrade`/`Connection` 并设 3600s 读超时、访问日志不记 query 以免令牌落盘）；`deploy/deploy.sh` 支持 `CNDB_ENABLE_PROXY=1`（自动带 profile）并在部署末尾用**真实 WebSocket 握手**验证升级链路；`deploy/bootstrap-server.sh`、`.env.prod.example`、`docs/DEPLOY_TENCENT.md` 同步更新
- 新增**按段落编辑锁 + 段落级三方合并**：文档可以多人同时编辑**不同段落**（同段互斥）——`POST|GET|DELETE /documents/{id}/paragraph-locks` 按位置键（p1/p2…）加锁并实时广播 `para.lock`；保存时回传 `base_content`，服务端做段落级三方合并：互不重叠自动合并（含他人改动），同一段被两人修改则 409 明确指出第几段；不传 `base_content` 时保持原有乐观锁语义
- 新增**进程内缓存**（不依赖 Redis）：TTL + LRU + 统计 + 前缀失效（`core/cache.py`，并预留 Redis 后端接入点），接入工作区列表与数据表列表两个热点读接口 + 写路径主动失效，新增运维端点 `GET /api/v1/admin/cache/stats`、`POST /api/v1/admin/cache/clear`；实测同会话 A/B：数据表列表 p50 **16.1ms → 3.4ms（提速 79%）**、工作区列表 4.8ms → 2.2ms
- 新增**实时协作通道**：`GET /api/v1/ws?workspace_id=&token=`（浏览器 WS 无法设置请求头，令牌走查询参数）提供工作区级实时通道 —— 连接即同步**在线状态**（谁在看/谁在编辑，多标签页聚合）、`presence.update` 上报当前文档、心跳 ping/pong（静默超时自动清理半开连接）；A4 统一事件**实时推送**（`event.created`）并按动作自动失效前端缓存（列表/详情无需手动刷新）、编辑锁变化实时推送（`doc.lock`）；文档编辑页展示同文档在线成员与「他人已获取编辑锁」提示，顶栏显示连接状态；断线指数退避重连、回到前台立即重连
- 新增**统一事件/审计流**：跨插件的 `core_event` 表（actor/action/target/summary/detail/request_id）与 `GET /api/v1/admin/events`（超管或审计管理员可读，支持动作/操作人/目标/工作区/request_id/关键词/时间筛选与分页）、`GET /api/v1/admin/events/actions`（动作统计）；认证动作（登录成功/失败、登出、改密、会话下线、**刷新令牌复用检测**）、用户管理操作、表记录变更均已接入；事件自动携带 `request_id`，可与访问日志/慢查询日志串联；系统管理台新增「事件流」标签页（筛选写入 URL，可分享/刷新保持）；迁移 `b4d2e7a9c1f3`
- 新增**会话/授权生命周期**：登录同时返回访问令牌与刷新令牌（不透明随机串，库中只存 SHA-256）；`POST /auth/refresh` 一次性轮换（旧令牌复用视为泄露，吊销全部会话）、`POST /auth/logout`（单枚 / `all=true` 全部下线）、`POST /auth/password` 自助改密、`GET|DELETE /auth/sessions` 会话列表与按会话下线；`accounts_user.token_version` 让改密与强制下线后既有访问令牌**立即失效**；登录失败限流（账号 5 次 / 来源 IP 20 次 / 5 分钟）返回 429 + `Retry-After`；前端 401 自动刷新一次并重放原请求（并发去重），登出会调用服务端吊销接口；新增迁移 `a3f1c9d2e7b4`（`accounts_refreshtoken` + `token_version`）与配置项 `JWT_REFRESH_EXPIRE_DAYS` / `LOGIN_MAX_FAILURES` / `LOGIN_WINDOW_SECONDS`
- 新增**请求级可观测性**：每个响应回写 `X-Request-ID`（客户端可传、缺省生成），访问日志输出 `method/path/status/duration_ms/request_id/user_id`（超过 `SLOW_REQUEST_MS` 升 WARNING 并标 `slow=true`，健康检查与静态资源降为 DEBUG），既有慢查询日志也带上同一 `request_id` 便于串联；新增 `ACCESS_LOG_ENABLED` / `SLOW_REQUEST_MS` / `SLOW_QUERY_MS` 三个可配置项
- 文档总览新增**按标签筛选**：下拉选择标签（写入 URL `?tag=`，可分享/刷新保持），文件夹层级过滤在前后端同口径；按标签筛选时隐藏系列卡片（文件夹无标签）
- 文档编辑器工具栏补两处编辑能力：**Markdown 表格骨架**下拉（2×2 / 3×3 / 4×4 一键插入，带空单元格占位）与**标题层级**下拉（一级/二级/三级/四级标题、正文=取消标题），此前标题按钮只能固定切 H2
- 文档总览新增**「最近打开」**：打开文档时记录到本地（按工作区分键、去重、最多 8 条），根层展示可点直接回到该文档，支持一键清除；已删除条目自动过滤避免死链
- 文档总览补上**置顶标识**：置顶的系列卡片与列表项显示「置顶」标签（此前只在树里有图标）
- 文档总览支持**多选批量移动 / 删除**：当前层级逐项勾选（含「全选」），批量栏提供「移动到…」与「批量删除」；后端新增 `POST /documents/batch` 逐项校验（防环 / 目标必须是文件夹 / 已删除或跨工作区跳过），失败项在 `skipped` 中返回并在前端提示「已移动 N 项，跳过 M 项（原因）」
- 文档编辑器支持**直接粘贴图片**：剪贴板含图片时自动上传并插入 `![名称](file:<file_key>)`（普通文本粘贴不受影响）；一次粘贴多张按顺序串行上传，插入采用函数式更新不会互相覆盖
- 编辑器新增**状态栏**：实时显示「字数 · 行数 · 预计阅读时长」（按 300 字/分钟估算），随输入即时刷新
- 文档编辑器支持**插入图片**：上传到工作区文件存储（复用既有 `POST /workspaces/{wid}/files`），正文写入站内引用 `![名称](file:<file_key>)`；非图片文件被拒、上传失败不改动正文；桌面顶栏「图片」按钮与窄屏「更多」菜单同一入口
- Markdown 预览渲染站内图片：`file:` 引用经带鉴权的 axios 取 blob 后展示（`<img src>` 无法携带 Authorization 头），支持点击放大预览、加载占位与失败提示；外部图片 URL 原样渲染
- 文档总览支持**排序切换**（手动顺序 / 最近更新 / 创建时间 / 标题）：系列卡片与列表同步排序、置顶项恒在最前；排序口径写入 URL（`?order=`），可分享与刷新保持
- 文档总览的**当前文件夹**改为 URL 承载（`?parent=`）：支持深链直达、刷新与浏览器后退（此前只存在于组件内存状态）
- 文档编辑器顶部新增**路径面包屑**（文档 / 各级文件夹，可点回对应文件夹列表），层级较深时不再需要靠左侧树回忆位置
- 文档编辑器支持**查找与替换**：Ctrl/Cmd+F 打开（接管浏览器查找）、Ctrl/Cmd+H 同开，Esc 关闭；实时计数「第几处 / 共几处」、上一个 / 下一个（越界环绕，Enter / Shift+Enter 亦可）、区分大小写开关、替换当前并自动跳到下一处、全部替换（字面量替换，不解释 `$1`）；选中正文后按 Ctrl+F 自动带入查询词
- 文档支持**个人置顶**：树/列表/详情返回 `pinned`，置顶项始终排在同级最前（其余保持手动顺序）；置顶按用户隔离（A 置顶不影响 B 看到的顺序），随文档彻底删除自动清理
- 文档树节点新增「更多」按钮：桌面悬停显现、窄屏常显，与右键菜单同一套入口（此前触摸端完全无法触发右键菜单，新建/重命名/移动/删除/置顶在手机上均不可达）
- 文档编辑器新增 Markdown 快捷工具栏与快捷键：加粗 / 斜体 / 行内代码 / 二级标题 / 无序列表 / 有序列表 / 引用 / 代码块 / 链接，作用于当前选区（再次点击可取消包裹、行级语法幂等切换），并支持 Ctrl/Cmd+B · I · K；纯函数层 `components/Document/markdownEdit.ts` 与工具栏组件 `MarkdownToolbar` 解耦，窄屏工具栏可横滑
- 表格视图自动补「序号」列：置于选择列之后、字段列之前，按当前分页 offset 续号（第 2 页从 51 起），列宽随总行号位数自适应（1 位 52px / 3 位 55px，上限 88px）；非字段列不参与排序 / 筛选 / 列宽拖拽，新增行（草稿）显示「—」；窄屏固定复选框与序号列作为行标识（不再固定首个字段列，保证约 260px 横滑窗口）

- 统一错误契约：core/errors.py 定义 CndbError 族（400/403/404/409），全局 handler 映射为统一 `{"detail","code"}` 响应体，未捕获异常返回统一 500
- 健康检查拆分：`/api/health`（liveness，进程存活）与 `/api/health/ready`（readiness，DB ping + 迁移版本，DB 不可达返回 503）
- 慢查询日志：SQLAlchemy 引擎级监听，超过 0.5s 的 SQL 记 warning
- 外部导入源（api_fetch）：幂等 GET 有限重试 + 指数退避
- 导入任务幂等守卫：analyze/execute 重复派发静默忽略，不崩后台线程
- 启动迁移失败给出可操作指引（备份恢复/重建），不再裸 traceback
- 示例文档种子：`examples/datasets/<工作区>/documents/` 目录树（5 个工作区共 32 篇典型文档，含 `[[标题]]` 双向链接与 `{{table:表名|view=视图名|limit=N}}` 数据表动态引用），`cndb seed` 按目录树注入文件夹 / 文档并解析为真实表 / 视图 ID
- 文档回收站：`GET /{wid}/documents/trash`（按删除时间倒序）、`POST /{wid}/documents/{doc_id}/restore`、`DELETE /{wid}/documents/{doc_id}/purge`；文件夹级联删除整棵子树共用同一删除批次，恢复时精确还原同批次子项、不连带复活先前单独删除的节点，彻底删除一并清理版本 / 标签关联 / 分享 / 权限 / FTS 索引与外存内容
- 文档出链解析 `GET /{wid}/documents/{doc_id}/links`：返回正文 `[[标题]]` 命中文档 ID 与断链清单（代码围栏内不计入）
- 文档断链修复 `POST /{wid}/documents/{doc_id}/links/repair`：把正文 `[[旧标题]]` 改指为指定现存文档（生成新版本可回溯；全部条目未命中返回 409）
- 文档前端：文档页新增回收站抽屉（软删除列表 / 恢复 / 彻底删除），编辑器新增出链抽屉（已解析与断链分栏，按目标文档修复断链）
- CLI 新增 `cndb docs gc`：文档外存孤儿文件体检与物理回收（默认 dry-run，`--apply` 实际删除，`--json` 输出报告；软删除文档的外存内容视为有效引用不回收）
- 文档导出：`GET /{wid}/documents/{doc_id}/export?format=md|docx|pdf` 把文档最新正文导出为 Markdown / Word / PDF 文件（工作区成员可用；文件夹与非法格式返回 400），编辑器顶栏新增「导出」下拉入口；DOCX/PDF 渲染器迁至 `documents/services/export/`，PDF 保留中文字体自动发现与页眉页脚
- 文档修改申请（双轨制写入）：viewer（或关闭直编的 editor）保存正文不再 403，而是由 `PUT /{wid}/documents/{doc_id}/content` 返回 202 + 申请载荷，待审正文只存 `documents_changerequest.proposed_content` 不写版本表；新增 `/{wid}/document-change-requests` 的列表 / 详情（含基准→待审正文 DIFF）/ merge（落库为新版本）/ close / update-base / 删除草稿端点，申请记录 `base_version_number` 基准，文档版本前进后其余 open 申请自动置 stale
- 文档彻底删除时一并清理该文档的待审修改申请，避免孤儿数据
- 差异对比可视化：新增 `components/DiffView`（unified diff 解析 / 增删配对 / token 级行内高亮 / 并排模型 + 纯函数单测），文档版本对比支持统一·并排双视图与增减统计，数据表变更项改为「字段 / 修改前 / 修改后（基准漂移时含当前值）」表格；样式全部由 `color-mix + var(--cn-*)` 组合，各主题自动适配
- 文档区二级导航：进入 `/w/:wid/documents*` 时在工作区 Tabs 右侧以竖线分割渲染「文档」根入口 + 二级页签（修改申请 / 问题清单），形式与表级页签一致；新增 `/w/:wid/documents/change-requests`（工作区级文档修改申请清单，支持状态筛选与内容 DIFF 审核）与 `/w/:wid/documents/issues`（文档问题清单）两个页面
- 文档问题清单：新增 `documents_issue` / `documents_issuecomment` / `documents_issueevent` 三张表（迁移 `e4f5a6b7c8d9`）与 `/{wid}/document-issues` 端点（列表 / 提交 / 详情 / 评论 / 关闭 / 重开），类别与状态取值同数据表问题清单；文档彻底删除时问题、评论与事件流水一并清理

### 移除

- reports 插件（报表模板 + Jinja2 渲染）：模型 / 路由 / 渲染器 / 前端页面与编辑器 / seed 示例模板整体移除，`reports_template` 表由新增迁移 `c2d3e4f5a6b7` 删除（历史迁移保留，downgrade 可重建空表）；工作区列表 `report_count` 字段与前端报表页签同步下线
- 依赖 `jinja2` 移除（仅报表模板使用）

- wechat_auth 插件（微信小程序登录）：路由/模型/客户端/配置项/依赖 `requests` 及配套测试整体移除；历史迁移保留，存量库中的 wechat_accounts 孤儿表不影响升级
- 前端死代码：未使用的 `userApi` 封装、`USER_ROLE_LABEL` 常量与 hooks barrel 重导出（ruff/knip/eslint 证据驱动）
- 死配置：Sphinx 文档骨架（`docs/*.rst`、`docs/conf.py`、`docs/_static/`）、`.readthedocs.yaml`、`tox.ini`（0.1.12 已声明删除但文件残留；tox 引用的 `docs` extra 早已不存在）；`.gitignore` 中失效的 `.tox/` 与重复的 `.mypy_cache/`
- 空目录：`src/cndb/plugins/{forms,workflows}`（源码已随表单/审批流插件移除，仅剩 `__pycache__`）
- 前端未使用生产依赖：zod、@tanstack/react-table、react-hotkeys-hook、zundo、immer（全仓库零引用）
- 与主测试重复的补覆盖率用例 12 个、零引用 fixture 2 个、只有 `pass` 的空壳测试 1 个（test_coverage_patch / test_cov_routers_records / test_edge_patch / test_cov_quick / test_tables_coverage / test_roles_e2e）
- 前端死导出：`LoginResponse`、`WorkspaceTrashResponse`、`getTagColor`（自称兼容旧 API，生产已全用 `getTagColorName`）、`ANTD_COLOR_NAMES`（仅被自身测试断言长度/内容）
- 前端第二套设置持久化：`theme/tableSettings.loadTableSettings` / `saveTableSettings` —— 与 `store/tableSettings` 的 zustand persist **共用同一个 localStorage key `cndb_table_settings`**，存在互相覆盖隐患；持久化职责收敛到 store，本模块只留类型/默认值/`densityToSize`
- 重复类型定义：`ViewMode`（`store/gridView.ts` 的副本）与 `WorkspaceRole`（issues/changeRequests 详情页各一份副本）
- 死条件：`GridCell` 的 `isReadonlyField` 中 `|| Boolean(field.is_primary && field.field_type === 'auto_id')` 被前一项 `readonly.has(field.field_type)` 完全覆盖（auto_id 本就在该集合内）
- 前端 `Field.is_primary` 与 6 个伪系统字段类型（`auto_id` / `formula` / `created_time` / `updated_time` / `created_by` / `updated_by`）的**全部恒假分支**（19 文件 +51/-100）。经确认无存量库使用后删除：后端 registry 的 19 种类型里没有这 6 个，`FieldResponse` 无 `is_primary`，且 `normalize_field_type` 对未知类型原样放行 —— 这些分支只可能来自存量库。一并删除只为其服务的 `includePrimary` schema 选项。**保留** `long_text`/`decimal`/`multi_select`（后端真实别名）与 `json`（真实类型），以及 `created_by`/`updated_by` 作为记录元数据的用法

### 变更
- 文档导出 Markdown 时，若正文含**可解析的站内图片**则改为打包 zip：`<标题>.md`（引用改写为 `assets/<file_key>`）+ `assets/` 图片文件；无图片仍为单文件 .md（行为不变），解析不到的引用原样保留不丢信息；前端按响应类型自适应 `.zip` / `.md` 文件名
- 文档导出 Word / PDF 时**嵌入站内图片**：`![alt](file:<file_key>)` 会被替换为真实图片（按正文可用宽度等比缩放），引用缺失或图片格式不支持时降级为「[图片缺失/无法嵌入：alt]」占位，不再静默丢图；Markdown 导出保留应用内引用（单文件无法内嵌二进制）

- 拆分超大文件（全部保持既有导入路径与导出面，行为不变）：
  - `cli/seed.py` 2703 行 → `cli/seed/` 包 11 个模块（sqlite/paths/datasets/fields/documents/views/templates/samples/permission_demo/runner），`__init__` re-export 历史符号
  - `plugins/reports/routers/reports.py` 1510 行 → 路由 495 行 + `renderers/{context,docx,pdf,pdf_fonts,xlsx,html,markdown}` + `services/stats` + `jinja`
  - 前端 `ReportsPage.tsx` 1047 → 267 行 + `TemplateEditorModal`/`RenderParamsModal`/`reportsConstants`
  - 前端 `GridCell.tsx` 839 → 188 行 + `EditCell`/`DisplayCell`/`cellValueUtils`（保留 4 个历史具名导出）
  - 前端 `GanttView.tsx` 1301 → 655 行 + `views/gantt/` 六个模块
  - 前端 `api/types.ts` 968 行 / 120 个导出 → `api/types/` 12 个按资源域拆分的模块 + `index.ts` 聚合；`api/index.ts` 原先手写列举的 90 个类型名改为 `export type * from './types'`
  - 前端 `ImportPanel.tsx` 958 → 615 行 + `ImportQualityPanel` / `ImportDiffTable` / `MiniStat`
  - 前端 `DocumentsPage.tsx` 792 → 553 行 + `SearchDrawer` / `TrashDrawer`（两者改为自持查询与状态，页面不再摊平 5 处 state 与 3 个 query/mutation）+ `seriesStats` / `documentDisplay`
  - 前端 `CalendarView.tsx` 770 → 205 行 + `calendar/{YearView,MonthView,WeekView,calendarUtils,calendarTypes}`
  - 后端 `workspaces/routers/workspaces.py` 1041 → 505 行 + `routers/member_routes.py`（成员/转让子路由）+ `services/backup_io.py`（备份落库）+ `routers/deps.py`（共享受保护依赖）
  - 后端 `tables/services/fields/field_ops.py` 1027 → 53 行 + `field_import.py`(502) / `select_options.py`(508)；field_ops 保留为兼容外观，使 7 处 `monkeypatch.setattr(field_ops, ...)` 继续生效
  - 前端 `KanbanView.tsx` 789 → 132 行 + `kanban/{KanbanCard,KanbanColumn,kanbanDensity,kanbanVisuals}`
  - 前端 `FileImportPreview.tsx` 774 → 609 行 + `importPreviewConvert.ts`（4 个纯转换函数）与 `useTableFlexFillStyle.ts`
  - 后端 `tables/routers/bulk.py` 752 → 35 行（聚合）+ `bulk_crud.py` / `bulk_export.py` / `bulk_import.py`；前缀与 tags 留在聚合 router 上，11 条路径逐条不变
  - 后端 `tables/services/transfer/normalize.py` 758 行 → `normalize/` 包（values 单值推断 / promote 列级提升 / coerce 精度与类型映射 + 转发全部 60 个符号）
  - 后端 `cli/users.py` 739 行 → `cli/users/` 包（io / db / commands / printing）；`users_command` 与 `register_users_subparser` 必须留在包 `__init__`，否则 10 处 `monkeypatch.setattr("cndb.cli.users.<cmd>")` 会静默失效
  - 后端 `cli/restore.py` 727 行 → `cli/restore/` 包（types / inspect / apply）
  - 前端 `theme.ts` 695 → 108 行 + `theme/meta.ts`、`theme/fonts.ts`、`theme/presets/{light,dark,common}.ts`；`THEMES` 仍写显式字面量以保证键序与 `THEME_MODES` 一致
  - 前端 `DocumentEditorPage.tsx` 802 → 640 行 + `DiffView` / `TagEditor` / `OutlineDrawer` / `BacklinksDrawer`
  - 前端 `DocumentEditorPage.tsx` 640 → 498 行 + `LinksDrawer` / `VersionsDrawer` / `InsertTableModal`（query 结果解包为 props）
  - 前端 `WorkspaceSettingsContent.tsx` 679 → 525 行 + `settings/{workspaceRoles,MemberZones,AddMemberModal,TransferOwnerModal}`
  - 前端 `TemplateEditorModal.tsx` 630 → 474 行 + `reports/useTemplateEditorData.ts`（7 个 query + 跨工作区扫描 effect + 9 个派生 memo 抽成 hook，JSX 原样保留）
  - 前端 `FileImportPreview.tsx` 609 → 357 行 + `FieldsList` / `SelectedFieldEditor` / `DataPreviewTable` 三个渲染闭包组件 + 共享的 `importPreviewTypes` / `importPreviewOptions`
  - 前端 `ViewConfigDialog.tsx` 523 → 214 行 + `viewTabItems.tsx`（四个 Tab 构造器）+ `ViewOptionItem.tsx`
- 重复实现收敛：
  - 后端 CSV 编码探测统一走 `transfer.decode_bytes_auto`（`cli/users._read_csv` 与 `import_tasks._parse_to_rows` 不再各写一套；后者原为硬编码 utf-8，GBK CSV 会 UnicodeDecodeError）
  - 前端新增 `utils/paletteColor`（GanttView 与 CalendarView 逐字相同的色板 + hash，WbsView 同一公式）、`utils/datetime`（issues/changeRequests 4 页各自的 formatTime）、`utils/formatSize`（文档页与管理面板）
- 覆盖率口径统一：Makefile `cov` 由裸 `--cov`（把 tests/ 自身计入分母，本地虚高到 97.9%）改为 `--cov=$(PACKAGE)`，与 CI 同口径（真实 95.4%），本地绿灯不再与 CI 脱节
- 配置一致性：`pyproject` 固定 `ruff==0.16.8`（与 `.pre-commit-config.yaml` 的 rev 真正对齐，注释不再失实）；`ci.yml` 用 YAML 锚点消除 push/pull_request 两份逐项相同的 paths；`Makefile .PHONY` 补齐 `gitkeep-check` 与全部短别名并去重
- 部署链路改为服务器端构建：CI 不再构建镜像、不再经 COS 中转，改为同步 wheel/锁定依赖/Dockerfile 到服务器后由 `deploy.sh`（SERVER_BUILD=1）本地 `docker build` 并部署；Dockerfile.prod 基础镜像与 pip 源支持 `--build-arg` 换源，手动回滚仍走 TCR pull
- `get_db` 请求路径异常时显式 rollback，避免半提交状态污染连接池
- 文档列表 / 文档树改为批量序列化：版本数与标签各用一次聚合查询，大文档树不再逐节点 N+1
- 反向链接扫描改为单条 SQL 取各文档最新版本，替换逐文档查询
- README 修正项目结构树、CLI 命令、e2e 包管理器与特性清单等失实内容

### 修复
- 修复**导入 WPS 导出的带图 XLSX 时进度卡在 5%、且无任何报错**：WPS 会把「仅样式」的整行/整列写进文件，把工作表声明范围撑到 1048576 行（实际几十行），旧解析实现（非只读 + 全量 `iter_rows`）会物化百万空行 → 内存暴涨/等同卡死，线程里没有异常所以前端看不到报错。现改为**有界流式读取**（`read_only` + `reset_dimensions` + 行/列上限，超限给可读错误），导入/建表/预览三条解析路径统一；并给导入任务加**阶段超时看门狗**（默认 600s，超时即判失败并提示「另存为干净副本后重试」），不再出现无声卡住
- 修复内置 nginx 反代的 `client_max_body_size` 用了 envsubst 变量却位于非模板文件（会导致 nginx 启动失败），改为常量并在注释中说明原因
- 段落锁**跟随内容重排**：保存时按内容把锁映射到新位置（中间插入/删除段落不再让锁漂移），被改写的段落释放其锁；他人锁定的段落提供「跳转到第 N 段」按钮
- 缓存扩展到 **文档树**（10s，写请求统一失效）与**记录列表**（5s，按 `record.*` 事件失效）：实测 p50 6.3ms → 3.6ms（-43%）与 7.9ms → 4.1ms（-48%），记录列表 p95 22.6ms → 4.9ms（-78%）
- 修复**未认证请求返回 500**：`get_current_user` 在 AUTH_ENABLED=True 时，「缺少认证头 / 认证头格式非法 / 令牌为空」原先返回 None，端点解引用 `current_user.id` 便抛 `AttributeError` → 现在统一返回 **401**（带 `WWW-Authenticate: Bearer`），前端既有的 401 登出逻辑可正常生效；`AUTH_ENABLED=False` 仍返回 None，匿名可用路由继续使用 `get_optional_user`
- 修复**中文全文检索命中为 0**：FTS5 的 `unicode61` 分词把连续中文当作单个 token，搜索「销售」「管理」「文档」这类常用词片段此前无结果 → 现在 FTS 无命中时自动追加**子串兜底通道**（title/summary/content 的大小写不敏感 LIKE，多词 AND、标题命中优先），只增不减、不改变既有命中；`_` 等 LIKE 通配符按字面转义

- 源字段类型变更后其他表引用它的 lookup 字段未同步类型：改为同步刷新 `config.source_field_type` 并在新类型占用物理列时清除 `broken`（源字段被删除或改为 link/lookup 时才失效），字段管理列表展示「引用 · 源类型」
- Windows 下附件上传恒返回「非法的文件标识符」：路径越界校验由字符串前缀比较改为 `Path.is_relative_to`，兼容反斜杠分隔符
- 外存（>2MB）文档多版本内容串档：历史版本读取改为按 `data/docs/{doc_id}/v{版本号}.md.gz` 定位，不再依赖只指向最新版本的 `Document.content_path`（此前 v1 会读到 v2 内容）
- 文档检索对非法 FTS5 输入不再 500：裸 `AND`/`OR`/`NOT`、裸 `*`、未闭合引号、含 `-`/`:` 的裸词统一按字面词加引号检索，解析层漏网时兜底转 400
- 文档外存文件缺失或损坏、内联 gzip+base64 内容损坏时降级为空内容并记 warning，详情 / 版本 / diff / 检索 / 分享读路径不再 500
- 软删除文档或文件夹后标签 `doc_count` 未刷新（已删文档仍被计数）；删除递归增加环保护，历史脏数据成环不再无限递归
- 文档并发保存触发的版本号唯一约束冲突返回 409 `doc_version_conflict`，不再裸穿 500
- 彻底删除回收站文档的响应字段命名冲突修正：布尔 `purged` 与数量键重名导致数量覆盖布尔值，数量改为 `purged_count`
- 手机端数据表视图切换困难：视图切换栏在窄屏下把所有控件（7 个模式按钮 + 搜索框 + 4 个操作按钮）挤在同一行，视图页签被压缩到几乎不可用。移动端改为「视图页签占满剩余宽度（可横滑）+ 模式 / 筛选 / 更多」三控件布局——模式切换收进带文字标签的下拉（表格 / 看板 / 日历 / 甘特图 / WBS / 矩阵 / 图表），新建 / 编辑 / 删除 / 导入 / 导出 / 表格设置收进「更多」菜单，搜索折叠为可展开的第二行（搜索词非空时常显）；桌面端布局不变
- 手机端宽表格排版崩坏：管理台用户表 8 列在窄屏被压缩到「昵称」逐字竖排、「邮箱」裁切在卡片外，工作区成员表用户名/邮箱被挤成多行。统一改为窄屏不压缩列宽、容器横向滚动（`scroll={{ x: 'max-content' }}`），成员表用户列固定 220px；管理台筛选控件窄屏整行排布
- 手机端管理台用户管理由 8 列表格改为卡片列表：用户名（昵称）/ 邮箱 / 电话 / 角色标签 / 状态 / 编辑·日志一屏一实体、无需左右滑动；勾选框保留以支持批量启用·禁用·改角色，分页信息保留；桌面端仍为可横滑表格
- 手机端表权限编辑：成员表窄屏保留列宽改横向滚动（用户列 220px），「隐藏字段」网格由三列改单列（三列在 390px 下每列约 110px，字段名被截断）
- 手机端导入预览：4 个页签（含计数，行宽 396px > 可视 342px）切换后把激活页签自动滚入视口，报告到达 / 参考列变化时重新校准（复用顶部导航的 tabScroll 逻辑）
- 手机端管理台「系统信息 / 系统备份」的描述列表由两列改单列、标签置于值上方（原先 390px 下标签列仅约 40px，「应用名称」被压成一字一行、数据库路径被挤成多行），桌面端保持两列
- 手机端数据表网格无法横滑：虚拟滚动表格的横向滚动由 rc-virtual-list 自绘细滚动条驱动（`.ant-table-tbody-virtual-holder` 的 `overflow` 为 hidden），触摸设备既不能原生横滑、也几乎点不中滚动条 → 窄屏关闭虚拟滚动改用原生滚动容器（实测 `.ant-table-body` 可滚动，页大小受分页约束故性能可接受）
- 手机端网格横滑时丢失行标识：窄屏固定选择列与首个数据列（`fixed: 'left'`），横滑时复选框与主字段常驻左侧并可读；桌面端不受影响
- 手机端导航层级感偏弱：工作区页签与二级页签（表级 / 文档级）同处一条横滑行，横滑后竖线分割移出视口后无法分辨层级 → 窄屏给二级段加浅底圆角容器并隐藏竖线（桌面保持原有 GitHub 风格分割）
- 手机端文档编辑页悬浮「文档树」按钮遮挡正文末行：内容区底部留出 72px（实测内容底 592 / 按钮顶 608，间隙 16px）
- 手机端数据表列表由 4 列表格改为卡片列表：一屏一表（表名 + 访问标签 / 记录·字段·成员 / 更新时间 / 打开·更多），操作菜单与表格共用同一套入口（重命名·复制表·删除表）并改为 click 触发（触摸设备无 hover）；拖拽排序仅在桌面端提供（触摸端拖拽手势不可靠），桌面端表格保持原样
- 手机端数据表设置页左侧竖排页签吃掉内容宽度、统计条第 4 项「创建日期」被裁切：窄屏页签改为顶部横排，`.ts-stats` 允许换行
- 手机端弹窗/抽屉适配：个人设置「用户资料」三字段并排时每格仅约 110px 导致昵称/邮箱被截断 → 窄屏纵向堆叠；表格设置「间距 / 每页行数」允许换行；帮助中心窄屏主题导航由左侧 150px 竖排菜单改为顶部横向可滚动胶囊，底部提示与重播按钮纵向排列
- 手机端甘特图不可用：工具栏 4 个区块合计约 570px 挤在一行，标题与「共 N 个任务」被压成竖排文字；左列固定 250px 使时间轴只剩约 90px。窄屏下工具栏换行、标题/统计 nowrap，左列收窄到 140px，时间轴宽度翻倍到约 218px
- 手机端数据表工具栏标题被压成「产…」：窄屏隐藏记录数徽标（底部「共 N 条」已给出）、把表设置 / 更新导出 / 数据治理 / 编辑行收进「更多」菜单（菜单改为 click 触发，兼容触摸设备），标题恢复完整展示
- 手机端数据表列表筛选分段控件把「我可编辑的」截断成「我可编…」：窄屏改用短文案（我拥有 / 可编辑 / 可读）
- 手机端顶部导航工作区页签被挤成 0 宽：同排的二级页签（表名 + 修改申请/问题清单/数据表设置）宽约 448px 且不收缩，把可收缩的工作区页签（数据表 / 文档 / 工作区设置）压到不可见。窄屏改为页签保持内容宽度 + 整行横滑，并在路由/计数徽标变化后把**当前子页的激活页签**自动滚入视口（桌面端布局不变）
- 手机端文档编辑器工具栏 9 个按钮折成三行挤掉正文：窄屏只保留「大纲」+「保存」，其余（反向链接 / 文档链接 / 插入表格引用 / 标签 / 修改申请 / 版本 / 导出）收进「更多」菜单（导出为二级子菜单）
- 手机端文档编辑器左右分栏在 390px 屏上每侧仅约 190px（正文一行只放得下几个字）：窄屏改为「编辑 / 预览」分段控件二选一、面板独占整宽（实测编辑区 390×428、预览区 358px 宽），桌面端保持左右分屏；窄屏点击大纲锚点会自动切到预览面板再定位

## [0.2.7] — 2026-10-01

### 新增

- 环境检查端口结果状态着色

## [0.2.6] — 2026-09-30

### 新增

- Windows 开机自启后台服务
- GUI 环境检查区新增端口占用终止按钮与端口占用兜底强杀逻辑
- 导出数据按时间命名；看板视图当天任务置顶、按严重程度区分

### 修复

- 表选项变更后同步存量数据；xlsx 导出兼容 openpyxl 不接受的复杂类型
- GUI 端口占用终止对死 PID 谎报成功、残留 PID 误报失败与停止服务不彻底问题；进程判活与进程名查询改用 Win32 API，移除 tasklist 依赖

### 变更

- 清理既有 lint/格式化债务；新手友好语言表述优化

## [0.2.5] — 2026-09-29

### 新增

- CLI 服务默认绑定 0.0.0.0，允许局域网访问
- 丰富日常待达示例数据与关联/引用字段回填

### 修复

- 启动时新增 schema 自愈机制，修复报表模板缺列报错
- 导出文档表格首行渲染问题；看板负责人与额外字段空值渲染占位标签

## [0.2.4] — 2026-09-28

### 新增

- **矩阵视图**：支持纵横两轴分类交叉，轴区双色淡染、分轴分界线与单元格高度自适应
- 备份文件名标注软件版本与数据库格式版本
- 报表按工作区过滤，工作区 tab 数量徽标
- 个人设置：右上角显示昵称、用户资料紧凑化、新增字体设置与主题恢复默认、用户默认主题样式配置
- 工作区级导航移入 Content 分页导航；表格骨架屏列数对齐最近已加载表可见字段数，优化表与页面切换加载态及过渡动画

### 变更

- 性能优化：Gzip 压缩、SQLite 缓存、反射缓存；seed 数据库写入耗时 16.1s → 5.1s

### 修复

- 主行与 link 字段写入合并为同一事务，修复 SQLite 隐式 ROLLBACK 导致的数据丢失
- Segmented 激活项改为主题色滑块加反色文字；隐藏字段勾选项三列网格对齐

### 移除

- 个人设置表格边框/表头/斑马纹装饰性配置（显示模式收编进表格页签）

## [0.2.3] — 2026-09-26

### 新增

- **引用（lookup）字段类型**：支持 link 模式跨表字段关联、过滤排序、嵌套分组（or/and）条件过滤与前端引入模式选择
- link 字段必填/唯一保存前预检与写入路径校验，lookup 字段约束明确拒绝
- 工作区导出导入升级至 v4，支持跨表引用重映射
- 报表：新增 HTML 输出格式、主题风格设置与 DOCX/PDF 渲染主题应用、模板编辑弹窗页签布局与校验失败自动跳转、员工名册参数下拉选择、多组示例报告模板与数据集
- 表格：列宽自适应拖拽调宽、列序拖拽调整、列宽双击重置与重置列布局菜单、表头字段类型图标
- 字段配置统一面板，聚合基础属性、默认值与类型专属配置
- 个人设置支持编辑昵称与邮箱；关联字段下拉选项使用目标表主字段值
- seed 新增 fields.json 字段设置种子（唯一/必填/关联/引用示例）

### 变更

- 表头关联/引用字段名移除下划线标识，仅保留图标
- CI 流水线并行与缓存优化，新增 CodeUp CI/CD 流水线；项目名称表述更新为通用数据管理平台

### 修复

- 报表跨工作区额外表字段与预览请求错误工作区、模板参数长内容截断、预览过滤统计显示为 0
- 物理列与 link 字段互转后行编辑 500；引入 lookup 后编辑行 500
- 备份 v4 字段 id 映射时机与关联回取值错误；备份导出导入数据行全部丢失与日期字段归一
- 工作区导入与自动默认视图「全部」重名冲突；表头多次点击无法取消排序
- 时间戳转换受运行时区影响；SQLite 数据库锁错误

### 安全

- 脱敏示例数据邮箱，消除密钥/通用密码字面量扫描误报并补充黑名单说明

## [0.2.2] — 2026-09-23

### 新增

- 字段自动预填锁定配置（表级开关）
- 看板视图截止日期徽章样式与显示逻辑优化

## [0.2.1] — 2026-09-23

### 新增

- **看板完成标志**：支持日期类型字段双向切换、判定操作符与无值操作符（统一视图判定模型），卡片完成态绿底灰字、完成勾选框与庆祝动画
- 备份恢复向前兼容：旧备份恢复时自动迁移 schema；native 备份内嵌 SQLAlchemy 兜底导出；GUI 恢复端新增恢复模式选择与降级报告呈现
- 导入推断层新增 Unix 时间戳与长文本识别；CSV/XLSX 结构守卫，空列名/重复列名明确报错
- 报表模板字段插入语法统一并完善预览对齐
- 项目 Logo

### 变更

- 后端拆分重构：field_types 按类型族拆分子模块、transfer.py 拆分为 services/transfer 子包（聚合导出 API 不变）、tables 插件服务归位 services/{core,fields,importing}、辅助脚本归位 cndb.cli 包
- 前端拆分重构：GridPage 按工具栏/视图栏/表格主体等域拆分、FieldManager 与 ImportExportDialog 目录化
- 前端性能与构建体积控制优化

### 修复

- 并发注册竞态导致的 500 错误并优化错误提示
- 深色主题白色元素与导出界面背景；看板新增项日期自动填充
- 旧浏览器兼容：Array.prototype.at polyfill、dayjs 导入方式调整

### 安全

- CSV/XLSX 导出增加公式注入防护

### 移除

- 画廊视图相关代码与测试
- 用户级视图偏好，改用默认视图作为落地基准

## [0.2.0] — 2026-09-20

### 新增

- 交互式新手引导与应用内帮助中心，全站升级功能 Tooltip 并在表单对话框内嵌新手说明
- 字段默认值：单行文本支持自动编号默认值，字段行展示必填/唯一备注；字段自动填充与默认值设置 UI 优化

### 修复

- 编辑字段保存前预检必填/唯一数据冲突
- text 字段 config 隐藏注册槽，修复编辑自动编号字段时模式 Radio 无法激活
- Header 报表/工作区设置按钮显式绑定当前工作区，无上下文时禁用
- Windows CI 控制台 cp1252 无法编码盒子绘制字符导致 info 命令崩溃

### 移除

- 完整界面按钮及冗余代码

## [0.1.14] — 2026-09-19

### 新增

- 完善视图导出功能
- 全项目字段类型标签统一为中文类别标签与统一配色

### 变更

- 表设置 Modal 改左侧竖向导航紧凑布局，字段列表改类型图标行卡片并统一主题变量
- PyPI 镜像更换为华为云

### 修复

- 导入预览样本值按首次出现顺序去重，避免重复值挤占样本位
- 字段选项颜色与编辑字段不同步及智能推荐撞色；表设置 initialTab=permissions 不加载数据与 row_filters 误清空

### 移除

- 回收站功能代码与测试

## [0.1.13] — 2026-09-19

### 新增

- Select 字段配色优化；选项列表标签与智能推荐优化

### 变更

- fspack 依赖升级至 0.6.6

### 移除

- 分享视图与表设置入口

## [0.1.12] — 2026-09-19

### 新增

- 导入 DIFF 展示字段级新旧对比与变更汇总，无更新行区分空态提示；导入参考列智能推荐与 DIFF 归一化识别
- multiselect 列表识别接入 JSON/XLSX 导入路径，支持负百分比落库
- 新增行交互：自动聚焦与自动滚动（E2E 回归覆盖）；新增 useDebouncedValue/useDebouncedCallback/useElementSize 通用 hooks
- GUI 日志文本组件支持复制与全选

### 变更

- httpx 从运行时依赖移至 test extra（源码仅使用 httpx2）；显式声明 requests 运行时依赖（wechat_auth 插件实际使用）
- ruff/pyrefly 配置收敛：移除不存在目录的排除项，修正 UP045 注释表述
- 表格视图切换性能优化；导入导出界面交互优化

### 修复

- xlsx 日期单元格被误推断为 select；导入日期序列化崩溃
- 身份证号预览精度丢失；新增行位置分页；工作区创建后跳转逻辑
- docker-compose.yml 源码部署构建上下文 `context: ..` → `context: .`（compose 文件位于仓库根目录）
- README 失实内容：npm → pnpm、`make bench` 改为脚本调用、移除不存在的 `.env.example` 指引、项目结构树对齐实际目录

### 移除

- 空壳包 `cndb.services` / `cndb.schemas`（模板脚手架遗留，无任何引用）
- Sphinx 文档骨架 `docs/` 与 `.readthedocs.yaml`、pyproject `docs` extra（文档入口以 FastAPI `/docs` 为准）
- `tox.ini` 与 Makefile `tox` / `doc` / `check-fast-par` 死目标（门禁统一由 `make check` 承载）

## [0.1.11] — 2026-09-19

### 新增

- Grid 行内编辑模式，替换原有新增弹窗；新增行改为新建行表单收集必填字段
- 数据实时转换预览与异常视觉标记；文件导入预览优化
- Excel 导入自动识别字段生成
- GUI：持久化与界面布局优化、归档文件备份管理、备份进度与结果反馈、系统信息界面刷新、服务启动端口与文件监控

### 变更

- 前端三层测试体系落地：vitest 283 用例接入 make check 门禁
- E2E 提速：信号化等待替换固定 sleep

### 修复

- Select 字段选项串扰与配色；seed 流程 alembic 版本标记缺失导致启动报错
- 抑制 Windows ProactorEventLoop 连接重置噪音，净化 e2e 与生产日志

### 移除

- 字段评论发表功能
- GUI 用户管理 Tab，用户管理仅保留 CLI 方式

## [0.1.10] — 2026-09-18

### 修复

- 打包环境下 GUI 服务启动路径查找与报错提示
- Windows 下启动服务弹出黑窗与进程启动失败问题
- 多场景交互与错误处理问题

## [0.1.9] — 2026-09-18

### 新增

- **报表功能增强**：多表引用 + DOCX/PDF/XLSX 富文本输出 + 前端编辑器增强（拖拽、固定区域滚动、布局优化）
- **桌面管理台（GUI）**：cndbw GUI 设计与 fspack 打包配置、`~/.cndb` 目录结构、桌面管理台功能完善
- 简化注册流程并新增 Admin CLI
- CSV 建表改造为导入数据表；导入预览支持重新 DIFF 与字段级对比视图
- 字段选项自动识别与 E2E；字段引入支持跨表映射预览与智能建议
- 自动数据库迁移机制与多版本迁移脚本

### 变更

- `__init__.py` 业务逻辑迁移到子模块并同步 alembic 双目录；目录路径与运行环境检测逻辑重构
- 构建方式改为 pyc 优化并禁用 site 包（fspack）；fastapi 版本范围限制以兼容 Win7

### 修复

- 导入后 select 字段选项丢失与无法编辑
- cndbw 脚本入口模块路径错误

## [0.1.8] — 2026-09-16

### 新增

- 导入器可配置字段映射与空隙填充选项；导入 upsert 增强（参考列匹配 + 未知列策略 + 分 Tab 预览）
- fspack 打包 CI/CD
- 甘特图时间刻度缩放

### 变更

- 批量操作权限检查逻辑简化；health 相关代码清理
- 补充边界测试，覆盖率提升至 95%

### 修复

- 数据表分页跳转异常，增强后端排序/过滤参数容错

## [0.1.7] — 2026-09-15

### 变更

- Python 版本锁定 3.12，移除过时的 Python 3.13/3.14 版本分类
- Makefile bump/push 命令简化与 pypi 上传匹配规则优化

### 修复

- 成员表选择用户下拉显示数字问题
- tables router 复制表接口类型提示与异常代码格式

## [0.1.6] — 2026-09-15

### 新增

- WBS 视图与甘特图显示优化；甘特图日期标签修复
- 字段引入（数据表引入字段设计与前端 UI）
- 工作区权限 Tab，修复数据表权限成员可见性
- 角色权限系统（E2E）

### 变更

- Windows 7 兼容：认证依赖版本调整，Python 版本支持降级到 3.12 并更新依赖约束
- fspack 打包配置接入并修复 fsp b 打包无法运行问题；Makefile 依赖安装与清理脚本重构

### 修复

- SQLAlchemy 遗留 API 警告与 pytest 配置；make check 乱码问题
- release workflow 中 pnpm 安装失败

## [0.1.5] — 2026-09-15

### 变更

- 强制 make check 门禁流程

### 修复

- 甘特图视角切换问题

### 新增

- 报表生成开发计划与测试基建；测试覆盖率最大化提升

## [0.1.4] — 2026-09-14

### 新增

- 三员用户账户注册功能
- 主题切换：3 套主题与 E2E
- 工作区详情与成员管理；备份恢复功能
- API 股票建表功能（API 数据自动建表与抓取）
- 表设置弹窗重构：embedded 模式与字段管理器；复制表功能 UI 刷新与 E2E

### 变更

- 视图组件拆分重构，统一 view_options 真相源
- 前端入口设计与 E2E 完善；ESLint 规则调整

### 修复

- 深色模式日历配色、深色视图白色背景、主题卡片与设置问题
- 工作区/表格多处交互细节（grid、api-import）；CI/CD 错误

## [0.1.3] — 2026-09-13

### 新增

- **多视图系统重构**：统一视图类型配置，支持看板/日历/画廊等多种视图
- 看板视图卡片排序与紧急置顶
- 用户偏好功能、表格视图体验与数据导入能力增强
- wheel docker 部署支持；前端打包集成与包资源打包配置
- 示例数据集与登录后流程优化

### 变更

- 视图模式按钮与左侧 Segmented 双向联动
- smart-color 颜色匹配与 fallback 逻辑优化

### 修复

- 看板 link 类型字段分组渲染为 [object Object]
- 日期字段编辑适配；非 grid 视图数据获取

## [0.1.2] — 2026-09-13

### 新增

- **Playwright E2E 测试**：smoke（登录 → Grid → 退出）+ critical（行 CRUD 全链路），配置见 `frontend/playwright.config.ts`
- **生产部署定型**：多阶段 `deploy/Dockerfile`（前端构建 + uvicorn）+ `deploy/nginx.conf` 反代 + `docker-compose.yml` 生产编排（SQLite/PostgreSQL 双形态）
- **示例数据集**：`examples/datasets/` 5 个 CSV（学生成绩 / 电商销售 / 房价预测 / 客户流失 / 气温天气）
- **`.env.example`**：部署环境变量模板

### 变更

- docker-compose.yml 从开发形态更新为生产形态（nginx 入口 + app 容器 + pg profile）
- `.gitignore` 添加 Playwright 产物目录

## [0.1.1] — 2026-09-11

### 新增

- 前端完成 F1–F9：登录注册 / 工作区 / Grid inline 编辑 / 视图 Tab / 导入导出 / 成员管理 / 主题切换 / 关系图 / 报表 / 公开分享页
- SPA fallback：`app.py` 中间件自动处理前端路由回退
- 前端构建产物挂载到 `src/cndb/static/`，uvicorn 统一提供

### 变更

- RowResponse 类型对齐后端扁平结构（移除嵌套 values 字段）

## [0.1.0] — 2026-09-10

### 新增

- 后端 P0–P4 完成：框架基础 + 6 插件 + 95%+ 测试覆盖率
- 插件架构：accounts / workspaces / tables / reports / health
- 动态数据表：SQLAlchemy Core 运行时 DDL
- link 字段多对多存储与查询
- 审计日志 + 回收站闭环
- 字段类型补齐至 11 种

# cndb → cndb2 重构方案

> 基线：F:\Dev\cndb（Django 5.2 + DRF，业务设计来源）
> 目标：F:\Dev\cndb2（cndb，FastAPI + SQLAlchemy 2.0 + Plugin 架构 + Vite/React/antd 前端）
> 原则：业务设计 100% 继承（元数据驱动、动态 DDL、视图规则、四级权限、导入导出、协作、报表），
> 技术栈全面切换（ORM/框架/前端/认证），不迁移存量数据（全新库，密码哈希不兼容 PBKDF2）。

## 一、模块映射（Django app → FastAPI plugin）

| cndb app | cndb2 plugin | 职责与关键平移点 |
|---|---|---|
| accounts | accounts | User（SQLAlchemy 化，nickname 保留）；JWT 登录/注册替换 Django Session；密码 bcrypt |
| tokens | 并入 accounts（token.py） | ApiToken：cndb_ 前缀明文一次性返回、SHA-256 摘要落库、prefix 识别，机制原样保留 |
| workspaces | workspaces | Workspace / WorkspaceMember（owner/admin/editor/viewer 四级角色 + pinned） |
| tables | tables（最大插件，内部子包） | 元数据模型、字段类型系统、动态 DDL、行数据、视图规则、表级权限、导入导出、评论、回收站、审计、表复制/移动、表关系图 |
| reports | reports | ReportTemplate（Jinja2 沙箱）+ docx/pdf/xlsx 渲染器 |
| webui | 废弃 | 前端由 React 重建（登录/工作区/表/Grid/看板/日历/画册/表单/共享/关系图/报表） |
| settings | core/config.py | pydantic-settings 承接 dev/prod/test 分环境配置 |

## 二、tables 插件内部结构（对应原文件逐项平移）

```
plugins/tables/
├── plugin.py            # PluginBase 子类，register_routes 挂载
├── models.py            # DataTable/DataField/DataView/TablePermission/RowComment/ImportTask/AuditLog
├── field_types/         # base.py + registry.py + builtin.py(9 种) + link.py —— 纯逻辑平移，pydantic 化校验
├── ddl.py               # 动态 DDL 引擎：SQLAlchemy Core（sa.Table/DDL）替代 Django 原生 SQL
├── records.py           # 行 CRUD + bulk + 粘贴填充/行复制语义
├── query.py             # 查询编译：筛选/排序/聚合(count/sum/avg/min/max)，方言化 JSON 访问
├── view_rules.py        # 视图规则归一化（Grid/Kanban/Calendar/Gallery/Form）
├── permission_rules.py  # 表级权限归一化
├── access.py            # 权限判定链（角色→表动作→行范围→字段隐藏）→ FastAPI Depends
├── transfer.py          # CSV/JSON/Excel 导入导出 + 错误行按原始行号报告
├── import_tasks.py      # 异步导入状态机（BackgroundTasks 起步，celery 预留）
├── trash.py / audit.py / comment.py / links.py / table_copy.py / table_move.py / table_graph.py
├── public.py            # 匿名路由：/forms/{slug}、/share/{slug}
└── routers/             # 按资源拆分 router（tables/fields/records/views/permission/...）
```

## 三、关键技术决策

1. 认证双轨：JWT（前端，core/security.py 已有）+ ApiToken（Bearer 头，SHA-256 校验）；
   统一 get_current_user 依赖注入，两者产出同一 User。
2. 动态行数据：物理表名 table_<hex12>、列名 field_<hex12> 系统生成的设计原样保留，
   用户输入永不进 SQL 标识符；行读写用 SQLAlchemy Core 动态构建 sa.Table（比原 Django 原生 SQL
   更干净，天然跨 SQLite/PostgreSQL 方言）。
3. link_to_table：关联物理表 link_<hex> 双写设计保留。
4. 路由前缀：扩展 PluginBase 增加可选 route_prefix（默认插件名）。tables 插件声明
   workspaces 前缀以保持 REST 嵌套形态 /api/v1/workspaces/{wid}/tables/...，
   与 workspaces 插件同前缀并存（FastAPI 多 router include 无冲突）。
5. 规则校验 pydantic 化：view_rules / permission_rules / field_types 的 dict 校验
   改为 pydantic 模型（Filter/Sorting/FieldOption/RowFilter），保存前归一化语义不变。
6. 异步导入：ImportTask 状态机（pending→running→done/failed）+ 进度轮询不变；
   执行器首版用 FastAPI BackgroundTasks + 线程（零基础设施），celery+redis 作为生产
   可选开关（依赖已声明未接入，接入动作放 P7 评估）。
7. Alembic：框架未初始化，P0 补齐；只管元数据库 schema，动态物理表 DDL 走自研引擎不经 Alembic。
8. 测试栈：pytest + httpx TestClient + pytest-asyncio（替换 pytest-django）；
   34 个测试文件的用例语义逐项迁移，覆盖率门禁 >=95% 不放宽。
9. JSON 字段查询/聚合：SQLite 用 json_extract、PG 用 jsonb 运算符，
   经 SQLAlchemy 方言封装在 query.py 单点处理。
10. 管理员后台：Django admin 不再存在；管理能力以超级用户标记 + 少量管理端点替代，不建独立后台 UI。

## 四、API 面（对齐 cndb，前缀 /api/v1）

- /api/v1/auth/：register / login（JWT）
- /api/v1/tokens/：ApiToken CRUD（列表/签发/撤销）
- /api/v1/workspaces/：CRUD、成员管理、reorder、graph
- /api/v1/workspaces/{wid}/tables/：表 CRUD/reorder/copy/move/import-csv
- .../fields/：字段 CRUD/reorder
- .../records/：行 CRUD/bulk/{id}/references/{id}/audit/{id}/comments/
- .../views/：视图 CRUD/reorder/{id}/rows/{id}/kanban/{id}/calendar/
- .../permission/：表级权限读写
- .../export/、.../import/、.../import/async/{task}
- /api/v1/reports/：模板 CRUD + 渲染下载
- /api/v1/public/forms/{slug}（匿名提交）、/api/v1/public/share/{slug}（匿名只读 grid）

## 五、前端页面规划（Vite+React18+TS+antd5+react-query）

| 路由 | 页面 | 对应原模板 |
|---|---|---|
| /login | 登录（JWT + axios 拦截器注入） | login.html |
| / | 工作区列表/创建（AppCenter 改造） | index.html 工作区切换 |
| /w/:wid | 主应用：表侧栏 + 视图 Tab + Grid/Kanban/Calendar/Gallery、行内编辑/批量/评论/回收站/导入导出/权限面板 | index.html |
| /w/:wid/graph | 表关系图 | graph.html |
| /w/:wid/reports | 报表模板管理与生成 | report.html |
| /f/:slug | 公开表单（匿名提交，不走 MainLayout） | form_page.html |
| /s/:slug | 共享视图（匿名只读） | share_page.html |

复用框架已有：MainLayout、api/client.ts（401 处理）、react-query 数据层、useResponsive。

## 六、阶段划分（每阶段收口：make check 全绿 + 阶段测试迁移完成）

- P0 框架基座：Alembic 初始化；User/认证（JWT+ApiToken）；PluginBase 扩展 route_prefix；
  前端登录页 + 路由守卫。验收：注册/登录/Token 签发撤销全链路测试绿。
- P1 工作区：Workspace/Member CRUD、四级角色依赖链、pin；前端工作区页。验收：角色矩阵测试绿。
- P2 表与字段（核心）：元数据模型 + 字段类型系统（9 内置 + link）+ DDL 引擎 + 行 CRUD/bulk
  + 查询编译（筛选/排序/聚合）；前端 Grid 基础版（行内编辑）。验收：DDL/类型/行/查询测试迁移绿。
- P3 视图：DataView 5 形态规则、view rows/kanban/calendar 端点、视图 CRUD/reorder；
  前端视图 Tab + Kanban/Calendar/Gallery。验收：view_rules/board 测试迁移绿。
- P4 权限与共享：TablePermission（动作制/行级/字段级）、公开表单 slug、共享 slug、匿名路由；
  前端权限面板 + 公开页。验收：access/permissions/public 测试迁移绿。
- P5 导入导出与协作：CSV/JSON/Excel 双向、异步导入轮询、行评论、回收站、审计、
  表复制/移动、表关系图端点；前端对应 UI。验收：transfer/import/trash/comment/audit 测试迁移绿。
- P6 报表：ReportTemplate + docx/pdf/xlsx 渲染器（Jinja2 沙箱）；前端报表页。验收：reports 测试迁移绿。
- P7 收尾：seed 演示数据、性能基准（rows 吞吐）、Docker 部署（nginx+uvicorn+PG）、
  README、celery 接入评估。验收：端到端冒烟 + make check 全绿。

## 七、风险与对策

| 风险 | 对策 |
|---|---|
| 动态 DDL 方言差异（SQLite/PG） | SQLAlchemy Core 单点封装；DDL 测试双库跑（开发 SQLite / CI 可选 PG） |
| JSON 字段聚合在 SQLite 受限 | query.py 方言分支；聚合测试覆盖两种库 |
| 原实现隐式依赖 Django 特性（save 钩子校验、ORM 事务） | 校验逻辑显式化到 service 层；保存钩子语义写入 pydantic 归一化函数 |
| 前端从模板+原生 JS 到 React 工作量大 | P2 先交付 Grid 最小可用，交互渐进补齐；antd Table 复用 |
| 异步导入线程与请求会话竞争 | 任务内独立 Session；状态更新乐观锁 |
| 密码哈希不兼容（PBKDF2→bcrypt） | 不迁移存量数据；如需迁移另立需求写兼容校验器 |

## 需求清单（按阶段勾选）

> 2026-09-11 回写：后端各阶段已按 git log 完成并勾选；其中前端交付项未实现，
> 统一归入 req-02 Phase F（前端全功能重建）。部分深层链路（link 数据层/权限判定/
> 审计写入/回收站闭环）经核查为"骨架在、链路断"，归入 req-02 Phase D 补齐。

- [x] P0 框架基座：Alembic + JWT/ApiToken 认证 + route_prefix 扩展（前端登录 → req-02 F1）
- [x] P1 工作区与成员（四级角色）
- [x] P2 表/字段/动态 DDL/行数据/查询编译（Grid 前端 → req-02 F3）
- [x] P3 五种视图规则与端点（视图前端 → req-02 F4）
- [x] P4 表级权限/行级/字段级 + 公开表单/共享视图（权限判定链 → req-02 D2）
- [x] P5 导入导出/异步导入/评论/回收站/审计/表复制移动/关系图（审计写入 → req-02 D3；回收站闭环 → req-02 D4；link 数据层 → req-02 D1）
- [x] P6 报表模板与三格式渲染（决策：保持简化版，不迁 seals/ReportLog/指令系统）
- [x] P7 seed/性能基准/Docker 部署/README 收尾（生产 compose 形态 → req-02 E3）

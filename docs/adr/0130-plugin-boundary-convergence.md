# 0130 插件边界收敛与布局治理（本轮只做收敛项，包化 / 内核化留待触发）

Status: Accepted

Related: `src/cndb/core/plugin_registry.py`、`src/cndb/core/http.py`、`src/cndb/plugins/files/__init__.py`、`docs/adr/0020-llm-platform-capability.md`、`CHANGELOG.md`

## 背景

2026-11-10 的结构 / 性能审计发现三类边界问题（均已在 P0 修复，见「落地状态」）：

1. **死目录**：`src/cndb/plugins/acquisition/` 只剩残留 `__pycache__`，无任何源码与引用，仍会被插件发现扫到。
2. **失败静默**：插件加载对 `ImportError` 与任意异常一律 `continue`，开发期拼错 import、漏 `plugin.py`、缺依赖都不会让启动失败，只是少几个路由 / 少几张表；`files`（附件归属数据层，无注册入口）因此长期处于「像插件又不是插件」的灰区。
3. **私有符号跨插件引用**：`workspaces` 备份 / 恢复直接 import `documents.services.content` 的 4 个下划线函数，`datasource` 的 provider 通过 `api_fetch` 兼容 shim 用到 `core.http` 的 2 个下划线函数，`workspaces` 内部还用 `_import_backup_into_workspace` 作为落库入口，共 7 个私有名，重构时无法用「下划线 = 模块私有」判断兼容边界。

审计同时提出两条结构性方案（插件目录包化、共享内核 `cndb/kernel`），本轮**明确不做**，只在本 ADR 记录触发条件与取舍，避免再被反复提起。

## 决策记录

| 编号 | 决策 | 内容 | 理由 | 放弃的选项 |
|---|---|---|---|---|
| D1 | 死目录 | 直接删除 `plugins/acquisition`，不留占位 | 无源码、无引用、无迁移，唯一效果是污染插件发现与目录阅读 | 保留并加 README 说明（噪音源仍在） |
| D2 | 插件发现的失败口径 | 先用 `find_spec` 判断目录内是否有 `plugin.py`：没有即共享模块目录（如 `files`），debug 跳过；有 `plugin.py` 但导入失败，`DEBUG=true`（开发 / 测试 / 默认桌面）直接抛出，`DEBUG=false`（生产，H36）记 error 后降级 | 开发期要让拼写与依赖问题在启动时暴露；生产期不能让单个插件拖垮整个服务 | 一律 fail-fast（生产风险）；一律静默跳过（本次要修的问题） |
| D3 | `files` 定性 | 保持为共享数据层（`FileOwner` 模型 + 归属 / 访问校验），**不**补 `plugin.py`；docstring 明确「不是插件」且未补 `plugin.py` 前不得放路由 | 它没有路由 / 导航 / 生命周期钩子，注册成插件只会多一层空壳 | 并入 `core/attachments`（跨插件 import 面更大，且它是 ORM 模型层，不宜进 core） |
| D4 | 跨插件调用面 | 7 个被跨插件引用的私有符号全部转公开名：`documents.content` 的 `external_version_path` / `decode_inline_compressed` / `store_content_bytes` / `sync_fts`，`core.http` 的 `extract_array` / `resolve_path`（`__all__` 同步），`workspaces.backup_io` 的 `import_backup_into_workspace` | 公开名 = 兼容承诺，私有名 = 可随手重构；既然已被跨插件调用，就应显式承认 | 保留私有名 + 在每个调用点写注释（契约仍隐式） |
| D5 | 插件布局包化 | **本轮不做**。触发器（2026-11-10 明确化为可核对口径）：① 任一插件根目录 `.py` 文件 > 8 个；② 某插件根级出现「同一职责被拆到 2 个以上平级文件」、需要收进包。`services/` 下既有的二级子包（pipeline `checks/{document,table}`、tables `transfer/normalize`）属既定分类结构，**不**作为触发条件 | 当前 12 个插件（另 1 个 `files` 共享目录）根级最多 5 个文件（详见「触发条件核对」），包化只带来 import 路径变长与 `__init__` 空壳 | 现在就把 `plugins/<name>/{routers,services,models}.py` 拆成包（改动面覆盖几乎所有插件，收益低） |
| D6 | 共享内核化 | **本轮不做**。触发器：`core/` 内出现「被 ≥3 个插件同时依赖**且含业务语义（领域规则）**」的模块；纯通用工具（如 25 行 `difflib` 包装）不计入 | `core` 承担的都是横切能力（DB / 配置 / 错误 / 事件 / 缓存 / 后台任务 / HTTP / 文本 diff），跨插件依赖保持单向（插件 → core），没有环 | 现在抽 `cndb/kernel` 包（纯改名 + 迁移，零行为收益） |

## 落地状态

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0-1 | 已落地 | `src/cndb/core/plugin_registry.py`（find_spec 分流 + 环境相关失败口径）、`src/cndb/plugins/files/__init__.py`（定性）、删除 plugins/acquisition 目录 | `tests/test_plugin_registry.py` | `ec456e23` |
| P0-2 | 已落地 | `src/cndb/core/http.py`（__all__ 同步公开名）、`src/cndb/plugins/documents/services/content.py`、`src/cndb/plugins/workspaces/services/backup_io.py`（公共入口）、`src/cndb/plugins/workspaces/services/workspace_backup.py` | `tests/test_api_fetch.py`、`tests/test_workspace_backup_v13.py`、`tests/test_workspace_backup_v16.py` | `c13cfce8` |
| P1 | 未开始 | 插件布局包化（D5 未触发，依据见「触发条件核对」） | 无 | — |
| P2 | 未开始 | 共享内核化（D6 未触发，依据见「触发条件核对」） | 无 | — |

## 触发条件核对（2026-11-10，只读统计）

统计方法：遍历 `src/cndb/plugins/<name>/*.py` 统计根级文件数；遍历 `src/cndb/plugins/<name>/services/` 统计子包；对每个插件目录 `rglob("*.py")` 抓 `from cndb.core[.X] import` / `import cndb.core.X` 得到「插件 → core 模块」依赖集。仅读文件，不改代码。

### D5 插件布局包化：**未触发**

| 插件 | 根目录 `.py` 数 | `services/` 下的子包 |
|---|---|---|
| accounts | 3 | 无（services 内为 .py 文件） |
| analytics | 4 | 无 |
| change_requests | 5 | 无 services（根级单文件 `services.py`，918 行） |
| datasource | 4 | 无 |
| design | 5 | `dsl` |
| documents | 3 | `charts` / `export` / `importers` / `preview` |
| files | 3 | 无 services（共享数据层，无 `plugin.py`） |
| help | 3 | `figures` |
| issues | 5 | 无 services（根级单文件 `services.py`，276 行） |
| llm | 3 | 无 |
| pipeline | 4 | `checks`（内嵌 `document` / `table`）、`dsl` |
| tables | 3 | `core` / `fields` / `governance` / `importing` / `transfer`（`transfer` 内嵌 `normalize`） |
| workspaces | 5 | `templates` |

判断依据：

- 条件 ①「根目录 `.py` > 8」：最大为 5（change_requests / design / issues / workspaces），**未满足**。
- 条件 ②「同一职责被拆到 2 个以上平级文件」：当前每插件根级职责文件（models / plugin / schemas / services / routers）各只有 1 个，**未满足**。
- `services/` 内已有的二级子包（pipeline `checks/document`、`checks/table` 各 5 文件；tables `transfer/normalize` 4 文件）是既定的分类结构，说明这些插件的 `services/` 已经是包组织，不构成「一层装不下、需要包化」的信号（D5 已据此把该条从触发器中移除）。
- 观察项（不属 D5）：`design/routers.py` 1060 行、`change_requests/services.py` 918 行 是「单文件过大」，拆分属文件内聚重构，不改变包结构。

### D6 共享内核化：**未触发**

`core/` 共 17 个模块，其中 11 个被插件引用；被 ≥3 个插件同时依赖的 8 个如下：

| core 模块 | 依赖插件数 | 行数 | 性质判断 |
|---|---|---|---|
| database | 12 | 213 | 横切：引擎 / Session / 事务 |
| config | 9 | 273 | 横切：配置项 |
| errors | 8 | 121 | 横切：统一错误类型 |
| events | 5 | 326 | 横切：统一事件 / 审计流（不含领域规则） |
| cache | 4 | 233 | 横切：进程内 TTL + LRU |
| http | 3 | 759 | 横切：HTTP 客户端 / SSRF 校验 / 重试 |
| task_runner | 3 | 94 | 横切：后台线程登记与超时 |
| textdiff | 3 | 25 | 通用工具：`difflib` 包装 |

判断依据：

- 上表 8 个模块全部是横切能力或通用工具，**没有一个承载领域规则**（accounts / workspaces / tables 的业务规则仍在各自插件内）。
- 依赖数分布在 1-2 的模块（crypto 2、ratelimit 1、security 1）更不满足阈值。
- 因此「被 ≥3 插件依赖且含业务语义」的模块数为 **0**，条件**未满足**。

## 交接

- 当前阶段：P0 已落地并全量门禁通过；2026-11-10 复核 D1-D4 与代码一致，D5 / D6 触发条件实测均未满足（数字见「触发条件核对」），P1 / P2 保持未开始
- 已完成：删除 `plugins/acquisition`；`files` 明确定性为共享数据层；插件发现用 `find_spec` 区分「无 plugin.py」与「导入失败」，`DEBUG` 下 fail-fast；7 个跨插件私有符号转公开名（文档、注释与 `__all__` 同步）；2026-11-10 复核：`acquisition` 目录不存在、`core/plugin_registry.py` 与 D2 一致、`files/__init__.py` 与 D3 一致、7 个公开名与两处 `__all__` 可用且无旧名残留
- 下一步：若再出现「新增插件后忘记 `plugin.py`」或「插件加载失败无感知」的问题，先检查 `DEBUG` 口径是否被部署脚本覆盖；D5 / D6 每次结构大改后重跑同口径统计，条件满足时另立 ADR 或在本 ADR 追加阶段
- 已知坑：`find_spec("cndb.plugins.<name>.plugin")` 会先导入父包，而父包 `__init__` **并非全空**（change_requests 44 行、issues 40 行、datasource 13 行、workspaces 12 行等做符号 re-export），因此发现阶段会执行这些模块级 re-export；在 `__init__` 里加 re-export 时不要做重活（DB 查询 / 线程 / 文件 IO）；`tests/test_plugin_registry.py` 用临时目录 + monkeypatch `find_spec` 验证分流，临时目录不在 `cndb.plugins` 命名空间下时真实 `find_spec` 会抛 `ModuleNotFoundError`，不要直接依赖真实导入

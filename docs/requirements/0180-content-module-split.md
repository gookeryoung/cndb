# 需求卡片：content.py 拆分（S2）

- 编号：0180
- 来源 / 提出人：用户（会话 2026-11-26「单独开对话补齐 cndb 项目 批次 3 任务」；批次范围见 `BACKLOG.md` 批次 3 第 2 项）
- 日期：2026-11-26
- 关联 ADR：ADR 0180（`docs/adr/0180-content-module-split.md`）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改 ADR / 代码（H26）。

## 需求原句（逐字）

> 单独开对话补齐 cndb 项目 批次 3 任务

批次 3 在 `BACKLOG.md`「### 批次 3：技术债（按成本收益排序）」中定义为三项，其中第 2 项即本次范围：

> 2. **`content.py` 拆分**：已 1400+ 行，按 `crud / links / graph / duplicate` 拆（未开始）。

`docs/REFACTOR_BACKLOG.md` §一 对同一文件的记录（口径与上句不一致，见 C7）：

> `| src/cndb/plugins/documents/services/content.py | 1156 | 拆 content/{crud,trash,links,tags,fts,serialize}.py；FTS/软删子树/标签计数高耦合，成本较高 |`

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「已 1400+ 行」 | 以实测为准：`src/cndb/plugins/documents/services/content.py` 当前 **1493 行**、48 个顶层符号、**无 `__all__`**。拆分后 `content` 变为包，包内**任何单文件 ≤ 400 行**；`build_link_graph`（132 行）、`_duplicate_node`（80 行）、`create_document`（78 行）、`update_content`（76 行）等大函数各自落在所属模块内，不因拆分再跨文件散开 | `services/content/**` | `wc -l` 逐文件核对；`make check-fast` |
| C2 | 「按 … 拆」 | 拆分边界以**实测调用图**为准而非文档措辞：按内聚块 `storage / access / write / trash / links / tags / fts / serialize / graph / duplicate` 分层；依赖方向严格单向 `storage → access → 业务模块`，**不允许环**；`storage` 层不得 import 任何业务模块 | `services/content/*.py` | 模块导入关系检查（禁止 `storage` import 业务模块）；`make check-fast` |
| C3 | （公开面不变） | 所有现有外部引用继续可用且语义不变：`from ...documents.services.content import X`（`src/` 中 12 个文件、约 20 处）与 `content_service.X` 属性访问（`routers/documents.py`、`obsidian.py`、`importers/importer.py`、`drafts.py`、`change_requests.py`、`move.py`、`references.py`，约 30 处）全部保持；包 `__init__.py` 显式 `__all__` 列出对外符号；`services/__init__.py` 的 `from . import (…, content, …)` 与 `__all__` 不改 | `services/content/__init__.py`、`services/__init__.py` | 现有调用点零改动即通过 `make test`；`python -c "import …content as c; c.__all__"` 核对 |
| C4 | （H28 兼容） | 测试依赖的具名导出与可 patch 目标**全部保留在 `content` 顶层**：`_DOCS_DIR`（含 `monkeypatch.setattr(content_service, "_DOCS_DIR", …)` 的**写后生效**语义）、`_get_workspace`、`_mark_deleted_subtree`、`_same_delete_batch`、`_apply_tags`、`_normalize_ts`、`_restore_subtree`、`_collect_purge_targets`、`_refresh_tag_counts`（`routers/tags.py` 直接 import 该私有名）、`create_document`、`latest_version`、`reset_link_graph_cache`、`build_link_graph`。受影响的 12 个测试文件**不得为适配拆分而放宽断言、删用例或改用非 canonical 目标** | `services/content/__init__.py`、`tests/**` | `make test` 全绿；逐条核对 `tests/conftest.py:228`、`test_cli_docs.py:42`、`test_cov_cli_extra.py:547`、`test_documents_robustness.py:48,708`、`test_documents_storage_gc.py:35`、`test_workspace_storage_usage.py:154`、`test_documents_file_import_api.py:501`、`test_cov_workspaces_extra.py:289,538,555,573`、`test_documents_link_graph.py:25,92,106`、`test_seed_documents.py:213,247,264` |
| C5 | （零行为变更） | 纯结构调整：**不新增表 / 列 / 迁移、不改接口签名与响应、不改前端、不改存储格式与压缩阈值**（`RAW_INLINE_MAX_SIZE = 4 * 1024`、`gz:` 前缀、外存路径 `data/docs/{doc_id}/v{n}.md.gz` 全部不动） | 全仓 | `git diff` 不得出现 `migrations/`、`frontend/`、`routers/**` 的语义改动 |
| C6 | （门禁） | 按 L2 执行：`make check-fast` → `make test` 全绿；覆盖率门槛不下降（`cov` 与 `frontend-coverage` 口径不变） | 门禁 | `make flow` |
| C7 | （口径统一） | 两份文档的拆分口径必须收敛到一处：`docs/REFACTOR_BACKLOG.md:47` 的行数 `1156` 更正为实测值并改为指向 ADR 0180 的最终分层；`docs/requirements/BACKLOG.md` 批次 3 第 2 项回填状态 | `docs/REFACTOR_BACKLOG.md`、`docs/requirements/BACKLOG.md`、`CHANGELOG.md` | `make check-docs`；人工比对两处措辞 |
| C8 | （分期与提交） | 按 H4 分期内聚提交，每期可独立编译与通过门禁：P0 建包 + `storage`/`access`、P1 `write`/`trash`、P2 `links`/`tags`/`fts`/`serialize`、P3 `graph`/`duplicate` + 文档回填 | 提交历史 | 每期 `make check-fast` 绿；`git log --oneline` 每期一个 `refactor:` 提交 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 外存根目录被运行时读取 | `workspaces/services/storage.py:61-65`、`documents/services/storage.py:58-61` | 两处 `return Path(content_service._DOCS_DIR)`，docstring 明写「运行时读取，兼容测试对 content._DOCS_DIR 的重定向」 |
| 2 | 测试 session 级重定向外存目录 | `tests/conftest.py:218-228`（setattr）、`:284-287`（读取清理） | 拆分后 `_DOCS_DIR` 若迁走则 patch 静默失效 |
| 3 | 字符串形式 patch | `tests/test_cov_workspaces_extra.py:289` `monkeypatch.setattr("cndb.plugins.documents.services.content.create_document", _boom)` | canonical 路径写死在字符串里 |
| 4 | 属性 patch 公有函数 | `tests/test_documents_robustness.py:708`（`latest_version`）、`tests/test_documents_file_import_api.py:501`（`create_document`） | 同 C4 |
| 5 | 直接调用私有符号的测试 | `tests/test_cov_documents_extra.py:528,571,583-584,609-611,617,1008,1012` | `_get_workspace` / `_mark_deleted_subtree` / `_same_delete_batch` / `_apply_tags` / `_normalize_ts` / `_restore_subtree` / `_collect_purge_targets` |
| 6 | 路由直接 import 私有名 | `documents/routers/tags.py:24`（`_refresh_tag_counts`、`require_editor`） | 需保留顶层别名或转公开 |
| 7 | 存储模块清单 | `documents/services/__init__.py:1-21` | `content` 仍是包名，清单无需改；若另立并列顶层模块则需同步 |
| 8 | 备份 / 跨区移动读写外存 | `workspaces/services/backup_io.py:615,825,904`、`workspace_backup.py:197,535` | 依赖 `external_version_path` / `store_content_bytes` / `decode_inline_compressed` / `load_content` |
| 9 | 图谱缓存与节点 id | `services/content.py:1184-1341`（`GRAPH_MAX_NODES`、`_graph_cache`、`_broken_node_id`） | 模块级可变缓存，迁模块后必须仍是**唯一实例**（拆成两份缓存会导致路由与检查读到不同图） |
| 10 | 管道检查读取正文 | `pipeline/services/checks/base.py:27`、`checks/document/links.py:13` | 只读 `latest_version` / `load_content` / `resolve_outgoing_links` |

## 未决问题

- [x] 拆分粒度按 BACKLOG 的 4 段还是 REFACTOR_BACKLOG 的 6 段（2026-11-26 结论）：都不采用。以 AST 实测调用图为据拆成 10 个内聚模块，两处旧措辞按 C7 收敛到 ADR 0180。
- [x] `_DOCS_DIR` 是否可以迁出 `content.py`（2026-11-26 结论）：不迁出。它是唯一被外部**运行时读取 + 测试写后生效**的模块常量，继续留在 `content` 包顶层；包内 `storage` 用函数内延迟读取，避免 import 期快照。
- [x] 图谱缓存迁到 `graph.py` 后是否会有多实例（2026-11-26 结论）：不会。`_graph_cache` 只由 `graph.py` 持有，`content` 包顶层只再导出 `reset_link_graph_cache` / `build_link_graph` 两个函数名，不导出缓存对象。
- [x] 是否顺便拆 `obsidian.py`（1712 行，全仓最大）（2026-11-26 结论）：不拆。本卡只处理批次 3 第 2 项，`obsidian.py` / `records.py` / `main_window.py` 仍在 `REFACTOR_BACKLOG.md` 排队。

## 卡点

- [x] 每条需求句都有 C 编号约束（C1 对应「1400+ 行」，C2 对应「按 … 拆」，C3–C8 为可验收的拆分约束）
- [x] 未决问题有结论

> S2：等待 ADR 0180 人工评审（H5）。评审通过前不进入实现。

# ADR 0180: content 模块拆分（单文件 1529 行 → 10 个内聚模块，公开面零变更）

Status: Accepted
Date: 2026-11-26
Related: `src/cndb/plugins/documents/services/content/`、`docs/requirements/0180-content-module-split.md`、`docs/adr/0130-plugin-boundary-convergence.md`、`docs/adr/0177-document-template-integration.md`、`docs/REFACTOR_BACKLOG.md`
需求卡片: `docs/requirements/0180-content-module-split.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「已 1400+ 行」→ 包内单文件 ≤ 400 行 | 实测 `src/cndb/plugins/documents/services/content.py` 1529 行 / 66 个顶层符号（48 个函数 + 9 个模块级常量 + `logger`）。按 D1 切为 10 个模块，**实测最大单文件 `write.py` 约 290 行、`trash.py` 约 265 行**，均远低于 400。四个大函数整块搬运不切分：`build_link_graph` 132 行留在 `graph.py`、`_duplicate_node` 80 行留在 `duplicate.py`、`create_document` 78 行与 `update_content` 76 行留在 `write.py` |
| C2 | 「按 … 拆」→ 按内聚块分层，单向无环 | 分层方向 `storage → access → {write, trash, links, tags, fts, serialize, graph, duplicate}`；`tags` / `fts` 为叶子服务层（`write` / `trash` / `links` / `serialize` 可下依赖）。**`storage.py` 的 import 列表只允许标准库 + 数据模型 + `cndb.core`，禁止 import 同包任何其它模块**；`access.py` 只可 import `storage`。模块清单见 D1 |
| C3 | 公开面不变 | `content` 由模块变包（`content/__init__.py`），`__init__.py` 用 `from .storage import load_content, …` 逐名再导出并在 `__all__` 中显式列出 **66 个顶层符号全部名称**（保持现有 `src/` 20 处 from-import、30 处 `content_service.X` 属性访问、以及 `documents/services/__init__.py:1-21` 的 `from . import (…, content, …)` 全不改） |
| C4 | H28 兼容：具名导出与可 patch 目标留在顶层 | 两类目标分别用两种手段保证 patch 生效（见 D3）：**① 可写模块常量 `_DOCS_DIR` 物理定义在 `content/__init__.py`**，包内 `storage.py` 用函数内延迟读取 `content._DOCS_DIR`（不在 import 期快照），于是 `monkeypatch.setattr(content_service, "_DOCS_DIR", …)` 依旧写后生效；**② 可 patch 的函数名**（`create_document` / `latest_version` / `build_link_graph` / `reset_link_graph_cache`）在 `__init__.py` 中是普通赋值再导出，同包内调用一律写成 `from .write import create_document` 的**模块属性访问**（`write.create_document(...)`）而不是 `from .write import create_document` 的本地绑定，因此 patch 包顶层属性对内部调用同样生效 |
| C5 | 零行为变更 | 不动 `migrations/`、`frontend/`、`routers/*` 任何语义；`RAW_INLINE_MAX_SIZE = 4 * 1024`、`_COMPRESSED_PREFIX = "gz:"`、外存路径 `data/docs/{doc_id}/v{n}.md.gz`、`_external_dir(doc_id, root=None)` 的 `root` 重定向参数、`GRAPH_MAX_NODES = 500` / 30s / 256 条缓存口径全部逐字保留 |
| C6 | 门禁 | L2：每期 `make check-fast` 绿、收尾 `make test` 全绿；覆盖率门槛与口径零调整 |
| C7 | 口径统一 | `docs/REFACTOR_BACKLOG.md:47` 的行数 1156 → 1529，建议列改为「已按 ADR 0180 拆为 10 个内聚模块」；`docs/requirements/BACKLOG.md` 批次 3 第 2 项回填（P3 收尾）；`CHANGELOG.md` 写 `(ADR 0180 Pn)` |
| C8 | 分期与提交 | P0 建包 + `storage`/`access`；P1 `write`/`trash`；P2 `links`/`tags`/`fts`/`serialize`；P3 `graph`/`duplicate` + 文档回填。每期一个 `refactor:` 提交，每期结束时包仍可 import、测试可跑 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。编号沿用卡片「现状影响面」，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 两个 storage 服务在**运行时**读 `content_service._DOCS_DIR` 作为外存根 | `src/cndb/plugins/documents/services/storage.py:61`、`src/cndb/plugins/workspaces/services/storage.py:65`（`return Path(content_service._DOCS_DIR)`，docstring 明写「运行时读取，兼容测试对 content._DOCS_DIR 的重定向」） | 常量若搬到子模块，这两处属性访问变成 `AttributeError`；且 patch 包顶层将不再影响实际读取点 | 确认（C4） |
| 2 | `tests/conftest.py` session 级 fixture 重定向外存根并据此清理 | `tests/conftest.py:228`（`monkeypatch_session.setattr(content_service, "_DOCS_DIR", docs_dir)`）、`:284-287`（`_clear_dir(Path(content_service._DOCS_DIR))`） | 若 `_DOCS_DIR` 迁走，**全仓所有外存用例**静默写回真实目录 | 确认（C4） |
| 3 | 字符串形式 patch canonical 路径 | `tests/test_cov_workspaces_extra.py:289` `monkeypatch.setattr("cndb.plugins.documents.services.content.create_document", _boom)` | 路径写死为 `…services.content.create_document`，包顶层必须仍是可 patch 的属性 | 确认（C4） |
| 4 | 属性 patch 公有函数 | `tests/test_documents_robustness.py:708`（`latest_version` → 返回固定旧版本，断言 409 `doc_version_conflict`）、`tests/test_documents_file_import_api.py:501`（`create_document` → 标题为「崩溃文档」时抛 `RuntimeError`，断言 created=1 / skipped=1） | 若内部调用走本地绑定，patch 不生效 → 这两个用例会**反向失败**（本应 409 的变 200、本应 skipped 的变 created） | 确认（C4） |
| 5 | 5 个文件分别 patch `_DOCS_DIR` | `tests/test_cli_docs.py:42`、`tests/test_cov_cli_extra.py:547`、`tests/test_documents_robustness.py:48`、`tests/test_documents_storage_gc.py:35`、`tests/test_workspace_storage_usage.py:154` | 同 #1/#2 | 确认（C4） |
| 6 | 测试直接调用 7 个私有符号 | `tests/test_cov_documents_extra.py:528`（`_get_workspace`）、`:571`（`_mark_deleted_subtree`）、`:583-584`（`_same_delete_batch`）、`:609-611`（`_apply_tags`）、`:617`（`_normalize_ts`）、`:1008`（`_restore_subtree`）、`:1012`（`_collect_purge_targets`） | 包顶层必须继续导出这些下划线名字 | 确认（C4） |
| 7 | 路由直接 from-import 私有名 | `src/cndb/plugins/documents/routers/tags.py:24`（`_refresh_tag_counts`、`require_editor`） | 同上；**不借本次转公开**（改名会扩大改动面，违反 C5） | 确认（C4） |
| 8 | `services/__init__.py` 显式列模块名并进 `__all__` | `src/cndb/plugins/documents/services/__init__.py:1-21` | `content` 仍是包名 → 该清单零改动；这一点决定了「拆成包」而不是「拆成并列 `content_*.py`」 | 排除（无需改） |
| 9 | 备份 / 跨区移动读写外存 | `src/cndb/plugins/workspaces/services/backup_io.py:615,825,844,904,908`、`src/cndb/plugins/workspaces/services/workspace_backup.py:197,529,535` | 依赖 `create_document` / `external_version_path` / `store_content_bytes` / `decode_inline_compressed` / `load_content` / `sync_fts`，均为包顶层导出名 | 确认（C3） |
| 10 | 图谱模块级可变缓存 | `src/cndb/plugins/documents/services/content.py:1184-1341`（`_graph_cache`、`_GRAPH_CACHE_TTL_SECONDS`、`_GRAPH_CACHE_MAX_ENTRIES`、`_broken_node_id`） | 若缓存对象被多处实例化，路由（`routers/documents.py:1587`）与检查会读到不同图 → 缓存失效语义与 H33 可见性裁剪结果不一致 | 确认（C4，见 D4） |
| 11 | 管道检查与检索只读正文 | `src/cndb/plugins/pipeline/services/checks/base.py:27`、`checks/document/links.py:13`、`documents/services/search.py:645`、`documents/services/attachments.py:25` | 只消费 `latest_version` / `load_content` / `resolve_outgoing_links` | 确认（C3） |
| 12 | 模块无 `__all__`，且从未定义过 | `src/cndb/plugins/documents/services/content.py`（全文无 `__all__`） | 现状「公开面」实为全部非下划线名字 + 被外部引用的 3 个下划线名字（`_DOCS_DIR`、`_apply_tags`、`_refresh_tag_counts`）；拆分前必须把这条隐式契约显式化，否则重构无法自证「公开面不变」 | 新增（D2） |

**核心缺陷（需求要补的）**：一个 1529 行的扁平模块同时承载存储分级、权限门控、写路径、回收站子树、双链解析、标签计数、FTS 同步、序列化、图谱构建、副本递归十种关注点，任何一处改动都要在整份文件里做全量 grep 才能判断影响面；且模块至今**没有显式导出清单**，「谁是公开面」只存在于调用方的 grep 结果里。

设计目标（不变量）：

- **I1 公开面等价**：拆分后 `content` 包顶层可访问的名字集合 ⊇ 拆分前 `content` 模块的名字集合（含 6 个被外部引用的下划线名字：`_DOCS_DIR`、`_apply_tags`、`_refresh_tag_counts`、`_get_workspace`、`_normalize_ts` 等测试直调项），且每个名字指向的函数 / 常量对象语义不变。
- **I2 依赖单向**：`storage` 不 import 同包模块；`access` 只 import `storage`；其余模块只 import `storage` / `access` / 叶子服务层，包内依赖图无环。
- **I3 单一可变状态**：`_DOCS_DIR` 与图谱缓存 `_graph_cache` 各自只有一份物理定义（`content/__init__.py` 与 `content/graph.py`），任何子模块通过**延迟属性读取**使用，不在 import 期固化。
- **I4 零行为变更**：不新增 / 修改表结构、迁移、接口签名、响应字段、前端代码；分级存储阈值与外存路径逐字不变。
- **I5 大函数不跨文件**：`build_link_graph`(132) / `_duplicate_node`(80) / `create_document`(78) / `update_content`(76) 各自完整落在单一模块内。
- **I6 每期可独立成立**：任一期的结束状态都能 `import` 并跑通全量测试（期间允许 `__init__.py` 从「部分子模块 + 剩余旧实现」混合导出）。

> 跨需求长期生效的不变量须在 ADR `Proposed → Accepted` 前登记入 [CONSTRAINTS.md](../CONSTRAINTS.md)，来源写 `ADR 0180 I#`（H27，ADR 0119）；本 ADR 作废删除前，先迁移仍在生效的 H 条目。本次拟登记 I2 / I3 两条（模块分层与单一可变状态），I1 / I4 / I5 / I6 为本次一次性验收口径，不登记。

## Decision

### 1. 数据模型

无。本次不涉及表 / 列 / 枚举 / 迁移，`src/cndb/alembic/versions/` 零改动。

### 2. 判定算法（唯一入口）

无新增判定入口。本次保留现有的两个「单一定义点」不扩散：

- `_docs_root()`（新增私有函数，仅 `storage.py` 内使用）：签名 `def _docs_root() -> Path`，实现为 `from cndb.plugins.documents.services import content as _pkg; return _pkg._DOCS_DIR`——**这是 `_DOCS_DIR` 的唯一读取口**，`_external_dir` / `_read_external_content` / `store_content_bytes` 都经它取根，从而保证测试 patch 包顶层后所有路径生效（I3）。
- `_graph_cache` / `reset_link_graph_cache()` / `build_link_graph()`：`graph.py` 是唯一持有缓存的模块，`__init__.py` 只再导出后两个**函数名**，不导出缓存对象本身（D4）。
- 跨模块调用一律用**模块属性访问**：`write.create_document(...)`、`storage.load_content(...)`，不用 `from … import 函数名` 的本地绑定（D3），以保证 patch 顶层属性对内部调用生效。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| 无 | 本次不改任何端点、请求 / 响应模型或状态码 |

### 4. 边界与例外

1. **`_DOCS_DIR` 的特殊性**：它是唯一被外部**运行时读取 + 测试写后生效**的模块常量，物理定义必须留在 `content/__init__.py`（不在 `storage.py`），这是 I3 的唯一例外形态——常量在包顶层、读取在子模块、经 `_docs_root()` 延迟取。
2. **`__init__.py` 允许阶段性混合**：P0 结束时子模块只有 `storage` / `access`，`__init__.py` 中其余符号仍来自旧实现（临时保留 `_legacy.py`）；P1–P3 逐期把符号搬空，P3 结束时删除 `_legacy.py`。**不允许**为了「一次性干净」在单期完成全部搬迁（违反 C8 的分期内聚提交）。
3. **`logger` 与 `_COMPRESSED_PREFIX` 归 `storage.py`**；`logs` 名称不变（`logging.getLogger(__name__)` 会随模块名变化，因此各模块统一 `logger = logging.getLogger("cndb.plugins.documents.services.content")` 固定名字，避免日志分类漂移）。
4. **不顺手转公开、不顺手改名**：`_apply_tags` / `_refresh_tag_counts` / `_get_workspace` / `_normalize_ts` / `_mark_deleted_subtree` / `_same_delete_batch` / `_restore_subtree` / `_collect_purge_targets` 全部保持下划线名（改名会同时触碰 `routers/tags.py`、`obsidian.py:1301` 与 4 个测试文件，超出 C5 的零行为变更口径）。转公开留作后续独立 ADR（参照 ADR 0130 D4 的做法）。
5. **不拆 `obsidian.py` / `records.py` / `main_window.py`**：仍在 `docs/REFACTOR_BACKLOG.md` 排队，各自需要独立 ADR。

### 5. 迁移

无 alembic 迁移；存量数据零迁移。搬运期间若需在 `docs/REFACTOR_BACKLOG.md` 更新行数，属文档改动（L0）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 无 | 无 | 后端内部重构，前端零改动 |

### 7. 测试清单

**判定层（单测）**：

- `tests/test_documents_content_split.py`（新增）：包顶层导出清单断言——① `set(dir(content)) ⊇ 66 个符号名` 的显式清单比对（I1）；② 6 个被外部引用的下划线名逐个 `hasattr` 断言；③ `content.__all__` 与清单一致、无重复项；④ 分层约束断言：解析 `content/storage.py` 的 AST，**其 import 节点不含同包模块**（I2，落地为可执行的静态检查）；⑤ `_DOCS_DIR` patch 后 `content.storage._docs_root()` 读到新值、`_external_dir(1)` 返回新根下路径（I3）。

**接口层**：

- 现有 12 个受影响测试文件**零改动**通过（`make test`），重点复核：`test_documents_robustness.py::TestVersionConflict`（409 口径）、`test_documents_file_import_api.py`（跳过计数）、`test_cov_documents_extra.py`（私有符号直调）、`test_documents_storage_gc.py` / `test_workspace_storage_usage.py` / `test_cli_docs.py`（外存重定向）、`test_cov_workspaces_extra.py::test_document_import_failure_records_error`（字符串 patch）。
- 备份往返与跨区移动既有用例（`tests/test_workspace_backup_*.py`、`tests/test_document_cross_workspace_move.py`）零改动通过。

**迁移 / 备份**：本次无迁移；`tests/test_migration_missing_model_columns.py` 的 head 常量不变（零迁移的验证点）。

**e2e（前端）**：无（前端零改动）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 建 `content/` 包：`__init__.py`（`_DOCS_DIR` + 全量再导出骨架 + `__all__`）、`storage.py`（常量 + `_docs_root` + 8 个读写函数）、`access.py`（5 个门控函数）、`_legacy.py`（其余符号临时落在原文件内容）；原 `content.py` 删除 | 中（包顶层导出遗漏 → 大量 import 失败；`_DOCS_DIR` 延迟读取写错 → 外存用例静默写真实目录） |
| **P1** | 搬 `write.py`（`create_document` / `replace_document_asset` / `ensure_text_document` / `update_content` / `_dispatch_document_saved` / `_mark_open_change_requests_stale` / `rollback_version` / `move_target_reason`）与 `trash.py`（回收站 10 个符号） | 中（`create_document` 被字符串 patch，必须走模块属性访问） |
| **P2** | 搬 `links.py` / `tags.py` / `fts.py` / `serialize.py` | 低（纯读与纯派生逻辑，无跨块可变状态） |
| **P3** | 搬 `graph.py` / `duplicate.py`，删除 `_legacy.py`，回填 REFACTOR_BACKLOG / BACKLOG / CHANGELOG | 中（图谱缓存唯一实例；`_duplicate_node` 依赖 `write.create_document`） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 拆成几个模块、边界怎么定 | 拆 **10 个内聚模块**：`storage` / `access` / `write` / `trash` / `links` / `tags` / `fts` / `serialize` / `graph` / `duplicate`，外加 `__init__.py`（导出面）与过渡期 `_legacy.py` | AST 实测的符号级调用图：48 个函数可完全切进 10 个强内聚块，跨块引用只有 6 个横切点（`load_content` / `sync_fts` / `_refresh_tag_counts` / `require_editor` / `get_document_or_404` / `store_content_bytes`），且全部落在 `storage` / `access` / `tags` / `fts` 四个底层模块 | ① BACKLOG 的 `crud / links / graph / duplicate` 4 段：`crud` 会把 storage + write + trash 重新合成 ~700 行，回到「半个巨型模块」；② REFACTOR_BACKLOG 的 `crud/trash/links/tags/fts/serialize` 6 段：缺 `graph` / `duplicate`（正是最需要隔离的 132 行 + 80 行），且 `crud` 同样过粗 | `src/cndb/plugins/documents/services/content/` |
| D2 | 拆成包还是并列模块 | 拆成**包** `content/`，用 `__init__.py` 显式 `__all__` 承载导出面 | `documents/services/__init__.py:1-21` 已把 `content` 当模块名列入 `from . import (...)` 与 `__all__`；拆成包后该清单零改动（Context #8）。并列 `content_*.py` 会让 `services/__init__.py` 增加 10 个条目，且破坏 `…services.content.X` 的 canonical 路径 | 并列模块 `content_storage.py` / `content_graph.py` 等：破坏包名完整性、需改 2 处模块清单、且 30 处属性访问的 `content_service` 别名语义变模糊 | `src/cndb/plugins/documents/services/content/__init__.py` |
| D3 | how to 保住 monkeypatch（H28） | 双轨：**常量**（`_DOCS_DIR`）物理定义留包顶层 + 子模块经 `_docs_root()` 延迟读取；**函数**（`create_document` / `latest_version` / `build_link_graph` / `reset_link_graph_cache`）在包顶层赋值再导出，包内调用一律 `模块.函数(...)` 属性访问 | H28 原文「拆分时 mock / monkeypatch 目标必须指向 canonical 模块」；`tests/test_cov_workspaces_extra.py:289` 用字符串路径 patch、`test_documents_robustness.py:708` / `test_documents_file_import_api.py:501` 用属性 patch，三者都要求「顶层属性是调用实际取值点」 | ① 在 12 个测试文件里改写 patch 目标到子模块：违反 C4「不得为适配拆分而改测试」；② 引入 `__getattr__` 转发：`monkeypatch.setattr` 会直接写 `__dict__` 覆盖 `__getattr__` 路径，反而不一致；③ 把 `_DOCS_DIR` 迁到 `storage.py` 再在包顶层 `from .storage import _DOCS_DIR`：`setattr` 只改包顶层，子模块读的是自己的旧值，**静默失效** | `content/__init__.py`、`content/storage.py` |
| D4 | 图谱缓存归属 | `_graph_cache` 及三个常量只由 `graph.py` 持有；`__init__.py` 只再导出 `build_link_graph` / `reset_link_graph_cache` 两个函数 | 缓存是模块级可变状态，多实例会导致路由与管道检查读到不同图（Context #10）；`reset_link_graph_cache` 在 `src/` 无外部调用（仅 `tests/test_documents_link_graph.py:25`），因此只需保证函数名可达 | 把缓存搬进 `__init__.py`：让「导出面模块」承载业务可变状态，后续任何再导出调整都会重新引入双实例风险 | `content/graph.py` |
| D5 | 私有符号是否借机转公开 | **不转**，8 个被外部引用的下划线名原样保留 | C5 零行为变更；转公开需同时改 `routers/tags.py:24`、`obsidian.py:1301`、4 个测试文件，属独立议题（ADR 0130 D4 已为「私有转公开」立过范式，应另开 ADR 复用该范式） | 本次顺手把 `_apply_tags` / `_refresh_tag_counts` 转公开：扩大改动面、混入两个语义不同的变更，且会让本次「纯结构搬运」的门禁失去可对比基线 | `content/__init__.py` |
| D6 | 常量 `logger` / `_COMPRESSED_PREFIX` / `RAW_INLINE_MAX_SIZE` / `DUPLICATE_SUFFIX` / `GRAPH_MAX_NODES` 归属 | `logger` / `_COMPRESSED_PREFIX` / `RAW_INLINE_MAX_SIZE` → `storage.py`；`DUPLICATE_SUFFIX` → `duplicate.py`；`GRAPH_MAX_NODES` 与另两个图谱常量 → `graph.py`；全部照旧从包顶层再导出 | 各常量只被本块使用（`src/` 无外部引用），按内聚就地安放；再导出保证 `content_service.RAW_INLINE_MAX_SIZE` 等旧写法仍可用 | 全部集中到 `constants.py`：会造出一个「所有模块都依赖它」的伪底层，反而弱化分层信息 | `content/storage.py`、`content/graph.py`、`content/duplicate.py` |
| D7 | `logger` 名称怎么取 | 各模块统一 `logger = logging.getLogger("cndb.plugins.documents.services.content")`（固定全名，不用 `__name__`） | 用 `__name__` 会让日志分类从 `…services.content` 碎成 `…services.content.write` 等 10 个 logger，改变现有日志过滤与告警口径（属 C5 之外的行为变化） | 用 `__name__`：日志分类漂移，运维侧按 logger 名的过滤规则失效 | 各子模块 |
| D8 | 过渡期怎么组织 | P0 引入 `_legacy.py` 承载尚未搬走的符号，`__init__.py` 同时从子模块与 `_legacy` 导出；P3 删除 `_legacy.py` | C8 要求每期可独立编译与全绿；一次性搬迁 1529 行会让单个提交无法评审、也无法定位回归 | 一次性提交全量拆分：违反 C8，且 `git diff` 无法区分「搬运」与「改动」 | `content/_legacy.py`（P3 删除） |
| D9 | 是否需要为拆分补测试 | 新增 1 个结构性测试文件 `tests/test_documents_content_split.py`（导出清单 / 分层 AST 检查 / `_DOCS_DIR` 延迟读取），**其余测试零改动** | I1–I3 是本次的可验证不变量，需要留成回归网；H28 的验证靠「旧测试零改动通过」而非新增 mock 用例 | 只依赖现有测试：`__all__` 遗漏与依赖反向这两类问题现有用例覆盖不到（删掉一个未被调用的导出，全量测试仍绿） | `tests/test_documents_content_split.py` |
| D10 | 是否顺带拆 `obsidian.py`（1712 行，全仓最大） | **不拆**，留作独立需求 | 卡片未决问题已结论；`obsidian.py` 的导入 / 导出 / vault 转换与 content 的耦合仅是调用关系，混入本次会让「零行为变更」无法自证 | 一并拆分：范围从 1 个文件扩到 3212 行，超出批次 3 的成本收益口径 | 无 |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：单文件 1529 行 → 最大约 290 行；「改存储策略」「改回收站子树」「改图谱」各自只需读一个模块；首次显式化公开面（`__all__` 66 项），后续任何导出调整都变成一次显式 diff 而不是隐式副作用；分层约束可静态校验（`storage` 不 import 同包），防止重构后重新长出环。
- **负向**：文件数从 1 增到 11，`grep` 单个符号的定位成本变为「先在 `__init__.py` 看归属再去子模块」；`__init__.py` 成为新的高频改动点（新增导出必须同步 `__all__`，否则 `test_documents_content_split.py` 会红）；`_legacy.py` 过渡期存在「同名符号两处定义」的短暂状态。
- **风险与缓解**：① 导出遗漏 → D9 的清单测试 + `make test` 双保险；② `_DOCS_DIR` 延迟读取写错导致用例写真实目录 → P0 单独跑 `test_documents_storage_gc.py` / `test_workspace_storage_usage.py` 并核对 `tmp_path` 下确有文件；③ 图谱缓存双实例 → D4 单点持有 + `test_documents_link_graph.py` 零改动通过；④ 单期过大 → 按 D8 的 `_legacy` 过渡逐期搬迁。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 私有符号转公开 | `documents.content` 导出名 | 本次**不转**，维持下划线名；转公开另开 ADR 并复用「转公开 + `__all__` 同步 + mock 目标改 canonical」的范式 | ADR 0130 D4 |
| 文档模板绑定 | `documents/content.py`（本次拆分的同一文件） | 0177 在该文件末尾追加了 `export_template_ref` 的写入 / 复制 / 移动清空逻辑，属 `write.py`（`create_document` / `update_content`）与 `duplicate.py`（`_duplicate_node` 复制绑定）；本次搬运**逐字保留**，不改其判定 | ADR 0177 |
| 版本分级存储 | `storage.py` 的 `store_content_bytes` | 压缩阈值 / `gz:` 前缀 / 外存路径以 `docs/REFACTOR_BACKLOG.md` §六与 ADR 0180 C5 为准，本次零改动 | REFACTOR_BACKLOG §六 |
| 图谱可见性 | `graph.py` 的 `build_link_graph` | H33「不可见文档不建节点 / 边」判定随函数整块搬运，不重写 | ADR 0168 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/documents/services/content/` | `tests/test_documents_content_split.py` | ``5840ca05`` |
| P1 | 已落地 | `src/cndb/plugins/documents/services/content/write.py`、`src/cndb/plugins/documents/services/content/trash.py` | `tests/test_documents_content_split.py` | ``f0896e44`` |
| P2 | 已落地 | `src/cndb/plugins/documents/services/content/links.py`、`src/cndb/plugins/documents/services/content/tags.py`、`src/cndb/plugins/documents/services/content/fts.py`、`src/cndb/plugins/documents/services/content/serialize.py` | `tests/test_documents_content_split.py` | ``52f5cb9c`` |
| P3 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 已落地（包结构 + `storage` / `access` / `write` / `trash` / `links` / `tags` / `fts` / `serialize`；`_legacy.py` 从 769 行降到 376 行，只剩 graph 与 duplicate 两组），P3 未开始。
- 下一步：P3 搬 `graph.py`（`GRAPH_MAX_NODES` / 两个 TTL 常量 / `_graph_cache` / `reset_link_graph_cache` / `invalidate_link_graph_cache` / `_prune_graph_cache` / `_broken_node_id` / `build_link_graph`）与 `duplicate.py`（`DUPLICATE_SUFFIX` / `_document_tag_ids` / `_unique_duplicate_title` / `_copy_asset_file` / `duplicate_document` / `_duplicate_node`），随后删除 `_legacy.py` 并去掉结构测试里 1400 行的放宽；`build_link_graph` 内的 `_pkg.load_content(...)` 与 `duplicate` 内的 `_pkg.create_document(...)` 必须继续经包属性解析（D3）。
- 已知坑：
  - `EXTERNAL_MIN_SIZE` 原先是从 `cndb.plugins.documents.models` 导入到 `content` 模块命名空间的**隐式转发**，拆包后三个测试（`test_documents_robustness.py:29`、`test_documents_storage_gc.py:17`、`test_workspace_storage_usage.py:157`）通过 `content_service.EXTERNAL_MIN_SIZE` 取它——P0 已在 `__init__.py` 显式再导出，否则收集期直接 `AttributeError`。
  - 包顶层 `_DOCS_DIR` 的赋值块必须放在 import 之后（放到前面会触发 ruff `E402`）。
  - 删掉 `content.py` 会让 `make adr-check` 报一批 `Related 路径不存在`（历史 ADR 里 `services/content.py` 与带行号的 `content.py:87-96` 全部失效），已统一改成 `services/content/` 目录；改的是「当时的证据路径」，行号一并失效属预期。
  - `_legacy.py` 是过渡文件（1332 行），结构测试对它放宽到 1400 行上限；P3 删除后该放宽项要一起去掉。
  - P1 起 `write.py` / `trash.py` 对同包的 import 只允许 `access` / `storage`（结构测试白名单校验）——写路径需要 `_apply_tags` / `sync_fts` 时**不能** `from .tags import ...`（tags / fts 在 P2 才拆且属上层），一律 `_pkg.<name>(...)` 延迟解析，包内依赖图才保持无环。
  - P2 起 `links.py` / `tags.py` / `fts.py` / `serialize.py` 的依赖白名单分别收紧为 `{access}` / `{}` / `{}` / `{storage}`（结构测试逐文件校验）；`links.py` 的 `repair_wikilinks` 要调 `update_content`（write）与 `serialize_document`（serialize）——两者与 `links` 不同层，一律 `_pkg.<name>(...)`，写 `from .serialize import serialize_document` 会让依赖图出现环并让 monkeypatch 失效。

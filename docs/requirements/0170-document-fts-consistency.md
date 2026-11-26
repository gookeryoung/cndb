# 0170 文档 FTS 索引一致性加固（S1）

- 编号：0170
- 来源 / 提出人：用户（会话 2026-11-26，P0 分析后确认「先做 P0，P2」→「先做 4 项 S1」）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；可见性 H33，流水线只读 H38）
- 状态：已确认范围（2026-11-26 选择「先做 4 项 S1」；卡片约束待复核）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 请分析文档部分功能对照典型知识库应用，功能上还有哪些需补齐完善的。

> 先做 P0，P2。

> （P2 分析结论）搜索一致性：FTS5 应用层同步无触发器、无定时重建；中文 LIKE 兜底。缺口：加索引校验 + 定时重建纳入调度。

补充确认：本卡只做 **FTS 索引一致性校验 + 定时重建**；中文分词优化（trigram 混合方案）在本批另卡 0171。

## 方案（口径）

**范围**：给现有 FTS5 索引（`documents_fts`）增加一致性校验能力与定时重建调度，修复潜在索引漂移。零新表、零迁移（复用已有虚拟表与 `rebuild_fts_index`）；不改检索语法/排序/高亮口径；不改中文兜底逻辑（归 0171）。

**现状问题**：FTS5 无 DB 触发器，全靠应用层在 6 处写路径显式调 `sync_fts` / `_sync_fts_delete`（`content.py:303/407/654`、`563/721`）；备份恢复手动 `ensure_fts_schema` + 删行（`workspace_restore.py:94-98`）。任一条写路径遗漏或异常，索引与正文漂移且无自检。

**校验**：新增 `verify_fts_index(db, *, workspace_id=None) -> FtsConsistencyReport`，比对「未删除文档数」与「FTS 有正文行数（content 非空）」，抽样核对标题/内容哈希；返回 `missing`（文档有、索引缺或空）、`orphan`（索引有、文档无或已删）、`mismatch`（索引内容哈希不符）。只读，不改业务数据（H38）。

**定时**：用 CLI `cndb docs fts-verify`（只读报告）与 `cndb docs fts-rebuild`（重建）承载；在 `app.py` lifespan 启动一个轻量后台线程，按固定周期（默认 6h，环境变量可调）调用校验，发现不一致时记录日志并自动调用 `rebuild_fts_index`，与现有 `start_storage_refresher` / `start_pptx_pdf_sweeper` 同范式；关闭时停止。重建只改 FTS 虚拟表，不改业务数据。

**可见性**：校验与重建覆盖全工作区索引（索引本身非文档可见性载体）；对外不暴露新读接口，CLI 输出不含文档正文，仅含 id 与计数（H38 的「发现物只记定位信息」）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「索引校验」 | 新增 `verify_fts_index()`，输出 missing/orphan/mismatch 三类计数与文档 id 列表；只读不改业务数据（H38） | `services/search.py` | 单测：人为删索引行 / 插孤儿行 / 改内容后校验能正确分类；正常库报 0 |
| C2 | 「定时重建纳入调度」 | CLI 增 `cndb docs fts-verify` / `fts-rebuild`；`app.py` lifespan 启动/停止后台校验线程（默认 6h 周期，env 可调），不一致时自动重建 | `cli/docs.py`、`app.py`、新 `core/fts_refresh.py`（或 services 内） | 单测：mock 周期触发校验→重建；lifespan 启停无残留线程；CLI 参数解析 |
| C3 | 「FTS5 应用层同步」（不回归） | 6 处现有 `sync_fts` / `_sync_fts_delete` 调用点行为不变；重建走 `rebuild_fts_index`，不新开写路径、不改正文 | `services/content.py:303/407/654/563/721` | 既有同步用例不改断言即全绿；重建前后检索结果逐条一致 |
| C4 | （备份兼容） | 备份/恢复仍手动同步 FTS；新增校验不依赖备份格式；旧备份恢复后校验应为 0 | `workspace_restore.py:94-98` | 备份往返 + 校验 0 漂移用例 |
| C5 | （可见性不回归） | 校验输出不含正文与可见性外文档标题，只含 id/计数；不新增对外读接口；H33 用例不改即全绿 | `services/search.py`、`cli/docs.py` | 单测断言输出字段；H33 全绿 |
| C6 | （测试 / 文档） | 同轮补校验单测 + CLI/调度单测；CHANGELOG 增条目；本卡回填落地结果 | 测试文件、`CHANGELOG.md` | `make flow` / `make test` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | FTS 建表 / 重建 | `services/search.py:51 _FTS_CREATE_SQL`、`:443 rebuild_fts_index` | C2 复用 |
| 2 | 写路径同步点 | `services/content.py:303/407/654/563/721`、`:996 sync_fts`、`:1027 _sync_fts_delete` | C3 不改 |
| 3 | 后台线程范式 | `app.py:76-122`（storage / figure / pptx sweeper） | C2 新增同范式线程 |
| 4 | CLI docs | `src/cndb/cli/docs.py:42 cmd_gc` | C2 加子命令 |
| 5 | 备份恢复 FTS | `workspace_restore.py:94-98` | C4 |
| 6 | 检索入口 | `services/search.py:186 search_documents` | C3 不改 |

## 不做

- 中文分词 / trigram 改造（0171）。
- FTS5 触发器（会引入 DB 层写路径，与 H38 「检查只读」及现有应用层同步口径冲突；本卡选校验+定时重建）。
- 新表、新迁移、改 FTS 虚拟表 schema、改检索语法/排序/高亮。
- 对外新增 API 端点（仅 CLI + 内部调度）。

## 卡点

- [ ] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

## 落地结果

- 代码落点：`services/search.py::verify_fts_index` / `rebuild_fts_index`（主表 + trigram 影子表；校验只读标题/正文长度/前 64 字符指纹，不加载完整正文）、`core/fts_refresh.py` 后台校验线程、`cli/docs.py::docs fts-verify|fts-rebuild`、`core/config.py` 三个 FTS 开关、`app.py` lifespan 接入；备份恢复同步两表。trigram 影子表本身的迁移 `c8d9e0f1a2b4` 属需求 0171。
- 测试：`tests/test_documents_fts_consistency.py`（含 0171 用例）；`tests/conftest.py` 补 FTS 虚表清理（裸 SQL 建表不在 `Base.metadata`，不清会跨用例污染）。`make check-fast`、`make test` 全绿。
- 提交 sha：待提交。

# 0171 文档中文搜索优化（S1）

- 编号：0171
- 来源 / 提出人：用户（会话 2026-11-26，P0 分析后确认「先做 P0，P2」→「先做 4 项 S1」）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；可见性 H33，流水线只读 H38）
- 状态：已确认范围（2026-11-26 选择「先做 4 项 S1」；卡片约束待复核）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 请分析文档部分功能对照典型知识库应用，功能上还有哪些需补齐完善的。

> 先做 P0，P2。

> （P2 分析结论）中文搜索性能：中文全文搜索靠 LIKE 兜底，大数据量全表扫描退化。补齐方向：评估 trigram 或外部分词。

补充确认：本卡做 **trigram 混合检索**（影子表），保留现有 LIKE 兜底作为短词（<3 字符）通道；不引入外部分词依赖、不改检索结果口径（命中集合/排序语义）。

## 方案（口径）

**范围**：新增一张 FTS5 `trigram` 影子表 `documents_fts_tri`，与现有 `documents_fts`（unicode61）并行维护；中文长词（≥3 字符）走 trigram 索引命中，避免 LIKE 全表扫描；短词（1-2 字符）与西文维持现有通道。零新运行时依赖、零外部服务；改检索路由与同步写路径 + 一条迁移。

**关键实测（2026-11-26，SQLite 3.53.1）**：
- `trigram` tokenizer 按 **3 字符**切分：`销售管` → 命中、`销售管理` → 命中；`销售`（2 字）→ **0 命中**，`报告`（2 字）→ 0 命中。
- 结论：纯 trigram 无法覆盖 2 字中文查询，必须保留 LIKE 兜底；trigram 只接管 ≥3 字符的中/长词，收益在大库场景。

**判定算法（唯一入口）**：在 `search_documents` 内，先走现有 FTS5 MATCH；`total == 0` 时按 query 的「最大中文连续段长度」分流：
- 若存在 ≥3 字符的中文片段 → 用该片段对 `documents_fts_tri` 做 MATCH，再对候选集用完整 query（含其余词/西文）按现有 AND 语义过滤 → 走既有高亮/排序封装；
- 否则（全为 <3 字符或纯西文）→ 维持 `_search_by_substring`（LIKE）兜底不变。
- 分流只增不减：任何情况下命中集合不得小于改前（trigram 结果 ∪ LIKE 结果 = 改前的 LIKE 覆盖范围）。

**索引维护**：`sync_fts` 同步写 `documents_fts_tri`（同 rowid、同 title/content/summary，content 同样截断 64KB）；`_sync_fts_delete` 同步清空；`rebuild_fts_index` 同步重建两表；`ensure_fts_schema` 幂等建两表；备份恢复的 FTS 同步（`workspace_restore.py:94-98`）扩到两表。迁移创建 trigram 虚拟表 + 存量回填（一次性，幂等）。

**排序/高亮**：trigram 通道无 bm25 语义时，沿用现有 `_search_by_substring` 的「标题命中 > 摘要命中 > 更新时间」映射，保持「rank 越小越靠前」口径；高亮沿用 `_mark`。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「中文搜索靠 LIKE 兜底」 | 新增 `documents_fts_tri` trigram 虚拟表 + alembic 迁移（幂等 + downgrade 可还原 + 存量回填） | 新迁移、`services/search.py:51` | 迁移单测：upgrade/downgrade、存量文档回填后长词命中；重复 upgrade 幂等 |
| C2 | 「大数据量全表扫描退化」 | ≥3 字符中文片段走 trigram MATCH；`<3` 字符或纯西文维持 LIKE 兜底；分流在 `search_documents` 唯一入口 | `services/search.py:186/264/339` | 单测：长词命中 trigram（断言不走 LIKE）、短词命中 LIKE；同一 query 改前改后命中集合不减 |
| C3 | 「不引入外部分词」 | 只用 SQLite FTS5 trigram tokenizer；不新增 Python 依赖、不引入 jieba/ES 等外部服务 | `pyproject.toml`（不变） | `make check-fast` 依赖白名单无新增；检索单测全绿 |
| C4 | 「索引维护」（一致性） | `sync_fts` / `_sync_fts_delete` / `rebuild_fts_index` / `ensure_fts_schema` / 备份恢复同步维护两表；0170 的 `verify_fts_index` 同时校验两表 | `services/content.py:996/1027`、`services/search.py`、`workspace_restore.py:94` | 写路径单测：建/改/删/恢复后两表一致；0170 校验对两表漂移均能报出 |
| C5 | （可见性 / 口径不回归） | 检索结果可见性过滤沿用 H33（`search_documents` 现有 where）；命中集合/排序语义/高亮字段不变 | `services/search.py:218-222` | 既有检索/高亮/H33 用例不改断言即全绿 |
| C6 | （测试 / 文档） | 同轮补迁移 / 分流 / 索引维护 / 口径不回归单测；CHANGELOG 增条目；本卡回填落地结果 | 测试文件、`CHANGELOG.md` | `make flow` / `make test` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | FTS5 建表 / 分段策略 | `services/search.py:1-15`（文档字符串）、`:51 _FTS_CREATE_SQL`、`:72 ensure_fts_schema` | C1/C4 |
| 2 | 检索分流 | `services/search.py:186 search_documents`、`:264 total==0 分支` | C2 |
| 3 | LIKE 兜底 | `services/search.py:339 _search_by_substring` | C2 保留 |
| 4 | 写路径同步 | `services/content.py:996 sync_fts`、`:1027 _sync_fts_delete` | C4 |
| 5 | 重建 | `services/search.py:443 rebuild_fts_index` | C4 |
| 6 | 备份恢复 | `workspace_restore.py:94-98` | C4 |
| 7 | 0170 校验 | `services/search.py`（0170 新增 `verify_fts_index`） | C4 扩到两表 |

## 不做

- 外部分词（jieba / IK / ES）、新运行时依赖、外部服务。
- 改检索结果的命中集合语义（只增不减）、排序语义、高亮格式。
- 改 FTS5 主表 `documents_fts` schema / tokenizer（保持 unicode61）。
- 2 字中文的索引化（trigram 硬约束，保留 LIKE）。
- 前端改动（检索 API 响应结构不变）。

## 未决问题

- [x] 迁移回填策略（2026-11-26 结论）：迁移 `c8d9e0f1a2b4` **只建表**；回填放在 `ensure_fts_schema` 首启检测「trigram 空 + 主表非空」时，从 FTS 主表已截断 64KB 的 content 直接复制（不需要 `load_content` 解分级存储，不引入迁移期 config/外存依赖）。主表数据本身就是同源正文，回填量与主表相同，一次 INSERT…SELECT 完成；实测大库阻塞风险可接受，未采用迁移内分批提交。

## 卡点

- [ ] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

## 落地结果

- 代码落点：`services/search.py`（`documents_fts_tri` trigram 表、`_longest_cjk_term` / `_trigram_candidate_ids`、`_search_by_substring` 候选收窄；≥3 字符走索引、2 字短词仍 LIKE 兜底）、`services/content.py::sync_fts` 双表同步、迁移 `c8d9e0f1a2b4`、备份恢复双表清理。
- 关键取舍：SQLite trigram 实测最少 3 字符（`销售`→0、`销售管`→1），纯 trigram 无法覆盖 2 字中文，故采用「LIKE 兜底 + 长词索引候选收窄」混合方案，命中集合只增不减。
- 测试：`tests/test_documents_fts_consistency.py` 与 `tests/test_documents_search_cjk.py` 全绿（既有 CJK 用例断言未改即通过）。
- 提交 sha：432c771e。

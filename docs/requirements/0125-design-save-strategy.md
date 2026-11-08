# 需求卡片：设计结构保存策略（草稿 / 版本分离）

- 编号：0125（与 ADR `docs/adr/0125-*.md` 同号）
- 来源 / 提出人：用户（产品需求）
- 日期：2026-11-08
- 关联 ADR：`docs/adr/0125-design-save-strategy-draft-separation.md`（Accepted）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。
> 本卡片修订 ADR 0113 需求卡片的 C2 / C3（3s 自动保存落 `auto` 版本的口径）。

## 需求原句（逐字）

> 设计结构，保存过于频繁反而不好区分版本，请结合最佳实践针对保存策略给出建议供选择。

## 已确认口径（2026-11-08 需求方选择）

| # | 问题 | 结论 |
|---|---|---|
| Q1 | 保存策略选型 | **A 草稿 / 版本分离**：自动保存只写个人草稿不留版本；手动保存才落 `manual` 版本 |
| Q2 | 草稿归属粒度 | **每人一份**（`design_id + user_id` 唯一），多人编辑互不覆盖 |
| Q3 | 兜底检查点 | **保留**：连续编辑距上次版本满 10 分钟且内容有变化，服务端落一条 `auto` 检查点 |
| Q4 | 草稿是否进备份 | **不纳入**工作区备份；恢复工作区时清空草稿，备份协议保持 v15 |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「保存过于频繁反而不好区分版本」 | 自动保存**不再创建版本**：3s 防抖只写个人草稿，`design.content` / 最新版本号 / 版本列表均不变 | `plugins/design/`、`frontend/src/pages/design/DesignEditorPage.tsx` | 接口层断言自动保存后版本数不变；前端单测断言只调草稿接口 |
| C2 | 「保存过于频繁反而不好区分版本」 | 草稿持久化：`design_designdraft`（每人每设计一份），保存停止输入 3s 后写入；内容与最新版本一致时删除草稿（等价于无修改） | `plugins/design/models.py`、`services/drafts.py` | 单测 / 接口：新建、覆盖、同内容删除 |
| C3 | 隐含（版本语义） | 只有手动保存（按钮 / Ctrl+S）才落 `manual` 版本；内容等于最新版不落版；最新版为 `auto` 时把该行提升为 `manual`（沿用 ADR 0113 D7） | `plugins/design/routers.py` | 接口：保存落版 / 去重 / 提升 |
| C4 | 「结合最佳实践」 | 兜底检查点：保存草稿时若距最新版本创建时间 ≥10 分钟且内容不同，服务端编译成功后更新当前内容并落一条 `auto` 版本；编译失败不落版、草稿保留 | `plugins/design/routers.py`、`services/drafts.py` | 接口：检查点到期 / 未到期 / 编译失败 |
| C5 | 「结合最佳实践」 | 崩溃恢复：打开设计时若本人草稿存在且与最新版不同，明确提示「恢复上次编辑 / 丢弃」；恢复后编辑器载入草稿内容 | `frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/api/design.ts` | 前端单测 + e2e |
| C6 | 隐含（权限） | 草稿仅 editor 本人读写（viewer 403）；草稿不进入版本列表 / diff / 他人查询 | `routers.py`、`schemas.py` | 接口权限用例 |
| C7 | 隐含（存量兼容） | 存量 `auto` 版本保留可看可 diff；迁移只新增草稿表，不改 `design_design` / `design_designversion`，`downgrade` 可还原 | `src/cndb/alembic/versions/` | 迁移升级 / 降级 / 幂等 |
| C8 | 隐含（备份口径） | 草稿不导出、不导入；覆盖恢复工作区时清空该工作区设计草稿；备份协议仍 v15 | `workspaces/services/workspace_backup.py`、`backup_io.py`、`workspace_restore.py` | 备份载荷断言 + 恢复后草稿计数为 0 |
| C9 | 隐含（交互一致性） | 自动保存状态文案改为「草稿已保存 / 草稿保存失败」；手动保存、刷新、恢复前取消 pending 草稿保存；同一时刻单个写在途 | `DesignEditorPage.tsx` | 前端单测 |
| C10 | 隐含（测试与文档） | 判定 / 接口 / 迁移 / 前端单测 / e2e 分层覆盖；CHANGELOG 与 ADR 索引同步 | 全链路 | `make check-fast` / `make flow` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 设计文件当前内容 | `src/cndb/plugins/design/models.py:61-67` | 自动保存会推进 `content` 与最新版本号 |
| 2 | 保存去重与主动提升 | `src/cndb/plugins/design/routers.py:529-537` | 需与新草稿写路径共存 |
| 3 | 前端 3s 自动保存 | `frontend/src/pages/design/DesignEditorPage.tsx:324-368` | 改为写草稿，不再传 `change_type=auto` |
| 4 | 文档草稿先例 | `src/cndb/plugins/documents/models.py:233-259`、`services/drafts.py` | 复用「每人一份 + base_version_number」范式 |
| 5 | 备份 designs 段 | `src/cndb/plugins/workspaces/services/workspace_backup.py:577-615` | 不含草稿，无需改载荷 |
| 6 | 覆盖恢复清理顺序 | `src/cndb/plugins/workspaces/services/workspace_restore.py:132-136` | 需补草稿表清理 |
| 7 | 迁移 head | `src/cndb/alembic/versions/b0c1d2e3f4a5_add_workspace_project_context.py` | 新迁移以此为 `down_revision` |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- 无（Q1-Q4 已由需求方确认；剩余实现细节由 ADR 决策记录给出）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

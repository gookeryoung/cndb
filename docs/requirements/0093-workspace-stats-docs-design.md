# 需求卡片：工作区设置统计补充「文档 / 设计」计数

- 编号：0093
- 来源 / 提出人：用户（会话 2026-11-04）
- 日期：2026-11-04
- 关联 ADR：无（S1，方案并入本卡片；统计缓存口径见 ADR 0046）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 工作区展开面板，工作区设置的统计信息，需补充文档、设计相关的统计信息

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「工作区设置的统计信息」 | **2026-11-08 更新**：统计信息已并入「基本设置」顶部统计概览；统计卡片补充「文档」「设计」两项：`GET /{wid}` 详情新增 `document_count` / `design_count` | `workspaces/routers/workspaces.py`、`workspaces/schemas/models.py`、`workspaces/services/stats_cache.py`、`frontend/src/pages/settings/WorkspaceSettingsContent.tsx` | 接口层：详情返回两个整数字段且与库内数据一致；前端：统计网格出现两张卡片 |
| C2 | （计数口径） | 文档数 = 未删除且非文件夹的 `documents_document`；设计数 = 未软删的 `design_design`；回收站 / 软删内容不计入 | `workspaces/services/stats_cache.py` | 单测：2 文档 + 1 文件夹 + 1 回收站文档 → 2；1 设计 + 1 软删设计 → 1 |
| C3 | （新鲜度） | 两个计数**不进** 30s 的 `workspace-stats` 缓存：文档 / 设计写路径没有统一缓存事件，缓存会展示旧值；改为详情请求实时两次索引 COUNT（ADR 0046 口径补充） | 同上 + `docs/adr/0046-web-performance-bottlenecks.md` | 单测：新增文档 / 设计后立即读详情即生效 |
| C4 | （模块门控） | 统计卡片按工作区模块显示：未启用「文档」/「设计」模块的工作区不展示对应卡片（与顶部页签、设置模块开关同口径） | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx`、`utils/workspaceModules.ts` | 前端单测：默认三模块显示两张卡片；`modules: ['tables']` 不显示 |
| C5 | （文档口径） | CHANGELOG 记录新增；CONTEXT 术语补充统计口径 | `CHANGELOG.md`、`CONTEXT.md` | `make check-docs` |
| C6 | 「工作区展开详情页需要显示文档、设计等信息（如有）」 | 工作区列表接口（`GET /workspaces`）同样返回 `document_count` / `design_count`（分组 COUNT，随列表 10s 缓存）；展开详情页按已启用模块渲染「文档」「设计」区块：`共 N 篇 / 共 N 个` + 直达模块页入口，计数为 0 时给空态文案，模块未启用不渲染 | `workspaces/routers/workspaces.py`、`workspaces/schemas/models.py`、`frontend/src/pages/workspace/WorkspaceList.tsx` | 后端单测：列表携带计数；前端单测：展开显示文档 5 篇 / 设计 2 个与跳转、模块未启用不渲染 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区设置「基本设置」顶部统计概览 | `frontend/src/pages/settings/WorkspaceSettingsContent.tsx`（`statItems`） | C1/C4 新增文档 / 设计卡片 |
| 2 | 工作区详情接口统计字段 | `workspaces/routers/workspaces.py`（`get_workspace`） | C1/C3 新增两个字段 |
| 3 | 工作区统计缓存 | `workspaces/services/stats_cache.py` | C3 计数不进缓存（避免旧值） |
| 4 | 详情响应 schema / 前端类型 | `workspaces/schemas/models.py`、`frontend/src/api/types/workspaces.ts` | C1 字段透传 |
| 5 | 工作区展开详情页 | `frontend/src/pages/workspace/WorkspaceList.tsx`（`WorkspaceRowDetail`） | C6 新增文档 / 设计区块 |
| 6 | 列表接口统计 | `workspaces/routers/workspaces.py`（`_list_workspaces_uncached`）、`WorkspaceWithPinnedResponse` | C6 列表也带两个计数 |

## 未决问题（已确认）

- [x] ① 文档数口径：**结论**不含文件夹与回收站内容（与文档树「文档」节点口径一致）。
- [x] ② 设计数口径：**结论**未软删的设计文件数（零件 / 装配都算）。
- [x] ③ 是否共享 30s 统计缓存：**结论**不共享，实时计算（写路径无统一缓存事件，缓存会滞后）。
- [x] ④ 方案分级：**结论**S1（只读统计字段 + 前端卡片，无数据模型变更）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-04 用户口述）

# 需求卡片：草稿修改预览入口收编 —— 草稿纳入版本历史

- 编号：0062（S1，无 ADR）
- 来源 / 提出人：需求方（会话确认）
- 日期：2026-10-28
- 关联 ADR：无（S1 常规功能，方案写入本卡片「口径」节）

> 本卡片是**需求原文与约束编号的唯一副本**。

## 需求原句（逐字）

> 移除草稿修改预览的查看修改按钮，把草稿版本纳入版本历史中，增加当前草稿并标记为当前，将原已发布版本标记为已发布。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 移除草稿修改预览的查看修改按钮 | 删除编辑页两处「查看修改」入口（窄屏图标按钮与顶栏按钮组 `data-testid=doc-draft-diff-btn`）与草稿 diff 独立抽屉（标题「草稿修改预览」） | frontend DocumentEditorPage | 前端单测：编辑页不再出现 doc-draft-diff-btn |
| C2 | 把草稿版本纳入版本历史中，增加当前草稿 | 版本历史抽屉顶部插入「当前草稿」伪条目（仅当存在草稿）：Tag「当前」、文案「基于 v{base} 的未提交修改（仅自己可见）」；「变更」按钮抛 `{base: draft.baseVersion, head: 0}`（head=0 为草稿哨兵，diff 面板走 `GET …/draft/diff`），无回滚按钮 | frontend VersionsDrawer / DocumentEditorPage | 前端单测：version-item-draft 存在、点 toggle-draft 抛 {base,head:0}、diff 内容来自 draft/diff |
| C3 | 将原已发布版本标记为已发布 | 存在草稿时原最新版本 Tag 由「当前」改为「已发布」（blue）；无草稿时维持「当前」不变 | frontend VersionsDrawer | 前端单测：有草稿时 getAllByText('已发布')、无草稿行为不变 |
| C4 | （由 C1 派生）草稿丢弃入口保留 | 「丢弃草稿」链路不受影响（discardMut 成功后关闭展开的 diff）；草稿条目不提供回滚 | frontend DocumentEditorPage | 既有单测回归 |
| C5 | （回归口径）无草稿行为不变 | 无草稿文档的版本历史 UI 与交互完全不变 | frontend VersionsDrawer | 既有 VersionsDrawer 用例全过 |

## 口径（方案）

- `VersionDiffPair` 语义扩展：`head=0` 表示当前草稿（哨兵值），注释写明。
- VersionsDrawer 新增可选 prop `draft?: { baseVersion: number } | null`；map 内 `hasDraft = draft != null`，`isCurrent = idx===0 && !hasDraft`，`isPublishedHead = idx===0 && hasDraft`。
- testid：`version-item-draft` / `version-diff-toggle-draft`；diff 面板 `headLabel` 草稿对显示「草稿」。
- DocumentEditorPage：删 `draftDiffOpen` / `draftDiffQuery` / 草稿 diff Drawer / 两处按钮；`diffQuery.queryFn` 按 `head===0` 三元路由到 `documentsApi.getDraftDiff`；`discardMut.onSuccess` 改 `setDiffPair(null)`；向 VersionsDrawer 传 `draft={serverDraft ? { baseVersion: serverDraft.base_version_number } : null}`。
- 紧凑化随本次一并落地（前期会话已确认）：操作按钮并入卡头右侧 text 小按钮「变更 / 回滚」，summary 单行省略 + title，间距收紧。

## 未决问题

- [x] 草稿 diff 的数据来源？→ 复用既有 `GET /api/v1/workspaces/{wid}/documents/{doc_id}/draft/diff`（ADR 0057），前端按 head===0 路由。
- [x] 是否需要 ADR？→ S1，无架构分叉，不强制；卡片即方案。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（会话内确认）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

## 落地状态

| 期 | 内容 | 状态 |
|---|---|---|
| 全量 | C1-C5 一次落地 | 待提交 |

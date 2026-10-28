# 需求卡片：文档草稿 — 修改内容查看（diff）、保存与丢弃

- 编号：0057（与 ADR `docs/adr/0057-*.md` 同号）
- 来源 / 提出人：用户（会话 2026-10-28）
- 日期：2026-10-28
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 文档，草稿，应当支持修改内容查看（只看diff），保存，丢弃等功能。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 修改内容查看（只看diff） | 编辑页存在草稿时，可一键查看「基准版本 → 草稿」的 unified diff，复用现有 `parse.unified_diff` 与前端 DiffView 组件；无草稿时不出现该入口 | backend documents / frontend DocumentEditorPage | 后端单测 + 前端单测 |
| C2 | 保存 | 已有 `PUT /{doc_id}/draft` 保持语义不变（只写个人草稿、不生成版本）；本需求不改其行为，仅确保 UI 入口可用 | 已实现，核对即可 | 既有测试回归 |
| C3 | 丢弃 | 前端编辑页提供「丢弃草稿」入口，调用既有 `DELETE /{doc_id}/draft` 并有确认提示；丢弃后回到最新版本内容，清空草稿态 | frontend DocumentEditorPage + api/documents | 前端单测 + e2e |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 草稿保存/提交/删除服务 | `src/cndb/plugins/documents/services/drafts.py` | 已实现，C2/C3 后端零改动或微改 |
| 2 | 草稿 REST 端点 | `src/cndb/plugins/documents/routers/documents.py:480-527` | GET/PUT/DELETE /draft 齐备 |
| 3 | 版本 diff 端点 | `src/cndb/plugins/documents/routers/documents.py:948` | GET /{doc_id}/diff，可参考新增草稿 diff |
| 4 | diff 计算 | `src/cndb/plugins/documents/services/parse.py:218` | unified_diff 复用 |
| 5 | 修改申请 diff 载荷 | `src/cndb/plugins/documents/services/change_requests.py:152` | diff_payload 模式可借鉴 |
| 6 | 前端丢弃 API 未接线 | `frontend/src/api/documents.ts:539` | discardDraft 已定义、无调用方 |
| 7 | 前端 DiffView 组件 | `frontend/src/components/DiffView/` | 版本对比已用，草稿 diff 可复用 |
| 8 | 编辑页草稿态 | `frontend/src/pages/documents/DocumentEditorPage.tsx:261-297` | serverDraft 状态、草稿标签已有 |

## 未决问题

- [x] Q1（C1 diff 基准）：以 `base_version_number`（编辑基准版本）为基准（与提交校验口径一致）；stale（文档已前进版本）时在 diff 中附带 stale 提示。已确认 2026-10-28。
- [x] Q2（C1 入口形态）：编辑页顶部「查看修改」按钮 + 抽屉，复用现有 DiffView 组件。已确认 2026-10-28。
- [x] Q3（C3 丢弃后跳转）：丢弃后载入最新版本内容并切回查看模式。已确认 2026-10-28。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-10-28 三个决策点均已拍板）

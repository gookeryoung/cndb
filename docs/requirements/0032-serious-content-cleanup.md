# 需求卡片：平台内容严肃化（清理菜谱类示例与「内容型浏览」文案）

- 编号：0032（与 ADR `docs/adr/0032-serious-content-cleanup.md` 同号）
- 来源 / 提出人：产品需求（会话提出）
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0032-serious-content-cleanup.md`
- 范围确认（2026-10-25，用户选择）：仅清理菜谱 / 美食相关；替换场景为「行业政策与合规台账」；大模型推荐提示词中「美食推荐做法」替换为同场景严肃预设。

## 需求原句（逐字）

> 平台内容需要更严肃，请清理【适合资讯、菜谱等内容型数据浏览与分享】这一类包含【菜谱】等非严肃内容，制定整改计划。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 平台内容需要更严肃 | 示例资产、帮助文案、界面提示与推荐提示词统一为政策 / 情报 / 运营等业务场景；面向用户的内容中不出现「菜谱 / 美食 / 家庭菜单 / 每日推荐」等生活娱乐表述（`CHANGELOG.md`、既有需求卡片与既有 ADR 的历史记录除外，见 C4） | `examples/datasets/工作区-数据源示例/`、`frontend/src/pages/help/`、`frontend/src/pages/grid/`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`src/cndb/plugins/help/services/examples.py`、`src/cndb/plugins/llm/services/prompts.py` | 全仓 `grep` 菜谱 / 美食 / 菜名 / 菜系 / 烹饪 / 分步做法，命中仅剩历史记录文件 |
| C2 | 清理【适合资讯、菜谱等内容型数据浏览与分享】这一类 | 删除该句及其同义表述，改写为「适合政策、情报、简报等长文本业务数据的阅读与分享」：帮助教程、视图工具栏 tooltip、画廊配置注释、画廊组件头注释共 4 处同口径 | `frontend/src/pages/help/content/tutorials.tsx:32`、`frontend/src/pages/grid/GridPage.tsx:133`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts:404`、`frontend/src/pages/grid/views/GalleryView.tsx:1` | 前端单测 + 帮助文档 e2e 文案断言 |
| C3 | 包含【菜谱】等非严肃内容 | 删除「美食推荐做法」全套示例资产，原位替换为「行业政策与合规台账」：8 行 CSV、字段必填设置、5 个视图、1 条 `llm_prompt` 同步任务、帮助示例清单条目、1 组推荐提示词；画廊 / 看板 / 过滤 / 图表四类视图展示能力不减 | `examples/datasets/工作区-数据源示例/`、`src/cndb/plugins/help/services/examples.py`、`frontend/src/pages/datasource/llmPromptPresets.ts` | seed 幂等测试 + 帮助示例接口测试 + e2e 卡片数断言 |
| C4 | 制定整改计划 | 本轮只交付需求卡片 + ADR（`Proposed`），不改任何代码 / 示例数据；评审通过后按 ADR 分期实施；`CHANGELOG.md`、`docs/requirements/0019|0022` 的需求原句作为历史记录保留不改写，ADR 0019 / 0022 中失效的示例条目改写为指向 ADR 0032 的当前口径 | `docs/requirements/0032-*.md`、`docs/adr/0032-*.md`、`docs/adr/README.md` | `make check-docs` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 示例 CSV「美食推荐做法」 | `examples/datasets/工作区-数据源示例/美食推荐做法.csv` | 8 行菜谱数据，需整体替换 |
| 2 | 示例字段必填设置 | `examples/datasets/工作区-数据源示例/fields.json:7-10` | 菜名 / 菜系必填 |
| 3 | 示例视图配置 | `examples/datasets/工作区-数据源示例/views.json:133-204` | 5 个视图，字段全部为菜谱字段 |
| 4 | 数据源同步种子 | `examples/datasets/工作区-数据源示例/datasource.json:5-60` | 美食 `llm_prompt` 任务与中文字段映射 |
| 5 | 帮助示例清单 | `src/cndb/plugins/help/services/examples.py:121-143` | 摘要 / 表条目 / 亮点含美食与菜谱 |
| 6 | 帮助教程文案 | `frontend/src/pages/help/content/tutorials.tsx:32` | 需求原句出处 |
| 7 | 画廊工具栏提示 | `frontend/src/pages/grid/GridPage.tsx:133` | 「适合资讯阅读与分享」 |
| 8 | 画廊配置 / 组件注释 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts:404`、`frontend/src/pages/grid/views/GalleryView.tsx:1` | 「资讯 / 菜谱等内容型表」 |
| 9 | 推荐提示词预设 | `frontend/src/pages/datasource/llmPromptPresets.ts:106-119` | `food_recipes`（7 组中的 1 组） |
| 10 | 默认系统提示词 | `src/cndb/plugins/llm/services/prompts.py:36` | 「美食做法」作为综述示例 |
| 11 | 后端 / 前端测试 | `tests/test_seed_datasource.py:177`、`tests/test_datasource_llm_provider.py:216-225`、`frontend/src/pages/datasource/llmPromptPresets.test.ts:46,125`、`frontend/src/test/msw.ts:179` | 硬编码表名 / 菜谱字段 / 文案 |
| 12 | e2e 画廊用例 | `frontend/tests/e2e/critical/gallery-view.spec.ts:5,60-69` | 断言「美食推荐做法」8 张卡 |
| 13 | 帮助图示 | `src/cndb/plugins/help/services/figures/registry.py:147-155` | 按示例清单与 CSV 指纹自动重建，需核验新图 |
| 14 | 文档口径 | `CONTEXT.md:31`、`docs/adr/0019-*.md`、`docs/adr/0022-*.md` | 示例同步任务与预设描述 |
| 15 | 存量已 seed 环境 | 部署实例数据库 | 旧「美食推荐做法」表 / 视图 / 任务仍在，需明确处置口径 |

## 未决问题

- [x] 整改范围 → 仅菜谱 / 美食相关，保留「国际形势发展动态」「天气每日」两张中性示例（2026-10-25 用户确认）
- [x] 替换场景 → 行业政策与合规台账（2026-10-25 用户确认）
- [x] 推荐提示词处理 → 用同场景严肃预设替换，预设总数保持 7 组（2026-10-25 用户确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认（范围 / 场景 / 预设三项已确认，待需求方对卡片整体拍板）

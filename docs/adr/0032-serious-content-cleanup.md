# ADR 0032: 平台内容严肃化（移除菜谱类示例与「内容型浏览」文案）

Status: Accepted
Date: 2026-10-25
Related: `docs/requirements/0032-serious-content-cleanup.md`、`examples/datasets/工作区-数据源示例/views.json`、`examples/datasets/工作区-数据源示例/fields.json`、`examples/datasets/工作区-数据源示例/datasource.json`、`src/cndb/plugins/help/services/examples.py`、`src/cndb/plugins/help/services/figures/registry.py`、`frontend/src/pages/help/content/tutorials.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/views/GalleryView.tsx`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`src/cndb/plugins/llm/services/prompts.py`、`tests/test_seed_datasource.py`、`tests/test_help_examples_api.py`、`frontend/tests/e2e/critical/gallery-view.spec.ts`、`CONTEXT.md`、`docs/adr/0019-llm-prompt-config-simplify.md`、`docs/adr/0022-gallery-view-content-tables.md`
需求卡片: `docs/requirements/0032-serious-content-cleanup.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 平台内容需要更严肃 | 面向用户的内容（示例数据、帮助文案、界面提示、推荐提示词、默认系统提示词）统一为政策 / 情报 / 运营业务场景；`grep 菜谱|美食|菜名|菜系|烹饪|分步做法` 只允许命中 `CHANGELOG.md`、需求卡片 0019 / 0022 原句与本文档的历史说明 |
| C2 | 清理【适合资讯、菜谱等内容型数据浏览与分享】这一类 | 4 处同口径改写为「适合政策、情报、简报等长文本业务数据的阅读与分享」：帮助教程、画廊工具栏 tooltip、`viewOptionSchema` 注释、`GalleryView` 头注释；画廊能力、schema、只读语义不变 |
| C3 | 包含【菜谱】等非严肃内容 | 「美食推荐做法」整套资产（CSV + 字段必填 + 5 个视图 + 1 条同步任务 + 帮助清单条目 + 1 组推荐提示词）原位替换为「行业政策与合规台账」，字段与视图设计见 §4；视图类型、数量与展示能力不减 |
| C4 | 制定整改计划 | 本轮仅交付卡片 + 本 ADR（`Proposed`），零代码改动；代码 / 示例 / 测试 / 文档按 §9 分期实施；`CHANGELOG.md` 与需求卡片 0019 / 0022 的原句作为历史记录保留，ADR 0019 / 0022 中绑定美食示例的失效条目改写为指向本 ADR 的当前口径 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `美食推荐做法.csv` 8 行菜谱数据（烹饪时长 / 菜系 / 难度 / 菜名 / 主要食材 / 分步做法 / 小贴士） | `examples/datasets/工作区-数据源示例/美食推荐做法.csv:1` | seed 建表与帮助下载均为生活娱乐内容 | 确认（C3） |
| 2 | 必填设置挂 `菜名` / `菜系` | `examples/datasets/工作区-数据源示例/fields.json:7-10` | 换表后必填字段失效 | 确认（C3） |
| 3 | 5 个视图（菜谱画廊 / 全部菜谱 / 按菜系看板 / 快手菜 / 菜系与时长概览）全部引用菜谱字段 | `examples/datasets/工作区-数据源示例/views.json:133-204` | 换表后字段引用全部 400 / seed 校验失败 | 确认（C3） |
| 4 | 「美食推荐做法（大模型动态拉取）」任务：菜谱 prompt、中文映射与 `菜名 + 菜系` 幂等键 | `examples/datasets/工作区-数据源示例/datasource.json:5-60` | 示例任务本身即菜谱内容 | 确认（C3） |
| 5 | 帮助示例清单：摘要「覆盖资讯、美食与天气」、菜品条目、亮点「画廊视图阅读资讯与菜谱」 | `src/cndb/plugins/help/services/examples.py:121-143` | 帮助页与下载白名单暴露菜谱资产 | 确认（C3） |
| 6 | 帮助教程原句「适合资讯、菜谱等内容型数据浏览与分享」 | `frontend/src/pages/help/content/tutorials.tsx:32` | 需求原句出处 | 确认（C2） |
| 7 | 画廊按钮 tooltip「适合资讯阅读与分享」 | `frontend/src/pages/grid/GridPage.tsx:133` | 同义表述残留 | 确认（C2） |
| 8 | 配置注释「资讯 / 菜谱等内容型表的阅读态」；组件头注释「内容型数据表」 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts:404`、`frontend/src/pages/grid/views/GalleryView.tsx:1` | 开发侧口径同上 | 确认（C2） |
| 9 | `food_recipes` 预设：名称 / 说明 / 7 个菜谱字段 / 长文本控制 prompt | `frontend/src/pages/datasource/llmPromptPresets.ts:106-119` | 推荐提示词直接产出菜谱 | 确认（C3） |
| 10 | 默认系统提示词把「美食做法」列为综述类任务示例 | `src/cndb/plugins/llm/services/prompts.py:36` | 模型口径仍在暗示生活内容 | 确认（C1） |
| 11 | 测试硬编码：种子任务表名 `["美食推荐做法", "国际形势发展动态"]`；provider 用例用 `菜名` / `宫保鸡丁`；预设测试断言名称与「每类 2 道，共 8 道」；msw 亮点「画廊视图阅读资讯」 | `tests/test_seed_datasource.py:177`、`tests/test_datasource_llm_provider.py:216-225`、`frontend/src/pages/datasource/llmPromptPresets.test.ts:46,125-131`、`frontend/src/test/msw.ts:179` | 换表后测试必红 | 确认（C3） |
| 12 | e2e「美食推荐做法 → 菜谱画廊 8 张卡」 | `frontend/tests/e2e/critical/gallery-view.spec.ts:5,60-69` | 同上 | 确认（C3） |
| 13 | 帮助图示按示例清单与 CSV 指纹自动重建（每个示例表一张「真实数据预览」） | `src/cndb/plugins/help/services/figures/registry.py:147-155` | 替换 CSV 后图自动重建，无需改图代码 | 排除（无需改代码） |
| 14 | `CONTEXT.md` 口径「两条 `llm_prompt`：美食推荐做法 / 国际形势发展动态」 | `CONTEXT.md:31` | 术语与种子口径需同步 | 确认（C3） |
| 15 | ADR 0019 §7 预设条目与 ADR 0022 示例表 / 视图设计节绑定美食示例 | `docs/adr/0019-llm-prompt-config-simplify.md:316,410-425`、`docs/adr/0022-gallery-view-content-tables.md:146-154,198` | 需求变更后属失效条目，须清理改写 | 新增（C4） |
| 16 | 存量已 seed 的部署实例仍保留旧表 / 视图 / 同步任务 | 实例数据库 | 不做自动删除会残留旧内容 | 新增（C1/C4） |

**核心缺陷（需求要补的）**：示例资产与产品文案把画廊视图定位成「资讯 / 菜谱」消费类内容，与平台面向企业 / 政务的严肃业务定位冲突；而示例是用户理解能力的第一入口，生活娱乐内容会直接拉低平台气质。

设计目标（不变量）：

- **I1 内容严肃**：面向用户的内容（示例、帮助、提示词、界面文案）零菜谱 / 美食 / 家庭菜单表述，统一政策 / 情报 / 运营口径。
- **I2 能力不减**：替换后仍以同一张表展示画廊 + 网格 + 看板 + 过滤 + 图表五类视图，图文示例与 e2e 覆盖不降级。
- **I3 零结构变更**：不改 `view_type` 枚举、画廊 schema、后端接口与数据库结构，不做 alembic 迁移。
- **I4 种子规模恒定**：数据源示例工作区仍为 3 张表、2 条 `llm_prompt` 任务；推荐提示词仍为 7 组；ADR 0029 的「18 个示例表文件」计数不变。

## Decision

### 1. 数据模型

无。gallery 仍是既有 `view_type`，`DataView.view_type` 自由字符串、`view_options` 结构不变；本 ADR 只更换示例数据与文案，零迁移。

### 2. 判定算法（唯一入口）

无。seed 仍沿用既有幂等口径：按工作区 + 表名（= CSV 文件名）建表、按同名更新视图 / 字段必填 / 同步任务；替换后新表名 `行业政策与合规台账`。

### 3. API 变更清单

无。帮助示例接口、图示接口、视图接口、数据源接口均不改签名与返回结构。

### 4. 示例资产设计（替换后的数据与视图）

**表结构与数据**：`examples/datasets/工作区-数据源示例/行业政策与合规台账.csv`，8 行，字段（中文，首列不带系统 `id`，沿用 ADR 0022 D7）：
`日期, 发文机构, 政策类型, 标题, 摘要, 合规要求, 适用部门, 风险等级, 落实状态, 生效日期, 链接`。

- 类型推断：`日期` / `生效日期` 为日期；`风险等级`（高 / 中 / 低）、`落实状态`（已落实 / 推进中 / 待落实）、`政策类型`（办法 / 通知 / 规划 / 征求意见）低基数，由既有 `promote.py` 自动提升 select，供看板与标签使用。
- 必填：`日期`、`标题`（`fields.json`）。
- 同步任务：`行业政策与合规台账（大模型动态拉取）`，`provider=llm_prompt`、`schedule.mode=manual`，幂等键 `日期 + 发文机构 + 标题`，字段映射同上；prompt 与预设保持一致（§7）。

**5 个视图**（`views.json`，与原示例同数量、同类型组合）：

| # | 名称 | 类型 | 关键配置 |
|---|---|---|---|
| 0 | 政策台账画廊（默认） | gallery | `title_field=标题`、`summary_field=摘要`、`tag_fields=[政策类型,风险等级]`、`meta_fields=[发文机构]`、`date_field=日期`、`summary_lines=4`；sortings `[日期 desc, 标题 asc]` |
| 1 | 全部政策 | grid | sortings `[日期 desc, 标题 asc]` |
| 2 | 按发文机构看板 | kanban | `group_field=发文机构`、`title_field=标题`、`priority_field=风险等级`、`card_fields=[政策类型,生效日期]` |
| 3 | 待落实政策 | grid | filters `落实状态 = 待落实`；sortings `[生效日期 asc, 标题 asc]` |
| 4 | 政策类型与风险概览 | chart | `charts[]`：柱状图 `政策类型`（count）+ 饼图 `风险等级`（count） |

**帮助示例清单**（`examples.py`）：摘要改为「把外部数据按计划写入数据表，覆盖政策、情报与运营监测三类业务内容，适合练习数据接入与画廊阅读」；表条目替换为 `行业政策与合规台账.csv`；亮点改为「画廊视图阅读政策台账与情报简报」。

### 5. 边界与例外

1. **存量环境不自动删除**：旧「美食推荐做法」表 / 视图 / 同步任务属实例内数据，自动删除有误删风险；升级说明给出人工清理路径（工作区表管理删除表、数据源同步删除任务）。新装 / 重 seed 环境不含旧内容。
2. **历史记录不追溯改写**：`CHANGELOG.md`、需求卡片 0019 / 0022 的「需求原句」保留原文（历史事实）；ADR 0019 / 0022 的失效示例条目按规则改写，不留「历史方案」段落。
3. **保留的示例**：`国际形势发展动态`（情报研判）与 `天气每日`（观测数据）保留，不属本次清理范围。
4. **帮助图示重建**：CSV 指纹变化会触发 `example-datasource-table-N` 重建；实施后需核验图示清单与 SVG 内容，无需改构建代码。

### 6. 迁移

无 alembic 迁移；`cndb seed` 幂等重跑即新增新表。存量实例清理见 §5 第 1 条。

### 7. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 帮助教程 | `frontend/src/pages/help/content/tutorials.tsx` | 画廊段落改写为「适合政策、情报、简报等长文本业务数据的阅读与分享」 |
| 视图工具栏 | `frontend/src/pages/grid/GridPage.tsx` | gallery tooltip 同上口径 |
| 视图配置 | `frontend/src/pages/grid/view-config/viewOptionSchema.ts` | 注释改为「长文本业务数据（政策 / 情报 / 简报）的阅读态」 |
| 画廊组件 | `frontend/src/pages/grid/views/GalleryView.tsx` | 头注释「内容型数据表」改为「长文本业务数据表」 |
| 推荐提示词 | `frontend/src/pages/datasource/llmPromptPresets.ts` | `food_recipes` 替换为 `policy_compliance`（行业政策与合规台账）：字段同 §4，幂等键 `日期 + 发文机构 + 标题`，prompt 要求输出 JSON、字段名中文、去重键稳定；与既有 `policy_tracker`（政策公告跟踪）区分：后者跟踪外部政策发布，本预设面向合规要求落地（合规要求 / 适用部门 / 落实状态 / 风险等级） |
| 默认系统提示词 | `src/cndb/plugins/llm/services/prompts.py` | 综述类示例「美食做法」改为「合规解读」 |
| 测试夹具 | `frontend/src/test/msw.ts` | 帮助亮点文案改为「画廊视图阅读政策与情报简报」 |

### 8. 测试清单

**判定层（单测）**：

- `frontend/src/pages/datasource/llmPromptPresets.test.ts`：7 组不变；`food_recipes` 断言改为 `policy_compliance`（名称、字段、幂等键子集）；「控制输出规模」用例改为「长文本字段分别截断说明」或删除该条并保留通用字段断言。
- `frontend/src/pages/grid/viewModes.test.ts` / `viewOptionSchema.test.ts`：不受影响，回归确认。
- `frontend/src/pages/help/ExamplesSection.test.tsx`、`HelpDocsPage.test.tsx`：按接口 fixture 渲染，确认新清单可渲染。

**接口层**：

- `tests/test_seed_datasource.py`：种子任务表名断言改为 `["行业政策与合规台账", "国际形势发展动态"]`；真实 `datasource.json` 结构合法性校验通过。
- `tests/test_datasource_llm_provider.py`：provider 用例的字段样例改为新字段（如 `标题` / `风险等级`），断言类型归一（`生效日期` 解析、`风险等级` 文本）不变。
- `tests/test_help_examples_api.py`：清单含新文件名、下载白名单可下载、旧文件名返回 404。
- `tests/test_views_api.py`、`tests/test_backup_seed_roundtrip.py`：seed 视图字段引用校验通过（新字段全为中文真实字段）。

**迁移 / 备份**：无迁移；`test_backup_seed_roundtrip.py` 回归确认 seed 往返不因换表报错。

**e2e（前端）**：

- `frontend/tests/e2e/critical/gallery-view.spec.ts`：第二条用例改为「行业政策与合规台账 → 政策台账画廊 8 张卡」，断言 `共 8 条`、8 张卡、标签 / 摘要可见；第一条（国际形势 12 张卡）不变。
- 帮助文档 e2e：教程文案不含「菜谱」，画廊段落出现「政策 / 情报」口径。
- `make frontend-coverage` 与 `make e2e` 为硬门禁。

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 示例资产：新增 `行业政策与合规台账.csv`（8 行）、删除 `美食推荐做法.csv`、改 `fields.json` / `views.json` / `datasource.json`、改 `examples.py` 清单 | 中（seed 视图字段校验 + 帮助图示重建） |
| **P1** | 文案与提示词：4 处文案同口径、`llmPromptPresets.ts` 预设替换、`prompts.py` 系统提示词示例、`msw.ts` 夹具 | 低 |
| **P2** | 测试与文档：后端 / 前端 / e2e 断言替换、`CONTEXT.md` 口径、ADR 0019 / 0022 失效条目改写、CHANGELOG 条目、落地状态回填 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整改范围 | 仅清理菜谱 / 美食相关；保留「国际形势发展动态」「天气每日」 | 需求方选择；两张表为情报 / 观测类中性内容，不属生活娱乐 | 一并剔除天气（会波及 analytics 模板与图示，收益不明确）；示例工作区整体业务化（改动面过大，超出本次诉求） | `examples/datasets/工作区-数据源示例/` |
| D2 | 美食示例的替换场景 | 行业政策与合规台账 | 需求方选择；政策 / 合规是平台典型严肃业务，且与既有政策类预设互补 | 商业航天动态（已有预设，示例重复）；供应链风险 / 安全事件（可行但需新造业务口径） | `examples/datasets/工作区-数据源示例/`、`src/cndb/plugins/help/services/examples.py` |
| D3 | 推荐提示词中的美食预设 | `food_recipes` → `policy_compliance`，总数保持 7 组 | 需求方选择「替换为严肃场景」；补足合规落地视角 | 直接删除（预设 7→6，能力缩水）；仅改文案（仍是生活主题） | `frontend/src/pages/datasource/llmPromptPresets.ts` |
| D4 | 文案口径 | 「适合政策、情报、简报等长文本业务数据的阅读与分享」 | 覆盖画廊实际适用面（长文本 + 标签 + 日期），去掉消费类暗示 | 保留「资讯」（仍偏内容消费）；只删「菜谱」二字（同句语义仍轻） | `frontend/src/pages/help/content/tutorials.tsx`、`frontend/src/pages/grid/GridPage.tsx` 等 4 处 |
| D5 | 存量已 seed 实例 | 不自动删除旧内容，升级说明给人工清理路径 | 示例表可能已被用户改造成真实数据，自动删除不可逆 | 新增清理迁移 / seed `--prune`（误删风险高，且 seed 应保持纯增量） | `docs/` 升级说明 |
| D6 | 历史文档处理 | `CHANGELOG.md` 与需求卡片原句保留；ADR 0019 / 0022 失效示例条目改写为指向本 ADR | 规则要求 ADR 不留失效方案，需求原句须逐字保留 | 全仓追溯删除历史文案（破坏可追溯性） | `docs/adr/0019-*.md`、`docs/adr/0022-*.md`、`CONTEXT.md` |
| D7 | 新表字段设计 | 11 个中文字段，含合规要求 / 适用部门 / 落实状态 / 风险等级 | 与「政策公告跟踪」区分，形成内部落地视角；低基数字段可撑起标签 / 看板 | 直接复用 `policy_tracker` 字段（与既有预设重复） | `examples/datasets/工作区-数据源示例/行业政策与合规台账.csv` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：示例、帮助、提示词与界面文案统一为严肃业务口径；画廊能力仍由政策台账完整示范（画廊 / 看板 / 过滤 / 图表）；零迁移、零接口变更。
- **负向**：示例数据需重新撰写并核验类型推断与视图字段；存量部署会残留旧表，需人工清理。
- **风险与缓解**：帮助图示指纹变化会触发重建，实施后核验 SVG 内容；seed 视图字段校验对新字段严格，先跑 `tests/test_views_api.py` 与 `tests/test_seed_datasource.py`。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 画廊视图能力 | `view_type=gallery`、`view_options` schema | 能力与 schema 不变，仅替换示例内容 | ADR 0022 |
| 推荐提示词清单 | `llmPromptPresets.ts` | 组数 7 不变，`food_recipes` 换为 `policy_compliance` | ADR 0019（本 ADR 改条目） |
| 示例资产清单 | `examples.py`、`examples/datasets/工作区-数据源示例/` | 表数量与文件计数不变，单表内容替换 | ADR 0029 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `examples/datasets/工作区-数据源示例/行业政策与合规台账.csv`、`examples/datasets/工作区-数据源示例/fields.json`、`examples/datasets/工作区-数据源示例/views.json`、`examples/datasets/工作区-数据源示例/datasource.json`、`src/cndb/plugins/help/services/examples.py` | `tests/test_seed_datasource.py`、`tests/test_help_examples_api.py`、`tests/test_views_api.py`、`tests/test_datasource_llm_provider.py` | 12acbd9e |
| P1 | 已落地 | `frontend/src/pages/help/content/tutorials.tsx`、`frontend/src/pages/grid/GridPage.tsx`、`frontend/src/pages/grid/view-config/viewOptionSchema.ts`、`frontend/src/pages/grid/views/GalleryView.tsx`、`frontend/src/pages/datasource/llmPromptPresets.ts`、`src/cndb/plugins/llm/services/prompts.py`、`frontend/src/test/msw.ts` | `frontend/src/pages/datasource/llmPromptPresets.test.ts`、`frontend/src/pages/help/HelpDocsPage.test.tsx` | 12acbd9e |
| P2 | 已落地 | `tests/test_seed_datasource.py`、`tests/test_datasource_llm_provider.py`、`frontend/src/pages/datasource/llmPromptPresets.test.ts`、`frontend/tests/e2e/critical/gallery-view.spec.ts`、`CONTEXT.md`、`CHANGELOG.md`、`docs/adr/0019-llm-prompt-config-simplify.md`、`docs/adr/0022-gallery-view-content-tables.md` | `tests/test_seed_datasource.py`、`frontend/src/pages/datasource/llmPromptPresets.test.ts`、`frontend/tests/e2e/critical/gallery-view.spec.ts` | 12acbd9e |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：全部落地（P0 / P1 / P2）
- 已完成：「美食推荐做法」整套资产替换为「行业政策与合规台账」；4 处画廊文案与 `food_recipes` 预设替换；后端 / 前端 / e2e 断言替换；`CONTEXT.md`、ADR 0019 / 0022 失效条目与 CHANGELOG 同步
- 下一步：e2e 全量回归确认；存量已 seed 实例按 §5 第 1 条人工清理旧表 / 视图 / 同步任务
- 已知坑：seed 视图字段校验对中文新字段严格；帮助图示按 CSV 指纹自动重建，需核验 SVG；`grep` 复验时排除 `CHANGELOG.md`、需求卡片 0019 / 0022 与本 ADR 历史说明
- 最近一次全绿：`make check`（cov 97.00%，5303 passed）

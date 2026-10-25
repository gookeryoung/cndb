# ADR 0030: 帮助文档图示例（服务端生成 SVG + 后台定期重建）

Status: Accepted（已评审）
Date: 2026-10-25
Related: `src/cndb/plugins/help/services/figures/`、`src/cndb/plugins/help/routers/figures.py`、`src/cndb/plugins/help/schemas.py`、`src/cndb/plugins/help/plugin.py`、`src/cndb/core/config.py`、`src/cndb/app.py`、`frontend/src/pages/help/HelpFigure.tsx`、`frontend/src/pages/help/content/`、`frontend/src/api/help.ts`、`frontend/src/index.css`、`frontend/src/test/msw.ts`、`tests/test_help_figures.py`、`tests/conftest.py`
需求卡片: `docs/requirements/0030-help-figures.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 增加更多的图示例 | 新增 17 张图（快速入门 2、教程 3、系统配置 1、典型示例 11），覆盖四部分正文；全部由 `FIGURE_SPECS` 清单登记，前端只按 key 引用 |
| C2 | 图示例 | 四类图：结构图（工作区）、流程图（五步上手 / 导入 / 同步链路）、枚举清单图（字段类型 / 权限角色 / 调度模式）、真实数据预览表（示例 CSV 表头 + 前 4 行） |
| C3 | 支持后台定期生成 | `FigureRefresher` 守护线程按 `HELP_FIGURES_INTERVAL_SECONDS`（默认 1800s）全量重建；`HELP_FIGURES_ENABLED=False` 可整体关闭；启动后延迟 `HELP_FIGURES_STARTUP_DELAY_SECONDS` |
| C4 | 实时生成 | `FigureStore.get()` 每次比对 `FigureSpec.fingerprint()`，不一致立即重建（不等定时轮次）；SVG 端点带 `ETag`，未变返回 304 |
| C5 | 避免代码更新后过期 | 指纹 = `sha1(构建函数源码 + 数据源摘要)`；数据源摘要取字段类型注册表 / 权限枚举 / 调度枚举 / 示例 CSV 的 `size+mtime+表头`，构建代码改动也会触发重建 |
| C6 | （需求澄清）图的形式 | 服务端生成 SVG 字符串 → 快照落 `CACHE_DIR/help-figures`；前端 `HelpFigure` 内联注入（`<img>` 无法继承主题变量），颜色只用 `var(--cn-*)` |
| C7 | （需求澄清）访问与降级 | 三个端点均 `get_current_user`；单张图构建失败回退旧快照，仍失败则前端降级为一行提示，不影响正文 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 帮助正文全部是 `Typography` + `Table` 的纯文字，无任何图 | `frontend/src/pages/help/content/*.tsx` | 概念类内容（结构 / 流程 / 权限）靠文字描述，新人理解成本高 | 确认（C1/C2） |
| 2 | 字段类型主题写死「共 16 种字段类型」，而 `default_registry` 实为 19 种 | `content/tutorials.tsx:129`、`tables/field_types/registry.py:91` | 典型「文档随代码漂移」：文案已过期 | 确认（C5） |
| 3 | help 插件只有示例清单与 CSV 下载两个端点 | `plugins/help/routers/examples.py` | 无图示数据来源 | 确认（C1/C6） |
| 4 | 已有后台刷新范式：单守护线程 + `Event` 唤醒 + 关闭 join | `core/storage_refresh.py` | 图示线程直接复用同一模型，无需新机制 | 确认（C3） |
| 5 | 可写缓存目录 `CACHE_DIR` 已存在并在启动时创建 | `core/config.py:80` | 快照有落点，不进数据库、不进备份 | 确认（C6） |
| 6 | 示例 CSV 通过 `assets.resolve_example_file` 白名单定位 | `plugins/help/services/assets.py` | 预览图可直接读真实文件，无需另建副本 | 确认（C2/C5） |
| 7 | 字段类型 / 工作区角色与视图可见性 / 调度模式均为枚举或注册表 | `field_types/registry.py`、`workspaces/models.py:59`、`tables/models.py:59`、`datasource/models.py:25` | 图的真相源现成，取枚举即「自动跟随代码」 | 新增（C5） |
| 8 | 前端 SVG/图表能力只有 echarts（懒加载）与 antd 图标 | `frontend/package.json` | 结构图用 echarts 会连带拉库；内联静态 SVG 零依赖 | 新增（C6） |
| 9 | 帮助页为独立 lazy chunk，有 gzip 体积预算 | `frontend/scripts/bundle-budget.json`、ADR 0029 P2 | 图示不能抬高帮助 chunk 体积 | 新增（C6） |
| 10 | Chrome 81 兼容基线：CSS 不用 `:where()` / 逻辑属性，作者样式由 postcss 转换 | ADR 0026 | 图示样式只能写在既有 `index.css` 的常规属性里，不引入新特性 | 新增（C6） |
| 11 | 测试默认不启动 `STORAGE_SNAPSHOT` 线程（内存库跨线程写会污染） | `tests/conftest.py:26` | 图示线程同样需在测试中默认关闭 | 新增（C3） |

**核心缺陷（需求要补的）**：帮助文档是「纯文字说明书」，而 cndb 的核心概念（工作区结构、字段类型、权限矩阵、导入链路、同步调度）本质是结构化的；同时任何手写图示 / 截图都会随代码更新而过期 —— 现状 §2 的「16 种」就是活证据。

设计目标（不变量）：

- **I1 图即代码**：每张图的内容来自代码或数据，不存在「手抄的图示文案」；`FIGURE_SPECS` 是图的唯一注册点。
- **I2 双重保鲜**：请求期按指纹即时重建（改了代码 / 数据，下一次访问就是新的）+ 后台周期全量重建（长期无人访问的图也不停在旧版）。
- **I3 零数据库**：图示不落库、不新增迁移、不进工作区备份；快照只写 `CACHE_DIR`（可随时删）。
- **I4 失败不扩散**：单张图构建异常不影响清单与其余图；前端拉图失败只降级一行提示。
- **I5 主题跟随**：同一份 SVG 在浅色 / 暗色主题下都成立，颜色只取 `--cn-*` 令牌。

## Decision

### 1. 图示构建（`services/figures/`）

```
figures/
├── svg.py        # 极简图元：rect / text / line / arrow / chip，640 定宽，属性行内无 <style>
├── builders.py   # 各类图的编排（数据源见下表）
├── registry.py   # FIGURE_SPECS 清单 + 指纹（源码摘要 + 数据源摘要）
└── store.py      # 快照仓库（内存 + 磁盘）+ FigureRefresher 后台线程
```

数据来源（C2/C5）：

| 图示 key | 类型 | 真相源 |
|---|---|---|
| `quick-start-flow` | 流程图 | 本模块编排代码（五步路径） |
| `workspace-structure` | 结构图 | 本模块编排代码（工作区三层承载） |
| `field-types` | 枚举清单 | `field_types.default_registry`（按 `FieldTypeCategory` 分组） |
| `permission-model` | 枚举清单 | `WorkspaceRole` + `ViewVisibility` |
| `import-flow` | 流程图 | 导入链路（选文件 → 识别表头 → 推断类型 → 预览 → 落表） |
| `datasource-sync` | 枚举 + 链路 | `ScheduleMode` + 固定执行链路 |
| `example-{scenario}-table-{n}` | 数据预览 | `examples/datasets` 下**真实 CSV**（表头 + 前 4 行 + 真实总行数） |

约束：

- 定宽 640、按内容算高；`viewBox` + `width="100%"`，由宿主 CSS 控制缩放。
- 颜色只用 `TEXT / MUTED / BORDER / SURFACE / SUBTLE / BRAND` 六个常量，值形如 `var(--cn-text-primary, #1f2937)`。
- 不输出 `<style>`、`<script>`、外链字体；箭头用多边形而非 `<marker>`（多图内联不会 id 冲突）。
- 文本长度按「CJK = 1 字宽、ASCII = 0.55 字宽」估算排版与截断，不依赖字体度量。

### 2. 指纹与保鲜（I1/I2）

```python
fingerprint = sha1( inspect.getsource(build) , data_digest() )
```

- `_code_digest(build)`：构建函数源码摘要（`lru_cache`），改配色 / 文案 / 节点即变；
- `data_digest`：各图自带 —— 字段类型图取 `name:label:category` 全量串，权限图取 `WorkspaceRole` + `ViewVisibility` 成员，同步图取 `ScheduleMode` 成员，预览图取 CSV 的 `size + mtime_ns + 表头`；
- 纯静态图（流程 / 结构）只有源码摘要，改代码即重建。

判定与重建：

| 时机 | 行为 |
|---|---|
| 请求清单 / 单张图 | 比对指纹；一致读快照，不一致**当场重建**并更新磁盘 |
| 后台周期（默认 1800s） | `refresh()` 全量比对重建；`force=False` 时指纹未变跳过 |
| `POST /figures/refresh` | `force=True` 全量重建 + 唤醒后台轮次重新计时 |
| 进程重启 | 先读 `index.json` + `<key>.svg` 快照，指纹一致直接复用（首屏不重建） |

### 3. 快照存储（I3）

- 目录：`settings.CACHE_DIR/help-figures/`，`<key>.svg` + `index.json`（`{version, items:[{key, fingerprint, generatedAt}]}`）。
- 写入失败（只读盘 / 磁盘满）只告警，退化为内存快照，接口不受影响。
- `index.json` 里已从清单删除的 key 在加载时忽略；`FigureStore.reset()` 供测试与排障清空。
- 无迁移、无新表、不进入工作区备份。

### 4. API 变更清单

`help` 插件（前缀 `/api/v1/help`）新增 3 个端点，均依赖 `get_current_user`（C7）：

| 端点 | 行为 |
|---|---|
| `GET /api/v1/help/figures` | `{items:[{key,title,caption,section,fingerprint,generatedAt}], generatedAt}`；过期项在内部按指纹重建 |
| `GET /api/v1/help/figures/{key}.svg` | 返回 `image/svg+xml; charset=utf-8`，`ETag: "<fingerprint>"`、`Cache-Control: private, max-age=300`；`If-None-Match` 命中返回 304；未知 key → 404 `图示不存在` |
| `POST /api/v1/help/figures/refresh` | `{rebuilt: n}`，强制重建全部并唤醒后台轮次 |

不做：图示编辑 / 上传、图片二进制（PNG / JPG）、游客访问、按用户个性化。

### 5. 配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `HELP_FIGURES_ENABLED` | `True` | 关闭后不启动后台线程；请求期即时重建仍生效 |
| `HELP_FIGURES_INTERVAL_SECONDS` | `1800` | 定时重建周期；`0` = 关闭定时轮次 |
| `HELP_FIGURES_STARTUP_DELAY_SECONDS` | `5` | 启动后首轮延迟，让迁移与首屏先跑完 |

生命周期挂在 `app.py` lifespan：启动时 `start_figure_refresher()`（失败只告警），关闭时**先停图示线程**（无事务）再停快照线程。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API | `frontend/src/api/help.ts` | `listFigures` / `getFigureSvg`（`responseType: 'text'` + 直通 `transformResponse`）/ `refreshFigures` |
| 组件 | `frontend/src/pages/help/HelpFigure.tsx` | 清单给指纹 → `queryKey: ['help','figure',key,fingerprint]` 拉 SVG → 清洗（去 `<script>` 与 `on*="`) → 内联渲染；图注 + 「图示更新于 …」；失败 / 未登记 / 清单失败三种降级 |
| 内容 | `content/{quickStart,tutorials,configuration}.tsx`、`content/ExamplesSection.tsx` | 插入 `<HelpFigure id="…" />`；示例区按清单逐表渲染真实数据预览 |
| 文案 | `content/tutorials.tsx` | 删除「共 16 种」硬编码，改为「完整清单见图示，随版本自动更新」 |
| 样式 | `frontend/src/index.css` | `.cn-help-figure*`：外框 + 内联 SVG 自适应 + 图注行；只用既有设计标尺与常规属性（Chrome 81 兼容） |
| 测试桩 | `frontend/src/test/msw.ts` | `mockHelpFigures` + 清单 / SVG 两个默认 handler |

体积：不新增依赖；SVG 走接口不进 bundle，帮助 chunk 预算不变。

### 7. 边界与例外

1. 未知 key：接口 404；前端若引用了未登记 key，渲染「图示未登记」而不是空白。
2. 构建异常：`store._render` 回退旧快照；无旧快照则向上抛，路由转 500 `图示生成失败`，且不影响其余图与帮助正文。
3. 资产缺失（wheel 裁剪 / 本地删 CSV）：该预览图输出「示例文件暂不可用」SVG，清单仍 200。
4. 只读文件系统：快照写盘失败仅告警，退化为内存快照。
5. 移动端：SVG 按容器 100% 缩放，图注换行由 flex-wrap 处理，不出现横向溢出。
6. 并发：`FigureStore` 全量操作持 `RLock`，请求与后台线程不会写出半份 `index.json`。
7. 测试环境：`conftest.py` 关闭 `HELP_FIGURES_ENABLED`，线程行为由用例直接构造 `FigureRefresher` 验证。

### 8. 迁移

无。零表结构变更、零数据迁移、零备份影响；删除 `CACHE_DIR/help-figures` 仅导致下次访问重建。

### 9. 测试清单

**判定层（单测）**
- 构建器：字段类型图覆盖 `default_registry` 全部 label；示例预览含真实 CSV 总行数与文件名；权限图含 `WorkspaceRole` 全部成员；每张图都是单根 `<svg>` 且不含 `<script>`。
- 指纹：CSV 内容变化 → 指纹变化；构建函数源码变化 → 指纹变化。

**接口层**
- 未登录三个端点均 401；清单字段完整（key 唯一、section 在五部分内、指纹 16 位十六进制）；SVG 200 且 `Content-Type: image/svg+xml`；`If-None-Match` 命中 304；未知 key 404；`POST /refresh` 返回 `len(FIGURE_SPECS)`。
- 快照：指纹未变不重建（`generatedAt` 不变）；新实例可从磁盘快照复用（`fingerprint` / `generatedAt` / `svg` 全等）；`force` 重建张数等于清单条数。
- 解耦守卫：`figures/` 子包不出现 `cndb.cli.seed`。

**前端组件**
- `HelpFigure`：内联渲染出 `<svg>`、显示图注与更新时间；正文 caption 覆盖后端图注；`<script>` 与 `onload=` 被清洗；拉图失败 / 未登记 / 清单失败三种降级；正文其余内容照常渲染。
- 既有：`ExamplesSection`（新增数据预览区）、`HelpDocsPage`、`helpNav` 用例全部保持通过。

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 图的形式 | 服务端生成**结构化 SVG**（示意 / 流程 / 枚举 / 数据预览） | 能表达 cndb 的概念结构；矢量、可 diff、体积小、随主题变色 | 真实 UI 截图（需登录态与浏览器、二进制体积大、仍是人工产物）；第三方绘图库（给后端加依赖，且图示本不需要复杂坐标系） | `builders.py`、`svg.py` |
| D2 | 图的真相源 | 全部来自代码 / 数据（注册表、枚举、真实 CSV、编排代码），不手抄 | 需求核心是「不要过期」；§2 的「16 种」证明手抄必漂移 | 前端硬编码图数据（与后端注册表双份真相，同样会漂移） | `registry.py` |
| D3 | 保鲜机制 | 请求期指纹即时重建 **+** 后台周期全量重建 | 前者保证「改了立刻对」，后者保证「没人访问的图也不停在旧版」；周期重建还能作为内容核验 | 只做定时（改动后最长要等一个周期）；只做请求期（长期无人访问的图无更新记录，且无法主动核验） | `store.py`、`app.py` |
| D4 | 指纹构成 | `sha1(构建函数源码 + 数据源摘要)` | 一并覆盖「代码改了」与「数据变了」两类过期；源码摘要免去人工 bump 版本号 | 手写版本号常量（人一定会忘）；只哈希数据源（改图不重建，出现旧图配新文案） | `registry.py` |
| D5 | 快照位置 | `CACHE_DIR/help-figures`（磁盘）+ 进程内内存 | 进程重启后首屏不重建；缓存可随时删，不进数据库/备份 | 落库（引入迁移与备份体积）；纯内存（每次重启全量重建，冷启动多几百毫秒） | `store.py`、`core/config.py` |
| D6 | 前端渲染方式 | 内联注入 SVG（`dangerouslySetInnerHTML` + 清洗） | 内联才能继承 `var(--cn-*)`，浅色 / 暗色自动适配 | `<img src>`（无法继承主题变量，暗色下会白底）；前端再画一遍（双份实现） | `HelpFigure.tsx` |
| D7 | 后台线程模型 | 复用 `storage_refresh` 的单守护线程 + `Event` + 关闭 join | 已有范式与运维经验；关闭顺序明确 | 交给外部 cron 调 `POST /refresh`（离线部署无 cron 保障，且多实例会重复） | `store.py`、`app.py` |
| D8 | 访问控制 | 仅登录用户（与示例接口一致） | 与 ADR 0029 D2 口径一致，帮助页本身就在 `ProtectedRoute` 内 | 游客可读图示：需额外公开端点与内容脱敏 | `routers/figures.py` |
| D9 | 图的数量与粒度 | 17 张：概念 6 张 + 每张示例表 1 张预览 | 预览图按表拆开，「下载前先看图」；示例共 11 张表 | 每个场景只给 1 张（丢信息）；再细到每个字段类型 1 张（图过剩） | `registry.py` |
| D10 | 失败处理 | 单图异常回退旧快照，仍失败则前端降级一行提示 | 帮助是阅读页，任何单图失败都不该拖垮正文 | 整体 500（一张图坏掉整页打不开） | `store.py`、`HelpFigure.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：帮助文档从「纯文字」变为「结构化图文」，概念类内容（工作区结构、权限模型、字段类型、导入链路、同步调度）一眼可读；图示随代码与数据自动重建，`16 种 → 19 种` 这类漂移在结构上被消除；零数据库、零迁移、零新依赖（后端只多用标准库 `csv` / `hashlib` / `inspect`，前端零新增）。
- **负向**：新增一个后端子包与一个后台线程（运维面 +1，可用 `HELP_FIGURES_ENABLED=False` 关闭）；17 张图的构建逻辑需要人维护（但漏改会被「指纹 + 测试」暴露）。
- **风险与缓解**：① 图与文案语义冲突 → 文案改为引用图，不再写死数量；② 构建函数抛异常 → 回退旧快照 + 前端降级（I4）；③ 快照写盘失败 → 退化内存快照；④ 多实例部署各自维护快照 → 内容由代码与数据决定，多实例结果一致，无一致性问题；⑤ 图片体积 → 单图 4~8 KB，按需拉取（清单只给元信息）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 帮助文档路由 / 导航 / 示例 | `pages/help/`、`plugins/help/` | 图示挂在既有 5 部分主题里，不新增导航层级；示例 CSV 仍由 `examples` 端点提供 | ADR 0029 |
| 后台周期刷新范式 | `core/storage_refresh.py` | 复用单守护线程 + `Event` + 关闭 join 的线程模型 | ADR 0024 |
| Chrome 81 兼容 | `frontend/src/compat/`、postcss | 图示样式只用常规 CSS 属性，不引入新特性 | ADR 0026 |
| 示例资产打包 | `pyproject.toml` `force-include` | 预览图与下载共用 `cndb/datasets`（源码态 `examples/datasets`） | 平台约定 |
| 前端体积预算 | `frontend/scripts/bundle-budget.json` | SVG 走接口不进 bundle，帮助 chunk 预算不变 | ADR 0029 P2 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/help/services/figures/svg.py`、`src/cndb/plugins/help/services/figures/builders.py`、`src/cndb/plugins/help/services/figures/registry.py`、`src/cndb/plugins/help/services/figures/store.py`、`src/cndb/plugins/help/routers/figures.py`、`src/cndb/plugins/help/schemas.py`、`src/cndb/plugins/help/plugin.py`、`src/cndb/core/config.py`、`src/cndb/app.py`、`tests/conftest.py` | `tests/test_help_figures.py` | 本地 |
| P1 | 已落地 | `frontend/src/pages/help/HelpFigure.tsx`、`frontend/src/api/help.ts`、`frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`frontend/src/pages/help/content/configuration.tsx`、`frontend/src/pages/help/content/ExamplesSection.tsx`、`frontend/src/index.css` | `frontend/src/pages/help/HelpFigure.test.tsx`、`frontend/src/pages/help/content/ExamplesSection.test.tsx`、`frontend/src/test/msw.ts` | 本地 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 已落地；待人工评审决定是否把 `Status` 改为 `Implemented`
- 已完成：后端图示引擎（`svg.py` 图元、`builders.py` 六类构建器 + 真实 CSV 预览、`registry.py` 17 条 `FIGURE_SPECS` + 指纹、`store.py` 快照与 `FigureRefresher` 线程、`routers/figures.py` 三端点含 ETag/304）；配置项 `HELP_FIGURES_*` 与 lifespan 启停；前端 `HelpFigure`（指纹缓存 + 清洗 + 三种降级）、`api/help.ts` 三方法、四部分正文插入图示例、示例区逐表数据预览、`.cn-help-figure*` 样式、msw 桩；字段类型主题删除「共 16 种」硬编码
- 下一步：seed 内容移除另行立需求（与图示无关）；若后续要给图示加「导出 PNG」，需评估新增依赖（当前刻意只做 SVG）
- 已知坑：图示快照在 `CACHE_DIR/help-figures`，**不要**把它当业务数据备份；新增图必须同时登记 `FIGURE_SPECS` 并在正文引用，否则前端显示「图示未登记」；预览图 key 由 `example-{scenario}-table-{n}` 序号生成，**调整清单里 tables 顺序会让图换名**（前端是按 index 引用的，顺序即契约）；`FigureStore` 的 `get` 会持锁重建，批量调用请走 `refresh()`；测试环境必须保持 `HELP_FIGURES_ENABLED=False`，否则线程会跨测试写同一缓存目录；SVG 内联渲染前必须保留 `sanitizeSvg`，不要为省一次正则直接塞 `dangerouslySetInnerHTML`
- 最近一次全绿：`make check-fast`（gitkeep / adr / ruff / pyrefly / tsc / eslint 全过）+ `make test`（5298 passed / 8 skipped）+ 前端 `vitest run --coverage`（181 文件 / 2147 用例通过，核心集合 lines 97.78% / branches 100%，全局 82.42%）
- 构建备注：`pnpm build` 会先清 `frontend/dist` 与 `src/cndb/static/assets`，本轮在本机被文件删除保护钩子拦在「清目录」阶段（vite 已成功转换 4547 modules + tsc 通过，非代码问题）；CI 上照常。清理这两个目录后可正常产出，`src/cndb/static` 为构建产物、不入库

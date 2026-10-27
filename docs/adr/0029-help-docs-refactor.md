# ADR 0029: 帮助功能重构为独立「帮助文档」路由（两级导航 + 典型示例下载）

Status: Accepted（已评审）
Date: 2026-10-25
Related: `frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/src/pages/help/helpNav.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/App.tsx`、`frontend/src/components/HelpTip.tsx`、`frontend/src/components/onboarding/OnboardingTour.tsx`、`src/cndb/cli/seed/runner.py`、`src/cndb/cli/seed/paths.py`、`pyproject.toml`、`docs/adr/README.md`
需求卡片: `docs/requirements/0029-help-docs-refactor.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 名称改为帮助文档 | 标题常量 `HELP_DOCS_TITLE = '帮助文档'`；页面 `<h1>`、浏览器标题、桌面顶栏入口、移动端用户菜单统一该文案；删除 `HELP_CENTER_TITLE` |
| C2 | 设置独立路由进入，而不是弹出DRAWER | 新增 `/help` 与 `/help/:section/:topic` 两条登录后路由（`App.tsx` 内 `ProtectedRoute`）；`MainLayout` 入口 `navigate('/help')`；删除 `HelpCenterDrawer.tsx`、`helpOpen` 状态与 lazy 引用 |
| C3 | 采用两级侧边栏导航 | `helpNav.tsx` 定义「部分 → 主题」两级树；`HelpDocsPage` 用 antd `Menu` 的 `SubMenu` 渲染一级、`Item` 渲染二级；`selectedKeys` / `openKeys` 由 URL 派生；窄屏 `Menu` 收进左侧 `Drawer`，顶部「目录」按钮唤出 |
| C4 | 按照快速入门、教程&最佳实践、典型示例、系统配置、问题排查等部分进行组织 | 一级固定 5 项且顺序固定（见 §2 映射表）；现有 6 个主题全部迁入且无孤儿内容；空主题不允许存在 |
| C5 | 典型示例请融入MAKE SEED对应的示例，后续将移除MAKE SEED的内容，仅保留帮助中的示例 | 新增独立后端插件 `src/cndb/plugins/help/`：静态清单 `HELP_EXAMPLE_MANIFEST` 描述三套 `examples/datasets` 场景，文件读取只走白名单；**不 import `cndb.cli.seed`、不查演示工作区 / 演示账号**；seed 命令与数据本期一行不改 |
| C6 | （需求澄清）图文说明 + CSV 下载 | 每个示例返回 `scenario / summary / tables[] / highlights[] / steps[]`；下载端点仅暴露清单登记的文件；前端提供 `<a download>`，不提供一键导入 |
| C7 | （需求澄清）仅登录用户 | 前端路由在 `ProtectedRoute` 内；后端两个端点均依赖 `get_current_user`，未登录 401 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 帮助内容由 `HelpCenterDrawer` 以 `Drawer`（`width=620`）承载，桌面左菜单 150px、移动端顶部胶囊导航（P0 已删除，改为 `HelpDocsPage`） | `frontend/src/pages/help/HelpDocsPage.tsx` | 无法深链、刷新即丢当前主题；无法承载两级目录与示例下载 | 确认（C2/C3） |
| 2 | 桌面顶栏「帮助」按钮打开抽屉；移动端用户菜单「帮助中心」同款（P0 改为 `navigate('/help')`） | `frontend/src/layouts/MainLayout.tsx` | 入口语义是弹层，不是页面 | 确认（C1/C2） |
| 3 | 内容为扁平 6 主题（快速上手 / 视图类型 / 导入导出 / 权限角色 / 字段类型 / 常见问题），单文件 244 行（P0 迁入 `pages/help/content/`） | `frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/content/` | 只有一级；无教程、示例、系统配置、排障分区 | 确认（C4） |
| 4 | 路由表只有 `/w/*`、`/admin`、`/public/share/:token`，未知路径 `*` 统一 `Navigate to="/w"` | `frontend/src/App.tsx:79`、`:136` | `/help` 当前会被兜底重定向，必须显式注册 | 确认（C2） |
| 5 | `MainLayout` 在 `/admin` 或 `!wsFeatures.tables` 时不渲染 Sider，内容区拿到整幅宽度 | `frontend/src/layouts/MainLayout.tsx:319`、`:489` | `/help` 需加入「无工作区侧栏」判定，否则会残留「请先选择工作区」占位 | 确认（C3） |
| 6 | 现有测试断言抽屉开合、移动端胶囊、6 主题与「帮助中心」常量（P0 已重写为 `pages/help/*.test.tsx` 与新的 MainLayout 用例） | `frontend/src/pages/help/HelpDocsPage.test.tsx`、`helpNav.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | 抽屉删除后测试全部失效，需按新页面模型重写 | 确认（C1/C2/C4） |
| 7 | 「重新播放新手引导」按钮位于抽屉 footer，点击后关抽屉并发 `requestTour()`（P0 迁到帮助页工具条） | `frontend/src/pages/help/HelpDocsPage.tsx` | 入口需迁移到帮助文档页；`useOnboardingStore.requestTour` 保持不变 | 确认（C2） |
| 8 | `cndb seed` 从 `examples/datasets` 注入三套工作区（销售 / 科研 / 数据源）及视图、文档、分析、数据源任务 | `src/cndb/cli/seed/runner.py:22`、`src/cndb/cli/seed/datasets.py:145` | 帮助示例的内容来源明确，但帮助不得依赖 seed 运行结果 | 确认（C5） |
| 9 | `examples/datasets` 已通过 hatch `force-include` 打包为 `cndb/datasets`，seed 侧有包内优先、仓库根兜底的路径解析 | `pyproject.toml:84`、`src/cndb/cli/seed/paths.py:12` | 帮助可复用同一资产源，wheel 安装版也能取到文件 | 确认（C5/C6） |
| 10 | 示例 CSV 三套场景共 18 个表文件 | `examples/datasets/工作区-某企业销售管理/`、`工作区-科研项目管理/`、`工作区-数据源示例/` | 示例需精选子集并写清单，避免把全部演示数据当「典型示例」 | 新增（C5/C6） |
| 11 | `HelpTip` 为行内问号提示，被设置页 / 字段页 / 视图配置复用，与帮助抽屉无代码耦合 | `frontend/src/components/HelpTip.tsx:21` | 不受本次重构影响 | 排除（C1-C7） |
| 12 | 后端尚无 help 插件；插件路由前缀由插件名或 `route_prefix` 决定 | `src/cndb/core/plugin_registry.py:90`、`:108` | 新插件按同一机制挂载 `/api/v1/help`，无需改核心 | 新增（C5/C6/C7） |

**核心缺陷（需求要补的）**：帮助内容现在是「不可定位、不可分享、只有一级目录」的弹层，且典型示例只存在于 `cndb seed` 的演示库里——用户不跑 seed 就看不到任何示例；seed 一旦移除，示例知识也随之消失。

设计目标（不变量）：

- **I1 导航单一真相源**：`helpNav.tsx` 同时驱动路由、侧栏、页面内容与默认重定向；不存在未挂到导航上的主题，也不存在导航里指向空内容的主题。
- **I2 文案单一真相源**：用户可见名称只取 `HELP_DOCS_TITLE` 与 `HELP_SECTIONS[].label`；前端源码中不再出现面向用户的「帮助中心」。
- **I3 示例自包含**：帮助示例只依赖「静态清单 + 白名单资产文件」，不 import seed、不查询数据库、不假设演示工作区存在；seed 删除后帮助仍完整可用。
- **I4 访问受控**：`/help` 与两个示例端点都要求登录；示例下载仅限清单登记文件，拒绝路径穿越。
- **I5 零数据库变更**：不新增表 / 列 / 迁移，不进入工作区备份；帮助内容随代码版本发布。

## Decision

### 1. 数据模型

无。帮助正文为前端静态 TSX；示例清单为后端 Python 常量；不落库、不新增迁移、不进入备份。

示例清单结构（`src/cndb/plugins/help/services/examples.py`）：

```python
HELP_EXAMPLE_MANIFEST: list[dict] = [
    {
        "key": "sales",
        "name": "某企业销售管理",
        "summary": "从销售明细、客户流失到营销活动与日常待办的完整销售运营示例。",
        "tables": [
            {
                "file": "电商销售.csv",
                "title": "电商销售",
                "description": "订单级销售明细，含渠道、产品、金额与日期。",
                "rows": 240,
            },
            {"file": "客户流失.csv", "title": "客户流失", "description": "客户维度的流失状态与回访记录。", "rows": 120},
        ],
        "highlights": ["图表视图看月度销售趋势", "看板视图跟踪客户流失回访", "数据分析模板：渠道占比"],
        "steps": ["下载 CSV", "新建数据表并导入", "按字段类型核对后创建视图"],
    },
    # research / datasource 同构
]
```

约束：

- `key` 匹配 `^[a-z][a-z0-9_-]{1,31}$` 且唯一；`file` 只允许清单登记的 `.csv` 文件名，不接受路径。
- `rows` 为示例说明用的近似行数，不做实时统计（避免读文件解析）。
- 清单是**唯一**示例来源；前端不得硬编码第二份示例清单。

### 2. 导航与内容组织（唯一入口）

`frontend/src/pages/help/helpNav.tsx` 导出：

```ts
export interface HelpTopic { key: string; label: string; content: React.ReactNode }
export interface HelpSection { key: string; label: string; icon: React.ReactNode; topics: HelpTopic[] }
export const HELP_SECTIONS: HelpSection[]
export const HELP_DOCS_TITLE = '帮助文档'
export function findTopic(sectionKey?: string, topicKey?: string): { section: HelpSection; topic: HelpTopic }
export function topicPath(sectionKey: string, topicKey: string): string   // `/help/${sectionKey}/${topicKey}`
```

一级固定 5 项与现有内容映射：

| 一级（顺序固定） | key | 二级主题 | 内容来源 |
|---|---|---|---|
| 快速入门 | `quick-start` | 认识 cndb / 十分钟上手 | 现有 `quick-start` 重写为「概念 + 五步流程」两个主题 |
| 教程&最佳实践 | `tutorials` | 视图类型 / 数据导入导出 / 权限与角色 / 字段类型 / 视图配置实践 | 现有 4 个主题迁入，补 1 个视图配置实践主题 |
| 典型示例 | `examples` | 某企业销售管理 / 科研项目管理 / 数据源示例 | 后端清单驱动（§1、§3） |
| 系统配置 | `configuration` | 工作区设置 / 个人设置与大模型 / 数据源同步 / 存储、备份与部署 | 新增内容，事实与设置页 / 文档一致 |
| 问题排查 | `troubleshooting` | 常见问题 / 使用与故障排查 | 现有 `faq` 迁入，补导入失败、权限不足、登录过期、同步失败 |

路由与默认落点：

- `/help` → `<Navigate to="/help/quick-start/overview" replace />`。
- `/help/:section/:topic` → `HelpDocsPage`；`findTopic` 对未知 key 回落第一个主题并 `replace` 纠正 URL（I1）。
- 侧栏 `openKeys` 默认全部展开；点击一级只展开/收起，不改变当前主题；点击二级 `navigate(topicPath(...))`。
- 窄屏（`isMobile`）：侧栏改为左侧 `Drawer`（宽 280），顶部工具条显示「目录」按钮；选中主题后自动关闭抽屉。
- 页面顶部提供「重新播放新手引导」按钮（`requestTour()`，不再关闭任何弹层）。

### 3. API 变更清单

新增后端插件 `src/cndb/plugins/help/`，插件名 `help` → 路由前缀 `/api/v1/help`。

| 端点 | 变更 |
|---|---|
| `GET /api/v1/help/examples` | 新增：返回 `{ "items": HELP_EXAMPLE_MANIFEST }`；登录即可（`get_current_user`） |
| `GET /api/v1/help/examples/{scenario}/files/{filename}` | 新增：下载清单登记的 CSV。`scenario` 必须在清单内、`filename` 必须匹配 `^[^/\\]+\.csv$` 且在该场景 `tables[].file` 内，否则 404；`Content-Disposition: attachment; filename*=UTF-8''<encoded>`；`media_type="text/csv; charset=utf-8"` |
| 资产定位 | 新增 `services/assets.py`：包内 `cndb/datasets` 优先、仓库根 `examples/datasets` 兜底（与 `src/cndb/cli/seed/paths.py:12` 同口径），**不 import seed 模块**；目录缺失时清单接口仍返回，下载 404 |

不做：上传、编辑、一键导入工作区、示例数据库查询。

### 4. 边界与例外

1. 未知 `section` / `topic`：前端回落第一个主题并 `replace`；后端不参与。
2. 清单文件缺失（wheel 裁剪 / 本地删文件）：清单仍可读，下载返回 404 与 `detail`「示例文件暂不可用」；不 500。
3. 路径穿越：`%2e%2e%2f`、反斜杠、绝对路径、非 `.csv` 后缀统一 404，不透出服务器路径。
4. 非登录：前端 `ProtectedRoute` 重定向 `/login`；接口 401。
5. 移动端：两级 `Menu` 收进抽屉；正文单列，示例表格横向滚动，不出现 150px 固定侧栏挤压。
6. 主题与 Chrome 81：沿用 `--cn-*` token 与现有 `Menu` 样式，不引入新 CSS 特性；帮助页 lazy chunk 独立，不抬高主入口体积。
7. 外链与旧入口：不保留 `/help` 之外的帮助弹层入口；`HelpTip` 行内提示不动；没有外部深链依赖旧抽屉状态。

### 5. 迁移

无。零表结构变更、零数据迁移、零备份影响。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 路由 | `frontend/src/App.tsx` | 新增 `HelpDocsPage` lazy；`ProtectedRoute` 内注册 `help` 与 `help/:sectionKey/:topicKey` 两条路由 |
| 布局 | `frontend/src/layouts/MainLayout.tsx` | 删除 `HelpCenterDrawer` lazy、`helpOpen` 状态与渲染；桌面「帮助文档」按钮与移动端菜单项改为 `navigate('/help')`；新增 `inHelpDocs` 判定（`/help` 下不渲染工作区 Sider） |
| 页面 | `frontend/src/pages/help/HelpDocsPage.tsx` | 两级侧栏 + 内容区 + 移动端目录抽屉 + 顶部重放引导按钮；URL 驱动选中态 |
| 导航 | `frontend/src/pages/help/helpNav.tsx` | 5 个一级部分、二级主题、`findTopic` / `topicPath` / 标题常量（唯一真相源） |
| 内容 | `frontend/src/pages/help/content/{quickStart,tutorials,configuration,troubleshooting}.tsx` | 现有 6 主题迁入并补齐系统配置 / 排障 / 最佳实践 |
| 示例 | `frontend/src/pages/help/content/ExamplesSection.tsx`、`frontend/src/api/help.ts` | 拉取清单、渲染场景卡（表清单 / 亮点 / 步骤 / CSV 下载链接） |
| 清理 | `frontend/src/components/HelpCenterDrawer.tsx`、`HelpCenterDrawer.test.tsx`、`helpContent.tsx`、`helpContent.test.tsx` | 删除；内容与测试迁至 `pages/help/` |
| 样式 | `frontend/src/index.css` 或 `layouts` 既有样式 | 复用 `.cn-page` / `Menu`；补帮助页两级栏与移动端抽屉的少量 token 样式 |

`ExamplesSection` 使用 TanStack Query（`queryKey: ['help','examples']`，`staleTime: 5min`），清单失败显示重试态，不阻塞其它主题。

### 7. 测试清单

**判定层（单测）**
- `helpNav`：一级恰好 5 个且顺序为快速入门 / 教程&最佳实践 / 典型示例 / 系统配置 / 问题排查；每级 topics ≥1；section/topic key 唯一；`findTopic` 未知 key 回落首个主题；每个 topic 都有非空 `content`。
- `topicPath` 与 URL 解析：编码安全、无重复斜杠。

**接口层**
- `GET /api/v1/help/examples`：登录 200 且清单字段完整（key/name/summary/tables/highlights/steps）；未登录 401。
- 下载：登记文件 200、`Content-Disposition` 含 RFC 5987 文件名、CSV 内容非空；未知 scenario / 未知文件 / 非 `.csv` / 含 `/`、`..` 名字 → 404；资产目录缺失时清单 200、下载 404。
- 解耦守卫：`src/cndb/plugins/help` 不出现 `cndb.cli.seed` 导入（源码断言或用例）。

**迁移 / 备份**
- 无（零迁移）。以现有备份往返用例继续通过作为回归。

**前端组件**
- `HelpDocsPage`：`/help` 默认重定向首个主题；深链 `/help/tutorials/roles` 渲染对应内容且二级选中；未知 key 回落并纠正 URL；移动端目录抽屉可开关且选中后关闭。
- `MainLayout`：桌面点「帮助文档」跳 `/help`，不再渲染 `help-center-drawer`；移动端菜单项同款；`/help` 下不渲染工作区 Sider。
- `ExamplesSection`：加载 / 失败重试 / 清单渲染 / CSV 下载链接 URL 正确。
- 「重新播放新手引导」按钮置 `tourRequested=true`。
- 文案：`HELP_DOCS_TITLE === '帮助文档'`；`HelpCenterDrawer` 文件不存在（删除）。

**e2e（前端）**
- 顶栏入口 → `/help` → 展开一级 → 切换二级 → 刷新后仍在当前主题 → 浏览器后退回到上一主题。
- 典型示例 → 下载 CSV（`download` 事件）→ 打开教程主题。
- 窄屏：目录抽屉导航可用。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 路由与页面骨架：`/help` + 两级 `helpNav` + 现有 6 主题迁入 5 个部分 + 名称统一 + 删除抽屉与旧测试 + `MainLayout` 入口改造 | 低（纯前端，无数据面） |
| **P1** | 典型示例：`help` 插件、示例清单、CSV 下载端点、`ExamplesSection` 与接口/组件测试 | 中（新增插件与文件读取安全边界） |
| **P2** | 内容补齐与验收：系统配置 / 问题排查正文、移动端与 e2e、bundle 预算、seed 解耦守卫；seed 删除另行立项 | 低（内容为主） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：改整页还是保留抽屉 / 弹窗 | 独立整页路由 `/help`，删除抽屉 | 需求明确「独立路由，而不是弹出 DRAWER」；整页才能承载两级导航、深链与下载 | 保留抽屉只加深主题：仍不可分享、刷新丢状态；Modal：空间更小 | `HelpDocsPage.tsx`、`App.tsx` |
| D2 | 访问范围 | 仅登录用户，路由挂 `ProtectedRoute` | 帮助含系统配置 / 排障等内部信息；公开会扩大信息面 | 游客可读：需额外公开布局与内容脱敏 | `App.tsx` |
| D3 | 路由形态 | `/help` + `/help/:section/:topic` | 深链、刷新、前进后退都可用；与工作区路径隔离 | 单 `/help` 内部 state 切换：不可分享；query 参数：多一层编解码且不合现有路径习惯 | `helpNav.tsx` |
| D4 | 导航层级 | 一级 5 部分（可折叠）+ 二级主题，单侧栏 | 满足「两级侧边栏」；5 个部分与需求逐字一致 | 顶部 Tabs + 侧栏：两级割裂；三级：当前内容量不需要 | `HelpDocsPage.tsx` |
| D5 | 内容承载 | 正文静态 TSX，随代码版本维护 | 无编辑 / 多语言需求，零表零接口，走现有前端门禁 | 后端存文档（复用文档插件）：引入权限、版本、备份与编辑面，超出需求 | `pages/help/content/` |
| D6 | 典型示例来源 | 后端 `HELP_EXAMPLE_MANIFEST` + 白名单资产文件，资产源复用 `examples/datasets`（wheel 内 `cndb/datasets`） | 不复制一套数据文件；seed 删除后资产仍在；wheel 可用 | 前端 public 静态副本：双份数据易漂移；查询演示库：依赖 seed 运行结果，违背 C5 | `plugins/help/services/examples.py` |
| D7 | 示例文件下载形态 | 只读 GET + 清单白名单 + 登录校验 | 需求澄清选「图文 + CSV 下载」；白名单天然防穿越 | 一键导入：需写工作区 / 表 / 权限，另有复杂度；打包 zip：单文件下载更直观 | `routers/examples.py` |
| D8 | seed 移除时机 | 本期只解耦，不删 seed | 需求原文「后续将移除」；seed 仍被 e2e / 演示部署使用，同期删除风险大 | 本期一并删除：影响 CI 与演示环境，且与重构目标无关 | — |
| D9 | 旧组件处理 | 直接删除抽屉与扁平 `helpContent`，不留兼容层 | 仓库规范：不留历史方案 / 兼容 shim；无外部深链依赖 | 保留重新导出：长期双份内容漂移 | `frontend/src/pages/help/helpNav.tsx` |
| D10 | 命名口径 | 用户可见名「帮助文档」，路由 `/help`，常量 `HELP_DOCS_TITLE` | 需求 1；`help` 路由短且稳定 | 改路由 `/help-docs`：无额外收益，链接更长 | `helpNav.tsx`、`MainLayout.tsx` |
| D11 | 新手引导入口 | 迁到帮助文档页顶部按钮，沿用 `requestTour()` | 抽屉删除后需要新落点；store 与引导组件不变 | 放个人设置：与帮助语义不一致，用户不易找到 | `HelpDocsPage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」。

## Consequences

- **正向**：帮助可分享、可刷新、可前进后退；两级目录把 6 个扁平主题重组为 5 个可扩展部分；典型示例脱离 `cndb seed` 独立存在，seed 后续可安全移除；零数据库变更，复用现有路由 / 插件 / 响应式能力。
- **负向**：新增后端 help 插件与文件下载端点（安全边界需测试覆盖）；内容拆分文件数增加；P0 需要重写全部帮助相关测试。
- **风险与缓解**：① 导航与内容漂移 → `helpNav` 单一真相源 + 完整性单测；② 资产在 wheel 中缺失 → 复用已验证的 `cndb/datasets` 打包路径，并以「目录缺失不 500」用例兜底；③ 移动端两级菜单拥挤 → 侧栏收抽屉、正文单列；④ 帮助页体积 → 页面 lazy + 内容按部分拆分。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 文档通用文件导入 | `plugins/documents/` | 帮助示例下载后使用现有 CSV 导入能力，不新增导入链路 | ADR 0010 |
| 画廊视图 | `GalleryView.tsx`、`galleryBoard.ts` | 数据源示例场景的推荐视图沿用现有画廊能力，帮助不新增视图类型 | ADR 0022 |
| 插件路由挂载 | `core/plugin_registry.py` | `help` 插件按既有机制挂载，不改核心 | 平台约定 |
| 打包资产 | `pyproject.toml` `force-include` | 示例 CSV 复用 `examples/datasets → cndb/datasets`，不新增打包条目 | 平台约定 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/src/pages/help/helpNav.tsx`、`frontend/src/pages/help/content/`、`frontend/src/App.tsx`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/index.css` | `frontend/src/pages/help/HelpDocsPage.test.tsx`、`frontend/src/pages/help/helpNav.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | 65418bce |
| P1 | 已落地 | `src/cndb/plugins/help/plugin.py`、`src/cndb/plugins/help/schemas.py`、`src/cndb/plugins/help/routers/examples.py`、`src/cndb/plugins/help/services/examples.py`、`src/cndb/plugins/help/services/assets.py`、`frontend/src/api/help.ts`、`frontend/src/pages/help/content/ExamplesSection.tsx` | `tests/test_help_examples_api.py`、`frontend/src/pages/help/content/ExamplesSection.test.tsx` | a09a88c7 |
| P2 | 已落地 | `frontend/tests/e2e/critical/help-docs.spec.ts`、`frontend/scripts/bundle-budget.json` | `frontend/tests/e2e/critical/help-docs.spec.ts` | 1994c57c |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0 / P1 / P2 全部落地；待人工评审决定是否把 `Status` 改为 `Implemented`
- 已完成：P0 —— `/help` 与深链路由、两级侧栏（桌面常驻 / 窄屏抽屉）、5 部分导航与内容迁移（含系统配置 4 主题、问题排查 2 主题）、名称统一、删除抽屉与旧测试、重放引导迁移、`/help` 不渲染工作区 Sider。P1 —— `plugins/help`（`HELP_EXAMPLE_MANIFEST` 三套场景 + 白名单 CSV 下载，`get_current_user` 鉴权、RFC 5987 文件名、资产包内优先 / 仓库兜底、目录缺失清单仍可读下载 404）、`frontend/src/api/help.ts`、`ExamplesSection`（TanStack Query `['help','examples']`，表格 / 亮点 / 步骤 / 鉴权 blob 下载 / 失败重试 / 场景缺失提示）。P2 —— `frontend/tests/e2e/critical/help-docs.spec.ts`（入口 → 两级导航 → 刷新 / 后退 → 示例清单 → CSV 下载 → 窄屏目录）与 `HelpDocsPage` 独立 lazy chunk 的体积基线（10.06 KiB gzip）
- 下一步：seed 内容移除另行立需求（`cndb seed` 与帮助已解耦，移除不影响帮助）
- 已知坑：`/help` 不在 `/w` 下，`MainLayout` 无 wid 分支会先等 `wsLoading`；深链纠正依赖 `findTopic`，新增主题必须同时挂到 `HELP_SECTIONS`；示例文件在 wheel 中位于 `cndb/datasets`、源码态位于 `examples/datasets`，`assets.py` 按此两处探测且**不得 import seed**；下载需登录，前端必须走 axios blob（`<a href>` 带不上 Authorization）；e2e 需独占 `:8000`，本地开着 `cndb serve` 时先停掉；`HelpTip` 与本次重构无关，勿动
- 最近一次全绿：`make flow`（`check-fast` + 后端 5283 passed / 8 skipped）+ `make frontend-coverage`（核心集合 lines 97.78% / branches 100%，全局 82.40%）+ `make e2e`（71 passed / 21 skipped）+ `pnpm build` 与 `bundle-budget`（全部关键 chunk 在预算内）

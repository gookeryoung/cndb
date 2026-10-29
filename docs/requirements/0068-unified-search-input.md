# 需求卡片：统一前端搜索框为公共 SearchInput 组件

- 编号：0068（与 ADR `docs/adr/0068-*.md` 同号，卡片存 `docs/requirements/0068-unified-search-input.md`）
- 来源 / 提出人：用户（会话内提出，分析结论已确认）
- 日期：2026-10-29
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 「数据表、文档等页面的搜索框，还没有统一。请分析此类情况。」
> 「按这个方案动手」（确认的方案：新建公共 SearchInput 组件统一各页面搜索框）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 搜索框统一 | 新建公共组件 `frontend/src/components/SearchInput.tsx`：antd `Input` + `SearchOutlined` prefix + `allowClear`，不使用 `Input.Search` 的搜索按钮形态 | frontend | 组件单测 + 全站 Grep 不再有裸 `SearchOutlined` prefix 搜索框 |
| C2 | 搜索框统一 | `SearchInput` 默认 `size="small"`，宽度由调用方通过 `style` / `width` 传入，移动端适配由调用方处理 | frontend | 组件单测 |
| C3 | 搜索框统一 | 文案规则：本地列表过滤用「过滤 <对象>…」，跨数据检索用「搜索 <范围>…」，省略号统一全角 `…`；现有半角 `...` / 无省略号文案全部改为对应口径 | frontend | 全站 Grep placeholder |
| C4 | 数据表、文档等页面 | 替换清单：MainLayout 侧栏表搜索、MainLayout 侧栏文档过滤、DocumentsPage 标题过滤、DocumentTree 树过滤、gridViewBar 视图搜索、WorkspaceList 搜索、UsersPage 用户搜索、AddMemberModal、PermissionEditor、FieldManager 字段过滤 | frontend | 各页面既有单测通过 |
| C5 | 搜索框统一 | `GlobalSearch`（顶栏 GitHub 风格搜索）形态特殊，**不纳入**本次统一，保持 borderless 独立实现 | frontend | GlobalSearch 既有测试不变 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 侧栏表搜索 | `frontend/src/layouts/MainLayout.tsx:439` | `Input` + prefix，placeholder `搜索表...` |
| 2 | 侧栏文档过滤 | `frontend/src/layouts/MainLayout.tsx:518-527` | `Input` small，placeholder `过滤标题` |
| 3 | 文档管理页标题过滤 | `frontend/src/pages/documents/DocumentsPage.tsx:478-487` | placeholder `过滤标题` |
| 4 | 文档树过滤 | `frontend/src/pages/documents/DocumentTree.tsx:584` | placeholder `过滤文档树…` |
| 5 | Grid 视图搜索 | `frontend/src/pages/grid/gridViewBar.tsx:358-369` | `Input.Search`，160px |
| 6 | 工作区列表搜索 | `frontend/src/pages/workspace/WorkspaceList.tsx:237` | placeholder `搜索工作区名称/标签...` |
| 7 | 管理台用户搜索 | `frontend/src/pages/admin/UsersPage.tsx:577` | `Input.Search` |
| 8 | 添加成员搜索 | `frontend/src/pages/settings/AddMemberModal.tsx:58` | placeholder 带半角 `...` |
| 9 | 权限编辑器成员搜索 | `frontend/src/pages/grid/permissions/PermissionEditor.tsx:637` | placeholder `搜索工作区成员...` |
| 10 | 字段管理过滤 | `frontend/src/pages/fields/FieldManager/index.tsx:595` | placeholder `按字段名过滤` |
| 11 | 顶栏全局搜索 | `frontend/src/components/GlobalSearch.tsx:286-299` | C5 排除项，保持不变 |

## 未决问题

- [x] 是否加防抖？→ 结论：本地过滤均为即时过滤（数据量小），不引入防抖；`useDebouncedValue` 保留给已有使用方（GlobalSearch 自带 250ms 防抖，不在本次范围）。
- [x] 是否统一为 `Input.Search` 带按钮？→ 结论：否，统一为无按钮 `Input` + prefix 形态（现有 8/10 处即此形态，按钮形态属少数派）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（方案已在会话中获用户确认）

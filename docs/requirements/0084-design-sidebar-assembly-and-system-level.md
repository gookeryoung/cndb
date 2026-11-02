# 需求卡片：【设计】侧栏装配结构树与系统级装配声明

- 编号：0084
- 来源 / 提出人：用户
- 日期：2026-11-02
- 关联 ADR：`docs/adr/0084-design-sidebar-assembly-and-system-level.md`（S2：DSL 语法 + IR 契约演进 + 前端布局架构）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 【设计】功能完善，进入该模块后，侧边栏应展示设计装配结构，参考文档结构。装配层级除了零件级的细节，还应显示组件级和复杂系统级。请基于上述内容，完善DSL设计，并给出系统装配结构的示例。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「进入该模块后，侧边栏应展示设计装配结构，参考文档结构」 | `MainLayout` 设计段（`inDesignContext`）新增侧栏导航 `renderDesignNav`，形态参照文档段 `renderDocumentNav`：Sider 内「设计」标题 + 标题过滤 + 装配树（设计根 → 系统 → 组件 → 分组 → 零件），展开设计懒加载既有 `GET /designs/{id}/outline` 端点（ADR 0083 D4，零新增端点）；点击设计进编辑器，点击大纲节点带 `?line=` 定位（ADR 0083 D7 交互沿用）；`SiderMode` 增加 `'design'`，设计段不再自动折叠为图标条；移动端抽屉共用同一导航 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/` | `MainLayout.test.tsx` 新增用例 + e2e |
| C2 | 「还应显示组件级和复杂系统级」（复杂系统级） | 结构 DSL 新增顶层声明 `system <名> { 实例* }`：表达「复杂系统由哪些组件与零件装配而成」；编译大纲（IR `outline`）新增 `kind: "system"` 节点，IR `version` 2 → 3；侧栏树层级为 设计 → **系统** → 组件（`module` 实例，可嵌套 = 子装配）→ 结构分组 → **零件**，与「复杂系统级 / 组件级 / 零件级」三级口径对齐 | `src/cndb/plugins/design/services/dsl/`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/api/design.ts` | 判定层单测（system 解析 / 大纲结构 / 几何等价）+ 前端单测 |
| C3 | 「完善DSL设计」 | `system` 的语法与语义校验口径：仅允许顶层（模块体 / 系统体 / 布尔块内声明报语法错误）；无参数表（可配置性走顶层 `param`）；不可实例化（`system` 名出现在实例位置报「system 不可实例化，请改用 module」）；名与 `module` / 图元 / 关键字重名报错；`system` + `module` 总数计入 `MAX_MODULES`（128）；`system` 为纯组织层——同原文把 system 体平铺到顶层，`nodes` / `params` 完全一致 | `src/cndb/plugins/design/services/dsl/parse.py`、`compile.py`、`limits.py` | `tests/test_design_dsl.py` 扩展 |
| C4 | 「给出系统装配结构的示例」 | 新建设计默认模板（`DEFAULT_DESIGN_CONTENT`）与帮助文档设计主题改为含 `system` 的完整三级装配示例（复杂系统 → 组件 → 零件，见 ADR §9 示例），保证新建即见三级层级 | `frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/help/content/*` | 前端单测 + e2e 断言模板含系统级节点 |
| C5 | 主区与侧栏分工（由「参考文档结构」派生，见未决问题①） | 结构树迁至侧栏后，`/w/:wid/design` 主区（「设计结构」页签本体）恢复为设计管理页：新建 / 打开 / 改名 / 描述 / 删除与版本 / 更新时间摘要，路由与二级页签（ADR 0083 C1/C2）不变——对齐文档模块「侧栏 = 导航树、主区 = 管理列表 / 编辑器」的分工 | `frontend/src/pages/design/DesignsPage.tsx` | `DesignsPage.test.tsx` 主流程回归 |
| C6 | 配套回归 | 编辑器语法高亮（`designLang.ts`）补 `system` 关键字；兼容回归：无 `system` 的旧原文与 v2 快照照常编译 / 渲染（树无系统级层不报错）；CHANGELOG 记录；e2e 新增侧栏装配树用例并回归 `design-structure-tree.spec.ts` | `frontend/src/pages/design/designLang.ts`、`CHANGELOG.md`、`frontend/tests/e2e/critical/` | `make flow` + `make e2e` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，已核实）

| # | 疑似受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 设计段 Sider 沿用数据表导航并自动折叠为图标条（`inFocusContext` 含 `inDesignContext`） | `frontend/src/layouts/MainLayout.tsx:405-420`、`:412-431` | C1 改造点：设计段需独立 Sider 形态 |
| 2 | 文档段侧栏范式 `renderDocumentNav`（标题 + 工具行 + 树；桌面 Sider 与移动抽屉共用） | `frontend/src/layouts/MainLayout.tsx:617` | C1 照抄形态的参照 |
| 3 | 装配结构树目前在主区「设计结构」页本体（0083 D6） | `frontend/src/pages/design/DesignsPage.tsx:203-276` | C1/C5 改造点：树迁侧栏、主区恢复管理页 |
| 4 | DSL 顶层仅 `param` / `module` / 实例三种语句，无系统级声明载体 | `src/cndb/plugins/design/services/dsl/parse.py:115-129` | C2/C3 关键缺口：`module` 实例 = 组件级、图元 = 零件级，「复杂系统级」无名可依 |
| 5 | IR v2 大纲节点仅 `assembly` / `group` / `part` 三类 | `src/cndb/plugins/design/services/dsl/compile.py:311-340`、`frontend/src/api/design.ts:59-82` | C2 契约演进点 |
| 6 | 大纲树映射与文案（`DesignTreeMeta.type` 四值） | `frontend/src/pages/design/designOutline.ts:11-105` | C2 需增 `system` 类型与「系统」文案 |
| 7 | 编辑器语法高亮关键字表不含 `system` | `frontend/src/pages/design/designLang.ts:13-16` | C6 改动点 |
| 8 | 编译期限制 `MAX_MODULES = 128`（仅计 module） | `src/cndb/plugins/design/services/dsl/limits.py:17` | C3 计数口径改动点 |
| 9 | 备份 v12 导出 DSL 原文、导入端逐版重编译 | `src/cndb/plugins/workspaces/services/backup_io.py` | 预计协议不变，`system` 随重编译重建 |
| 10 | 新建设计默认模板为法兰板（无系统级写法） | `frontend/src/pages/design/DesignsPage.tsx:30-46` | C4 改动点 |

## 未决问题（含结论，已由需求方拍板）

- [x] ① 主区「设计结构」页形态：**结论**恢复为设计管理列表（结构树由侧栏承担，避免双树冗余，对齐文档模块分工，即 C5）。
- [x] ② `system` 是否允许多个：**结论**允许（一份设计可同时含「产品 + 工装」等多个系统根，各自成树顶层系统节点）。
- [x] ③ 编辑器页内是否另做大纲面板：**结论**本期不做（侧栏树已承担导航与定位，编辑器保持 DSL + 预览双栏）。

2026-11-02 需求方原话：「对齐文档模块，允许，不做。按此执行。」

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（①②③ 已于 2026-11-02 拍板）

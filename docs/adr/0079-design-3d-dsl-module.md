# ADR 0079: 【设计】模块与结构 DSL（3D 机械制图实时预览与生成）

Status: Proposed（待评审）
Date: 2026-11-01
Related: `src/cndb/plugins/base.py`、`src/cndb/core/plugin_registry.py`、`src/cndb/plugins/pipeline/plugin.py`、`src/cndb/plugins/documents/models.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/utils/workspaceType.ts`、`docs/adr/0026-chrome81-compat.md`、`docs/adr/0047-permission-denied-message.md`、`docs/adr/0075-workspace-full-backup.md`、`docs/adr/0076-pipeline-check-dsl.md`
需求卡片: `docs/requirements/0079-design-3d-dsl-module.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 在数据表和文档同级，新增【设计】模块（在文档之后） | 新插件 `src/cndb/plugins/design/`（`route_prefix="workspaces"`），顶部工作区页签「设计」插入「文档」与「数据分析」之间（icon `ToolOutlined`），路由 `/w/:wid/design`；前端新增 `design` feature key（`data_doc` / `doc` 开、`data` 关，D8） |
| C2 | 设计DSL专用语言，用于描述产品结构设计 | 自研文本 DSL「结构 DSL」（文件约定 `.cnmd`）：`param` 参数 / `module` 模块复用 / 六种图元 / 四种变换 / 三种布尔 / 白名单算术与三角函数；手写递归下降编译为 IR，零新增后端依赖（D2） |
| C3 | 支持典型3D机械制图的实时预览 | 编辑器用既有 CodeMirror 6（自定义 StreamLanguage），输入防抖 300ms 调 `POST /design/preview`（无落库即时编译），前端按 IR 经 three.js + `three-bvh-csg` 渲染（含布尔求值）；诊断按行/列回显编辑器 gutter；参数面板改参即重编译重渲染（D4） |
| C4 | 和生成 | P2 从 IR 求值结果在前端导出 STL / OBJ / GLB 与正交三视图 PNG；不承诺 STEP / DWG 等 BREP 格式（D5） |
| C5 | 请制定开发计划 | §8 分期：P0 引擎与数据模型 → P1 API 与实时预览前端 → P2 生成导出 / 备份 v11 / 帮助与示例种子 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 插件基类提供 `register_models` / `register_routes` / `register_navigation` 钩子，`plugin_registry` 自动发现各插件的 `plugin` 单例并挂路由 | `src/cndb/plugins/base.py:68`、`src/cndb/core/plugin_registry.py:41`、`src/cndb/app.py:138-139` | 新模块无需改应用装配代码，按目录约定即可被发现 | 确认：`design` 以标准插件接入 |
| 2 | 工作区级页签由 `MainLayout` 按类型特性拼装（tables / documents / analytics / datasource / quality） | `frontend/src/layouts/MainLayout.tsx:241-276` | 「设计」页签有现成挂载点与门控分支；`workspaceTypeFeatures` 需扩一个 feature key | 确认：新增 `design` key + 页签插在文档之后（C1） |
| 3 | 文档模块已建立「内容原文 + 每保存一版」范式（`Document` / `DocumentVersion`），编辑器基于既有 CodeMirror 6 依赖 | `src/cndb/plugins/documents/models.py:67`、`frontend/package.json:36-41` | 设计的定义载体、版本化与编辑器选型可直接复用该范式与依赖 | 确认：两表建模对齐文档；编辑器不引 Monaco（D11） |
| 4 | 流水线 DSL 已确立「原文入库 + 保存期编译 IR 快照 + 运行读 IR」的判定口径 | `docs/adr/0076-pipeline-check-dsl.md` D2、`src/cndb/plugins/pipeline/models.py`（`content` + `compiled` 列） | 结构 DSL 沿用同一口径可保证运行期零语法错误、历史可复现 | 确认：`design` 两表同样存 `content` + `compiled`（I1/I2） |
| 5 | 工作区备份当前协议 v10（v9 + `pipelines[]`），恢复走「清空 + 全量重建」 | `src/cndb/plugins/workspaces/services/workspace_backup.py:37`、`workspace_restore.py` | 设计定义与版本需纳入备份；旧备份（≤v10）导入不能受影响 | 新增：v11 顶层 `designs[]`（含版本），D9 |
| 6 | 前端有 Chrome 81 兼容基线（构建目标 `chrome81` + 定时冒烟）与分 chunk 体积预算门禁 | `docs/adr/0026-chrome81-compat.md`、`docs/BUNDLE_BUDGET.md`、`frontend/scripts/bundle-budget.mjs` | three.js 是首个 3D 渲染依赖（gzip 数百 KB），必须独立 lazy chunk 并新增预算基线；Chrome 81 支持 WebGL2，但需以冒烟验证 three.js 实际可用版本 | 新增：P1 落地时锁定「可用的最低 three.js 版本 + bvh-csg」并跑 `pnpm e2e:chrome81`（D4 风险项） |
| 7 | 权限判定与 403 文案统一入口 | `docs/adr/0047-permission-denied-message.md`、`src/cndb/plugins/workspaces/permissions.py` | 设计写路径的拒绝提示直接复用 | 确认：viewer 写入 403 文案走统一入口（D6） |
| 8 | alembic 迁移链头为流水线迁移 `y3z4a5b6c7d8` | `src/cndb/alembic/versions/y3z4a5b6c7d8_add_pipeline_plugin.py:20` | 新迁移单条挂接，存量零迁移 | 确认：`down_revision = "y3z4a5b6c7d8"`（D9） |
| 9 | 文档 / 表格写路径有双轨制（viewer 转修改申请） | `src/cndb/plugins/documents/services/change_requests/resolve_write_mode.py` | 设计是否纳入双轨需定口径 | 排除：设计源是技术产物，评审诉求由版本列表回看承载，不建双轨（D6） |
| 10 | 帮助文档为前端静态 TSX（一级 5 部分），示例种子在 `examples/datasets/<工作区>/` | `frontend/src/pages/help/`、`examples/datasets/` | 设计模块需要帮助主题与示例设计，有现成范式 | 新增：P2 补帮助主题 + `designs/*.cnmd` 种子（与 `pipelines/*.yaml` 同范式） |

**核心缺陷（需求要补的）**：现状没有任何机制能让用户**用一门专用语言描述产品结构（参数化几何 + 布尔组合）并在浏览器里实时看到三维模型、拿到可交付的模型文件**——三维内容在本平台完全缺席。

设计目标（不变量）：

- **I1 原文唯一真相源**：DSL 原文是唯一事实；任何渲染 / 导出只能消费后端编译产出的 IR，前端不得自行解析 DSL。
- **I2 保存即校验**：保存 / 更新时完整编译并落 `compiled` 快照；编译不通过拒绝落库（400 + 结构化诊断），运行期不出现语法 / 结构错误（对齐 ADR 0076 I2）。
- **I3 编译确定性**：同原文 + 同参数覆盖 → 同 IR；编译过程无随机、无时间依赖、无外部 IO。
- **I4 权限最小面**：写路径仅 owner / editor；viewer 对全部写端点 403（ADR 0047 文案），无隐藏写入口子。
- **I5 单位固定**：长度一律 mm、角度一律 deg，DSL 内不存在单位换算语义；IR 显式携带单位声明，前端渲染不得自行缩放。
- **I6 限制有界**：编译期限制（体积 / 嵌套 / 图元 / 参数 / 模块数）超限报错，不产出半截 IR。

## Decision

### 1. 数据模型

新插件 `src/cndb/plugins/design/`，两张表（均 `TimestampMixin` + 工作区级 `workspace_id` 外键 `ondelete="CASCADE"`，命名与文档模块同范式）：

**`design_design`** —— 一份结构设计：

| 列 | 类型 | 说明 |
|---|---|---|
| `workspace_id` | FK(workspaces_workspace) CASCADE | 工作区级，级联删除 |
| `title` | String(200) | 名称，同工作区内唯一（`UniqueConstraint(workspace_id, title)`） |
| `content` | Text | DSL 原文（`.cnmd`），用户可读可编辑的唯一真相源 |
| `compiled` | JSON | 保存期编译出的 IR 快照（校验通过才可落库）；预览 / 渲染只读 IR |
| `description` | String(500) | 用途说明，默认空 |
| `is_deleted` | Boolean | 软删（列表过滤），默认 false；回收站 UI 不在本期范围 |
| `created_by_id` / `updated_by_id` | FK(accounts_user, SET NULL) | 创建 / 最后修改人 |

**`design_designversion`** —— 版本（对齐 `DocumentVersion`：每次保存落一版）：

| 列 | 类型 | 说明 |
|---|---|---|
| `design_id` | FK(design_design) CASCADE | 所属设计 |
| `workspace_id` | FK(workspaces_workspace) CASCADE | 冗余便于工作区级过滤 |
| `version_number` | Integer | 同设计内递增，`(design_id, version_number)` 唯一 |
| `content` | Text | 该版 DSL 原文 |
| `compiled` | JSON | 该版 IR 快照 |
| `comment` | String(200) | 版本备注，默认空 |
| `created_by_id` | FK(accounts_user, SET NULL) | 提交人 |

不建状态机（draft / published）、不建文件夹层级、不建分享与修改申请（D6 / D8）。

### 2. DSL 规范与判定算法（唯一入口）

**结构 DSL（`cnmd`）语法 v1**——类 OpenSCAD 的图元 / 变换 / 布尔子集，但为自研语法、只做数据不做代码：

```text
// 参数：驱动参数面板，可被预览覆盖重编译
param width = 80          // 长度单位 mm
param height = 40
param hole_d = 8

// 模块：带默认值的可复用结构
module plate(w, h, t) {
  difference {
    box(size = [w, h, t])
    translate([w/2, h/2, -1]) {
      cyl(d = hole_d, h = t + 2)   // 减切通孔：两端各出 1mm
    }
  }
}

plate(width, height, 12)            // 顶层实例（产出几何）
```

- **语句**：`param name = expr`（顶层）、`module name(p, p = default) { body }`、图元调用、变换包裹（块或单子句）、布尔块、模块实例化、`//` 与 `/* */` 注释。
- **图元（P0 固定 6 种）**：`box(size=[x,y,z] | w=,h=,d=)`、`cyl(d=,h=,fn=)`（沿 Z 轴）、`sphere(r=,fn=)`、`cone(d1=,d2=,h=,fn=)`、`torus(r=,tube=,fn=)`、`tube(od=,id=,h=,fn=)`；`fn` 为分段数（默认 64，上限 256）。新图元属于 DSL 版本演进（双端同步），不开放注册表（双端渲染语义必须一致）。
- **变换**：`translate([x,y,z])`、`rotate([rx,ry,rz])`（deg）、`scale([x,y,z])`、`mirror([x,y,z])`；变换内可嵌套变换（矩阵按外→内复合）。
- **布尔**：`union {}` / `difference { 首个为保留体，其余为切割体 }` / `intersection {}`；可任意嵌套。
- **表达式**：数值字面量、标识符、`+ - * / %`、括号、比较与三元不做（v1）、白名单函数 `sin cos tan asin acos atan2 sqrt abs min max pow floor ceil round`、常量 `PI`。
- **编译期限制（I6）**：原文 ≤ 256KB；嵌套深度 ≤ 32；图元实例总数 ≤ 2000；`param` ≤ 64；`module` ≤ 128；模块实例化递归 ≤ 16 层。超限报诊断，不出 IR。

**编译入口（唯一）**：`design/services/dsl/compile.py::compile_design(content: str, overrides: dict | None) -> CompileResult`，递归下降（词法 → 语法 → 常量折叠求值 → IR），无 eval、无新依赖（对齐 ADR 0076 D3 的沙箱口径）。`CompileResult` 携带 `ir` 与结构化诊断列表 `[{severity, line, col, message}]`。保存端点与预览端点都只调它（I1）；参数覆盖只在此入口合并求值，前端永不自行求值。

**IR 形态（v1，双端契约）**：

```json
{
  "version": 1,
  "units": {"length": "mm", "angle": "deg"},
  "params": [{"name": "width", "value": 80}],
  "nodes": [
    {"op": "difference", "children": [
      {"op": "box", "size": [80, 40, 12]},
      {"op": "cyl", "d": 8, "h": 14, "fn": 64,
       "transform": {"translate": [40, 20, -1]}}
    ]}
  ]
}
```

表达式已在编译期求值为字面量；`nodes` 为布尔树，`transform` 修饰单个图元。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/designs` | 新增：设计列表（过滤软删） |
| `POST /api/v1/workspaces/{wid}/designs` | 新增：创建（原文必经编译，失败 400 + diagnostics） |
| `GET /api/v1/workspaces/{wid}/designs/{id}` | 新增：详情（含原文与 IR） |
| `PUT /api/v1/workspaces/{wid}/designs/{id}` | 新增：改名 / 描述 |
| `PUT /api/v1/workspaces/{wid}/designs/{id}/content` | 新增：保存原文 → 编译 → 落 `compiled` + 新版本 |
| `DELETE /api/v1/workspaces/{wid}/designs/{id}` | 新增：软删 |
| `POST /api/v1/workspaces/{wid}/designs/preview` | 新增：即时编译（请求体 `{content, overrides?}`），无落库；返回 `{ir, diagnostics}` |
| `GET /api/v1/workspaces/{wid}/designs/{id}/versions` | 新增：版本列表（P2 暴露回看 / 恢复端点） |
| `POST /api/v1/workspaces/{wid}/designs/{id}/versions/{n}/restore` | 新增（P2）：以历史版原文重新编译保存为新版 |

写端点（POST / PUT / DELETE）owner / editor；全部端点工作区成员可读（D6）。

### 4. 边界与例外

1. 预览端点不落库、不计版本：高频调用（每次防抖触发）只做编译，无任何写副作用；诊断按行 / 列返回，编辑器 gutter 定位。
2. 保存失败（编译不过）保持库内旧 `compiled` 不动，前端编辑器仍显示用户草稿（「保存被拒但内容不丢」）。
3. 顶层无实例（只有 param / module 声明）编译通过但 `nodes` 为空 → 合法，预览显示空画布 + 提示「顶层尚无实例」。
4. 几何非法值（负尺寸 / 分段数越界 / 除零）按编译诊断报错，不做静默截断（I6）。
5. 布尔求值结果可能因前后端三角化差异出现极小数值偏差：IR 为语义契约，导出文件以**前端求值结果**为准（D5），不承诺与服务端（若未来引入）逐字节一致。
6. 大模型 / 搜索 / 质量检查等其他模块不改：设计 DSL 不进文档正文引用体系（无 `{{design:}}` 嵌入，v1 不做）。

### 5. 迁移

单条迁移 `z4a5b6c7d8e9_add_design_plugin.py`（`down_revision = "y3z4a5b6c7d8"`）：建 `design_design` / `design_designversion` 两表 + 索引（`ix_design_design_ws`、`(workspace_id, title)` 唯一、`(design_id, version_number)` 唯一）。幂等（`op.create_table` 前查存在）；downgrade 全量 DROP 两表。存量数据零迁移（纯新增表）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 类型门控 | `frontend/src/utils/workspaceType.ts` | 新增 `design` feature key；`data_doc` / `doc` 开、`data` 关；文案表与测试同步 |
| 页签 | `frontend/src/layouts/MainLayout.tsx` | 「设计」页签插在文档之后（`ToolOutlined`）；URL 门控重定向分支补 `/design` |
| 路由 | `frontend/src/App.tsx` | `lazy` 挂 `/w/:wid/design`（列表）与 `/w/:wid/design/:id`（编辑器） |
| 列表页 | `frontend/src/pages/design/DesignsPage.tsx` | 新建 / 打开 / 改名 / 删除 / 描述 |
| 编辑器 | `frontend/src/pages/design/DesignEditorPage.tsx` | CodeMirror 6 编辑器 + 预览画布 + 参数面板 + 诊断列表 + 导出入口；three.js 相关全部 `lazy` 子组件 |
| 语言支持 | `frontend/src/pages/design/designLang.ts` | CodeMirror `StreamLanguage` 高亮（关键字 / 图元 / 数值 / 注释） |
| 预览循环 | `frontend/src/pages/design/useDesignPreview.ts` | 300ms 防抖调 preview 端点，带参数覆盖；请求竞态以最后胜出（序号丢弃过期响应） |
| 渲染 | `frontend/src/pages/design/renderTree.ts` | IR → three.js 场景；`difference` / `union` / `intersection` 经 `three-bvh-csg` 求值；正交 / 透视切换与相机拖拽 |
| 导出 | `frontend/src/pages/design/exporters.ts` | STL（二进制）/ OBJ / GLB + 正交三视图 PNG（前 / 上 / 右） |
| API 封装 | `frontend/src/api/design.ts` | 端点封装 |
| 体积预算 | `frontend/scripts/bundle-budget.json` | 新增 Design 编辑器 chunk 基线（走 `bundle:budget:update` 带 reason）；three.js 仅在编辑器 lazy chunk 内出现 |
| 帮助 | `frontend/src/pages/help/content/` | P2：设计模块主题（语法说明 + 示例） |

### 7. 测试清单

**判定层（单测）**：`tests/test_design_dsl.py`——词法 / 语法各语句形态、表达式求值与白名单函数、参数覆盖、模块默认值与递归上限、六图元参数合法性、布尔嵌套、诊断行/列、全部编译期限制（超限报错不出 IR）、编译确定性（同输入同输出）。

**接口层**：`tests/test_design_api.py`——CRUD、保存落版本、编译失败 400 + diagnostics 且旧 IR 不动、preview 无副作用（库内无新行）、viewer 写 403（ADR 0047 文案）、成员可读、重名 409。

**迁移 / 备份**：`tests/test_design_migration.py`（幂等 + downgrade）、`tests/test_workspace_backup_v11.py`（v11 往返含版本、v10 旧备份导入无 designs 字段正常）。

**前端单测**：`designLang.test.ts`（高亮分词）、`useDesignPreview.test.ts`（防抖 / 竞态 / 覆盖参数）、`renderTree.test.ts`（IR 分派与布尔节点）、`exporters.test.ts`（STL 头部与三视图产物）、`DesignsPage.test.tsx` / `DesignEditorPage.test.tsx`（列表与编辑器主流程）。

**e2e（前端）**：`frontend/tests/e2e/critical/design-3d-preview.spec.ts`——新建设计 → 输入示例 DSL → 画布出现（Canvas/WebGL 上下文断言）→ 诊断展示 → 导出 STL 下载；`pnpm e2e:chrome81` 冒烟覆盖设计编辑器路由。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `design` 插件骨架 + 两表 + 单条迁移 + DSL 编译引擎（词法 / 语法 / 求值 / IR / 诊断 / 限制）+ 判定层单测 | 低 |
| **P1** | API（CRUD / preview / 版本）+ 前端设计页签与编辑器（CodeMirror 语言包 + three.js 实时预览 + 参数面板）+ 体积预算基线 + Chrome 81 冒烟 | 中（three.js 新依赖与 Chrome 81 实测；布尔求值性能） |
| **P2** | 导出（STL / OBJ / GLB + 正交三视图）+ 版本回看 / 恢复 + 备份 v11 往返 + 帮助主题与示例种子（`examples/datasets/<工作区>/designs/*.cnmd`）+ e2e 收口 | 中 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 新插件 `design`（工作区级，与 tables / documents 同级）+ 自研文本 DSL 唯一真相源 + 后端编译 IR + 前端 three.js 渲染（C1-C4） | 插件架构零装配改动（Context #1）；DSL 原文 + compiled 快照已有 ADR 0076 先例（Context #4） | 复用 documents 存 DSL 为普通文档（无编译 / 参数 / 3D 语义，版本模型错位）；表单化建模（表达力受限，无法承载嵌套布尔与复用） | `src/cndb/plugins/design/`、`frontend/src/pages/design/` |
| D2 | DSL 载体与形态 | 自研「结构 DSL」（`.cnmd`）：param / module / 6 图元 / 4 变换 / 3 布尔 / 白名单表达式；原文入 `content`，保存与预览期编译 IR 入 `compiled`，手写递归下降 | 覆盖「产品结构设计」所需的表达力（参数化 + 复用 + 布尔组合）；编译期求值保证运行期零语法错误（I2）；零新增后端依赖 | 直接嵌 OpenSCAD / Python（任意代码执行，沙箱不可控）；YAML / JSON 声明式（嵌套布尔与模块复用表达力差，见 ADR 0076 D2 同型权衡）；lark 等 parser 依赖（语法小而稳，手写更省） | `design/services/dsl/`（`lexer.py` / `parse.py` / `expressions.py` / `compile.py`）、`design/models.py` |
| D3 | 判定唯一入口 | `compile_design(content, overrides)` 为唯一编译入口；保存与 preview 端点共用；前端零解析、零求值，只消费 IR（I1） | 单一判定口径避免双端语法漂移；参数面板改参经 preview 端点重编译而非前端求值 | 前端并行实现解析器（双真相源，必然漂移）；预览落库（防抖高频调用，写放大不可接受） | `design/services/dsl/compile.py`、`design/routers/` |
| D4 | 实时预览技术 | three.js（WebGL2）+ `three-bvh-csg` 客户端布尔求值；编辑防抖 300ms 调 preview 端点；three 相关代码全部收敛进编辑器 lazy chunk 并设体积预算基线；新依赖 `three` / `@types/three` / `three-bvh-csg` 需人工确认 | 「实时」要求渲染延迟在百毫秒级，客户端渲染是唯一现实路径；Chrome 81 支持 WebGL2（Context #6），以冒烟实测锁定版本 | 服务端渲染回传位图（并发与延迟差，实时性不达标）；不布 CSG、切割体半透明显示（对机械零件误导，孔洞不可见）；Babylon.js（体积更大，同等能力无优势） | `frontend/src/pages/design/renderTree.ts`、`useDesignPreview.ts`、`frontend/package.json` |
| D5 | 生成口径 | P2 前端从 IR 求值结果导出 STL（二进制）/ OBJ / GLB + 正交三视图 PNG；不承诺 STEP / DWG / 工程标注（BREP 内核超 v1 范围，卡片未决问题①） | 网格格式覆盖 3D 打印 / 预览 / 交付主流诉求；three.js 自带导出器，零新增依赖 | 后端 manifold3d / trimesh 生成（新增原生依赖、离线镜像复杂化，且无服务端批量需求，卡片未决问题②）；STEP / DXF（需 BREP 内核，成本不成比例） | `frontend/src/pages/design/exporters.ts` |
| D6 | 权限口径 | 成员可读；owner / editor 可写；viewer 全部写端点 403（ADR 0047 统一文案）；不建修改申请双轨 | 设计源是技术产物，协作评审由版本列表回看承载；双轨复杂度与收益不成比例（Context #9） | 复用文档 / 表格双轨制（viewer 保存转申请：IR 与版本语义需全链路二次设计，v1 不做） | `design/routers/` |
| D7 | 版本模型 | 每次保存落 `design_designversion`（对齐 `DocumentVersion`），P2 暴露版本列表与「以旧版原文重新保存」的恢复端点 | 结构设计天然多轮迭代，回看与回退是最低配协作诉求 | 只存最新（丢历史，评审无据）；每次保存存整套导出产物（体量与格式演进不可控） | `design/models.py`、`design/routers/versions.py` |
| D8 | 模块入口与类型门控 | 页签「设计」位于「文档」之后，icon `ToolOutlined`，路由 `/w/:wid/design`；`workspaceTypeFeatures` 新增 `design` key：`data_doc` / `doc` 开、`data` 关 | 需求明确排位（C1）；`data` 型定位纯数据、无内容创作语义（Context #2） | 新增第四种工作区类型 `DESIGN`（迁移 + 文案 + 门控全链改动，需求未要求类型隔离）；全部类型开放（`data` 型页签膨胀） | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/utils/workspaceType.ts` |
| D9 | 迁移与备份 | 单条 alembic 迁移挂 `y3z4a5b6c7d8` 之后；备份协议 v11 顶层增 `designs[]`（含版本），恢复走既有「清空 + 全量重建」路径；≤v10 旧备份导入不受影响 | 纯新增表存量零迁移（Context #8）；备份逐版本演进有 v9→v10 先例（Context #5） | 复用 v10（协议有版本号语义，混装破坏兼容判断）；设计不进备份（跨环境迁移丢数据） | `alembic/versions/z4a5b6c7d8e9_add_design_plugin.py`、`workspace_backup.py`、`workspace_restore.py`、`backup_io.py` |
| D10 | 限制与配额 | 编译期限制：原文 ≤ 256KB、嵌套 ≤ 32、图元 ≤ 2000、param ≤ 64、module ≤ 128、模块递归 ≤ 16；工作区不设数量上限（对齐文档不设上限） | 有界编译保证 preview 端点延迟可控（I6）；上限取值留有余量，实测后可再收紧 | 无限制（恶意 DSL 可构造指数嵌套拖垮预览端点） | `design/services/dsl/limits.py` |
| D11 | 编辑器选型 | CodeMirror 6（既有依赖）+ 自写 `StreamLanguage` 高亮 + 诊断 gutter；诊断数据来自编译端点 | 文档模块已用 CodeMirror 6（Context #3），心智与依赖一致；DSL 语法小，StreamLanguage 足够 | Monaco（体积与 worker 复杂度高，与体积预算冲突）；纯 textarea（无高亮与诊断定位） | `frontend/src/pages/design/designLang.ts`、`DesignEditorPage.tsx` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：平台首次具备三维结构表达能力；DSL 原文 + IR 快照使设计可版本化、可备份、可确定性复现；后端零新增依赖，前端新依赖全部隔离在 lazy chunk；参数面板让同一设计族一份源码多规格出图。
- **负向**：前端引入 three.js（首个重型渲染依赖，需预算基线长期看护）；布尔求值在客户端，复杂设计的预览性能依赖用户设备；放弃 STEP / 工程标注使 v1 产物面向「沟通与 3D 打印」而非「制造工艺链」。
- **风险与缓解**：three.js 与 Chrome 81 内核兼容性 → P1 以 `pnpm e2e:chrome81` 实测锁定版本，失败则回退可用的旧版 three（WebGL2 在 81 可用，风险集中在 JS 语法与 API 面）；CSG 三角化差异 → IR 为语义契约、导出以客户端求值结果为准（边界 #5）。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 行业对照（可选）

| 维度 | OpenSCAD | Onshape / Fusion（参数化 CAD SaaS） | 本设计 |
|---|---|---|---|
| 描述载体 | 代码式 CSG DSL（module / union / difference / translate） | GUI 特征树 + 表达式约束 | 文本 DSL + 编译 IR + Web 实时预览（D2） |
| 布尔运算 | 服务端网格化 | BREP 内核 | 客户端 `three-bvh-csg`（D4） |
| 导出 | STL / OFF / DXF 等 | STEP / STL / DWG 全链 | STL / OBJ / GLB + 三视图 PNG，不做 BREP（D5） |
| 单位语义 | 无单位（隐式） | mm / inch 显式 | 固定 mm / deg，编译期校验（I5） |

来源：OpenSCAD 官方手册（Manual，openscad.org）；Onshape 文档（onshape.com/help）。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| DSL 编译快照范式 | `content` + `compiled` 双列 | 结构 DSL 沿用流水线 DSL 的「原文唯一真相源 + 保存期编译」口径 | ADR 0076 D2 / 本 ADR D2 |
| 备份协议演进 | `payload/backup.json` | v11 增 `designs[]`，v9/v10 兼容导入不破坏 | ADR 0075 / 本 ADR D9 |
| Chrome 81 基线 | `.browserslistrc` + 冒烟 | three.js 新依赖纳入既有兼容与体积门禁，不豁免 | ADR 0026 / 本 ADR D4 |
| 403 文案口径 | 权限拒绝统一入口 | viewer 写设计走同一文案 | ADR 0047 / 本 ADR D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 未开始 | — | — | — |
| P1 | 未开始 | — | — | — |
| P2 | 未开始 | — | — | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：方案评审（Proposed，未进入实现）
- 已完成：需求卡片 0079、本 ADR、CONTEXT.md 术语、ADR 索引登记
- 下一步：人工评审通过后 `Status` 改 `Accepted`，按 P0（DSL 引擎 + 两表 + 迁移）开工，交给 `implementer`
- 已知坑：three.js 在 Chromium 81 内核的实际可用版本未实测（P1 首个动作是锁定版本 + 冒烟）；`three-bvh-csg` 与 three 主版本需配对锁定
- 最近一次全绿：`make check-docs` @ 本次方案提交（2026-11-01）

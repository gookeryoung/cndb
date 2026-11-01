# ADR 0083: 【设计】模块二级导航「设计结构」与装配大纲树

Status: Accepted（2026-11-01 评审通过，进入实现）
Date: 2026-11-01
Related: `src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/services/dsl/nodes.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/plugins/design/schemas.py`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/DslEditor.tsx`、`frontend/src/api/design.ts`、`docs/adr/0079-design-3d-dsl-module.md`
需求卡片: `docs/requirements/0083-design-structure-subnav-and-assembly-tree.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「增加【设计结构】二级导航入口」 | `MainLayout` 新增 `DESIGN_SUBPAGES`（单条目「设计结构」，`to: ''`，icon `ApartmentOutlined`），渲染条件 `inDesignContext`，形态照抄 `DOCUMENT_SUBPAGES` 的 `cn-table-crumb` + `role="tab"` 页签；`/w/:wid/design` 无子段时激活，编辑器页显示但无子页激活（D6） |
| C2 | 「作为默认页」 | `/w/:wid/design` 复用既有路由，页面内容由平面列表改造为结构树页（保留新建 / 打开 / 改名 / 删除 / 描述）；不新增路由、不新增页面文件（D6） |
| C3 | 「使用树形结构展示不同装配层级的组件和零件」 | 编译链路在产出 `nodes` 的同时产出顶层 `outline`（组件 `assembly` / 布尔分组 `group` / 零件 `part` 三类节点），IR `version` 1 → 2；前端只消费 `outline` 渲染树、零解析（I1）；跨设计 BOM 引用不做（D1） |
| C4 | 「节点带 DSL 源位置」 | 大纲节点携带 1 基 `line` / `col`（语句起始位置）；树节点展示「第 N 行」，点击组件 / 分组 / 零件节点进入编辑器并定位该行（`?line=N`）；实例计数由前端按 children 派生，不落后端（D3 / D7） |
| C5 | 配套回归 | 设计门控（`wsFeatures.design` + URL 重定向）回归；帮助「工作区二级页签」与设计主题文案同步；CHANGELOG 记录；e2e `navigation.spec.ts` 补页签断言 + 新增结构树 e2e |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 文档区二级页签已有「结构优先」范式（`DOCUMENT_SUBPAGES` 首项 `to: ''`），页签由 pathname 驱动激活态 | `frontend/src/layouts/MainLayout.tsx:58-63`、`:905-932` | 设计区可同形接入，无需新组件 | 确认：C1 直接复用形态 |
| 2 | 设计区已有 `inDesignContext` 与 URL 门控重定向，但无二级页签渲染 | `frontend/src/layouts/MainLayout.tsx:391`、`:433-439` | 只需补 crumb 分支，门控逻辑不变 | 确认：C1 改造点 |
| 3 | 设计路由仅两条：`/w/:wid/design`（列表）、`/w/:wid/design/:id`（编辑器） | `frontend/src/App.tsx:102-106` | 「默认页」可在原路由替换页面内容，不新增路由 | 确认：C2 复用路由 |
| 4 | IR 编译期把模块实例内联展开：`_emit_module_call` 直接以调用方环境求值模块体，产物只有图元 / 布尔树 | `src/cndb/plugins/design/services/dsl/compile.py:319-331`、`nodes.py:110-121` | 装配层级在产物中完全丢失 → 树无法从 `nodes` 还原 | 新增：C3 的根因，需与 IR 同源产出大纲 |
| 5 | IR 契约 `IR_VERSION = 1`，顶层为 `version / units / params / nodes` | `src/cndb/plugins/design/services/dsl/compile.py:43`、`:84-89`、`frontend/src/api/design.ts:48-54` | 新增 `outline` 属双端契约演进，须定版本口径 | 新增：D2 |
| 6 | 设计列表页为平面 `Listy`（新建 / 打开 / 改名 / 删除 / 描述） | `frontend/src/pages/design/DesignsPage.tsx:121-190` | 默认页改造须保留这些能力 | 确认：C2 改造点 |
| 7 | 设计写路径已排除双轨修改申请 | `docs/adr/0079-design-3d-dsl-module.md` D6 | 二级页签不引入「修改申请 / 问题清单」 | 确认：C1 只放一个条目 |
| 8 | 编辑器只有诊断行装饰，无按行定位 / 滚动能力 | `frontend/src/pages/design/DslEditor.tsx:27-45`、`DesignEditorPage.tsx:225` | C4 需给 `DslEditor` 增可选 `revealLine` | 新增：D7 |
| 9 | 编译期有界限制（原文 ≤256KB、嵌套 ≤32、图元 ≤2000、模块 ≤128、递归 ≤16） | `src/cndb/plugins/design/services/dsl/limits.py` | 大纲节点数天然有界，无需新限制 | 确认：I3 |
| 10 | 备份协议 v12 导出设计原文、导入端逐版重编译（不搬 `compiled`） | `src/cndb/plugins/workspaces/services/backup_io.py`、`workspace_backup.py:44`（`BACKUP_VERSION = "12"`）、ADR 0075 / 0079 D9 | 大纲随重编译自然恢复，备份协议不变 | 确认：§5 无迁移 |

**核心缺陷（需求要补的）**：编译产物只描述「最终几何」，不描述「几何由哪些组件与零件按什么层级装配而成」，因此前端没有任何数据可以把装配层级画成树；同时设计区缺少与文档区对齐的二级导航入口。

设计目标（不变量）：

- **I1 同源**：`outline` 与 `nodes` 由同一次编译产出，前端只消费 IR，不解析 DSL（沿用 ADR 0079 I1）。
- **I2 无副作用变更**：新增 `outline` 不改变 `nodes` / `params` 的任何取值与诊断结果；同原文 + 同覆盖 → 同 `outline`（沿用 I3）。
- **I3 有界**：大纲节点数 ≤ 图元数 + 模块实例数 + 布尔块数，沿用既有编译期限制，不新增限制项。
- **I4 源位置准确**：`line` / `col` 为语句起始位置的 1 基坐标；同一模块被多次实例化时，其内部零件行号重复出现（指向声明处，不做虚拟行号）。

## Decision

### 1. 数据模型

无新表、无新列、无迁移：大纲写进既有 `design_design.compiled` / `design_designversion.compiled` JSON 快照（ADR 0079 §1）。

IR 形态 v2（`version: 2`，新增顶层 `outline`）：

```json
{
  "version": 2,
  "units": {"length": "mm", "angle": "deg"},
  "params": [{"name": "width", "value": 80}],
  "nodes": [ /* 与 v1 完全一致 */ ],
  "outline": {
    "children": [
      {"kind": "assembly", "name": "plate", "line": 10, "col": 1, "children": [
        {"kind": "group", "op": "difference", "line": 11, "col": 3, "children": [
          {"kind": "part", "primitive": "box", "line": 12, "col": 5},
          {"kind": "part", "primitive": "cyl", "line": 14, "col": 7}
        ]}
      ]}
    ]
  }
}
```

节点三类（叶子 `part` 不带 `children`）：

| kind | 来源 | 携带字段 | 子节点 |
|---|---|---|---|
| `assembly` | DSL `module` 实例化 | `name`（模块名）、`line` / `col`（调用语句位置） | 模块体内的实例大纲 |
| `group` | 布尔块 `union` / `difference` / `intersection` | `op`、`line` / `col` | 布尔块内实例 |
| `part` | 六种图元调用 | `primitive`（`box`/`cyl`/`sphere`/`cone`/`torus`/`tube`）、`line` / `col` | 无（叶） |

变换（translate / rotate / scale / mirror）**不建大纲节点**：其语义已下推到图元 `transform.ops`，作为装饰出现在零件节点信息上不构成装配层级（D3）。模块参数绑定值不进大纲（树只需名称 / 类型 / 源位置；参数值在编辑器参数面板可见）。

### 2. 判定算法（唯一入口）

大纲在 `compile_design(content, overrides)` 内部产出，与 IR 同一编译流程（D2）：`_Emitter` 在 `_emit_instance` 分派处同步收集大纲节点——

- `PrimitiveCall` → `part`（复用 `_eval_primitive` 的定位信息）；
- `ModuleCall` → `assembly`（先绑参、再递归体内实例，子节点挂在 `assembly.children`）；
- `BooleanCall` → `group`（子节点挂在 `group.children`）；
- `TransformCall` → 透明穿透，直接把其子实例的大纲挂到当前父节点（不新增层级）。

失败路径不变：任何一个编译错误仍返回 `ir=None` + 诊断，不产出半截大纲（对应 ADR 0079 I6）。`CompileResult` 结构不变（大纲在 `ir.outline` 内）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/designs/{id}/outline` | 新增：单设计装配大纲，响应 `{design_id, version_number, outline, source}`；`source` 取 `compiled`（快照含 `outline`）或 `content`（历史快照缺大纲、按原文即时编译派生） |
| 其余设计端点 | 不变；`GET /designs/{id}` 与版本端点的 `compiled` 载荷自然多出 `outline` 字段（旧消费方忽略未知字段） |

写端点仍为 owner / editor；`outline` 为只读端点，成员（含 viewer）可读（沿用 ADR 0079 D6）。

### 4. 边界与例外

1. 历史 `compiled`（IR v1，无 `outline`）走原文即时编译派生，**只读不落库**：结构树可用，下次保存 / 恢复后自然写回 v2 快照（D5）。
2. 历史快照的 `content` 若已不可编译（定义演进导致），端点降级为 200 + `outline: {children: []}` + `source: "content"`？——否：按 I2「保存即校验」的既有口径，`content` 落库时必已编译通过，此处直接 400 暴露问题更诚实；采用 **400 + 编译诊断**（与保存端点同口径）。
3. 顶层无实例（只有 param / module 声明）：`outline.children` 为空数组，合法（与 ADR 0079 边界 #3 一致）。
4. 同一模块多次实例化：多个 `assembly` 节点共享同一批零件行号（指向模块声明体内），前端不合并、不按名去重（同名不同实例是真实装配关系）。
5. 视图侧只做展示：大纲不提供写入口，不可在大纲中改名 / 删除节点（改结构须改 DSL 原文）。
6. 编辑器默认视图不变；`?line=N` 越界（超过行数）时钳制到末行，不报错。
7. 大纲不进入文档正文引用体系（不新增 `{{design:}}` 嵌入），不参与搜索索引。

### 5. 迁移

无。`compiled` 为既有 JSON 列，新增键不需要 alembic 迁移；备份 v12 导出原文并在导入端重编译，大纲随之重建；工作区旧备份兼容路径（≤v11）不受影响。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| 二级页签 | `frontend/src/layouts/MainLayout.tsx` | 新增 `DESIGN_SUBPAGES`（「设计结构」），`inDesignContext` 下渲染 crumb；`activeDesignSubpage` 由 `location === /w/:wid/design` 判定 |
| 默认页 | `frontend/src/pages/design/DesignsPage.tsx` | 主体由 `Listy` 改为 `Tree`：根节点 = 设计（标题 + 版本 + 更新时间），展开时懒加载大纲；设计节点保留打开 / 编辑 / 删除入口，顶部「新建设计」与两个 Modal 不变；空态沿用 `Empty` |
| 大纲映射 | `frontend/src/pages/design/designOutline.ts` | 纯函数：设计 + 大纲 → `DataNode[]`（图标 / 标签 / 「第 N 行」/ 类型中文名 / 前端派生实例计数），便于单测 |
| API | `frontend/src/api/design.ts` | 新增 `DesignOutlineNode` / `DesignOutline` / `DesignOutlineResult` 类型与 `designsApi.outline` |
| 编辑器定位 | `frontend/src/pages/design/DslEditor.tsx`、`DesignEditorPage.tsx` | `DslEditor` 新增可选 `revealLine`：滚动到该行并置光标；编辑器页读 `?line=` 传入 |
| 类型 | `frontend/src/api/design.ts` | `DesignIR` 增可选 `outline`，`version` 注释改为 v2 |
| 帮助 | `frontend/src/pages/help/content/*` | 「工作区二级页签」与设计主题补「设计结构」树说明 |

### 7. 测试清单

**判定层（单测，`tests/test_design_dsl.py` 扩展）**：顶层图元 → `part`；模块实例 → `assembly` 且子节点在 `children`；模块嵌套多层层级正确；布尔块 → `group` 且 `op` 正确；变换透明穿透（不产生大纲节点、其子节点层级不变）；`line` / `col` 取值与源行一致（1 基）；空程序 → `outline.children == []`；模块多实例 → 多个 `assembly` 节点且零件行号重复；`outline` 与 `nodes` 同源一致性（图元计数相等）；编译失败无 `outline`；确定性（同输入同大纲）。

**接口层（`tests/test_design_api.py` 扩展）**：`GET /designs/{id}/outline` 成员可读、viewer 可读、非成员 403 / 不存在 404；新建设计后 `source == "compiled"` 且结构正确；手工把 `compiled` 置为无 `outline` 的 v1 快照 → `source == "content"` 且树正确、库内 `compiled` 未被改写（只读无副作用）。

**前端单测**：`designOutline.test.ts`（节点标签 / 图标 / 行号 / 计数 / 空大纲）；`DesignsPage.test.tsx`（树渲染、展开触发大纲请求、新建 / 改名 / 删除主流程回归、节点点击跳转 URL 含 `?line=`）；`MainLayout.test.tsx`（设计结构页签激活态与编辑器页无子页激活）；`DesignEditorPage.test.tsx`（`?line=` 传入 `DslEditor`）。

**e2e（前端）**：`frontend/tests/e2e/critical/design-structure-tree.spec.ts`——进入设计模块 → 默认页为结构树 → 展开设计出现组件 / 零件节点与行号 → 点击零件节点进入编辑器并定位；`navigation.spec.ts` 补「设计结构」页签断言。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 编译链路产出 `outline` + IR v2 + 判定层单测 | 低（口径与 IR 契约变更集中在一处入口） |
| **P1** | `outline` 端点 + 二级页签 + 结构树默认页（懒加载、保留既有操作）+ 前端单测 | 中（旧快照兼容路径与树交互） |
| **P2** | 编辑器行定位 + 帮助文案 + CHANGELOG + e2e 收口 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 装配树语义口径 | 方案 A：单设计内派生树——设计为根，`module` 实例为组件（可嵌套 = 装配层级），图元为零件（C1-C3） | 用户确认；树数据由既有编译链路派生，零新表零迁移；跨设计装配无真实诉求证据 | 跨设计 BOM 引用（需新关系表、引用语法、循环防护、备份与版本语义全链设计，超出「参考文档模块」范围）；前端解析 DSL 建树（违反 ADR 0079 I1，双端语法漂移） | `design/services/dsl/compile.py` |
| D2 | IR 契约演进 | `IR_VERSION` 1 → 2，顶层新增 `outline`；`nodes` / `params` / `units` 原样不动（I2） | 大纲与几何必须同源同次编译；旧消费方按字段名读取，未知键无害；`version` 递增符合 ADR 0079 §2「双端契约随语法演进递增」 | 独立「大纲端点内部解析原文、不落快照」（每次请求重复编译，且丢失版本快照语义）；新增独立大纲表（数据冗余且与版本同步成本高） | `compile.py`、`frontend/src/api/design.ts` |
| D3 | 大纲节点模型 | 三类节点 `assembly` / `group` / `part`；变换透明穿透；节点只带名称 / 类型 / 行列；计数由前端派生 | 装配层级与布尔语义都要可见；变换是装饰不构成层级，且已下推到图元 | 仅 `assembly` + `part` 两类（布尔块内切割体与保留体同级，结构误导）；把变换建成节点（树噪声，与「下推」口径冲突）；把参数绑定值写进大纲（体量膨胀、参数面板已有） | `compile.py`、`frontend/src/pages/design/designOutline.ts` |
| D4 | 大纲数据获取方式 | 新增单设计只读端点 `GET /designs/{id}/outline`，前端按设计展开懒加载 | 避免列表响应膨胀（`compiled` 可达数百 KB）；展开才编译 / 读快照，成本按需 | 列表内联全部大纲（响应体量与首屏延迟）；一次请求返回全工作区树（N 次快照读取 + 大响应） | `design/routers.py`、`design/schemas.py`、`frontend/src/api/design.ts` |
| D5 | 历史快照兼容 | 端点优先读 `compiled.outline`；缺失（IR v1）时按原文即时编译派生并标注 `source: "content"`，**不落库**；下次保存自然回填 | 读端点保持无副作用；无需批量迁移与写放大；`content` 落库时已通过编译，派生确定性可复现 | 忽略无大纲的旧快照（结构树对既有设计空白）；批量迁移重编译全部设计（写放大 + 版本语义污染）；写时回填读结果（读端点产生写副作用） | `design/routers.py` |
| D6 | 前端页面形态 | 复用 `/w/:wid/design` 路由，改造 `DesignsPage` 为结构树默认页，保留新建 / 改名 / 删除 / 描述；二级页签仅一个条目 | 用户明确「作为默认页」且范围收敛为导航 + 默认页；避免新增页面与旧列表页并存造成两个「根页」 | 新增独立 `/design/structure` 路由并保留旧列表为另一子页（与「默认页」语义重复，且范围外）；新增文件夹 / 修改申请 / 问题清单子页（ADR 0079 D6 排除，且超出本期范围） | `frontend/src/layouts/MainLayout.tsx`、`DesignsPage.tsx` |
| D7 | 源位置交互 | 节点展示「第 N 行」，点击组件 / 分组 / 零件节点打开编辑器并定位（`?line=N`，`DslEditor.revealLine`） | 用户确认「节点带 DSL 源位置」；定位让树成为可导航的结构目录，而非只读清单 | 只展示行号不可跳转（信息价值折半，用户需手工找行）；在树内直接展开 DSL 片段（重复编辑器能力，渲染与权限面扩大） | `frontend/src/pages/design/DslEditor.tsx`、`DesignEditorPage.tsx` |
| D8 | 权限与写入面 | 大纲端点为只读，成员（含 viewer）可读；不新增写路径、不引入双轨修改申请 | 沿用 ADR 0079 D6（成员可读 / owner-editor 可写）；结构修改仍走编辑器保存 | 在大纲节点上提供改名 / 删除（与「原文唯一真相源」冲突）；viewer 只读态隐藏结构树（与模块读权限口径冲突） | `design/routers.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：设计模块获得与文档模块一致的二级导航与默认页；装配层级（组件 / 布尔分组 / 零件）首次可见，并可按源行定位回编辑器；大纲与 IR 同源，前端零解析，无新表无迁移。
- **负向**：IR 契约升到 v2，`compiled` 快照体积小幅上升（大纲与图元线性相关）；历史快照首次查看结构树时有一次即时编译开销；结构树只读，不能替代编辑器内的结构编辑。
- **风险与缓解**：旧快照派生路径依赖原文仍可编译 → 端点按保存口径返回 400 诊断而非静默空树（边界 #2）；大纲与 `nodes` 一致性漂移 → 单测断言图元计数相等；树规模（≤2000 图元）→ 懒加载 + antd Tree 虚拟滚动默认能力，实测后可按需收紧。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 原文唯一真相源 / 编译 IR | `design_design.compiled` | 大纲随同一次编译产出，前端不解析 DSL | ADR 0079 I1 / 本 ADR D2 |
| 双端契约演进 | IR `version` | v1 → v2 增量加 `outline`，`nodes` 不变 | ADR 0079 §2 / 本 ADR D2 |
| 权限口径 | 设计读写边界 | 只读端点成员可读，无双轨修改申请 | ADR 0079 D6 / 本 ADR D8 |
| 备份协议 | `payload/backup.json` v12 | 原文导出 + 导入重编译，大纲随重建，协议不变 | ADR 0075 / 0079 D9 / 本 ADR §5 |
| 二级页签范式 | `cn-table-crumb` / `cn-table-tab` | 设计区页签与文档区同形 | 需求卡片 0082 / 本 ADR D6 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/schemas.py` | `tests/test_design_dsl.py` | 待提交 |
| P1 | 已落地 | `src/cndb/plugins/design/routers.py`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/api/design.ts`、`frontend/src/index.css` | `tests/test_design_api.py`、`frontend/src/pages/design/designOutline.test.ts`、`frontend/src/pages/design/DesignsPage.test.tsx`、`frontend/src/layouts/MainLayout.test.tsx` | 待提交 |
| P2 | 已落地 | `frontend/src/pages/design/DslEditor.tsx`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`CHANGELOG.md` | `frontend/src/pages/design/DesignEditorPage.test.tsx`、`frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`frontend/tests/e2e/critical/navigation.spec.ts` | 待提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：Accepted；P0 / P1 / P2 已落地，等待提交与人工确认 `Implemented`
- 已完成：IR v2 装配大纲（`outline`）+ 判定层单测；`GET /designs/{id}/outline`（快照优先 / v1 快照按原文派生 / 成员可读）；前端设计区二级页签、结构树默认页、`?line=` 编辑器定位、帮助文案、CHANGELOG、e2e（结构树 + 导航页签）
- 下一步：提交 0083 变更（注意工作区里同时存在 ADR 0080 P3「质量检查按域拆分」的未提交改动，`MainLayout.tsx` / `App.tsx` / `api/index.ts` / 帮助文案等文件两者共用，需按 hunk 拆分或与用户确认后一并提交）；提交后回填本表「提交」列 sha，并由人确认 `Status`
- 已知坑：antd Tree 展开带 collapse motion（`motionDeadline=500ms`），动画窗口内 rc-tree 的 `listChanging` 会吞掉后续展开点击——前端单测须在每次点展开箭头前等待约 600ms；IR 升 v2 后 `frontend/src/api/design.ts` 与既有 `version` 断言需同步；`compiled` 为 JSON 列无迁移，备份 v12 导入端重编译即可重建大纲；编辑器测试须 `vi.mock('./PreviewCanvas')`（jsdom 无 WebGL）
- 最近一次全绿：`make check-fast`、`make test`（6495 passed）、`pnpm test`（2867 passed）、`make frontend-coverage`（双门槛达标）、目标 e2e `design-structure-tree.spec.ts` + `navigation.spec.ts` @ 2026-11-01（未提交，无 sha）

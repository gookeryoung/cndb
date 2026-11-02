# ADR 0084: 【设计】侧栏装配结构树与系统级装配声明

Status: Accepted
Date: 2026-11-02
Related: `src/cndb/plugins/design/services/dsl/parse.py`、`src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/services/dsl/nodes.py`、`src/cndb/plugins/design/services/dsl/limits.py`、`frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/pages/design/designLang.ts`、`frontend/src/api/design.ts`、`docs/adr/0079-design-3d-dsl-module.md`、`docs/adr/0083-design-structure-subnav-and-assembly-tree.md`
需求卡片: `docs/requirements/0084-design-sidebar-assembly-and-system-level.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「进入该模块后，侧边栏应展示设计装配结构，参考文档结构」 | `MainLayout` 新增 `renderDesignNav`（设计清单 → 懒加载装配树），`SiderMode` 增加 `'design'`，设计段退出 `inFocusContext` 自动折叠逻辑；移动端抽屉共用；大纲数据复用 ADR 0083 D4 端点与 D7 点击定位交互（D4） |
| C2 | 「还应显示组件级和复杂系统级」 | DSL 新增顶层 `system` 声明，编译大纲新增 `kind: "system"` 节点，IR `version` 2 → 3；树层级 设计 → 系统 → 组件 → 分组 → 零件（D1 / D2） |
| C3 | 「完善DSL设计」 | `system` 仅顶层、无参数表、不可实例化、名空间与 module 共享、计入 `MAX_MODULES`、纯组织层（几何与平铺等价）（D3） |
| C4 | 「给出系统装配结构的示例」 | 默认模板与帮助示例改为「四轮小车」三级装配示例（§9），新建即见系统 / 组件 / 零件三级（D8） |
| C5 | 主区与侧栏分工 | 结构树迁侧栏，`/w/:wid/design` 主区恢复设计管理页（新建 / 打开 / 改名 / 描述 / 删除 + 版本 / 更新时间摘要），路由与二级页签不变（D5） |
| C6 | 配套回归 | `designLang.ts` 补 `system` 关键字；无 `system` 原文与 v2 快照兼容（I5）；CHANGELOG；e2e 侧栏装配树 + 既有结构树回归 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论；ADR 新发现的条目追加编号。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 设计段 Sider 沿用数据表导航（`siderMode` 无 `'design'`），且 `inFocusContext` 含 `inDesignContext`，进入设计段自动折叠为 60px 图标条 | `frontend/src/layouts/MainLayout.tsx:412-420`、`:422-431` | 设计段没有任何侧栏内容可放装配树 | 确认：C1 需新增 Sider 形态并移出自动折叠集合 |
| 2 | 文档段侧栏范式 `renderDocumentNav`：标题 + 工具行（展开 / 排序 / 过滤）+ 树，桌面 Sider 与移动抽屉共用同一渲染函数 | `frontend/src/layouts/MainLayout.tsx:617-680` | 设计段可同形接入，无需新布局骨架 | 确认：C1 直接复用范式 |
| 3 | 装配结构树是「设计结构」主区页本体（设计根 → assembly → group → part，懒加载 + 点击定位） | `frontend/src/pages/design/DesignsPage.tsx:203-276` | 树迁侧栏后主区出现空缺，需恢复管理形态 | 确认：C5 改造点（卡片①） |
| 4 | DSL 顶层语句仅 `param` / `module` / 实例三种；`module` 实例映射大纲 `assembly`（组件级），图元映射 `part`（零件级） | `src/cndb/plugins/design/services/dsl/parse.py:115-129`、`compile.py:311-340` | 「复杂系统级」没有声明载体：顶层实例是无名散件，无法表达「一个系统由哪些组件装配而成」 | 确认：C2/C3 的根因（核心缺陷） |
| 5 | IR 契约 `IR_VERSION = 2`，大纲节点三类 `assembly` / `group` / `part`；前端 `DesignOutlineNode` 三分支联合类型 | `src/cndb/plugins/design/services/dsl/compile.py:48`、`frontend/src/api/design.ts:50-82` | 新增 `system` kind 属双端契约演进，须递增版本 | 新增：D2 |
| 6 | 大纲树映射纯函数 `designOutline.ts`：`DesignTreeMeta.type` 为 `design / assembly / group / part` 四值，标签文案「组件 / 结构分组 / 零件」 | `frontend/src/pages/design/designOutline.ts:11-22`、`:68-105` | 需增 `system` 类型与「系统」文案；映射逻辑可整体复用 | 确认：C2 前端落点 |
| 7 | 编辑器高亮关键字表 `KEYWORDS` 含 `param / module` 与布尔 / 变换，不含 `system` | `frontend/src/pages/design/designLang.ts:13-16` | `system` 语句会按普通标识符着色 | 确认：C6 改动点 |
| 8 | 编译期限制 `MAX_MODULES = 128` 只统计 module 声明 | `src/cndb/plugins/design/services/dsl/limits.py:17`、`compile.py:81-83` | `system` 声明需纳入有界计数，避免大纲节点无界 | 确认：C3 计数口径 |
| 9 | 大纲端点 `GET /designs/{id}/outline`：快照优先，v1/v2 快照按原文即时编译派生（只读不落库）；点击定位 `?line=N` 已就绪 | `src/cndb/plugins/design/routers.py`、`frontend/src/pages/design/DslEditor.tsx` | 侧栏树零新增端点、零新增交互协议 | 确认：C1 直接复用 ADR 0083 D4/D7 |
| 10 | 备份协议 v12 导出 DSL 原文、导入端逐版重编译（不搬 `compiled`） | `src/cndb/plugins/workspaces/services/backup_io.py` | `system` 随重编译自然重建，备份协议不变 | 确认：§5 无迁移 |
| 11 | 导出器（STL / OBJ / GLB / 三视图）与实时预览只消费 IR `nodes`，不读 `outline` | `frontend/src/pages/design/exporters.ts`、`PreviewCanvas.tsx` | `system` 纯组织层不影响几何链路 | 新增：I2 的旁证 |

**核心缺陷（需求要补的）**：装配层级缺少「复杂系统级」的声明载体——顶层实例是无名的散件集合，无法表达「一个复杂系统由哪些组件、哪些零件按什么层级装配而成」；同时结构树在主区而非侧栏，与文档模块「侧栏 = 导航树」的范式不一致，进入设计段侧栏是折叠的图标条。

设计目标（不变量）：

- **I1 同源**：`system` 节点与 `nodes` 由同一次编译产出，前端只消费 IR，不解析 DSL（沿用 ADR 0079 I1 / 0083 I1）。
- **I2 几何无副作用**：`system` 是纯组织层——把 system 体平铺到顶层（保持语句顺序），`nodes` / `params` / 诊断完全一致；预览与导出零感知。
- **I3 有界**：`system` + `module` 声明总数 ≤ `MAX_MODULES`（128），沿用既有编译期限制，不新增限制项。
- **I4 源位置准确**：`system` 大纲节点携带声明语句起始的 1 基 `line` / `col`（沿用 ADR 0083 I4）。
- **I5 向后兼容**：无 `system` 的旧原文照常编译（大纲无系统级层）；v2 快照照常渲染；旧消费方按字段名读取未知 `kind` 不崩。

## Decision

### 1. 数据模型

无新表、无新列、无迁移：`system` 写进 DSL 原文（`design_design.content`），大纲写进既有 `compiled` JSON 快照。

**DSL 语法增量**（文法只加一条产生式）：

```
program      := (param_decl | module_decl | system_decl | instance)*
system_decl  := "system" IDENT "{" instance* "}"
```

- `system` 是**顶层声明**，与 `param` / `module` 同级：模块体 / 系统体 / 布尔块内出现 `system` 报语法错误（与 param / module 的既有口径一致）。
- **无参数表**：系统是单例根装配，不可实例化，参数没有调用方；可配置性走顶层 `param`（系统体内直接引用全局 param）。
- **不可实例化**：`system` 名出现在实例位置 → 语义错误「system 不可实例化，请改用 module」。
- **名空间与 `module` 共享**：system 名与 module 名互不重名，也不能撞图元名 / 关键字（`_is_keyword` 增补 `system`）。
- **允许多个**：一份设计可含多个系统根（如「产品 + 工装」），各自成为大纲顶层系统节点（卡片②建议结论）。

**IR 形态 v3**（`version: 3`，`outline` 增 `system` kind，其余顶层键与 v2 完全一致）：

```json
{
  "version": 3,
  "units": {"length": "mm", "angle": "deg"},
  "params": [{"name": "wheel_d", "value": 40}],
  "nodes": [ /* 与不含 system 的等价平铺写法逐节点一致（I2） */ ],
  "outline": {
    "children": [
      {"kind": "system", "name": "rover", "line": 26, "col": 1, "children": [
        {"kind": "assembly", "name": "chassis", "line": 27, "col": 3, "children": [
          {"kind": "group", "op": "difference", "line": 20, "col": 5, "children": [
            {"kind": "part", "primitive": "box", "line": 21, "col": 7},
            {"kind": "part", "primitive": "cyl", "line": 22, "col": 7}
          ]}
        ]},
        {"kind": "part", "primitive": "sphere", "line": 38, "col": 3}
      ]}
    ]
  }
}
```

大纲节点四类（叶 `part` 不带 `children`）：

| kind | 来源 | 携带字段 | 层级口径 | 子节点 |
|---|---|---|---|---|
| `system` | DSL `system` 声明 | `name`、`line` / `col`（声明语句位置） | **复杂系统级** | 系统体内的实例大纲 |
| `assembly` | DSL `module` 实例化 | `name`、`line` / `col` | **组件级**（可嵌套 = 子装配） | 模块体内的实例大纲 |
| `group` | 布尔块 | `op`、`line` / `col` | 结构分组 | 块内实例大纲 |
| `part` | 六种图元调用 | `primitive`、`line` / `col` | **零件级** | 无（叶） |

变换仍透明穿透（不建大纲节点，沿用 ADR 0083 D3）；`system` 体与 `module` 体一样只允许实例语句，变换 / 布尔 / 组件调用 / 图元均可直接出现。

### 2. 判定算法（唯一入口）

编译仍在 `compile_design(content, overrides)` 单入口内完成（沿用 ADR 0079 D3 / 0083 D2）：

- **语法层（`parse.py`）**：`KEYWORD_SYSTEM = "system"`；`_parse_system_decl` 解析 `system IDENT { instance* }` 产出 `SystemDecl(name, body, line, col)`；`Program` 增 `systems` 元组；`_is_keyword` / 模块名与 system 名互斥校验同步收紧。
- **语义层（`compile.py`）**：
  - `_collect_modules` 扩为同时收集 system，module 与 system 名冲突报「重复声明」；`len(modules) + len(systems) > MAX_MODULES` 报上限错误（I3）。
  - `_Emitter.emit_top` 按**顶层语句出现顺序**交错展开实例与 system 体：system 体经 `_emit_instances` 展开为几何（`nodes` 顺序 = 平铺顺序，I2），大纲侧产出 `{"kind": "system", ...}` 节点包裹其 children。
  - 实例位置的 `system` 名：`_emit_module_call` 查注册表命中 system 声明时报「system 不可实例化，请改用 module」。
- **失败路径不变**：任一编译错误仍返回 `ir=None` + 诊断，不产出半截大纲（ADR 0079 I6）。

### 3. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /api/v1/workspaces/{wid}/designs/{id}/outline` | 不变：快照优先（v3 快照自然含 `system` 节点），v1/v2 快照按原文即时编译派生（派生结果含 `system`，前提是原文本身有）；`source` 口径不变 |
| 其余设计端点 | 不变；`GET /designs/{id}` 与版本端点的 `compiled` 载荷 `version` 升为 3（旧消费方忽略未知字段） |

写端点仍为 owner / editor；大纲只读端点成员（含 viewer）可读（沿用 ADR 0083 D8）。

### 4. 边界与例外

1. 多个 `system`：合法，各成大纲顶层系统节点，按声明顺序排列。
2. `system` 体为空：合法（与模块体空块同口径），大纲 `children: []`。
3. 无 `system` 的设计（全部存量）：大纲顶层直接是 `assembly` / `group` / `part`，侧栏树无系统级层，**合法不报错**（I5）。
4. v2 快照（大纲无 `system`）：端点直接返回快照大纲，前端按既有 kinds 渲染；不强制重编译、不迁移（D7）。
5. `system` 名被当作模块调用 / 与 module 重名 / 在嵌套位置声明：分别报语义 / 语义 / 语法错误，均带行列定位。
6. 侧栏树只读：不提供在大纲节点上改名 / 删除（改结构须改 DSL 原文，沿用 ADR 0083 边界 #5）。
7. 大纲不进入文档正文引用体系、不参与搜索索引（沿用 ADR 0083 边界 #7）。

### 5. 迁移

无。`compiled` 为既有 JSON 列，新增 `system` kind 不需要 alembic 迁移；备份 v12 导出原文并在导入端重编译，`system` 随之重建；工作区旧备份兼容路径（≤v11）不受影响。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| Sider 形态 | `frontend/src/layouts/MainLayout.tsx` | `SiderMode` 增 `'design'`；`inFocusContext` 移除 `inDesignContext`（设计段不再自动折叠）；新增 `renderDesignNav(mobile, collapsed)`：设计清单（懒加载 outline 展开）+ 标题过滤，点击设计进编辑器、点击大纲节点带 `?line=` 定位；移动端抽屉共用 |
| 侧栏树组件 | `frontend/src/pages/design/DesignStructureNav.tsx`（新） | 装配树渲染与懒加载逻辑（自 `DesignsPage` 迁出）：设计根 → 系统 → 组件 → 分组 → 零件，复用 `designOutline.ts` 映射；编辑器页高亮当前设计 |
| 大纲映射 | `frontend/src/pages/design/designOutline.ts` | `DesignTreeMeta.type` 增 `'system'`；`outlineToTree` 增 system 分支（标签「系统 · 第 N 行 · N 个零件」，图标与组件区分） |
| 主区管理页 | `frontend/src/pages/design/DesignsPage.tsx` | 主区由结构树恢复为设计管理页（列表：新建 / 打开 / 改名 / 描述 / 删除 + 版本 / 更新时间摘要）；`DEFAULT_DESIGN_CONTENT` 换为 §9 三级装配示例（C4） |
| 类型 | `frontend/src/api/design.ts` | `DesignOutlineSystemNode`（`kind: 'system'`）并入 `DesignOutlineNode` 联合；`DesignIR.version` 注释改 v3 |
| 高亮 | `frontend/src/pages/design/designLang.ts` | `KEYWORDS` 增 `'system'` |
| 帮助 | `frontend/src/pages/help/content/*` | 设计主题补 `system` 语法与三级装配说明，示例同步 §9 |

### 7. 测试清单

**判定层（单测，`tests/test_design_dsl.py` 扩展）**：`system` 声明解析成功；大纲产出 `system` 节点且 children 正确；系统体含组件 / 分组 / 图元 / 变换的层级正确（变换透明穿透）；**几何等价性**（同原文把 system 体平铺到顶层 → `nodes` / `params` 完全一致，I2）；多 system 按序排列；空 system 体 → `children == []`；`system` 名被调用报「不可实例化」；system 与 module 重名报错；嵌套位置声明 `system` 报语法错误；`system + module > 128` 报上限；`line` / `col` 为声明语句 1 基起点；无 system 原文的大纲与 v2 行为一致（回归）；确定性（同输入同大纲）。

**接口层（`tests/test_design_api.py` 扩展）**：新建设计（含 system 模板）后 outline 端点返回 `system` 节点且 `source == "compiled"`；手工置 v2 快照（无 system）→ `source == "content"` 派生含 system（原文有则含）、库内 `compiled` 未被改写；预览端点对含 system 原文的 `nodes` 与平铺等价。

**前端单测**：`MainLayout.test.tsx`（设计段 Sider 渲染装配树、不再折叠、移动抽屉共用、编辑器页高亮当前设计）；`DesignStructureNav.test.tsx`（懒加载触发、节点点击跳转 URL 含 `?line=`、过滤）；`DesignsPage.test.tsx`（管理页主流程回归：新建模板含 `system`、打开 / 改名 / 删除）；`designOutline.test.ts`（system 节点标签 / 计数 / 空大纲）；`designLang.test.ts`（`system` 高亮为 keyword）。

**e2e（前端）**：`frontend/tests/e2e/critical/design-sidebar-assembly.spec.ts`——进入设计模块 → 侧栏出现设计清单 → 展开出现「系统 / 组件 / 零件」三级与行号 → 点击零件节点进入编辑器并定位；`design-structure-tree.spec.ts` 与 `navigation.spec.ts` 按主区改版回归调整。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `system` 语法 + 语义校验 + IR v3 大纲 + 判定层单测 | 低（增量产生式，几何链路零改动） |
| **P1** | 侧栏 `renderDesignNav` + `SiderMode 'design'` + 主区管理页恢复 + 前端单测 | 中（布局切换与既有结构树 e2e 回归） |
| **P2** | 默认模板 / 帮助文案 / 语法高亮 / CHANGELOG / e2e 收口 | 低 |

### 9. 系统装配结构示例（DSL → 大纲 → 侧栏树）

四轮小车（rover）：1 个系统根、3 种组件、13 个零件，覆盖三级装配层级。

**DSL 原文**（同时是新建设计的默认模板候选，C4）：

```
// ── 参数：全局驱动，参数面板可覆盖重编译 ──
param body_len = 120
param body_w = 60
param body_t = 8
param wheel_d = 40
param wheel_w = 16
param axle_d = 10

// ── 组件级：module（可复用 / 可实例化 / 可嵌套 = 子装配）──

// 车轮：轮辋减轮毂孔（零件级细节由图元 + 布尔表达）
module wheel(d, w) {
  rotate([90, 0, 0])
    difference {
      cyl(d = d, h = w)
      translate([0, 0, -1]) cyl(d = d * 0.35, h = w + 2)
    }
}

// 车轴：空心圆管，轴向转水平
module axle(d, len) {
  rotate([90, 0, 0]) tube(od = d, id = d * 0.6, h = len)
}

// 底盘：带中心过孔的板
module chassis(len, w, t) {
  difference {
    box(size = [len, w, t])
    translate([0, 0, -1]) cyl(d = 14, h = t + 2)
  }
}

// ── 系统级：复杂系统装配声明（顶层根，不可实例化）──
system rover {
  chassis(body_len, body_w, body_t)                                    // 组件：底盘

  translate([body_len / 2 - 18, 0, 0]) axle(axle_d, body_w + 2 * wheel_w)                 // 前轴
  translate([body_len / 2 - 18,  body_w / 2 + wheel_w / 2, 0]) wheel(wheel_d, wheel_w)    // 前轮
  translate([body_len / 2 - 18, -body_w / 2 - wheel_w / 2, 0]) wheel(wheel_d, wheel_w)

  translate([-body_len / 2 + 18, 0, 0]) axle(axle_d, body_w + 2 * wheel_w)                // 后轴
  translate([-body_len / 2 + 18,  body_w / 2 + wheel_w / 2, 0]) wheel(wheel_d, wheel_w)   // 后轮
  translate([-body_len / 2 + 18, -body_w / 2 - wheel_w / 2, 0]) wheel(wheel_d, wheel_w)

  translate([0, 0, body_t + 42]) sphere(r = 14)                        // 零件级细节：传感器球头
}
```

**编译大纲（`outline`，IR v3）**：设计根下唯一 `system rover` 节点，children 依次为 `assembly chassis`（内含 `group difference` → `part box` + `part cyl`）、`assembly axle` ×2（各含 `part tube`）、`assembly wheel` ×4（各含 `group difference` → `part cyl` ×2）、`part sphere`——变换全部透明穿透，不占层级。

**侧栏树（渲染效果）**：

```
▾ rover 设计 · v1
  ▾ rover   系统 · 第 30 行 · 13 个零件
    ▾ chassis   组件 · 第 31 行 · 2 个零件
      ▾ 差集   结构分组 · 第 24 行
        · 立方体  零件 · 第 25 行
        · 圆柱    零件 · 第 26 行
    ▾ axle     组件 · 第 33 行 · 1 个零件（前后各一）
    ▾ wheel    组件 · 第 34 行 · 2 个零件（×4 实例）
    · 球体      零件 · 第 41 行
```

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 复杂系统级载体 | DSL 新增顶层 `system` 声明：命名、只组装配、不实例化；大纲映射为 `kind: "system"`（C2/C3） | 系统级需要显式命名与「根」语义；module 兼任则树无法分级；数据由既有编译链路派生，零新表零迁移 | 让 module 兼任系统（同名不同义，树无法区分层级）；前端推断「顶层 assembly 即系统」（无语义依据，脆弱，违反 I1） | `parse.py`、`compile.py` |
| D2 | IR 契约演进 | `IR_VERSION` 2 → 3，`outline` 增 `system` kind；`nodes` / `params` / `units` 原样不动（I2） | 与几何必须同源同次编译；旧消费方按字段名读取，未知 kind 不崩（I5）；版本递增符合 ADR 0079 §2 口径 | `assembly` 节点加 `level` 字段（v2 快照缺字段双口径，新旧树文案分叉）；独立「系统树」端点（重复编译、版本语义割裂） | `compile.py`、`frontend/src/api/design.ts` |
| D3 | `system` 语法形态 | 无参数表、不可实例化、仅顶层、可多个；名空间与 module 共享；计入 `MAX_MODULES` | 系统是单例根，参数无调用方（可配置性走顶层 param）；多个系统覆盖「产品 + 工装」场景；有界计数沿用既有限制（I3） | 带参数表（死配置面，参数面板无法覆盖）；允许 system 被实例化（退化为 module，分级语义消失）；限定单 system（表达力受限，且无校验收益） | `parse.py`、`limits.py` |
| D4 | 侧栏形态 | `SiderMode` 增 `'design'` + `renderDesignNav`，照抄文档段范式；设计段退出 `inFocusContext` 折叠集合；移动抽屉共用；复用 0083 D4 端点与 D7 定位交互 | 用户明确「参考文档结构」；文档侧栏（需求 0065）已验证同一渲染函数双端复用；零新增端点 | 在编辑器内做大纲抽屉（「进入模块即见」不满足）；主区大树 + 侧栏小树并存（双树冗余、状态双份） | `MainLayout.tsx`、`DesignStructureNav.tsx` |
| D5 | 主区「设计结构」页形态 | 恢复为设计管理页（新建 / 打开 / 改名 / 描述 / 删除 + 摘要），路由与二级页签不变 | 对齐文档模块「侧栏 = 导航树、主区 = 管理列表 / 编辑器」分工；管理操作在窄侧栏中交互降级；二级页签语义（ADR 0083 C1/C2）原样保留 | 主区保留结构树（与侧栏重复，两处懒加载状态）；删除主区页（「设计结构」页签失去落点） | `DesignsPage.tsx` |
| D6 | 权限与写入面 | 侧栏树成员（含 viewer）可见；大纲只读；不新增写路径 | 沿用 ADR 0083 D8（成员可读 / owner-editor 可写）；侧栏是导航不是编辑面 | viewer 隐藏侧栏树（与模块读权限口径冲突）；侧栏节点提供改名 / 删除（与「原文唯一真相源」冲突） | `DesignStructureNav.tsx` |
| D7 | 兼容口径 | 无 system 原文与 v2 快照照常编译 / 渲染，树缺系统级层不报错；不迁移、不强制重编译 | 读路径无副作用（沿用 0083 D5）；下次保存自然落 v3 快照 | 批量重编译迁移（写放大 + 版本语义污染）；对无 system 设计前端伪造「系统 = 设计根」层（假数据，树语义漂移） | `compile.py`、`designOutline.ts` |
| D8 | 示例落点 | 默认模板与帮助示例统一换为「四轮小车」三级装配示例（§9）；既有法兰板示例保留在帮助中作为组件级用例 | 用户明确要求「给出系统装配结构的示例」；新建即见三级层级，示范 `system` 写法 | 保留法兰板为默认模板（新建后树无系统级，新语法无示范入口）；示例只进帮助不进模板（示范触达低） | `DesignsPage.tsx`、`help/content/*` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：设计段获得与文档段一致的侧栏导航范式，进入模块即见装配结构；装配层级首次具备显式的「复杂系统 → 组件 → 零件」三级口径，且由 DSL 声明驱动而非前端推断；`system` 纯组织层，几何 / 预览 / 导出 / 备份链路零改动。
- **负向**：IR 契约升到 v3（第三次递增）；`DesignsPage` 主区形态回摆（0083 D6 的树主区被侧栏替代，属需求演进而非返工）；侧栏与主区两处组件需各自维护懒加载状态边界。
- **风险与缓解**：v2 快照派生路径 → 端点口径不变、单测覆盖（判定层 + 接口层）；侧栏窄空间的树交互（行号 / 计数截断）→ 详情文案收敛为一行次级文本；`system` 与 module 名冲突的面扩大 → 编译期重名诊断带行列定位。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 原文唯一真相源 / 编译 IR | `design_design.content` / `compiled` | `system` 写进原文，大纲随同一次编译产出 | ADR 0079 I1 / 本 ADR D1 |
| 双端契约演进 | IR `version` | v2 → v3 增量加 `system` kind，`nodes` 不变 | ADR 0079 §2 / 本 ADR D2 |
| 装配大纲 | `outline` | 三类节点扩为四类，系统级居首 | ADR 0083 D2/D3 / 本 ADR D1 |
| 大纲获取与定位交互 | `GET /designs/{id}/outline` + `?line=` | 端点与交互协议零变更，侧栏复用 | ADR 0083 D4/D7 / 本 ADR D4 |
| 权限口径 | 设计读写边界 | 侧栏树只读、成员（含 viewer）可见 | ADR 0083 D8 / 本 ADR D6 |
| 备份协议 | `payload/backup.json` v12 | 原文导出 + 导入重编译，协议不变 | ADR 0075 / 0079 D9 / 本 ADR §5 |
| 侧栏范式 | `renderDocumentNav` / `SiderMode` | 设计段同形接入，自动折叠集合移除 design | 需求 0065 / 本 ADR D4 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/design/services/dsl/nodes.py`、`src/cndb/plugins/design/services/dsl/parse.py`、`src/cndb/plugins/design/services/dsl/compile.py`（SystemDecl / Program.items 保序、system 文法与重名 / 不可实例化诊断、IR_VERSION=3 与 system 大纲节点） | `tests/test_design_dsl.py`、`tests/test_design_api.py` | f901c8e |
| P1 | 已落地 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/DesignsPage.tsx`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/pages/design/designLang.ts`、`frontend/src/api/design.ts`（SiderMode='design' + renderDesignNav，设计段退出自动折叠；侧栏装配树；管理列表 + 四轮小车模板） | `frontend/src/pages/design/DesignStructureNav.test.tsx`、`frontend/src/pages/design/DesignsPage.test.tsx`、`frontend/src/pages/design/designOutline.test.ts`、`frontend/src/pages/design/designLang.test.ts`、`frontend/src/layouts/MainLayout.test.tsx` | f901c8e |
| P2 | 已落地 | `frontend/src/pages/help/content/quickStart.tsx`、`frontend/src/pages/help/content/tutorials.tsx`、`CHANGELOG.md`、`frontend/tests/e2e/critical/design-structure-tree.spec.ts`、`frontend/tests/e2e/critical/design-sidebar-assembly.spec.ts`（system 语法 + 侧栏三级装配；既有结构树 e2e 改侧栏断言） | `frontend/tests/e2e/critical/design-sidebar-assembly.spec.ts`、`frontend/tests/e2e/critical/design-structure-tree.spec.ts` | f901c8e |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：Accepted（P0 / P1 / P2 全部落地；2026-11-02 用户拍板「对齐文档模块，允许，不做」）
- 已完成：需求卡片 0084；`system` DSL 声明与 IR v3 大纲；侧栏 `DesignStructureNav`（桌面 Sider + 移动抽屉共用、编辑器自动展开高亮、点击定位）；`DesignsPage` 恢复管理页与四轮小车模板；帮助文档、CHANGELOG、e2e 同步
- 下一步：按需补系统装配示例的种子数据集；推送 / 发版需人工授权（提交在 main 本地，未推送）
- 已知坑：antd Tree 展开动画窗口（约 600ms）会吞点击，单测 / e2e 展开前先等待；v2 快照派生只在读路径生效，保存一次后自然落 v3；侧栏大纲按设计懒加载，切换设计时缓存不失效，改名后树标题由列表查询刷新
- 最近一次全绿：`make flow`（2026-11-02，`make check-fast` + 后端 6515 passed / 17 skipped）；前端全量 `pnpm vitest run` 全绿；`pnpm e2e` 113 passed / 22 skipped（含 `design-sidebar-assembly.spec.ts` 与改版 `design-structure-tree.spec.ts`）

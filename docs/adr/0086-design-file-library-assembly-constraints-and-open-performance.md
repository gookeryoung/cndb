# ADR 0086: 设计文件库、组件级装配约束与系统级打开性能

Status: Accepted（2026-11-02 需求方确认后按 P0→P1→P2 实施）
Date: 2026-11-02
Related: `src/cndb/plugins/design/models.py`、`src/cndb/plugins/design/services/dsl/lexer.py`、`src/cndb/plugins/design/services/dsl/parse.py`、`src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/services/dsl/limits.py`、`src/cndb/plugins/design/routers.py`、`src/cndb/cli/seed/designs.py`、`src/cndb/plugins/workspaces/services/workspace_backup.py`、`src/cndb/plugins/workspaces/services/backup_io.py`、`src/cndb/plugins/workspaces/services/workspace_restore.py`、`frontend/src/api/design.ts`、`frontend/src/pages/design/DesignEditorPage.tsx`、`frontend/src/pages/design/DesignStructureNav.tsx`、`frontend/src/pages/design/designOutline.ts`、`frontend/src/pages/design/PreviewCanvas.tsx`、`frontend/src/pages/design/renderTree.ts`；上游 ADR 0079 / 0083 / 0084 / 0075 / 0026
需求卡片: `docs/requirements/0086-design-file-library-assembly-constraints-and-open-performance.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。约束沿用 C1..C11。

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 不同零件的分文件参数化定义 | `design_design` 升级为「设计文件」记录：`kind ∈ {part, assembly}`、稳定 `file_key`、显示目录 `folder`、独立 `content` 与版本序列；`part` 文件顶层 `param` 即公开参数，顶层实例即零件几何；可单独打开 / 保存 / 回看 |
| C2 | 分文件参数化定义（参数传递） | 装配用 `use "<file_key>"(参数…) as <实例名>` 引用 `part` 文件；每次 `use` 独立绑定参数并展开该零件 IR；同一零件多实例互不影响；`part` 内部可继续 `use` 其他 `part`（子零件），生成嵌套组件 |
| C3 | 分文件（引用完整性） | 引用按不可变 `file_key` 解析为 `file_id`；编译前构建依赖图，缺失 / 跨工作区 / 循环引用给带文件与行列的诊断；`design_designref` 表记录直接引用，删除被引用文件 409 并返回引用方 |
| C4 | 分文件（版本与可复现） | 装配每次保存都把**依赖闭包**（`file_id/key/version_number/content_hash`）写入版本 `dependencies`；历史版本按快照依赖解析编译，缺失依赖报错而非取最新；备份 v13 导出文件类型 / 目录 / 依赖 |
| C5 | 组件级装配约束定义 | DSL 新增 `constraint <id> <type>(a = <label>.<anchor>, b = …, offset/value/angle = …)`，仅装配 / 零件文件顶层或 `system` 体内声明；MVP 类型 `fixed / coincident / concentric / distance / angle`；引用端使用组件实例标签 + 默认命名基准 `origin / x / y / z` |
| C6 | 组件级装配约束（求解） | 唯一编译入口内新增确定性位姿传播：`fixed`/首个基准件接地 → 按约束声明顺序 BFS 传播；欠约束警告、冲突 / 过约束 / 无解报错且不产出 IR；求解结果以变换下推到图元节点，IR `constraints` 记录状态 |
| C7 | 系统级装配打开卡滞 | 详情不再携带 `compiled`，新增带 ETag 的 `GET /{id}/ir`；前端首屏直接消费 IR 快照，内容 / 依赖未变不发 preview；侧栏树虚拟滚动 + 一次后序计数 + 可见节点才建元素；点击大纲节点按其 `file_id` 打开源文件 |
| C8 | 卡滞（渲染预算） | 3D 首帧先渲染非布尔近似 / 骨架，CSG 与布尔网格在 Web Worker 分片求值；结果按节点内容哈希缓存；新 IR 到达取消旧任务；相同子树 / 未变参数不重复求值 |
| C9 | 卡滞（可量化验收） | 固定 `perf` 基准（≥200 组件 / ≥2000 图元）纳入 `@perf` e2e：编辑器可交互 ≤1s、3D 首帧 ≤1.5s、单次长任务 ≤200ms、侧栏首屏 ≤500ms；CI 取 3 次中位数并记录实测基线 |
| C10 | 参考 CAD（安全与有界） | 预算按依赖闭包累计：闭包原文 ≤1MB、文件 ≤64、引用深度 ≤8、图元 ≤2000、module+system ≤256；`folder` / `file_key` 规范化拒绝绝对路径、`..`、控制字符；引用限同工作区；读写沿用工作区角色 |
| C11 | 完善系统级设计功能（兼容 / 旧设计重构 / 示例） | 新增幂等 `cndb design-refactor`：提取可安全拆分的顶层 `module` 为 `part` 文件、重写装配 `use`、编译前后 `nodes` 等价校验；失败保留原文并报告。旧单文件 DSL 继续可编译；种子改为 `designs/parts/*.cnmd` + 装配文件；帮助 / CHANGELOG / e2e 同步 |

## Context

现状逐条核对（沿用卡片影响面编号；新增条目从 #14 起）：

| # | 现状 | 位置 | 影响 | 与卡片关系 |
|---|---|---|---|---|
| 1 | 一份设计 = 一行 `design_design`，`title` 工作区内唯一，无 `kind` / `file_key` / `folder` / 依赖字段；版本表也只有原文 + `compiled` | `src/cndb/plugins/design/models.py:21-84` | 无法表达「零件文件 vs 装配文件」「跨文件引用」「依赖快照」 | 确认 C1-C4 |
| 2 | DSL 顶层只接受 `param` / `module` / `system` / 实例（任意顺序），无文件引用 / 实例标签 / 约束声明 | `src/cndb/plugins/design/services/dsl/parse.py:119-151`、`:182-192` | 复用只能同文件 `module`，无法分文件传参；约束无处声明 | 确认 C1-C6 |
| 3 | 词法只识别数值 / 标识符 / 标点，无字符串字面量；`file_key` 无法引用中文名 / 含空格名 | `src/cndb/plugins/design/services/dsl/lexer.py:50-127` | 需新增 `STRING` token 承载文件 key | 新增 C1-C3 |
| 4 | 模块实例化在本文件模块表中查名、直接内联展开；无外部文件解析、依赖图、跨文件预算 | `src/cndb/plugins/design/services/dsl/compile.py:399-413`、`:57-102` | 无法编译分文件装配；拆文件会绕过单文件 256KB / 2000 图元预算 | 确认 C1-C3 / C10 |
| 5 | IR 为 v3：`nodes` + `outline`，大纲节点无 `file_id` / 文件来源 / 约束；编译器无位姿求解阶段 | `src/cndb/plugins/design/services/dsl/compile.py:52-102`、`:355-384`、`frontend/src/api/design.ts:48-107` | 约束结果无处下推；跨文件大纲点击只能打开当前设计 | 确认 C5-C8 |
| 6 | 详情端点返回完整 `content` + `compiled`；编辑器数据到达后无条件启动 `useDesignPreview`，即使内容未改也会重编译 | `src/cndb/plugins/design/routers.py:238-247`、`frontend/src/pages/design/DesignEditorPage.tsx:55-70`、`useDesignPreview.ts:42-65` | 打开一次 = 详情传输 + 全量重编译 + 快照重复；大装配首屏主因 | 确认 C7 |
| 7 | 侧栏展开即拉全量大纲并递归建完所有 antd Tree 节点 | `frontend/src/pages/design/DesignStructureNav.tsx:103-149` | 节点多时主线程长任务、展开卡顿 | 确认 C7 |
| 8 | 每个节点递归调用 `countParts` 统计子树，父亲又对子节点重复求和 | `frontend/src/pages/design/designOutline.ts:61-65`、`:84-110` | 深树 / 大装配 O(N²) 重复遍历 | 确认 C7 |
| 9 | IR 变更在主线程同步求值全部布尔树并重建整组网格；无 worker / 缓存 / 渐进 / 取消 | `frontend/src/pages/design/renderTree.ts:126-164`、`PreviewCanvas.tsx:134-157` | 大装配首帧长任务、页面无响应 | 确认 C8 |
| 10 | 编译上限只按单份 `content` 计 | `src/cndb/plugins/design/services/dsl/limits.py:8-23` | 拆文件后总图元 / 原文可越过原预算 | 确认 C10 |
| 11 | 备份 v12 的 `designs[]` 只含 title/content/description/versions；无 kind/key/folder/dependencies | `src/cndb/plugins/workspaces/services/workspace_backup.py:557-584`、`backup_io.py:1125-1220` | 分文件 / 依赖版本无法往返 | 确认 C4 |
| 12 | 种子按 `designs/*.cnmd` 平铺，一文件一设计；无 parts 目录 / 拓扑顺序 / 跨文件解析 | `src/cndb/cli/seed/designs.py:17-93` | 分文件种子无法注入 | 确认 C1/C11 |
| 13 | 无设计性能基线；现有 `@perf` 只覆盖表格 LCP | `frontend/tests/e2e/perf/grid-lcp.spec.ts` | C9 无可比基线 | 确认 C9 |
| 14 | 删除只软删 `is_deleted`，无引用检查 | `src/cndb/plugins/design/routers.py:293-305` | 删除被引用零件会让装配后续编译断链 | 新增 C3 |
| 15 | 实测近 2000 图元夹具：后端编译约 7ms、IR JSON 约 127KB | 本地基准（2026-11-02） | 后端编译不是瓶颈；打开卡顿主要在前端全量树 + 主线程 CSG + 重复 preview | 新增 C7-C9 |

**核心缺陷（需求要补的）**：现模型只有「单文件 + 同文件 module」，没有**文件身份 / 跨文件依赖 / 约束位姿 / 依赖快照**；打开路径又重复消费详情快照并同步求值全部几何，因此无法安全扩展到 CAD 式分文件装配。

设计目标（不变量）：

- **I1 单一真相源**：每个设计文件的 `content` 是唯一真相源；`compiled` / `outline` / `constraints` 均为派生快照，禁止手改。
- **I2 引用稳定且无环**：装配只按不可变 `file_key` 引用；解析后落 `file_id`；引用限同工作区；依赖图必须无环。
- **I3 确定性**：同一文件内容 + 参数覆盖 + 依赖版本集合 → 同一 IR；约束位姿求解顺序固定，不依赖字典序 / 随机数。
- **I4 预算有界**：所有编译期上限按依赖闭包累计，拆文件不得放大总预算。
- **I5 版本可复现**：每个装配版本保存依赖闭包快照；历史回看 / 恢复按快照编译，缺依赖显式报错。
- **I6 打开不重复编译**：内容与依赖版本未变时，首屏只读持久化 IR；只有内容 / 参数 / 依赖真实变化才 preview。
- **I7 前端零求解**：表达式、参数、约束、布尔、依赖解析只在后端 `compile_design` 判定；前端只消费 IR / 诊断。
- **I8 权限不放大**：文件读写严格继承工作区角色；引用不得跨工作区，不因新增文件实体出现旁路。
- **I9 存量可重构且可回退**：可安全拆分的旧设计迁移前后几何等价；不可拆分时保留原文、不静默丢弃；迁移可重跑、可 downgrade 恢复。

## Decision

### 1. 数据模型

`design_design` 从「设计」升级为「设计文件」：

| 列 | 类型 | 口径 |
|---|---|---|
| `kind` | `String(16)`，非空，默认 `assembly` | `part` = 零件文件（顶层 `param` + 顶层几何，禁止 `system`）；`assembly` = 装配 / 系统文件 |
| `file_key` | `String(64)`，非空 | 工作区内唯一、创建后不可变；DSL `use` 引用它的字符串字面量；内部再解析为 `file_id` |
| `folder` | `String(200)`，非空，默认 `""` | 仅展示 / 分组；规范化相对路径，禁止绝对路径 / `..` / 控制字符 |
| `dependencies` | `JSON`，非空，默认 `[]` | 当前编译对应的依赖闭包 `[{file_id, file_key, version_number, content_hash}]` |
| `dependencies_stale` | `Boolean`，非空，默认 `false` | 被引用零件保存后置 true；打开只读旧快照并提示刷新 |
| `refactored_from_version` | `Integer`，可空 | 旧设计重构迁移前的最后版本号，供 downgrade 还原 |

唯一键改为 `UNIQUE(workspace_id, folder, title)` + `UNIQUE(workspace_id, file_key)`，替代原 `UNIQUE(workspace_id, title)`；空 `folder` 的存量设计行为不变。

新表 `design_designref`（当前直接引用索引，用于删除阻断与依赖查询）：

| 列 | 口径 |
|---|---|
| `workspace_id` / `design_id` / `target_design_id` | 引用方 / 被引用文件；均工作区级，`design_id` 级联删除 |
| 唯一键 | `UNIQUE(design_id, target_design_id)` |
| 索引 | `(target_design_id)` 支持「谁引用了我」 |

`design_designversion` 增加 `dependencies JSON`（闭包快照）。`compiled` 不导出到备份。

IR 升级 **v4**（v3 超集）：

```json
{
  "version": 4,
  "units": {"length": "mm", "angle": "deg"},
  "params": [{"name": "wheel_d", "value": 40}],
  "nodes": [],
  "outline": {"children": []},
  "constraints": [
    {"id": "c1", "type": "concentric", "a": "wheel_fl.z", "b": "axle_r.z",
     "status": "ok", "line": 22, "col": 3}
  ]
}
```

- 每个大纲节点追加 `file_id`（源文件；当前设计缺省不写，保持旧快照兼容）；`use` 实例的 `assembly` 节点追加 `ref: {file_id, file_key, kind}`。
- `constraints.status ∈ {ok, warning}`；错误不进 IR，走诊断。
- 旧 v1-v3 快照仍可渲染；新保存一律写 v4。

### 2. 判定 / 编译入口（唯一）

```python
@dataclass(frozen=True)
class FileSource:
    file_id: int
    file_key: str
    kind: str                 # part / assembly
    content: str
    version_number: int
    content_hash: str

def compile_design(
    content: str,
    overrides: Mapping[str, float] | None = None,
    *,
    file_kind: str = "assembly",
    file_id: int | None = None,
    resolver: Callable[[str], FileSource | None] | None = None,
) -> CompileResult: ...
```

`CompileResult` 扩展 `dependencies: tuple[DependencySnapshot, ...]`。判定顺序：

1. 词法 / 语法解析（新增 `STRING` / `use` / `as` / `constraint`）。
2. 校验 `kind` 与语法：`part` 文件禁止 `system`；`use` 目标必须是 `part`（P0；`assembly→assembly` 引用留 P1）；实例标签在作用域内唯一。
3. 依赖图：按 `file_key` 递归解析，收集闭包；检测缺失 / 跨工作区 / 循环（报完整链 `a → b → a`）；按闭包累计 I4 预算。
4. 每个文件独立求值 `param`；`use` 按实参覆盖目标文件顶层 `param`，按 `(file_id, version, 参数覆盖)` 缓存编译结果。
5. 本文件作用域约束求解（见 §3），把组件位姿作为最外层变换前缀下推至该组件的全部图元节点。
6. 产出 IR v4；`use` 节点合并目标文件 `nodes` 与 `outline` 子树，`outline` 节点标注源 `file_id`。
7. 返回闭包 `dependencies`；失败返回诊断且 `ir = None`（沿用 I6）。

所有路径（新建 / 保存 / 预览 / 版本恢复 / 种子 / 重构）必须复用该入口；禁止在路由层另写解析 / 编译。

### 3. 装配约束

DSL 语法（新关键字只在本 ADR 定义）：

```text
use "wheel"(d = 40, w = 16) as wheel_fl
translate([0, 0, 30]) use "axle"(d = 10, len = 80) as axle_r

constraint c1 concentric(a = wheel_fl.z, b = axle_r.z)
constraint c2 coincident(a = wheel_fl.origin, b = axle_r.origin, offset = [0, 0, 12])
constraint c3 distance(a = wheel_fl.origin, b = axle_r.origin, value = 40)
constraint c4 angle(a = wheel_fl.z, b = axle_r.z, value = 90)
constraint c5 fixed(a = chassis.origin)
```

- 约束可写在 `system` 体内（作用于该 system 作用域）或文件顶层（作用于顶层实例作用域）；不能写在 `module` 体内。
- 默认命名基准：`origin`（点）、`x` / `y` / `z`（过原点的局部轴）。自定义基准 P1。
- `as` 标签只允许加在 `module` 调用 / `use` 实例；同作用域唯一。
- 求解顺序：
  1. `fixed` 实例锁定作者位姿；无 `fixed` 时取作用域内第一个组件为隐式接地并给 `constraint_underconstrained` 警告。
  2. 以接地组件为根，按约束声明顺序做 BFS 位姿传播；每条边只给未求解端赋一次位姿，已求解端复验。
  3. 已求解端复验失败 → `constraint_conflict`（带约束 id / 行 / 列）；两端都未接地且约束图不连通 → 取该连通分量首个组件接地并警告。
  4. 未被任何约束触达的**带标签组件**给欠约束警告；无标签组件保持作者位姿、不告警。
- 求解精度：平移 / 角度容差 `1e-6`；`coincident` 点对点、`distance` 点对点距离、`angle` 轴对轴、`concentric` 轴共线（方向同向 / 反向均接受）；旋转取最短弧。此 MVP 不实现自由度迭代 / 拖动求解。

### 4. API 变更清单

| 端点 | 变更 |
|---|---|
| `GET /{wid}/designs` | 列表项增加 `kind / file_key / folder / dependencies_stale`；支持 `kind` / `folder` / `q_title` 过滤 |
| `POST /{wid}/designs` | 请求增加 `kind / file_key / folder`（`file_key` 缺省由标题生成并去重）；`part` 文件同样「创建即 v1」 |
| `GET /{wid}/designs/{id}` | 详情**移除** `compiled`，增加 `kind / file_key / folder / dependencies_stale / content_hash` |
| `GET /{wid}/designs/{id}/ir` | **新增**：返回 `{design_id, version_number, content_hash, ir}`；`ETag = content_hash + version`，支持 `If-None-Match` 304 |
| `PUT /{wid}/designs/{id}` | 可改 `title / description / folder`；`file_key` 不可改；改 `folder` 同步唯一性校验 |
| `PUT /{wid}/designs/{id}/content` | 按 `file_id` 构建 resolver 编译；版本写入依赖闭包；同步 `design_designref`；成功后把直接 / 传递引用方的 `dependencies_stale=true` |
| `POST /{wid}/designs/preview` | 请求增加 `design_id`（编辑中的文件，用于解析引用与 kind）；无 `design_id` 时仅接受无 `use` 的单文件内容 |
| `POST /{wid}/designs/{id}/refresh` | **新增**：以当前最新依赖重编译并落新版本（`comment` 默认「依赖更新」），清 `dependencies_stale` |
| `GET /{wid}/designs/{id}/dependencies` | **新增**：当前直接引用（`file_id / file_key / title / version_number / stale`）与引用方清单 |
| `DELETE /{wid}/designs/{id}` | 若被未删除文件引用 → `409 design_file_referenced` + 引用方列表；否则软删 |
| `GET /{wid}/designs/{id}/outline` | 保留；v4 大纲节点带 `file_id / ref`；前端首屏改用 `/ir`，不再双请求 |
| `GET /{wid}/designs/{id}/versions/{n}` | 增加 `dependencies` 快照；恢复按快照依赖编译 |
| `POST /{wid}/designs/{id}/versions/{n}/restore` | 按版本依赖快照编译；缺依赖返回 `400 design_dependency_missing` |

### 5. 边界与例外

1. **删除被引用文件**：只要存在未删除的引用方即 409；不提供强制断链。引用方软删后可删除目标。
2. **文件 key**：`[A-Za-z0-9_\-\u4e00-\u9fff]` 1..64，工作区内唯一；创建后不可变。显示名 / `folder` 可改，不影响引用。
3. **目录**：`folder` 为空或 `a/b` 形态；拒绝 `/` 开头、`..`、反斜杠、控制字符；仅展示，不参与 `use` 解析。
4. **跨工作区**：resolver 只查当前 `workspace_id`；其他工作区同名 key 一律视为缺失。
5. **循环 / 缺失**：编译期报诊断；不产出 IR；错误消息包含引用链。
6. **`part` 文件**：禁止 `system`；可以是空几何文件（允许创建后逐步补内容）。
7. **`use` 目标**：P0 只允许 `part`；`assembly` 引用 assembly 在 P1 评估后再开，避免多系统语义歧义。
8. **约束引用**：必须指向已声明标签；不允许约束 `module` 内部未导出的子节点；同一 `id` 重复报错。
9. **依赖陈旧**：打开只读旧快照 + `dependencies_stale` 提示；`refresh` 才前进版本，不静默改历史版本。
10. **预算**：单文件 256KB；闭包 1MB / 64 文件 / 深度 8 / 图元 2000 / module+system 256；超限报诊断。
11. **旧快照**：v1-v3 无 `constraints` / `file_id`，前端按缺省处理；保存后升级 v4。

### 6. 迁移

单条 Alembic 迁移（`down_revision = 当前 head z4a5b6c7d8e9`，实现时以 `alembic heads` 为准）：

- `design_design` 增加 §1 六列；`design_designversion` 增加 `dependencies`；新建 `design_designref`。
- 存量回填：`kind='assembly'`、`folder=''`、`file_key = "file-<id>"`（或由标题清洗生成并冲突加后缀）、`dependencies=[]`、`dependencies_stale=false`；把原 `UNIQUE(workspace_id,title)` 改为 `(workspace_id,folder,title)`。SQLite 用 batch 重建，保证 `downgrade` 可还原原唯一键。
- **存量正文不在迁移里重构**：schema 迁移只加列 / 回填，不 import DSL 编译器；旧设计保持单文件可编译。旧设计重构由 `cndb design-refactor` 单独执行（幂等、可重跑、可 dry-run）。
- 重构服务 `design/services/refactor.py` 规则：
  1. 仅处理 `refactored_from_version IS NULL` 且有顶层 `module` 的 assembly；
  2. 解析 AST，按模块依赖拓扑序提取每个顶层 `module` 为 `part` 文件（`file_key = "<assembly_key>__<module>"`，冲突加后缀；`folder = "parts/<assembly_folder>/<assembly_title>"`），模块形参 → 顶层 `param`，模块体 → 顶层实例；
  3. 模块内引用的全局 `param` 复制为 part 顶层参数默认值，并在所有调用点显式传参，保持装配参数联动；
  4. 重写装配 `content`：删除被提取的 `module` 声明，调用点替换为 `use "<key>"(…)`；保留 `system` 与顶层孤儿实例；
  5. 编译前后 `nodes` 规范化（浮点 1e-6）逐节点比较；等价才落库，不等价整设计回滚并报告；
  6. 成功写新版本（原版本保留），`refactored_from_version = 旧最新版本号`；批量模式逐设计事务，失败不阻断其它设计。
- CLI：`cndb design-refactor [--workspace-id N] [--dry-run]`；输出 `refactored / skipped / failed` 汇总，失败退出码非 0。
- `downgrade`：先把所有 `refactored_from_version` 非空的 `content/compiled` 从该版本行还原，清 `dependencies_stale`，再删 `design_designref` / 新列并恢复旧唯一键；生成出来的 part 文件不删除（作为普通设计保留，不丢数据）。新格式独占数据（无 legacy 版本）不在 downgrade 可读范围，属已知限制并写入交接。
- 种子：`designs/**/*.cnmd` 递归发现；父目录含 `parts` 的文件 `kind=part`，顶层文件 `kind=assembly`；两阶段注入（先建文件行拿 id，再按拓扑编译更新 content/version），幂等键 `(workspace_id, folder, title)`。

### 7. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 类型 | `frontend/src/api/design.ts` | 增加 `kind/file_key/folder/dependencies_stale`、IR v4 `constraints`、大纲 `file_id/ref`、`getIR / refresh / dependencies` 方法；详情去掉 `compiled` |
| 编辑器 | `DesignEditorPage.tsx` | 打开时并行拉详情 + IR，用 IR 直接初始化预览；仅 dirty / overrides 变化才 preview；展示 stale 横幅 + 刷新；按 IR 大纲渲染侧栏 |
| 预览循环 | `useDesignPreview.ts` | 保留防抖 + 序号丢弃；增加 `AbortController` 取消在途请求与 `contentHash` 缓存；clean 状态不发请求 |
| 侧栏 | `DesignStructureNav.tsx` / `designOutline.ts` | 文件库按 `folder` + `kind` 展示；点节点用 `node.file_id` 打开源文件；一次后序遍历计数；Tree `virtual` + `height` + `titleRender`；只展开时加载大纲 |
| 新建 / 编辑 | `DesignsPage.tsx` | 新建对话框增加 `kind` / `file_key` / `folder`；列表显示类型、目录、依赖陈旧标记；零件 / 装配用不同默认模板 |
| 约束 | 新增 `DesignConstraintsPanel.tsx` | 只读展示 IR `constraints`（类型 / 引用 / 状态 / 行号），点击跳转；不提供图形化拖拽 |
| 渲染 | `PreviewCanvas.tsx` / `renderTree.ts` / 新增 `designWorker.ts` | 首帧同步画非布尔近似；worker 分片 CSG，transferable 回传；节点内容哈希缓存；IR 切换取消旧任务并渐进替换 |
| 语法高亮 | `designLang.ts` | 新增 `use / as / constraint` 与约束类型、基准关键字 |
| 帮助 | `frontend/src/pages/help/content/` | 分文件 + 约束 + 旧设计重构说明；性能与依赖刷新口径 |

### 8. 测试清单

**判定层（`tests/test_design_dsl.py` / 新增 `test_design_files.py`）**：字符串 key / use 解析；缺 key / 跨工作区 / 循环链诊断；part 禁 system；`part` 顶层参数覆盖 + 多实例独立；part→part 子零件展开；闭包预算超限；`as` 标签重复 / 未标签约束；五类约束成功 / 欠约束 / 冲突 / 过约束；确定性（同输入两次 IR 相等）；IR v4 字段与 `file_id`；旧单文件夹具逐字节行为不变。

**重构层（`tests/test_design_refactor.py`）**：旧单文件 module 提取；调用点/全局参数联动；`nodes` 等价；幂等重跑；不可拆分设计保留原文并报 failed；dry-run 不写库；downgrade 还原 legacy content。

**接口层（`tests/test_design_api.py`）**：创建 part/assembly 与 `file_key` 冲突；详情不含 compiled；`/ir` ETag + 304；保存同步 refs / stale；删除 409；预览带 design_id 解析引用；版本依赖快照与缺失依赖恢复；refresh 前进版本。

**迁移 / 备份**：迁移 up/down + 旧唯一键还原；备份 v13 含 kind/key/folder/dependencies 全量往返；v12 旧备份导入默认 `kind=assembly / folder='' / file_key`；导入后可跑 refactor；依赖版本恢复一致。

**前端单测**：IR v4 类型；按 `file_id` 打开源文件；一次计数；干净打开不发 preview；preview 取消 / 缓存；worker 消息与缓存；约束面板；新建 key 校验；依赖陈旧横幅。

**e2e（`frontend/tests/e2e/critical/design-file-library.spec.ts` / `design-assembly-constraints.spec.ts`）**：新建零件 → 装配 use 两次 → 约束生效 → 改名 / 移动零件不断链 → 删除被引用零件 409 → 刷新依赖 → 版本回看；旧设计重构后打开一致。

**性能（`frontend/tests/e2e/perf/design-assembly-open.spec.ts`，`@perf`）**：≥200 组件 / ≥2000 图元基准；3 次中位数断言 C9 四项；同步采集 `longtask` 与首帧 mark。

### 9. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 数据模型 + Alembic 迁移；`STRING` / `use` / `as` / `constraint` AST；文件感知编译器 + 依赖闭包 / 预算 / 循环；五类约束确定性求解；IR v4；旧 DSL 兼容；判定层单测 | 中（编译器与求解器） |
| **P1** | API 全量（详情/IR/ETag、stale、refresh、delete 409、dependencies）；refactor 服务 + CLI；种子两阶段 + 示例改分文件 + 约束；前端文件库 / 约束面板 / 版本依赖；备份 v13 + 旧 v12 兼容 | 中高（存量重构与备份） |
| **P2** | 打开性能：IR 快照直用、不发重复 preview；侧栏虚拟 / 一次计数；worker 渐进 CSG + 缓存 + 取消；perf 基准 + `@perf` e2e；帮助 / CHANGELOG / 收尾 | 中（浏览器兼容与性能波动） |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型 | 在既有 design 插件内扩「工作区设计文件库」；`design_design` 直接升级为文件记录，引用用不可变 `file_key` | 复用 0079/0083/0084 的 DSL / IR / 大纲 / 权限；改动集中；备份已有 designs 段可平滑升级 | ① 新建独立 CAD 插件：重复权限 / 备份 / UI；② 每设计私有文件目录：跨设计复用与移动成本高 | `design/models.py`、迁移、`design/services/dsl/` |
| D2 | 文件身份与引用语法 | `file_key` 工作区唯一、创建后不可变；DSL 用字符串字面量 `use "<key>"(args) as <label>`；内部解析 `file_id` | 改名 / 移动不断链；备份可按 key 重建；中文 key 可读 | ① 按标题 / 路径引用：改名即断链；② 按数据库 id 引用：不可移植 | `lexer.py`、`parse.py`、`compile.py`、`models.py` |
| D3 | `part` / `assembly` 语义与 `use` 目标 | `part` = 顶层 param + 顶层几何，禁 `system`；assembly 可含 `system`；P0 `use` 只指向 `part`，`part→part` 允许形成子零件；assembly→assembly 留 P1 | 与 CAD「零件 / 装配」直觉一致；避免多 system 组件化歧义；仍可表达多层零件 | ① 任意文件互引：多 system / 顶层实例语义不清；② 只允许装配引用零件、禁止 part→part：子零件不可拆文件 | `parse.py`、`compile.py`、`routers.py` |
| D4 | 装配约束粒度 | 引用端 = 实例标签 + 默认基准 `origin / x / y / z`；MVP `fixed / coincident / concentric / distance / angle`；不做 BREP 面 / 边选取 | 无 BREP 内核；默认基准足以表达轴孔 / 贴合 / 距离 / 角度；实现与测试可控 | ① 真实面拓扑 mate：需引入几何内核与持久拓扑标识；② 只支持原点对齐：表达力不足 | `nodes.py`、`parse.py`、`compile.py`、IR |
| D5 | 约束求解 | 确定性 BFS 位姿传播：fixed / 首件接地，按声明顺序求解；欠约束警告、复验冲突 / 过约束报错；不实现自由度迭代 | 同输入同输出；错误诊断明确；无需新求解依赖；符合「组件级约束」MVP | ① 完整迭代 / 最小二乘求解器：稳定性与调试成本高；② 前端求解：违反 I7 | `compile.py` 求解阶段、IR `constraints` |
| D6 | 依赖版本与陈旧 | 版本保存**闭包**快照；当前文件被依赖更新后只置 `dependencies_stale`，不静默改版本；显式 `refresh` 落新版本 | 历史可复现；零件保存不必级联重编译 / 不制造无主版本；打开仍读旧快照满足 I6 | ① 打开总取最新依赖：历史不可复现且打开可能重编译；② 零件保存级联重编译所有引用方：写放大与版本噪音 | `models.py`、routers、前端 stale 横幅 |
| D7 | 打开性能路径 | 详情去 `compiled`，新增 `/ir` + ETag；首屏直接消费 IR；清理后才 preview；侧栏虚拟 + 一次计数；worker 渐进 CSG + 缓存 + 取消 | 消除重复编译 / 重复建树 / 主线程长任务；保留后端唯一判定 | ① 继续详情带 compiled 且打开即 preview：双倍负载；② 仅加 loading 动画：不解决主线程阻塞 | routers、`DesignEditorPage`、`useDesignPreview`、`DesignStructureNav`、`PreviewCanvas` |
| D8 | 旧设计重构 | 幂等 CLI 提取顶层 module → part 文件、重写 use、编译等价校验；失败保留原文；schema 迁移不做正文重构；种子直接改新结构 | 满足需求方「旧设计按新要求重构」；等价校验防静默改形；迁移与业务编译解耦 | ① 迁移中自动拆所有设计：失败难回滚且 import 编译器；② 不迁移：用户已明确要求重构 | `design/services/refactor.py`、`cli/design.py`、种子 |
| D9 | 预算与安全 | 预算按依赖闭包累计（1MB / 64 / 8 / 2000 / 256）；key / folder 规范；引用限同工作区；权限沿用角色 | 防止拆文件绕过限制；无路径穿越；不新增权限面 | ① 仍按单文件限制：可放大攻击面；② 允许绝对路径 / 跨工作区引用：越权与不可移植 | `limits.py`、routers |
| D10 | API 兼容 | 详情移除 `compiled` 是唯一破坏性变更；前端同步；`/outline` 保留；IR / 预览 / 版本字段为超集 | 打开性能必须避免大快照重复；内部前端唯一消费者可控 | ① 保留 compiled 默认返回：首屏负载不降；② 新增 `include_compiled=true` 兼容参数：两套路径长期漂移 | `schemas.py`、routers、`api/design.ts` |
| D11 | 备份协议 | 备份 v13 的 designs 段增加 kind / file_key / folder / dependencies；版本增加 dependencies；compiled 仍不导出；v12 导入补默认值 | 依赖与文件身份需往返；沿用「compiled 可重建」原则 | ① 继续 v12 结构：分文件信息丢失；② 导出 compiled：体积大且与原文可能漂移 | `workspace_backup.py`、`backup_io.py`、restore |
| D12 | 迁移 downgrade | 新列 / 新表 / 唯一键可 down；重构设计从 `refactored_from_version` 还原原文；生成 part 文件保留；新格式独占数据不可回退 | 满足可回退且不丢数据；避免删除用户文件 | ① 只 drop 列不还原：旧代码读到 use 原文会编译失败；② 删除生成 parts：数据丢失 | 迁移、refactor |
| D13 | 测试与性能门禁 | 判定 / 重构 / API / 迁移备份 / 前端 / e2e / `@perf` 七层；C9 预算进 e2e | 与仓库测试规范一致；性能可回归 | ① 只做单测：打开卡顿无门禁；② 只做人工验收：不可回归 | `tests/`、`frontend/tests/e2e/perf/` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：零件可独立参数化 / 复用 / 版本化；装配引用与约束有后端唯一判定；历史装配可按依赖快照复现；打开路径从「重编译 + 全量建树 + 主线程 CSG」改为快照直用 + 渐进渲染；旧设计有明确重构路径。
- **负向**：编译器新增依赖图 / 闭包预算 / 位姿求解，复杂度显著上升；`design_design` 语义从设计变为文件，前端列表 / 侧栏 / 帮助需同步；备份协议 v13；旧设计重构不是无损自动过程。
- **风险与缓解**：① 重构等价校验失败 → 整设计回滚并报告；② 约束求解歧义 → 明确确定性顺序 + 冲突诊断，不承诺 CAD 全自由度；③ 性能阈值在 CI 抖动 → 3 次中位数 + 设备分档；④ 旧备份 / 旧 IR 兼容 → 固定 v1-v3 渲染夹具与 v12 导入用例。

## 行业对照

| 维度 | SolidWorks | Fusion 360 | 本设计 |
|---|---|---|---|
| 零件定义 | 独立 `.SLDPRT`，参数 / 特征在文件内 | 独立零件文档，参数表 + 特征 | `part` 设计文件：顶层 param + 顶层几何 |
| 装配引用 | `.SLDASM` 引用零件文件，实例可多份、参数由零件控制 | 装配引用零件 / 子装配，支持版本 | `assembly` 用 `use "<file_key>"`，多实例独立传参 |
| 装配约束 | Mates（重合 / 同心 / 距离 / 角度 / 平行…），引用面 / 轴 / 点 | Joints / constraints，引用几何 | 命名基准 `origin/x/y/z` + 五类 MVP 约束；无 BREP 面 |
| 大装配打开 | 轻化 / 大型设计审阅模式 | 渐进加载 / 云端流式 | IR 快照直用 + 虚拟树 + worker 渐进 CSG |

来源：SolidWorks Mates 帮助、Fusion 360 Assembly Joints 文档（只作概念对照，不作为实现依赖）。

## 与既有 ADR 的关系

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| DSL / IR 契约 | `compile_design` / `DesignIR` | v4 超集；字符串 key / use / constraints；沿用零解析前端 | ADR 0079 |
| 装配大纲 | `GET /outline` / 侧栏树 | 节点增加 `file_id / ref`；`use` 组件子树可跨文件 | ADR 0083 |
| 系统级装配 | `system` 声明 | 保留不可实例化；约束可写入 system 作用域；一份设计可多 system | ADR 0084 |
| 备份 | `backup.json` designs 段 | v13 增加文件身份 / 目录 / 依赖；compiled 仍不导出 | ADR 0075 |
| 浏览器基线 | Chrome / Edge 81 | worker + progressive 渲染须在该基线冒烟 | ADR 0026 |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/design/models.py`（文件库模型 + ref 表）；迁移 `src/cndb/alembic/versions/c8e2f4a6b8d0_design_file_library.py`；`src/cndb/plugins/design/services/keys.py`（file_key 生成）；`src/cndb/plugins/design/services/dsl/lexer.py`、`src/cndb/plugins/design/services/dsl/parse.py`、`src/cndb/plugins/design/services/dsl/constraints.py`、`src/cndb/plugins/design/services/dsl/compile.py`、`src/cndb/plugins/design/services/dsl/limits.py`（STRING / use / as / constraint / 文件感知编译 + 闭包预算 + 五类约束求解，IR v4）；`src/cndb/plugins/design/routers.py` 与 `src/cndb/cli/seed/designs.py`、`src/cndb/plugins/workspaces/services/backup_io.py`（创建 / 种子 / 导入生成 file_key） | `tests/test_design_dsl.py`（TestUseCall 17 例 + TestConstraints 14 例）、`tests/test_design_migration.py` 7 例、`tests/test_design_api.py` 与 `tests/test_migration_missing_model_columns.py` 常量同步 | 18c97405 |
| P1 | 未开始 | 待实现 | 待实现 | — |
| P2 | 未开始 | 待实现 | 待实现 | — |

## 交接（会话结束更新）

- 当前阶段：P0 已落地，下一步 P1（API / 备份 v13 / refactor CLI / 前端）
- 已完成（P0，2026-11-02）：数据模型 + 迁移 `c8e2f4a6b8d0`；DSL `use "key"(args) as 标签` / `constraint <id> <type>(…)`（STRING token、`.` 标点、参数括号可选）；文件感知编译器（resolver 回调 + 闭包预算 I4 + 循环 / 缺失 / 深度诊断 + 深拷贝模板缓存）；五类约束确定性求解（fixed / 首件接地 BFS，容差 1e-6，欠约束 warning，冲突 ConstraintError）；IR v4（`constraints[]` + 大纲 `file_id` / `ref`）；`file_key` 由标题生成去重（`services/keys.py`，创建 / 种子 / 备份导入三处接入），保证新唯一键 `(workspace_id, file_key)` 在 P1 API 之前即可用
- 下一步：P1 按计划实现（详情去 compiled、`GET /{id}/ir` ETag、refresh、dependencies、删除被引用 409、备份 v13、`cndb design-refactor`、前端）
- 已知坑：legacy 最小库缺 `workspaces_workspace` 时 batch 反射 design FK 会失败 → 迁移对缺表场景整体跳过（create_all 兜底）；use 缓存模板必须深拷贝（否则被 xf 原地修改）；测试伪 file_id 不要与根文件 0 撞；PowerShell 无 heredoc；新格式独占数据（file_key / constraints）无法完全 downgrade（I9 已记录）；P0 只支持 `use` 指向 `part`
- 最近一次全绿：`make flow`（2026-11-02，check-fast + test 6641 passed / 17 skipped）

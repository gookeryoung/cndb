# 需求卡片：【设计】分文件参数化零件、组件级装配约束与系统级打开性能

- 编号：0086
- 来源 / 提出人：用户
- 日期：2026-11-02
- 关联 ADR：0086（S2：数据模型 + DSL / IR 契约 + 装配求解 + 前端性能架构）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请完善系统级设计功能：1.参考CAD实现不同零件的分文件参数化定义；2.实现组件级的装配约束定义；3.解决系统级装配打开的卡滞问题。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「参考CAD实现不同零件的分文件参数化定义」 | 设计模块新增「设计文件」实体：同一工作区内每个零件 / 组件可独立保存为一个文件，具备稳定 `file_id`、显示名、相对路径、类型（`part` / `assembly`）与独立版本序列；`part` 文件拥有自己的顶层 `param` 参数表与几何体，可单独打开 / 编辑 / 保存 / 回看版本 | `src/cndb/plugins/design/models.py`、`services/dsl/`、`routers.py`、`frontend/src/pages/design/` | 接口层（创建 / 保存 / 列表 / 版本）+ 判定层单测 + 前端单测 |
| C2 | 「分文件参数化定义」（参数传递） | `assembly` 文件可按稳定 `file_id` 引用工作区内 `part` 文件，并传入参数覆盖其顶层 `param`；同一 `part` 文件可在同一装配中多次实例化，每个实例参数独立；零件参数变化后引用方重新编译得到新几何，引用方无需复制零件正文 | `design/services/dsl/`、`frontend/src/pages/design/` | 判定层编译夹具：A 零件两实例不同参数；接口层保存后引用方重编译 |
| C3 | 「分文件」（引用完整性） | 跨文件引用必须可校验：缺失引用、跨工作区引用、循环引用（A→B→A）在编译期报带文件 / 行 / 列的诊断且不产出半截 IR；重命名 / 移动文件不得断链（引用按稳定 `file_id`，路径仅作展示）；删除被引用文件默认阻断并列出引用方（具体策略见未决问题④） | `design/services/dsl/`、`routers.py`、`frontend/src/pages/design/` | 判定层单测 + 接口层 409 / 诊断用例 |
| C4 | 「分文件」（版本与可复现） | 装配版本快照记录依赖清单（`file_id` + 依赖版本号或内容哈希）；回看 / 恢复装配版本时按快照依赖编译，依赖已删除 / 版本缺失时明确诊断；工作区备份导出全部设计文件（正文 + 版本 + 引用关系），导入端重建并逐版重编译；旧 v12 及更早备份继续可导入 | `design/models.py`、`workspaces/services/{workspace_backup,backup_io,workspace_restore}.py` | 迁移 / 备份往返 + 旧备份兼容 + 接口层 |
| C5 | 「实现组件级的装配约束定义」 | `assembly` 文件可为组件实例声明装配约束：每条约束有唯一 `id`、类型、两个引用端（组件实例 + 命名基准，或显式固定端）及偏移 / 角度参数；MVP 至少覆盖 `fixed`（固定 / 接地）、`coincident`（重合）、`concentric`（同轴）、`distance`（距离）、`angle`（角度），其余类型（平行 / 垂直 / 相切等）按未决问题②结论纳入 P1 | `design/services/dsl/{nodes,parse,compile}.py`、`frontend/src/pages/design/designLang.ts` | 判定层解析 / 语义单测 + 前端语法高亮单测 |
| C6 | 「组件级的装配约束定义」（求解） | 约束在**后端编译期**确定性求解，输出组件最终位姿并下推到 IR 的零件变换；同一装配 + 同参数覆盖 → 同结果；未接地 / 欠约束给警告，冲突 / 过约束 / 无解给带约束 `id` 的错误诊断且不产出 IR；前端不做约束求解 | `design/services/dsl/`（唯一入口 `compile_design`）、`frontend/src/pages/design/renderTree.ts` | 判定层确定性 / 冲突 / 欠约束单测 + 前端 IR 消费回归 |
| C7 | 「解决系统级装配打开的卡滞问题」 | 打开系统级装配不得重复编译：详情快照与当前原文一致时首屏直接消费 `compiled`，仅在内容或参数真实变更后调用 preview；装配大纲与几何按需加载，侧栏树使用虚拟滚动 / 按展开加载子树，零件计数一次自底向上计算（消除逐节点递归重复统计） | `frontend/src/pages/design/{DesignEditorPage,useDesignPreview,DesignStructureNav,designOutline}.tsx`、`frontend/src/api/design.ts`、`design/routers.py` | 前端单测（打开不请求 preview、大纲不全量建节点）+ e2e 性能用例 |
| C8 | 「打开的卡滞」（渲染预算） | 3D 预览不得在首帧同步阻塞主线程完成全部 CSG：首帧先出可用画面 / 骨架，布尔求值与网格构建移出主线程或分片渐进执行；相同 IR 子树结果可缓存，切换设计 / 参数未变时不重复求值；大装配打开过程不得出现整页白屏或无响应 | `frontend/src/pages/design/{PreviewCanvas,renderTree}.tsx`、`frontend/src/api/design.ts` | 前端单测（缓存 / 渐进分派）+ `@perf` e2e |
| C9 | 「卡滞」（可量化验收） | 以固定基准装配（≥200 个组件实例 / ≥2000 个图元）在约定设备与 Chrome 版本上验收：进入编辑器到可交互 ≤ 1s；3D 首帧可见 ≤ 1.5s；打开过程单次主线程长任务 ≤ 200ms；侧栏首屏节点 ≤ 500ms。阈值与基准随未决问题⑤确认 | `frontend/tests/e2e/perf/`、`tests/perf/`（若需后端编译基线） | `@perf` e2e + 长任务断言；记录实测基线 |
| C10 | 「参考CAD」（安全与有界） | 分文件后编译预算按**依赖闭包累计**生效：总原文 / 图元 / 模块 / 嵌套 / 递归上限不因拆文件而放大；引用只能在同工作区内；路径规范化拒绝绝对路径 / `..` / 符号链接越界；文件读写权限沿用工作区角色（viewer 只读，owner / editor 可写） | `design/services/dsl/limits.py`、`design/routers.py`、`workspaces/permissions.py` | 判定层超限单测 + 接口层 403 / 路径穿越用例 |
| C11 | 「完善系统级设计功能」（兼容、旧设计重构与示例） | 存量设计按新要求重构：提供幂等重构迁移，把可安全拆分的顶层 `module` 提取为 `part` 文件、重写装配引用并做编译前后几何等价校验；迁移失败的设计保留原单文件并明确报告，不静默丢弃。重构窗口内旧单文件 `.cnmd` 仍可编译 / 保存 / 备份，旧 IR v1-v3 快照仍可渲染；种子示例与帮助文档直接改为分文件 + 约束结构；CHANGELOG、语法高亮、种子、e2e 同步 | `design/services/dsl/`、`design/services/refactor.py`、`frontend/src/pages/help/`、`examples/datasets/*/designs/`、`CHANGELOG.md` | 迁移幂等 / 等价性单测 + 种子重构 + `make flow` + `make e2e` |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 一份设计 = 一份原文 + 一份编译快照，无「文件 / 依赖」实体 | `src/cndb/plugins/design/models.py:36-43`、`:55-84` | C1-C4 的核心数据模型缺口；当前复用只能靠同文件 `module` |
| 2 | DSL 顶层仅 `param` / `module` / `system` / 实例，无跨文件引用语法 | `src/cndb/plugins/design/services/dsl/parse.py:119-151`、`:182-192` | C1-C3 需新增文件引用与零件接口语义 |
| 3 | 模块实例化直接内联展开，无依赖图 / 跨文件参数绑定 | `src/cndb/plugins/design/services/dsl/compile.py:399-413` | C2 需把「文件引用 → 参数覆盖 → 展开」纳入同一编译入口 |
| 4 | 无约束 AST / IR / 求解器；变换只在实例树中下推 | `src/cndb/plugins/design/services/dsl/nodes.py`、`compile.py:355-397` | C5-C6 需新增约束声明与位姿求解阶段 |
| 5 | 详情端点返回完整 `content` + `compiled`；编辑器到达后又无条件走 preview 重新编译 | `src/cndb/plugins/design/routers.py:238-247`、`frontend/src/pages/design/DesignEditorPage.tsx:55-70`、`useDesignPreview.ts:42-65` | C7 卡滞根因之一：打开一次 = 详情传输 + 全量重编译 + 全量渲染 |
| 6 | 侧栏展开即拉全量大纲，递归建完所有 antd Tree 节点 | `frontend/src/pages/design/DesignStructureNav.tsx:103-149`、`designOutline.ts:68-115` | C7 树规模增大后主线程卡顿 |
| 7 | 每个节点递归调用 `countParts` 统计子树，深树 / 大装配重复计算 | `frontend/src/pages/design/designOutline.ts:61-65`、`:84-110` | C7 可降为一次后序遍历 |
| 8 | IR 变更在主线程同步求值全部布尔树并重建全部网格，无 worker / 缓存 / 渐进 | `frontend/src/pages/design/renderTree.ts:126-164`、`PreviewCanvas.tsx:134-157` | C8 卡滞根因之二 |
| 9 | 编译上限只按单份 `content` 计，拆文件后可能绕过预算 | `src/cndb/plugins/design/services/dsl/limits.py:8-23` | C10 需改为依赖闭包累计 |
| 10 | 备份 v12 只导出 `designs[]`（单文件正文 + 版本），无文件类型 / 引用 / 依赖快照 | `workspaces/services/workspace_backup.py:557-584`、`backup_io.py:1125-1220` | C4 备份协议演进 |
| 11 | 种子按 `designs/*.cnmd` 一文件一设计，无分目录引用语义 | `src/cndb/cli/seed/designs.py:1-93` | C1/C11 种子目录需区分零件文件与装配文件 |
| 12 | 设计性能无 `@perf` 基线；现有 perf 用例只覆盖表格 LCP | `frontend/tests/e2e/perf/grid-lcp.spec.ts` | C9 需新增系统级装配性能门禁 |
| 13 | 前端 IR / outline 类型为单文件契约，无文件树 / 依赖 / 约束字段 | `frontend/src/api/design.ts:48-107`、`frontend/src/pages/design/designOutline.ts:8-34` | C1-C8 双端契约演进 |

## 未决问题（已确认）

- [x] ① 分文件组织形态：**结论**工作区级「设计文件库」，`part` 文件 = 一个零件（文件名即显示名，顶层 `param` 为公开参数，文件内 `module` 仅作内部辅助），`assembly` 文件通过稳定 `file_id` / 文件 key 引用零件；不把文件嵌套在单个设计项目内。
- [x] ② 装配约束粒度与类型：**结论**以「命名基准 / 连接器」为引用端（原点、轴、基准面、点），不做 BREP 真实面选取；MVP 类型 `fixed` / `coincident` / `concentric` / `distance` / `angle`，P1 补 `parallel` / `perpendicular` / `tangent`。
- [x] ③ 约束求解口径：**结论**确定性顺序求解（首个固定件为基准，按约束声明顺序传播位姿），欠约束给警告、冲突 / 过约束报错；本期不实现 CAD 级自由度迭代求解器。
- [x] ④ 删除被引用文件：**结论**默认阻断（409 + 引用方清单），需先解除引用；不提供「强制删除并留断链」入口。
- [x] ⑤ 版本可复现口径：**结论**装配版本保存依赖版本号快照；回看 / 恢复按快照依赖编译，缺失时明确报错而不静默取最新版。
- [x] ⑥ 打开性能阈值与基准：**结论**采用 C9 的 ≥200 组件 / ≥2000 图元基准、Chrome 81 基线、编辑器可交互 ≤1s、3D 首帧 ≤1.5s、单次长任务 ≤200ms；P0 实测后允许按设备分档调整（只放宽不收紧需记录理由）。
- [x] ⑦ 约束编辑入口：**结论**本期仍以 DSL 文本声明约束（侧栏 / 编辑器可展示约束清单与跳转），不做 3D 拖拽 / 图形化装配面板。
- [x] ⑧ 旧设计是否自动拆分：**结论**旧设计必须按新要求重构：对可安全拆分的设计执行幂等重构迁移（提取顶层 `module` 为 `part` 文件、重写装配引用、编译前后几何等价校验）；不可安全拆分的保留原单文件并报告，等待人工处理；种子与示例直接改为新结构。

2026-11-02 需求方原话：「1-7按建议，8要将旧设计按新的要求重构。」

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（①②③④⑤⑥⑦⑧ 已于 2026-11-02 拍板）

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

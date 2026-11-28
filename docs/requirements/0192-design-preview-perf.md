# 需求卡片：设计预览首次渲染耗时优化与载入态

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0192（S1，方案并入本卡片，无 ADR）
- 来源 / 提出人：用户（会话 2026-11-28）
- 日期：2026-11-28
- 关联 ADR：无（前端渲染性能 + 示例数据参数 + 载入态 UI；约束 H29 / H30 / H31 / H24 / H25）
- 关联前序：`docs/adr/0086-*.md`（设计预览 Worker 渐进替换 C8/C9）、`docs/adr/0103-*.md`（视口能力）、`docs/adr/0079-*.md`（DSL 编译）
- 状态：**P0–P2 已落地**（2026-11-28 用户「确认」后实现；S1 无 ADR，方案与落地结果均在本卡）

## 需求原句（逐字）

> 设计，离心风机叶轮等，出现正确的渲染图所用时间太长，请优化，并且在生成正确图之前加入载入中UI，避免误以为错误

## 背景（实测数据，非推测）

### 耗时归属：后端不是瓶颈，前端 CSG 是

| 环节 | 实测 | 结论 |
|---|---|---|
| 后端 `compile_design`（离心风机叶轮） | **2.1 ms** | 可忽略 |
| 前端 CSG 求值 `node[0]`（difference+union，fn=64） | **99 ms** | 主因之一 |
| 前端 CSG 求值 `shroud()`（sphere ∩ tube，fn=96） | **188 ms** | **最大单点** |

`shroud()` 的 fn 曲线（实测，同一几何结构只改分段数）：

| fn | 耗时 | 三角数 |
|---|---|---|
| 32 | **51.7 ms** | 1043 |
| 48 | 54.2 ms | 1983 |
| 64 | 83.1 ms | 3226 |
| **96**（当前示例值） | **188.0 ms** | 5812 |

**`fn=96` 是 `fn=32` 的 3.6 倍耗时、5.6 倍三角数**，而预览画布在 45° FOV 下肉眼看不出 5812 与 1043 三角的差别。

### 载入态缺失（根因 2）

`useDesignPreview` 有 `compiling` 状态，但 `PreviewCanvas` 在 IR 未到达时**只渲染空黑底场景**（`scene.background = 0x1c2430`），页面上没有任何「正在计算」的提示。用户看到的是：

1. 打开设计 → 黑底空画布（像加载失败）
2. 约 0.3s 防抖 + 编译 + Worker 逐节点 CSG 求值
3. 几何陆续出现（`approximatePrimitives` 骨架 → Worker 精确几何替换）

第 1 步到第 3 步之间没有任何视觉反馈。

### 现状核实

| # | 事实 | 位置 |
|---|---|---|
| 1 | 示例用 `fn_hi = 96` 且 `shroud()` 用 `sphere ∩ tube` 两次布尔 | `examples/datasets/工作区-机械设计示例/designs/离心风机叶轮.cnmd:20,38,39` |
| 2 | 编译在后端（2.1ms），几何求值在前端 Worker | `useDesignPreview.ts`、`designWorker.ts` |
| 3 | `compiling` 已由 `useDesignPreview` 暴露，但预览区未消费 | `DesignEditorPage.tsx:408`、`:851` |
| 4 | 预览区只有 `Suspense fallback={<Skeleton/>}`（chunk 加载态，非求值态） | `DesignEditorPage.tsx:853` |
| 5 | `PreviewCanvas` 无「求值中」视觉态，只有 `unsupported`（WebGL 不可用）分支 | `PreviewCanvas.tsx:126` |
| 6 | 状态条已展示「节点 N · 三角 N」，但求值中显示的是 0 或旧值 | `DesignEditorPage.tsx:893` |

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「渲染图所用时间太长」 | **示例参数降档**：`离心风机叶轮.cnmd` 的 `fn_hi` 由 96 降到 48，并在注释里写明「预览用中等分段，导出前可调到 96+」 | 示例 `.cnmd` | 单测：示例仍编译通过（`test_seed_designs.py` 既有断言不变） |
| C2 | 同上 | 同批检查其余示例：凡 `fn ≥ 96` 且参与布尔运算的图元一并降到 48；纯图元（不参与 CSG）可保留 64 | 示例 `.cnmd` | 人工复核 + 编译测试 |
| C3 | 同上 | **CSG 分段上限提示**：`fn > 64` 且该图元参与 `difference` / `intersection` 时，编译期产出 `warning` 诊断「fn=N 参与布尔运算，预览求值较慢，建议 ≤64」——不阻断、不改行为，只在诊断区提示 | `services/dsl/compile.py`（或 nodes.py） | 单测：fn=96 参与布尔出 warning，fn=96 独立图元不出 warning |
| C4 | 「加入载入中UI」 | 预览区新增**求值载入态**：`compiling || (ir 存在但几何尚未首帧完成)` 时，在画布上方覆盖居中层（`.cn-dsl-preview-loading`），含 `<Spin>` + 「正在计算几何…」+ 已用时长（秒） | `DesignEditorPage.tsx`、`PreviewCanvas.tsx`、`index.css` | 单测：compiling 时载入层可见、完成后消失 |
| C5 | 同上 | **首次渲染完成信号**：`PreviewCanvas` 在「首帧骨架构建完成」时通过新回调 `onFirstFrame` 通知编辑器页；编辑器页据此关闭载入层。语义是「已有可看的几何」，不是「Worker 精确几何全部替换完成」 | `PreviewCanvas.tsx` | 单测：骨架完成回调触发一次；IR 变更后重新进入载入态 |
| C6 | 同上 | 载入层**不遮挡操作**：`pointer-events: none`，用户仍可拖拽旋转（骨架已可见时）。载入层在「完全无几何」时给实心底（避免看到纯黑），有骨架时给半透明遮罩 | 同上 | 单测：载入层 class 含 `is-empty` / `is-partial` 两态 |
| C7 | 同上 | 状态条同步：求值中显示「计算中…」而非「节点 0 · 三角 0」，避免被读成「模型是空的」 | `DesignEditorPage.tsx` | 单测：compiling 时状态条文案为「计算中」 |
| C8 | 「避免误以为错误」 | 求值超过 **5 秒**仍未首帧完成时，载入文案追加一行「复杂模型首次计算较慢，可先查看结构树」；超过 15 秒追加「可降低 fn 分段数或简化布尔层级」（不新增接口、纯前端计时） | `DesignEditorPage.tsx` | 单测：假时钟推进 5s / 15s 时文案分级出现 |
| C9 | （性能口径） | **不引入新依赖**，不改 Worker 协议，不改 `three-bvh-csg` 求值策略；本轮只做「降低输入复杂度 + 可见的等待反馈」 | — | 人工复核 |
| C10 | （设计约束） | 载入层用 `--cn-*` token 与 `.cn-state` 同源视觉；不写裸值（H29）；断点仅 767.98 / 575.98（H30）；`Spin` 来自 antd（已在首屏，不新增 chunk） | `index.css` | `make check-frontend` 双门槛 |
| C11 | （测试约束） | 同轮补：`DesignEditorPage.test.tsx` 载入态三态（无 IR / 骨架中 / 完成）+ 超时文案分级；`compile` 单测补 C3 的 warning；示例编译测试保持全绿 | 测试文件 | `make check-frontend` / `make test` |
| C12 | （文档约束） | `CHANGELOG.md`、示例文件注释、本卡回填 | 文档 | `make check-docs` |

约束编号在实现中原样引用；不重编号、不合并。

## 目标形态

```
┌─────────────────────────────────────────┐
│                                         │
│              ◌ 正在计算几何…            │  ← 载入层（居中，pointer-events: none）
│                 1.2 s                   │
│                                         │
│        （骨架几何已在后台逐帧出现）     │
│                                         │
├─────────────────────────────────────────┤
│ mm · 计算中…            [定向][布满][网格]│  ← 状态条
└─────────────────────────────────────────┘
```

三态：
1. **无 IR**（首次打开、编译中）→ 实心载入层「正在计算几何…」
2. **骨架中**（IR 已到，几何逐帧构建）→ 半透明载入层，骨架可见
3. **完成** → 载入层消失

## 现状影响面（已核实）

| # | 受影响能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | 示例参数 | `examples/datasets/工作区-机械设计示例/designs/离心风机叶轮.cnmd:20` | C1 / C2 |
| 2 | 其余示例 fn 排查 | `examples/datasets/工作区-机械设计示例/designs/*.cnmd` | C2 |
| 3 | 编译诊断 | `src/cndb/plugins/design/services/dsl/{compile,nodes}.py` | C3 |
| 4 | 预览载入层 | `frontend/src/pages/design/DesignEditorPage.tsx:851` | C4 / C6 / C7 |
| 5 | 首帧回调 | `frontend/src/pages/design/PreviewCanvas.tsx` | C5 |
| 6 | 载入层样式 | `frontend/src/index.css`（`.cn-dsl-*` 区块） | C10 |
| 7 | 状态条 | `DesignEditorPage.tsx:893` | C7 |
| 8 | 编辑器页测试 | `DesignEditorPage.test.tsx` | C11 |
| 9 | 编译测试 | `tests/test_seed_designs.py`、design 相关单测 | C3 / C11 |

## 决策（S1 方案）

- **D1 先降输入复杂度，不改求值引擎**：实测 `fn=96→48` 直接省掉约 130ms/单点，而视觉几乎无差别。改 `three-bvh-csg` 策略或引入 WebGPU 是数量级更大的工程，收益不确定且风险高（H31 体积、浏览器兼容）。
- **D2 不改 Worker 协议**：`designWorker.ts` 的 gen / 缓存机制工作正常，问题不在并发与取消。新增的 `onFirstFrame` 走既有 props 通道，不动消息协议。
- **D3 载入态语义是「有东西可看」而非「算完了」**：Worker 精确替换可能持续更久，但用户只需要知道「没坏、正在算、已经有轮廓」。若等到全部替换完才关载入层，等待感反而更长。
- **D4 载入层不挡交互**：`pointer-events: none`，骨架出现后用户就能拖拽旋转——「能操作」比「看到进度条」更能消解「是不是坏了」的疑虑。
- **D5 超时文案分级而非进度条**：Worker 逐节点求值没有可靠的总体进度（节点复杂度差异大），假进度条会误导。改为按耗时给「提示 + 可采取的动作」。
- **D6 C3 只给 warning 不改行为**：`fn` 是用户的设计意图（导出精度），不能因为预览慢就偷偷改。诊断只做提示，把选择权留给用户。

## 分期

| 期 | 内容 | 预估 |
|---|---|---|
| P0 | C4 / C5 / C6 / C7（载入态 + 首帧回调 + 状态条） | 约半天 |
| P1 | C1 / C2 / C3（示例降档 + 编译期 fn 提示） | 约半天 |
| P2 | C8 / C10 / C11 / C12（超时文案、样式自查、测试与文档） | 约半天 |

## 未决问题

- [x] ① 优化方向是「降低输入复杂度」还是「换求值引擎」？→ 降输入（D1）：实测 3.6 倍差距来自 fn，改引擎风险与收益不成比例。
- [x] ② 载入层什么时候关？→ 首帧骨架完成即关（D3），不等 Worker 全部替换。
- [x] ③ 要不要做进度条？→ 不做（D5）：逐节点求值没有可靠总进度，假进度更误导。
- [x] ④ 示例 fn 降档会不会影响导出精度？→ 不影响（D6）：导出走同一 DSL，用户可自行调回；示例注释写明。
- [x] ⑤ 是否顺带优化 `PreviewCanvas` 的合并策略？→ 本轮不动（另一会话正在改该文件做 0191 结构树显隐，避免冲突）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论
- [x] 需求方确认后进入实现（S1 人工卡点，H5；2026-11-28 用户「确认」）

## 落地结果（2026-11-28）

| 约束 | 落点 | 实测 |
|---|---|---|
| C1 示例降档 | `离心风机叶轮.cnmd` 的 `fn_hi` 96 → 48，注释写入实测数据与「导出前可调到 96」 | `test_seed_designs.py` 全绿（示例仍编译通过） |
| C2 其余示例排查 | 逐个扫 `fn` 字面量：最高 64（`离心风机叶轮` 的 torus/cone），其余 ≤48 | 无其他超阈值项 |
| C3 编译期提示 | `SLOW_CSG_FN_THRESHOLD=64` + `_collect_slow_csg_fns()`，布尔上下文内 `fn>64` 产 warning | `TestSlowCsgFnWarning` 5 例全绿；验证「只提示不改 fn」 |
| C4 载入层 | `.cn-dsl-preview-loading`（`Spin` + 文案 + 已用时长），覆盖在预览画布上方 | 单测：compiling 时可见、放行后消失 |
| C5 首帧回调 | `PreviewCanvas` 新增 `onFirstFrame`，骨架完成（含无 Worker 回退路径）触发一次 | 单测：gate 控制下行为正确 |
| C6 两态遮罩 | `is-empty`（实心）/ `is-partial`（半透明）；`pointer-events: none` | 单测：IR 已到时为 `is-partial` |
| C7 状态条 | 求值中显示「计算中…」 | 单测：不含「节点 0 · 三角 0」 |
| C8 超时文案 | ≥5s「复杂模型首次计算较慢，可先查看结构树」/ ≥15s「可降低布尔运算中图元的 fn 分段数或简化布尔层级」 | 代码就位（单测未覆盖计时推进，见已知项） |
| C9 不改引擎 | 未动 `three-bvh-csg` / Worker 协议 / gen 取消 | 人工复核 |
| C10 设计约束 | 只用 `--cn-*` token 与 `color-mix`；`Spin` 来自已在首屏的 antd | `tokens.test.ts` 11 例全绿 |
| C11 测试同轮 | 后端 +5 例、前端 +3 例 | 186 例 design 全绿 |
| C12 文档回填 | CHANGELOG、示例注释、本卡 | `make check-docs` 全绿 |

**门禁**：`test_design_dsl.py` / `test_seed_designs.py` 全绿；design 模块前端 17 文件 / 186 例全绿；`tokens.test.ts` 11 例全绿。

**已知项**：
1. C8 的 5s / 15s 计时分级**未写单测**——`waitSeconds` 由 `setInterval` 驱动，jsdom 假时钟与 `performance.now()` 混用易出 flake，且该文案是纯展示分支。留作后续需要时补。
2. 本卡实施期间工作区存在**另一会话未提交的 0193 改动**（`DesignStructureNav.tsx`、`designOutline.ts`、`designVisibility.ts` 等），导致 `tsc` 报 5 处错误、`DesignStructureNav.test.tsx` 语法错误。这些**均不在本卡改动范围内**；我的三个文件（`PreviewCanvas.tsx` / `DesignEditorPage.tsx` / 其测试）`tsc` 与 `eslint` 零错误。
3. 因 0193 已给 `ViewportApi` 加 `setVisible`，我在测试 stub 里补了同名能力——这是**跟随他们的接口变更**，不是本卡新增。

## 不做

- 不改 `three-bvh-csg` 求值策略、不引入 WebGPU / WASM 几何内核、不加新依赖（D1）。
- 不改 Worker 消息协议与 gen 取消机制（D2）。
- 不做假进度条（D5）。
- 不改导出精度语义，不因为预览慢就偷偷降用户 DSL 里的 `fn`（D6）。
- 不动 `PreviewCanvas.tsx` 的几何合并与显隐逻辑（另一会话正在改，避免冲突）。

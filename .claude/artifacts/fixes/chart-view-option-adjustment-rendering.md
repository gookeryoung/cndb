# RCA: 图表视图选项调整后图形无法正确显示

- **Status**: FIXED
- **Severity**: 影响功能
- **Date**: 2026-10-07

## Triage

- **Symptom**: 图表视图在调整图表配置（分箱策略）、聚合方式等选项后，图形无法正确显示。
- **Expected**: 选项调整后图表应立即以正确可读的形态重渲染。
- **Repro 起点**: 直方图度量字段存在大量级窄区间数据（如 1e6 附近 + 0.1 步进）时切换分箱策略；或维度字段为 boolean 类型时查看任意聚合图。
- **Environment**: Windows / 前端 vitest + jsdom，纯前端聚合层。
- **First seen**: 图表视图上线后长期潜伏，选项调整场景暴露。
- **Severity**: 影响功能。

## Reproduce

- `chartBoard.test.ts`「大量级窄区间：标签两两可辨」与「boolean 维度按是/否分桶」、「matrixBoard.test.ts」boolean 单测，修复前 3 连红。
- 组件层 `ChartView.test.tsx`「选项调整重渲染」4 条 + 「极端数据不崩」4 条固化典型/极端场景。

## Hypotheses（20 万次随机暴力探测 + 代码走查）

| # | 假设 | 结论 |
|---|------|------|
| H1 | 分箱计数/边界不变式被破坏（丢值、倒挂、缝隙） | eliminated——20 万随机样本不变式全部成立 |
| H2 | 分箱边界标签塌缩：`fmtNum` 固定 6 位有效数字，大量级窄区间下相邻边界折叠成同串（`1000000~1000000`），类目轴标签重复不可读 | **confirmed**——正是「调整分箱后显示异常」的根因 |
| H3 | boolean 维度归桶显示英文 true/false（与展示语义是/否不一致） | **confirmed**——独立的显示正确性缺陷 |

反向追溯：H2 的 bad value（塌缩标签）首次引入点在 `chartBoard.ts fmtNum` 的固定精度签名；H3 在 `matrixBoard.axisKeyForRow` 类型分派缺 boolean 分支。均在首次引入帧修复。

## Fix（外科手术式）

1. `chartBoard.ts`：新增 `labelPrecision(width, max)`（整数位数 + 箱宽所需小数位自适应有效数字，下限 6、上限 17），`histogramBins` 边界标签改用该精度。
2. `matrixBoard.ts`：`axisKeyForRow` 补 boolean 分支 → 是/否，空值仍归未分组（chartBoard 与 buildMatrixGrid 共用，单点修复两视图）。

## Verify

- 红→绿→红三步闭环：修复前 3 条红 → 修复后 76 条全绿 → stash 反向证明撤走修复测试回红（46 条不受影响）→ pop 复绿。
- `make check` 本地全绿（lint/typecheck/覆盖率双门槛达标）。

## Defense-in-depth

极端数据不变式测试锚定（Σcount==样本数、from≤to 单调、首箱含 min 末箱含 max），覆盖大量级窄区间/负值混合量级/科学计数法量级跨度/FD 极小非零 IQR 四类场景——同类回归将来直接被不变式抓住。

## 关联

- 设计：`.trae/designs/chart-view.md`（labelPrecision 契约 + boolean 归桶）
- 迭代：`.trae/docs/iter-29-chart-extreme-data.md`
- seed 示例：`examples/datasets/工作区-低质量数据/views.json`（16 个极端图表配置）

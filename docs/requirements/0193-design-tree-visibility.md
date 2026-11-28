# 需求卡片：装配结构树零组件显隐控制（勾选部分显示）

- 编号：0193（S1，方案并入本卡片，无 ADR）
- 状态：P0 + P1 已落地
- 日期：2026-02-17
- 关联 ADR：无（方案并入本卡片）
- 关联模块：设计（`frontend/src/pages/design/`）

## 需求原句

> 设计，装配结构树需要对照同类应用进行功能增强，如勾选部分零组件显示，未勾选的不显示。

## 现状影响面

| # | 现状 | 位置 | 后果 |
|---|---|---|---|
| 1 | 装配结构树（侧栏 + 编辑器大纲）纯只读导航：点击仅定位 / 高亮，无任何「显示 / 隐藏」概念 | `DesignStructureNav.tsx`（Tree 无 checkbox）、`DesignEditorPage.tsx` | 对照 SolidWorks / Onshape / Fusion 等同类 CAD 应用，装配树的标准能力是勾选控制零组件在视口中的显隐，目前缺失 |
| 2 | `ViewportApi` 只有 `highlight(indices)`（3s 渐隐强调），没有持久显隐能力 | `PreviewCanvas.tsx:42-50` | 无法承载「勾选 = 长期隐藏」语义 |
| 3 | 静态网格按 IR 顶层 `nodes` 合并构建，逐 mesh 无归属记录 | `PreviewCanvas.tsx`（`group.add(mesh)`） | 显隐必须按 `node_index` 粒度生效，需要 mesh ↔ node_index 对应关系 |
| 4 | 结构树在两个位置渲染：侧栏 `DesignStructureNav`（Tree）与编辑器内大纲（若共用 `designTree.tsx`） | `designTree.tsx` | 显隐状态若只在一处维护，两棵树会漂移 |

## 约束（C1..Cn）

| # | 需求片段 | 约束 | 落点 | 验证 |
|---|---|---|---|---|
| C1 | 「勾选部分零组件显示，未勾选的不显示」 | 结构树节点带勾选框（`Tree` `checkable`）：**默认全勾 = 全显示**；取消勾选即隐藏该节点及其全部子节点（隐藏 `node_index` 集合按大纲下钻收集）；部分勾选的父节点呈半选态；重新勾选恢复显示 | `DesignStructureNav.tsx`（侧栏树）、`designOutline.ts`（新增 `collectHiddenNodeIndices` 下钻收集） | 单测：取消勾选组件 → 其子零件 index 全部进入隐藏集合；半选态正确 |
| C2 | 「未勾选的不显示」 | 视口按隐藏集合持久显隐：`ViewportApi` 新增 `setVisible(indices, visible)`；`PreviewCanvas` 按 mesh ↔ `node_index` 分组置 `mesh.visible = false`（含 Worker CSG 精确结果与回退路径）；隐藏后包围盒 / fit / 统计按剩余可见网格计算 | `PreviewCanvas.tsx` | 单测 + 编辑器页测试：隐藏集合变化 → 对应 mesh visible 翻转；stats 节点数同步 |
| C3 | （派生）两棵树状态一致 | 显隐状态提升为**编辑器页单一状态**（`Set<string>` 大纲 key），经 props / context 下发侧栏树与视口；侧栏树勾选 → 状态 → 视口生效；反向（未来视口拾取隐藏）也只改这一处。刷新 / 切产品重置为全显 | `DesignEditorPage.tsx`、`DesignStructureNav.tsx`（props 传入 checkedKeys / onCheck） | 单测：侧栏勾选后编辑器视口 `data-hidden-nodes`（可观测通道，仿 0103 高亮通道）同步 |
| C4 | （派生）隐藏态可感知、可恢复 | 侧栏树头或视口工具条提供「全部显示」一键恢复（隐藏集合非空时出现）；状态条在隐藏非空时追加「隐藏 N」读数；勾选状态**会话级记忆**（切走再切回同一产品保留，刷新重置），复用 `usePersistedState` 口径 | `DesignStructureNav.tsx`、`DesignEditorPage.tsx` | 单测：勾选 → 切产品 → 切回，勾选保留；「全部显示」点击后集合清空、mesh 全亮 |
| C5 | （测试约束） | 同轮补：`designOutline` 纯函数用例（隐藏集合下钻 / 半选判定）、`PreviewCanvas.test.ts`（visible 翻转 / stats）、`DesignStructureNav.test.tsx`（checkbox 渲染 / onCheck 回调 / 全部显示）、`DesignEditorPage.test.tsx`（状态贯通：勾选 → `data-hidden-nodes`） | 测试文件 | `make check-frontend` / `make e2e-affected` |

## 分期

| 期 | 内容 |
|---|---|
| P0 | C1 + C2 + C3：勾选显隐主链路（树 checkbox → 状态 → 视口 mesh visible） |
| P1 | C4：全部显示入口 + 隐藏读数 + 会话级记忆 |

## 未决问题（实现前澄清）

1. 隐藏粒度：按大纲节点（系统 / 组件 / 分组 / 零件均可勾选）实现——与 CAD 惯例一致，P0 即支持任意层级勾选。
2. `difference` 布尔分组隐藏一个子件时 CSG 语义（父 group 结果仍按剩余子件求值）与视觉预期可能有出入：P0 按「隐藏 = 该子 mesh 不参与显示」处理，视觉异常留待反馈再定语义（不做布尔重算）。

## 人工确认

- [x] 需求与 C1..C5 确认（会话 2026-02-17「开始」）

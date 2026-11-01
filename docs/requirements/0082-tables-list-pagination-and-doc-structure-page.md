# 需求卡片：数据表列表分页与文档结构二级页

- 编号：0082
- 来源 / 提出人：用户（工作区导航逻辑优化）
- 日期：2026-11-01
- 关联 ADR：无（S1 常规功能：前端列表分页 + 一个只读文档结构页，无数据模型 / 权限 / 架构分叉）

> 本卡片是**需求原文与约束编号的唯一副本**：无 ADR，实现与测试直接对照 C1..Cn。

## 需求原句（逐字）

> 工作区导航逻辑优化，数据表一级功能模块下，缺少用于显示数据表列表的分页。文档也缺少二级导航页用于导航到文档结构。

需求澄清结论（用户已确认，二轮更正）：
1. 「分页」= 在数据表列表页增加分页组件；
2. 「文档结构」= 既有文档总览列表页（/w/:wid/documents）的别称，**不新建页面**，只需补二级页签导航入口。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「数据表一级功能模块下……数据表列表的分页」 | 数据表列表页（TablesList）桌面端表格增加分页：底部 Pagination 组件（客户端分页），含页码、每页条数切换（默认 50，可选 10/20/50/100）、总数展示；翻页/改页大保留当前筛选档位；列表为空或不足一页时分页器不渲染（与总数文案并存不冲突） | `frontend/src/pages/workspace/TablesList.tsx` | `TablesList.test.tsx` 新增分页用例 |
| C2 | 「……显示数据表列表的分页」 | 窄屏卡片列表同样受分页控制（共用同一 current/pageSize 状态）；拖拽排序在分页态下仍按全量序列提交（跨页拖拽不属于本期范围，仅当前页内可见行参与） | `frontend/src/pages/workspace/TablesList.tsx` | 单测：改 pageSize 后卡片数量变化 |
| C3 | 「文档缺少二级导航页用于导航到文档结构」 | MainLayout 文档区二级页签（documents-crumb 的 DOCUMENT_SUBPAGES）新增「文档结构」项，指向既有文档总览列表页 `/w/:wid/documents`（不新建页面、不新增路由），位置在修改申请 / 问题清单之前；落在 `/w/:wid/documents`（无子段）时该页签激活，编辑器与子页不激活；帮助文档「工作区二级页签」相关文案同步 | `frontend/src/layouts/MainLayout.tsx`、`frontend/src/pages/help/content/*` | `MainLayout.test.tsx` 新增用例；帮助内容层级测试回归 |
| C4 | 配套回归 | CHANGELOG 记录；既有 e2e `navigation.spec.ts` 补文档结构页签断言 | `CHANGELOG.md`、`frontend/tests/e2e/critical/navigation.spec.ts` | `make flow` + `make e2e` |

## 现状影响面（候选，已核实）

| # | 现有能力 | 位置 | 备注 |
|---|---|---|---|
| 1 | TablesList 表格 `pagination={false}` 全量平铺 | `frontend/src/pages/workspace/TablesList.tsx:717` | C1 改造点 |
| 2 | 文档区二级页签仅 修改申请 / 问题清单 | `frontend/src/layouts/MainLayout.tsx:56-59` | C4 改造点 |
| 3 | 侧栏文档树已用 tree 端点 + buildDocTree | `frontend/src/layouts/MainLayout.tsx:196-224` | C3 页面复用同源口径 |

## 未决问题

- [x] 「分页」与「文档结构」的形态 → 用户已确认（见澄清结论）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

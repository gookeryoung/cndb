# 需求卡片：修改申请 UI 对齐质量检查（列表 / 详情 / 冲突处理）

- 编号：0108（与 ADR `docs/adr/0108-*.md` 同号；S1 项不写 ADR，方案见「口径」节）
- 来源 / 提出人：用户
- 日期：2026-11-06
- 关联 ADR：无（S1）

> 本卡片是**需求原文与约束编号的唯一副本**：如后续升级 S2 写 ADR，ADR 只引用 C1..Cn，不复制原文。

## 需求原句（逐字）

> 修改申请UI布局和STYLE，参考质量检查进行重新设计。包括详情页也要参考质量检查运行历史详情页的设计风格。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 参考质量检查进行重新设计 | 列表页根容器改为 `cn-page` + `cn-page-head` 紧凑页头（`PullRequestOutlined` 图标、标题「修改申请」、按模式切换的口径副标题、scope / 视图 `Segmented` 与「新建修改申请」主按钮）；通过 `SectionBox` 方盒 + `.cn-qc-row` 行态组织内容，不再使用 Card / 手写 padding | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx` | 前端单测（`change-requests-page` / 页头标题 / 双栏 testId） |
| C2 | 参考质量检查进行重新设计 | 工作区级（无 `:tid`）沿用需求 0107 的左右分栏口径并改为质量检查式双栏：左 `SectionBox`「涉及的工作表」（计数徽标 + `role=listbox/option` 选中态），右 `SectionBox`「修改项」（单行申请行 + 展开 caret）；展开懒加载详情、字段级 diff 与当前行上下文的能力与只读口径不变 | 同上 | 前端单测（分组 / 默认选中 / 切换 / 展开 diff / 返回导航） |
| C3 | 参考质量检查进行重新设计 | 单表视图同行合并改为左右双栏：左「行分组」（`行 #id` + 行值预览 + 申请数徽标 + 冲突 / 漂移 / 行已删除标签 + 底部「新增行申请」），右为选中分组的申请清单与批量审批按钮；默认选中首个可用分组，选中项失效时自动回落；平铺视图改为全宽 `SectionBox` | 同上 | 前端单测（组顺序 / 切换 / 批量审批 / 冲突跳转 / 平铺切换） |
| C4 | 详情页也要参考质量检查运行历史详情页的设计风格 | 详情页根容器 `cn-page cn-qc-run-page`：页头（申请标题 + 状态 / 基准过期 / `#id · 提交人 提交于 时间` + 返回 / 刷新基准 / 关闭 / 重开）、运行式告警叠放（基准过期 / 漂移字段 / 目标行已删除）、`cn-qc-run-summary` 6 格概要条（变更项 / 新增 / 修改 / 删除 / 漂移字段 / 讨论） | `frontend/src/pages/changeRequests/ChangeRequestDetailPage.tsx` | 前端单测（`cr-summary` / 页头 heading / 双栏 testId） |
| C5 | 详情页也要参考质量检查运行历史详情页的设计风格 | 详情页双栏 `cn-cr-detail-split`（左宽右窄）：左 `SectionBox`「变更项」（操作类型徽标 + 行号 + 字段摘要 / 整行删除 + 漂移提示 + 逐项 apply/skip `Segmented` + `FieldDiffTable`），右纵向「审批」（合并备注 + 执行合并；非 open 展示处理人 / 处理时间 / 处理备注；viewer 不渲染合并按钮）与「讨论与动态」（动作流水 + 评论输入） | 同上 | 前端单测（既有合并 / 跳过 / 门控 / 刷新基准 / 评论用例保持） |
| C6 | 修改申请UI布局和STYLE | 冲突处理页改为 `cn-page` 页头（行号 + 待合并申请数 / 冲突字段数 + 返回）+ 左「当前行值」/「待合并申请」、右「冲突字段裁决」/「自动应用字段」/「行级操作裁决」/「合并备注与提交」双栏方盒；裁决、delete 互斥、校验与载荷逻辑不变 | `frontend/src/pages/changeRequests/ChangeRequestRowMergePage.tsx` | 前端单测（裁决 / 载荷 / 互斥用例保持 + 骨架断言） |
| C7 | 参考质量检查进行重新设计 | 样式层删除旧 `.cn-cr-split*` / `.cn-cr-side-*` 块，复用 `.cn-qc-split` / `.cn-qc-row` / `.cn-qc-run-summary` / `.cn-qc-run-stat` / `.cn-qc-empty`；新增 `.cn-cr-*` 专属类全部走 `--cn-*` token，不写裸间距 / 字号 / 颜色；断点只用 `1023.98px` / `767.98px`（详情双栏与列表双栏、行 meta 在窄屏纵向堆叠） | `frontend/src/index.css`、`docs/DESIGN_SYSTEM.md` | 样式审阅 + 前端全量测试 |

## 口径（S1 方案，无 ADR）

- 纯前端改动：不改 `frontend/src/api` 类型、不改后端端点 / 数据模型 / 权限口径；审批、合并、评论、刷新基准、批量审批与冲突裁决逻辑全部保留。
- 概要条 6 格按现有响应派生：变更项数、create / update / delete 计数、`field_conflicts` 去重字段数、actions 条数；无接口新增字段。
- 保留测试与用户路径依赖的全部文案 / role / placeholder / 按钮名（如「批量审批」「执行合并」「写下评论…」「执行批量合并」「请先裁决冲突字段」）。
- 单表视图与详情页的布局选择已与需求方确认：单表同行合并改左右双栏；详情页右栏放「审批 + 讨论动态」。
- 不自动提交、不自动 push；实现与门禁全绿后由需求方确认提交。

## 现状影响面（候选，已粗查）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区级 / 单表列表布局 | `frontend/src/pages/changeRequests/ChangeRequestsPage.tsx` | 本次重构对象；查询与批量审批逻辑保留 |
| 2 | 详情页布局 | `frontend/src/pages/changeRequests/ChangeRequestDetailPage.tsx` | 本次重构对象；mutation 与门控保留 |
| 3 | 冲突处理页布局 | `frontend/src/pages/changeRequests/ChangeRequestRowMergePage.tsx` | 本次重构对象；裁决与载荷保留 |
| 4 | 修改申请样式块 | `frontend/src/index.css`（旧 `.cn-cr-*` 块） | 旧双栏 / 上下文类替换为 QC 原语 + 新 `.cn-cr-*` 文案排版类 |
| 5 | 三个页面单测 | `frontend/src/pages/changeRequests/*.test.tsx` | 同行合并用例改写为双栏口径；新增骨架断言 |
| 6 | 设计系统文档 | `docs/DESIGN_SYSTEM.md`（工作台原语表） | 补修改申请类名与复用说明 |

## 未决问题

- [x] Q1 单表视图（同行合并）布局：改为左右双栏（左行分组 / 右选中组申请）（2026-11-06 需求方确认）
- [x] Q2 详情页右栏内容：审批 + 讨论动态（2026-11-06 需求方确认）
- [x] Q3 概要条口径：6 格按现有字段派生，不新增接口字段（2026-11-06 需求方确认）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

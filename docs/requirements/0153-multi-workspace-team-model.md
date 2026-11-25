# 需求卡片：多工作区统一管理（团队层 + 工作区权限边界）

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0153（与 ADR `docs/adr/0153-multi-workspace-team-model.md` 同号）
- 来源 / 提出人：产品负责人（会话提出 + 五问确认）
- 日期：2026-11-25
- 关联 ADR：[ADR 0153](../adr/0153-multi-workspace-team-model.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请结合最佳实践，对多个工作区的管理给出推荐思路，包括但不限于父工作区-子工作区架构（工作区内实现权限分配）等，请给出方案。

五问确认（逐字）：

> 1团队下工作区维持列表，不需要树；2部门单层架构，保持扁平；3默认看不到；4默认一对一，可考虑引用设计，但是权限只有拥有团队有；5按建议

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「团队下工作区维持列表，不需要树」 | 团队↔工作区为平铺集合关系：团队页按列表分组展示工作区，无树展开 / 拖拽层级；API 返回平铺数组 | `workspaces` 插件 + `frontend/src/pages/workspace/` | 接口测试断言平铺载荷；前端单测断言无树结构 |
| C2 | 「部门单层架构，保持扁平」 | 团队表**不含** `parent_team_id`，不支持团队嵌套；权限解析不做向上遍历 | `workspaces/models.py` | 迁移测试断言无该列；判定层单测断言解析路径深度固定为 2 层 |
| C3 | 「默认看不到」 | 团队管理员（`team_admin` / `team_owner`）默认**不获得数据面权限**：读数据、导出、下载附件一律按工作区角色判定，非成员即 404 | `workspaces/permissions.py` | 接口测试：team_admin 非工作区成员 → `GET /workspaces/{wid}` 403/404、`GET /tables` 404 |
| C4 | 「默认一对一」 | `Workspace.team_id` 单值可空（空 = 个人工作区），不提供多团队归属（无关联表、无数组列） | `workspaces/models.py` + 迁移 | 迁移测试 + 接口测试（重复挂载直接覆盖或 400，不存在第二归属） |
| C5 | 「可考虑引用设计，但是权限只有拥有团队有」 | 设计复用模块库新增 `visibility=team`：仅拥有工作区（发布方）所属**团队成员**可检索 / 引用；`public` 与 `workspace` 口径不变；归档仍只阻断新引用 | `design` 插件（ADR 0118 扩展） | 判定层单测 + 接口测试：同团队成员可见、跨团队 404 |
| C6 | 「5按建议」 | 不引入父-子工作区（`parent_workspace_id`）；本期不实现跨工作区数据读取（汇总 / 链接工作区留 P3 另立 ADR） | 全局 | ADR 决策记录 D1 / D11；评审确认 |
| C7 | 「多个工作区的管理」 | 新增团队层：团队 CRUD、团队成员、团队内工作区列表、团队策略（默认工作区角色 / 模块 allowlist），提供统一管理入口 | `workspaces` 插件 + 前端团队页 | 接口测试 + 前端单测 + e2e |
| C8 | 「工作区内实现权限分配」 | 工作区内权限分配口径不变（owner/editor/viewer 三档 + 表 `Role` + 视图三档 + 行级规则 + 文档权限），只把判定收敛为单一入口并加「能力位」映射 | `workspaces`、`tables`、`documents` | 判定层单测：迁移前后逐用户逐工作区结果一致（I3） |
| C9 | 隐含：不能让管理员变成「全能可见」 | 团队管理面与工作区数据面分离；工作区 `visibility` 三档真正参与判定（现为死字段） | `workspaces/permissions.py` | 判定层单测覆盖 3 档 × 成员态 × 团队角色 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 工作区扁平列表（pinned + tags + 两分组） | `frontend/src/pages/workspace/WorkspaceList.tsx:190` | 需增加「团队 → 工作区」分组层 |
| 2 | 成员角色判定散落 | `src/cndb/plugins/workspaces/permissions.py:31`、`src/cndb/plugins/workspaces/routers/deps.py:20` | 需收敛为 `resolve_capabilities` 唯一入口 |
| 3 | `Workspace.visibility` 三档未参与任何判定 | `src/cndb/plugins/workspaces/models.py:137`、`routers/deps.py:20` | 死字段，需给出启用口径 |
| 4 | 工作区列表 10s 缓存按用户隔离 | `src/cndb/plugins/workspaces/routers/workspaces.py:76` | 团队成员 / 策略变更需扩维度失效 |
| 5 | 设计复用模块库 `public/workspace` 两档 | `src/cndb/plugins/design/models.py:36`、`design/routers.py:824` | 需新增 `team` 档 |
| 6 | 工作区备份自包含（v9-v16） | `src/cndb/plugins/workspaces/services/backup_io.py` | 团队不随备份往返，需在 ADR 定死 |
| 7 | 存储配额按工作区 | `workspaces/models.py:170`、`services/storage_snapshot.py` | 团队层只做默认值下发（P2） |
| 8 | 403 文案依赖「一个工作区一个拥有者」 | `workspaces/permissions.py:74` | 需补团队角色分支 |

## 未决问题

- [x] 是否需要树形层级 → **否**：团队与工作区均为平铺列表（C1 / C2）
- [x] 团队管理员是否可看数据 → **否**，默认看不到（C3）
- [x] 工作区是否可属多个团队 → **否**，一对一可空（C4）
- [x] 跨工作区是否共享数据 → **否**，仅设计模块库按团队共享引用（C5 / C6）
- [ ] 待人工确认：本方案新增的不变量 I1-I8 是否登记进 `docs/CONSTRAINTS.md`（H27，需方案评审拍板）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论（剩 1 条：H 条目登记由人工方案评审确认）

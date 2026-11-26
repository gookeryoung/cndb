# 0176 文档级 ACL（S1，需 ADR）

- 编号：0176
- 来源 / 提出人：用户（会话 2026-11-26「进批次 2，先写正文批注和文档级 ACL 两份 ADR」）
- 日期：2026-11-26
- 关联 ADR：`docs/adr/0176-document-level-acl.md`（Proposed）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改 ADR 与代码。

## 需求原句（逐字）

> 进批次 2，先写正文批注和文档级 ACL 两份 ADR。

（批次 2 在 `BACKLOG.md` 中定义为「0176 文档级 ACL（按人 / 角色的文档级覆盖，重建
`documents_permission`）」。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 文档级覆盖 | 每篇文档可选 `acl_mode = inherit`（默认，沿用现状）或 `restricted`（仅授权主体可读）；`restricted` 下按「用户 / 工作区角色」授权读取 | `documents` 插件 | 单测：restricted 文档未授权成员读 404 |
| C2 | 只收紧读、不放大写 | ACL 只授 READ；写权限仍由 `resolve_write_mode` 决定，任何 ACL 条目不得把 viewer 提升为可写 | 判定层 | 单测：授权 READ 的 viewer 仍走修改申请 |
| C3 | 管理员与创建者 | 超管 / 工作区 OWNER 恒可读全量文档；文档创建者对自己创建的文档恒可读（即使 restricted 未列名） | 判定层 | 单测：owner/创建者不受 restricted 限制 |
| C4 | 单一判定（H64） | 新增 `resolve_document_access` 作为文档读 / 写的唯一入口；列表 / 树 / 检索 / 图谱 / 反链 / 导出 / 版本等读路径统一按其 SQL 条件过滤 | 服务层 | 单测：各读路径对 restricted 文档结果一致 |
| C5 | 私有工作区（H66） | `visibility=private` 的非 owner 数据面恒为空，ACL 不得把任何主体放进来 | 判定层 | 单测：private + ACL 授权仍 404 |
| C6 | 管理入口 | 修改 ACL 需 owner 或（editor + 文档创建者）；viewer 403；跨工作区 404 | API 单测 | 单测：越权 403 / 跨区 404 |
| C7 | 分享链接 | 既有游客分享 token 是显式能力凭据，ACL 不回收已发出的链接；新建 / 停用分享沿用现有 editor+ 门槛 | 分享 | 单测：restricted 文档的既有 share token 仍可读（风险在 ADR 记录） |
| C8 | 生命周期 | ACL 随文档软删 / 恢复 / 跨区移动处理：软删保留；跨区移动丢弃目标工作区不存在的用户主体并记 warning；备份含 ACL 并支持旧包缺键 | 备份 / 移动 | 单测：移动后主体过滤、备份往返 |
| C9 | 审计 | ACL 变更写 `document.acl_update` 事件（复用 0173），只记主体计数与模式，不记用户名单明细 | 事件 | 单测：事件不含名单 |
| C10 | 前端 | 文档抽屉新增「权限」页：模式切换、用户 / 角色授权列表；列表对 restricted 文档显示「受限」图标（图标优先，颜色辅助） | 前端 | 组件测试 |
| C11 | 测试与文档 | 后端 + 前端单测、迁移、CHANGELOG；ADR 决策表无「待定」 | 测试 / 文档 | 定向测试全绿 |

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 文档可见性只有状态维度 | `visibility.py:43,59,125` | 无 per-doc 主体概念 |
| 2 | 工作区数据面单一判定（H64） | `permissions.py:207` | ACL 必须在其之上叠加，不得旁路 |
| 3 | 表级权限先例 | `tables/models.py:466`（`read_role`）、`tables/services/core/access.py` | 可借鉴「角色门槛」表达，但不引入行级 |
| 4 | 历史文档权限表已删 | 迁移 `2c3d4e5f6a70` | 重建需新表，不复用旧表名 |
| 5 | 私有工作区（H66） | `permissions.py:236`、`visibility.py:46` | ACL 不得放宽私有工作区 |
| 6 | 分享 token | `models.py:210-221` | 显式能力凭据，与 ACL 并行 |
| 7 | 跨区移动 | `move.py:264` | ACL 主体需按目标工作区成员过滤 |
| 8 | 备份 / 恢复 | `backup_io.py:587`、`workspace_backup.py` | 新表纳入往返与旧包兼容 |
| 9 | 检索 / 图谱 / 反链 | `content.py:794`、`search.py` | 读路径需统一接入 ACL 条件 |
| 10 | 超管 / OWNER 全量 | `visibility.py:46` | 必须显式绕过 ACL |

## 未决问题

- [x] 是否支持「拒绝」条目（2026-11-26 结论）：不支持。只用「受限 + 白名单」，避免 allow/deny 优先级歧义。
- [x] 是否允许 ACL 放大写权限（2026-11-26 结论）：不允许。ACL 只授 READ，写权限仍走工作区双轨制。
- [x] 游客分享是否受 ACL 约束（2026-11-26 结论）：不回收已发出 token（capability 语义）；新建分享仍按 editor+，风险在 ADR 记录。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题有结论

## 落地结果

（实现后回填）

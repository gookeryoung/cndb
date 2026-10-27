# ADR 0047: 权限不足错误提示增强（角色 + 拥有者联系指引）

Status: Accepted（已评审，2026-10-27）
Date: 2026-10-27
Related: `src/cndb/core/errors.py`、`src/cndb/plugins/tables/services/core/access.py`、`src/cndb/plugins/tables/services/core/view_access.py`、`src/cndb/plugins/workspaces/permissions.py`、`docs/adr/0003-view-visibility-permission-model.md`
需求卡片: `docs/requirements/0047-permission-denied-message.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「权限不足等情况……给出更详细的说明」 | 新增统一文案构造入口 `permission_denied_detail()`（见 Decision §2），所有**工作区维度**的 403 拒绝点改走该入口；detail 必含角色说明与被拒层级（工作区级/表级/视图级） |
| C2 | 「向工作区拥有者【...】申请权限」 | 构造入口内部查询工作区拥有者展示名（nickname 回退 username），拼接「如需提升权限，请联系工作区拥有者【xxx】」；拥有者不可得时省略联系人片段 |
| C3 | 「如【...查看者...】」 | 角色中文标签统一表 `WORKSPACE_ROLE_LABELS` 落在 `workspaces/models.py`（owner=所有者、editor=编辑者、viewer=查看者），help figures 与本 ADR 共用同一标签口径 |
| C4 | 「提升用户体验」 | 响应体形状保持 `{detail, code}` 不变，前端零改造（detail 原样透出）；无登录态/公开分享路径不接本入口 |
| C5 | 「分析并处理此类问题」 | 只改文案不改任何权限判定；404「不存在」与 403 的存在性区分语义不变（ADR 0003 口径维持） |

## Context

现状逐条核对（以代码为准）。沿用卡片「现状影响面」编号，结论补 `文件:行号`：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 工作区角色门槛 403 detail=「权限不足」，函数内已有 `role` 可用但未输出 | `src/cndb/plugins/tables/services/core/access.py:232` | 用户不知道自己是什么角色 | 确认 |
| 2 | 表级动作 403 detail=「表级权限不足」，文案在 5 处重复散落 | `access.py:268`、`src/cndb/plugins/tables/routers/records.py:65,303,332`、`src/cndb/plugins/tables/routers/bulk_crud.py:97` | 无角色/联系指引 | 确认 |
| 3 | 视图权限 403 detail=`FORBIDDEN_DETAIL`=「视图权限不足」 | `src/cndb/plugins/tables/services/core/view_access.py:56,237` | 同上 | 确认 |
| 4 | 文档侧拒绝点：require editor 与「非工作区成员」 | `src/cndb/plugins/documents/services/content.py:133-136`、`documents/services/change_requests.py:59,67`、`documents/routers/documents.py:115,435`、`documents/routers/vault.py:58`、`documents/routers/tags.py:38`、`documents/services/issues.py:48` | 「非工作区成员」无申请加入指引 | 确认 |
| 5 | 工作区管理类 403（仅所有者可…）已含部分角色语义但无联系人 | `src/cndb/plugins/workspaces/routers/deps.py:27`、`workspaces/routers/member_routes.py:133,174,215`、`workspaces/routers/workspaces.py:291,352,688` | 初级用户不知道找谁 | 确认 |
| 6 | 申请审核 / 表成员管理 / issues 类 403 已含角色语义（「仅 owner/editor…」） | `src/cndb/plugins/change_requests/services.py:370,396,433,714`、`change_requests/routers/change_requests.py:165`、`src/cndb/plugins/tables/routers/members.py:44,46,290`、`src/cndb/plugins/issues/routers/issues.py:118`、`documents/routers/issues.py:97`、`documents/services/change_requests.py:362,382,403` | 缺拥有者联系人 | 确认 |
| 7 | 系统级/账户级 403 与工作区角色无关（超管、审计、分享密码、账号停用） | `src/cndb/core/events_api.py:27`、`src/cndb/core/system_api.py:42`、`src/cndb/plugins/accounts/routers/users.py:59,70,72`、`workspaces/routers/roles.py:33`、`accounts/routers/auth.py:80,171`、`documents/routers/public.py:105,126` | 不属工作区角色体系 | 排除 |
| 8 | 统一异常体系已有 `PermissionDeniedError`（403 + `permission_denied` 错误码） | `src/cndb/core/errors.py:74-78` | 服务层抛出路径统一走它，可复用 | 确认 |
| 9 | 前端 detail 归一化已支持字符串 detail 原样透出 | `frontend/src/api/client.ts:159-168` | 零改造可行 | 确认 |
| 10 | 角色中文标签已有两处口径：help figures `_ROLE_LABELS`、成员授权标签 | `src/cndb/plugins/help/services/figures/builders.py:44`、`src/cndb/plugins/tables/services/core/row_access.py:49` | 需收敛到单一来源避免漂移 | 确认 |
| 11 | 拥有者展示名已有现成查询模式（owner_member join User） | `src/cndb/plugins/workspaces/routers/workspaces.py:241-242`、`workspaces/permissions.py:15` | 可抽公共查询 | 确认 |

**核心缺陷（需求要补的）**：403 响应只说「不足」，不说「你是谁（角色）」「缺什么（层级）」「找谁（拥有者）」，初级用户无从自助处理。

设计目标（不变量）：

- **I1 判定不变**：本设计只改 403 的 `detail` 文案，`check_action` / `check_workspace_permission` / `view_access` 的判定链与返回值（404/403 区分、存在性不泄露）零变化（对应 C5、卡片 Q4）。
- **I2 响应契约不变**：错误响应体保持 `{"detail": ..., "code": ...}`（`core/errors.py:11-13` 约定），不新增字段（卡片 Q1 结论）。
- **I3 标签单一来源**：工作区角色中文标签只在 `workspaces/models.py` 定义一处，其余引用（help figures、本入口）不重复字面量。
- **I4 覆盖收敛**：工作区维度的全部 403 点位（Context #1-#6）统一走同一构造入口；系统级点位（#7）明确排除。

## Decision

### 1. 数据模型

无（零迁移、零新表新列）。

### 2. 判定算法（唯一入口）

新增文案构造入口（放 `src/cndb/plugins/workspaces/permissions.py`，避免反向依赖）：

```python
WORKSPACE_ROLE_LABELS = {"owner": "所有者", "editor": "编辑者", "viewer": "查看者"}


def get_workspace_owner_display_name(db, workspace) -> str | None:
    """工作区拥有者展示名：nickname 回退 username；无 owner 成员返回 None。"""


def permission_denied_detail(
    db,
    workspace,
    user,
    *,
    scope: str,
    requirement: str = "",
) -> str:
    """构造 403 detail 文案（唯一出口）。

    scope: "工作区级" | "表级" | "视图级" | "文档"（缺失层级语义时传空串）
    requirement: 额外要求描述，如 "仅 owner/editor 可合并修改申请"
    """
```

文案模板（成员 / 非成员两分支，对应卡片 Q2）：

- 成员：`当前用户在此工作区的角色为【{label}】，{scope}权限不足；如需提升权限，请联系工作区拥有者【{owner}】`，`requirement` 非空时追加 `（{requirement}）`。
- 非成员（role=None）：`你不是该工作区成员，{scope}权限不足；如需加入，请联系工作区拥有者【{owner}】`。
- 拥有者不可得：省略「，请联系…【{owner}】」片段，其余不变。

配套便捷函数 `raise_permission_denied(db, workspace, user, *, scope, requirement, code=...) -> NoReturn` 直接抛 `PermissionDeniedError`；现有 `HTTPException(403)` 调用点改为抛该入口（服务层统一异常体系，`I2` 由 `PermissionDeniedError.to_payload` 保证）。

### 3. API 变更清单

无新增/修改端点；仅既有 403 响应的 `detail` 文案变化。受影响端点为 Context #1-#6 各调用点的所属路由（表记录读写、视图访问、文档读写、工作区成员管理、修改申请、issues 等），不改路径、不改状态码。

### 4. 边界与例外

1. 系统级 / 账户级 / 分享密码 403（Context #7）不走本入口，文案维持现状。
2. 公开分享（无登录态）路径不接本入口，避免向游客暴露拥有者信息。
3. `row_filters_bypass`、`hidden_fields`、`check_action` 优先级链逻辑不动；仅 `get_table_or_404`、`check_workspace_permission` 等抛错点换文案。
4. 文档「修改申请」双轨 202 分流是正常业务流，不产生 403，排除在外（卡片 Q4）。
5. help figures 的角色标签（`builders.py:44` 含英文后缀「所有者 owner」）改为引用同一标签来源但保留其展示格式，仅字面量来源收敛。

### 5. 迁移

无（纯文案层改动，存量零迁移）。

### 6. 前端

| 层 | 文件 | 改动 |
|---|---|---|
| API 封装 | `frontend/src/api/client.ts` | 无改动（detail 原样透出，回归验证） |
| 帮助文档 | `frontend/src/pages/help/content/troubleshooting.tsx` | 「看不到某张表 / 按钮无权限」条目补充新文案示例与处理步骤（找拥有者提权） |

### 7. 测试清单

**判定层（单测）**：`tests/test_permission_denied_message.py`

- 成员各角色（owner/editor/viewer）文案含正确角色标签与拥有者名；
- 非成员（role=None）文案为「申请加入」分支；
- 拥有者缺失降级文案；nickname 空 → username 回退；
- `requirement` / `scope` 拼接边界（空串不追加括号）。

**接口层**：

- 现有权限测试中精确断言旧 detail 的用例同步更新（`tests/test_tables_*.py`、`tests/test_row_permissions_api.py`、`tests/test_view_access_p0.py`、`tests/test_documents_*`、`tests/test_permission_workflow_scenario.py` 等，以 `grep -rn "权限不足\|非工作区成员" tests/` 实测清单为准）；
- `tests/test_error_contract.py` 补断言：403 响应体仍是 `{detail, code}`。

**迁移 / 备份**：无。

**e2e（前端）**：现有权限相关 spec 不回归（文案断言如有需同步）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | 标签单一来源 + `permission_denied_detail` / `raise_permission_denied` 入口 + 工作区级与表级 403 接入（Context #1、#2）+ 单测 | 低 |
| **P1** | 视图级、文档侧、工作区管理类、申请审核 / issues / 表成员类点位接入（Context #3-#6）+ 旧文案测试回填 | 中（点位多，逐个过） |
| **P2** | 帮助文档 troubleshooting 补条目 + 前端回归 + `make flow` 全绿 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案选型：403 增强采用纯文案 vs 结构化字段 | **纯文案**：`{detail, code}` 形状不变，角色与拥有者拼进 detail | 前端零改造、错误契约（`core/errors.py:11-13`）不动、风险最小 | 结构化字段（需改错误契约 + 前端适配，收益当前用不上） | `src/cndb/plugins/workspaces/permissions.py` |
| D2 | 非成员被拒文案 | 「你不是该工作区成员，…如需加入，请联系工作区拥有者【xxx】」，与成员模板区分 | 需求方确认（卡片 Q2） | 统一同一模板（不区分会让非成员误以为自己角色低） | 同上 |
| D3 | 覆盖范围 | 工作区维度**全部** 403 点位收敛（Context #1-#6）；系统级/分享/账户级排除 | 需求方确认；存在性与安全性边界（公开路径不暴露拥有者） | 仅表级+工作区级（留散落点位会继续漂移） | 同上 + 各调用点 |
| D4 | 角色标签来源 | `WORKSPACE_ROLE_LABELS` 落 `workspaces/models.py` 单一来源，help figures 引用它 | 现有 `builders.py:44`、`row_access.py:49` 两处字面量易漂移（I3） | 各点位就地写字符串 | `workspaces/models.py`、`help/services/figures/builders.py` |
| D5 | 入口归属与形态 | `permission_denied_detail` + `raise_permission_denied` 放 `workspaces/permissions.py`；调用点从裸 `HTTPException(403)` 改抛统一异常 | 该模块已是角色判定公共层、无反向依赖；统一异常体系已有 `PermissionDeniedError` | 放 `core/errors.py`（会引入 DB 依赖）；只加 helper 不换异常类型（散落 HTTPException 继续存在） | `workspaces/permissions.py`、`core/errors.py` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：初级用户可从 403 文案直接获知角色、层级与提权对象；403 文案单一出口，后续演进（如结构化）只改一处。
- **负向**：403 路径多一次拥有者查询（单行 join，开销可忽略）；涉及点位多，P1 改动面较宽。
- **风险与缓解**：旧文案被测试/e2e 精确断言 → 以 grep 实测清单逐一回填；公开路径泄拥有者 → 边界第 2 条排除。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 与既有 ADR 的关系（可选）

| 轴 | 载体 | 决定 | 由谁 |
|---|---|---|---|
| 404/403 存在性区分 | 视图/表访问判定 | 维持「看不到按不存在」口径，本 ADR 不触碰 | ADR 0003 |
| 统一错误契约 | `{detail, code}` 响应体 | 形状不变，detail 文案增强 | 本 ADR |

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/permissions.py`、`src/cndb/plugins/tables/services/core/access.py`、`src/cndb/plugins/accounts/services/preferences.py`、`src/cndb/plugins/documents/services/export/table_refs.py` | `tests/test_permission_denied_message.py`、`tests/test_access_audit.py` | `68bc0031` |
| P1 | 未开始 | Context #3-#6 各点位 | 同上 + 既有权限测试回填 | — |
| P2 | 未开始 | `frontend/src/pages/help/content/troubleshooting.tsx` | 既有 e2e 回归 | — |

> P0 附注：`preferences.py` 与 `table_refs.py` 的降级捕获由 `except HTTPException` 放宽为 `except (HTTPException, CndbError)`，适配表级 403 改抛统一异常。

## 交接（会话结束更新）

- 当前阶段：P0 已落地，待提交；P1 未开始
- 已完成：P0（标签单一来源 + 构造入口 + 工作区级/表级 403 接入 + 单测 + 两处降级捕获放宽）
- 下一步：提交 P0（仅本 ADR 相关文件）；P1 按 Context #3-#6 点位逐个接入并回填旧文案断言
- 已知坑：工作区另有未提交 WIP（`tables/services/core/records.py`、`workspaces/services/stats_cache.py`、`record_counts.py` 等）导致 `make check-fast` typecheck 报 3 个错误、全量测试 2 个失败（`test_filter_sort_api` / `test_cov_routers_edge`），均与本 ADR 无关；P1 时注意 `get_view_or_404` 仍抛 HTTPException
- 最近一次全绿：P0 相关 95 用例通过；`make test` 全量 5541 通过 / 2 失败（均为上述无关 WIP）

# ADR 0160: 主页待办聚合端点（`GET /api/v1/home/summary`）

Status: Proposed（待评审）
Date: 2026-11-27
Related: `src/cndb/plugins/workspaces/routers/workspaces.py`、`src/cndb/plugins/change_requests/models.py`、`src/cndb/plugins/issues/models.py`、`src/cndb/plugins/workspaces/models.py`、`src/cndb/plugins/workspaces/services/links.py`、`src/cndb/core/cache.py`、`frontend/src/components/HomeNav.tsx`、`docs/CONSTRAINTS.md`
需求卡片: `docs/requirements/0160-home-navigation-layout.md`（需求原文与约束编号的唯一副本）

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用编号 C1..Cn，本表只补「设计怎么落地」：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C8 | `GET /api/v1/home/summary` 只读；逐工作区同权过滤，无读权计 0 且不暴露存在性；载荷不含提示词 / 密钥 / 行数据；按用户隔离，缓存 TTL ≤ 30s | 独立只读路由 `plugins/workspaces/routers/home.py`；逐工作区复用各插件的既有判定（`require_capability` / 成员行 / 模块开关），不可读即计 0 且不返回该工作区；载荷只有计数与 `partial` 标记；进程内缓存 key 含 `user_id`、TTL 20s、写路径失效 |
| C1 | 主页导航 rail 的「待办」入口 | 前端 `HomeNav`（A′ 口径：只有新建 / 最近访问 / 全部工作区）在「全部工作区」条目右侧渲染待办总数徽标；rail 不可折叠，无需折叠态分支 |

## Context

现状逐条核对（以代码为准）：

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 待办只有**工作区内**接口：修改申请按表列（`/workspaces/{wid}/tables/{tid}/change-requests`）、问题按表列（`/workspaces/{wid}/tables/{tid}/issues`）、链接审批按工作区列（`/workspaces/{wid}/links/inbox`） | `src/cndb/plugins/change_requests/routers/requests.py`、`src/cndb/plugins/issues/routers/issues.py:70`、`src/cndb/plugins/workspaces/routers/links.py:325` | 主页要显示「哪个工作区有几条待办」必须逐工作区 × 逐表并发请求（10 个工作区 × 5 张表 = 50 次），首屏体验不可接受 | 新增（C8） |
| 2 | 三个待办源的「待处理」口径分散在各模型常量 | `change_requests/models.py:19`（`CR_STATUS_OPEN`）、`issues/models.py:29`（`ISSUE_STATUS_OPEN`）、`workspaces/models.py`（`WorkspaceLinkStatus.PENDING`） | 聚合时必须在同一处给出统一口径，否则前端拼出来的数字天然不一致 | 新增（C8） |
| 3 | 工作区列表已有「进程内短 TTL 缓存 + 写路径失效」范式 | `src/cndb/plugins/workspaces/routers/workspaces.py:114`（`_list_cache()` / `cache_key` / `WORKSPACE_LIST_TTL_SECONDS`）、`src/cndb/core/cache.py` | 聚合端点照抄同一范式，不引入 Redis 与新的失效机制 | 确认（C8） |
| 4 | 主页 rail 目前只有计数（工作区数 / 团队工作区数）与最近访问 | `frontend/src/components/HomeNav.tsx` | 缺「有待办」的可见信号，用户不知道去哪个工作区 | 新增（C1） |

**核心缺陷（需求要补的）**：跨工作区的「待我处理」没有任何单一入口，主页无法回答「我今天该去哪个工作区」。

设计目标（不变量）：

- **I1 只读**：端点不写任何业务表、不写 `core_event`、不分配 id；失败不改状态。
- **I2 逐工作区同权**：每个工作区的计数恒等于该用户在**该工作区**内本来就可见的待办条数；任一工作区不可读（非成员 / 团队无 `data_role` / 模块未开放）→ 该工作区计 0，且**不出现**在响应里。计数永不来自「绕过判定」的全局查询。
- **I3 不泄露存在性**：响应只含计数与聚合数，不含工作区 id / 名称 / 条目标题 / 行数据 / 提示词 / 密钥；不可读工作区不出现、不产生 404 差异。
- **I4 缓存按用户隔离**：缓存 key 必含 `user_id`，TTL ≤ 30s，工作区内写路径（提交 / 审批 / 关单 / 授链接）与成员变更主动失效。
- **I5 降级不阻断**：任一块查询异常 → 该块计 0 并置 `partial=true`，HTTP 仍 200；主页不能因为「待办统计」整页报错。

## Decision

### D1 独立只读端点，挂在 `/api/v1/home/summary`

- 路由：`GET /api/v1/home/summary`（登录即可用；无工作区参数）。
- 不并入 `/workspaces`：主页语义是「跨工作区的聚合」，与单个工作区资源无关；也避免 `/workspaces/{workspace_id}` 吞路径。
- 不新增表、不改任何模型的「待处理」状态口径，只**读**既有常量。

### D2 响应载荷（白名单）

```json
{
  "workspace_count": 6,
  "team_count": 2,
  "pending": {
    "change_requests": 4,
    "issues": 7,
    "link_requests": 1,
    "total": 12
  },
  "partial": false
}
```

- 只有聚合计数，**没有** `by_workspace`（A′ 口径下主页 rail 只有「全部工作区」一项，逐工作区徽标没有落点；为不引入"按 id 索要计数"的枚举面，直接不返回）。
- 不含条目标题 / 时间 / 行数据、不含工作区 id / 名称：点击计数只跳到工作区列表，明细仍走既有按工作区 / 按表接口（不复制一条新的业务读通路，I3）。

### D3 逐工作区聚合（判定复用，不新写判定）

对每个可见工作区依次做既有判定，再统计：

| 块 | 入口判定（复用） | 统计口径 |
|---|---|---|
| 修改申请 | 表级 `review_requests` 能力（既有 `require_capability` 语义） | `status == open` 的条数（仅统计用户有审批权的表） |
| 问题 | 工作区成员 + 表级读权 | `status == open` 的条数（字段隐藏 / 行级规则不影响计数，因为不返回行内容） |
| 链接审批 | 工作区 `MANAGE_LINKS` | `status == PENDING` 的条数（源工作区所有者视角，与 `links/inbox` 同口径） |
| 工作区 / 团队数 | `GET /workspaces` 同一列表口径 | 直接复用列表长度，不额外查询 |

- 实现落在 `plugins/workspaces/routers/home.py`（编排）+ 各插件既有的查询函数（不在新文件里复制 SQL 判定）。
- 单工作区块循环内 `try/except`：异常 → 该工作区块全部计 0，`partial=true`（I5）。

### D4 缓存

- 进程内缓存，key = `cache_key("home-summary", user_id, id(db.bind))`，TTL 20s（≤30s，I4）。
- 主动失效：复用 `workspaces.py` 已有的失效函数入口（成员 / 工作区 / 团队变更时清）；新增待办写路径（提交修改申请 / 审批 / 关单 / 链接申请与审批）在其落库后清 `home-summary`。
- 不使用 Redis：单机部署，与现有 `_list_cache()` 同源。

### D5 前端接线

- `HomeNav` 拉一次 `GET /api/v1/home/summary`（`useQuery`，`staleTime: 20_000`），在「全部工作区」与各团队条目右侧渲染总待办徽标；折叠态（60px）不渲染徽标。
- 徽标颜色走 `--cn-brand-color` 中性强调，不用红色告警（不是故障）。
- 请求失败时静默隐藏徽标（不弹错误提示），主页其它内容不受影响。

### 决策记录（唯一决策台账）

| # | 决策 | 选择 | 理由 / 否决项 |
|---|---|---|---|
| D1 | 端点形态 | 新增 `GET /api/v1/home/summary` | 否决「前端逐工作区并发聚合」（>5 工作区时 50+ 请求、口径分散在三个插件前端）；否决「并入 `/workspaces` 列表载荷」（列表是最热读路径，加重缓存体积与失效面） |
| D2 | 载荷粒度 | 只返回聚合计数（无 `by_workspace`） | 否决「返回条目标题」（新增一条跨工作区业务读通路，泄露面与判定面都变大）；否决「`by_workspace` 索引键」（A′ 口径下无落点；任何按工作区维度的返回都会引入可枚举面，违反 I3） |
| D3 | 判定来源 | 复用各插件既有判定与状态常量 | 否决「在聚合层重写 SQL 条件」（口径漂移；H51 工作区判定单一入口、H17 不泄露） |
| D4 | 失败口径 | 单块降级 + `partial=true`，仍 200 | 否决「整体 500」（主页是入口页，辅助信息不应阻断主内容）；否决「静默 0 不标记」（无法区分「真的没有」与「查询失败」） |
| D5 | 缓存 | 进程内 20s + 写路径失效 | 否决「不加缓存」（首页每次挂载 × N 工作区 × 3 张表聚合）；否决「Redis」（单机部署，现无 Redis 依赖） |
| D6 | 权限失败语义 | 不可读工作区计 0 且不出现在响应里 | 沿用 H17 / H61 的 fail-closed 精神：不返回部分可见数据、不暴露存在性 |

## Consequences

- 正面：主页能回答「有没有待我处理的事」，点击一步到位；不新增表、不新增授权面、不复制业务读通路、不返回可枚举的 id。
- 代价：首页多一个聚合查询（有缓存）；只给总数时用户需要点进工作区列表再找具体条（分级明细留给各工作区页面）。
- 风险：待办写路径漏挂失效 → 计数最多陈旧 20s（TTL 兜底，不产生越权，只影响新鲜度）。

## 与既有 ADR 的关系

- 承接 [0153](0153-multi-workspace-team-model.md)：跨工作区读一律「逐工作区判定」，本条不改团队角色天花板（H49）。
- 沿用 [0154](0154-workspace-link.md) / [0158](0158-link-as-analytics-datasource.md) 的链接读口径（`resolve_link` / `MANAGE_LINKS` 既有判定），不新增链接通路（H53 / H54）。
- 复用 [ADR 0021](0021-home-favorite-views-panel.md) 的主页双列布局与 [需求 0160](../requirements/0160-home-navigation-layout.md) 的主页导航 rail，不改布局骨架。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P2 | 未开始 | `src/cndb/plugins/workspaces/routers/home.py`（新增）、`frontend/src/components/HomeNav.tsx` | `tests/test_home_summary.py`（新增）、`frontend/src/components/HomeNav.test.tsx` | `（待回填）` |

## 交接（会话结束更新）

- 当前阶段：Proposed，待人工评审；评审通过后按单一期内聚实现（后端端点 + 前端徽标 + 两侧测试）。
- 下一步：`make adr-check` → 人工评审 D1..D6 → 实现 → `make cov` + `make check-frontend` → 回填本表 sha。
- 已知坑：待办写路径分散在三个插件（提交 / 审批修改申请、开 / 关问题、申请 / 审批链接），失效调用点漏挂只影响新鲜度（TTL 20s 兜底）不影响安全；徽标只做聚合数，不要顺手加「最近 5 条待办列表」或 `by_workspace`（会变成新的跨工作区业务读通路 / 枚举面，需另立 ADR）。

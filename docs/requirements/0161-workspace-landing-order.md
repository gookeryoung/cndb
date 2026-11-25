# 需求卡片：进入工作区的默认落地页可按用户自定义排序

> 需求原文与约束编号 C1..Cn 的唯一副本在本卡片，ADR 只引用不复制（H26）。

- 编号：0161
- 分级：**S1**（跨 accounts 后端 + 前端导航判定 + 个人设置 UI；无新表 / 无迁移 / 无权限口径变化 / 无契约破坏性变更）→ 方案并入本卡片，不立 ADR
- 来源 / 提出人：用户（会话 2026-11-28，「进入工作区时，每个用户对看到的默认页面排序（数据表先还是文档先）需要可自定义，请给出方案」，方案评审结论：「按推荐」）
- 日期：2026-11-28
- 关联：复用 [ADR 0021](../adr/0021-home-favorite-views-panel.md) 的 per-user `accounts_user.preferences` 载体；沿用 [ADR 0080](../adr/0080-workspace-module-selection.md) D9 的落地段判定入口（`workspaceLandingSegment`）与 [需求 0081](0081-topnav-zones-and-home-search.md) C4 的顶部一级导航固定顺序口径

## 需求原句（逐字）

> 进入工作区时，每个用户对看到的默认页面排序（数据表先还是文档先）需要可自定义，请给出方案

方案评审确认（2026-11-28，人工「按推荐」）：

> 1. 排序粒度：**完整三段全序**（数据表 / 文档 / 设计，非仅「谁是第一个」）；2. 作用范围：**只影响默认落地页**，顶部一级导航顺序保持固定；3. 配置入口：**个人设置新增「默认页」页签**。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「每个用户」 | 偏好按用户隔离，存 `accounts_user.preferences.landing_order`（JSON，**零迁移**）；读写只作用于当前用户，A 的设置不影响 B；**不进工作区备份**（与 ADR 0020 个人配置同口径） | `accounts/services/preferences.py`、`accounts/routers/preferences.py` | 接口测试：跨用户不可见 |
| C2 | 「默认页面排序」 | `landing_order` 恒为三模块**完整排列**：去重、丢未知项、缺失项按 `tables → documents → design` 补到尾部；渲染顺序即优先级 | 同上 | 单测：归一化矩阵（缺项 / 未知项 / 重复 / 非数组 / 空数组） |
| C3 | 「数据表先还是文档先」 | 落地段判定改为「按偏好顺序取**该工作区已启用**的第一个模块」；偏好首位模块未启用时顺延，不 404、不空白 | `frontend/src/utils/workspaceModules.ts` | 前端单测：模块组合 × 偏好顺序矩阵 |
| C4 | （存量兼容） | 未设置 / 值非法 / 老用户 = 默认 `tables → documents → design`，与升级前逐条一致（I2） | 前后端默认值 | 既有用例全绿 + 新增默认值用例 |
| C5 | （作用范围边界） | **只影响默认落地**：顶部一级导航顺序、切工作区「保持当前模块」的优先权、「继续上次 / 深链」均不变；偏好只在根路由 `/w/:wid` 与「落在未启用模块的回落」两处生效 | `App.tsx`、`layouts/MainLayout.tsx`、`pages/workspace/WorkspaceList.tsx` | 单测：导航顺序断言不变；切工作区保持模块用例不变 |
| C6 | （配置入口） | 个人设置新增页签「默认页」：三行有序列表（上移 / 下移）+ 「恢复默认」+ 预览文案「进入工作区时优先打开：X → Y → Z」；保存即乐观更新偏好缓存 | `pages/settings/SettingsModal.tsx`、`store/ui.ts`、`hooks/useLandingOrder.ts` | 组件单测：上移下移 / 恢复默认 / 失败回滚 |
| C7 | （门禁） | 后端覆盖率 ≥95%（`make cov`）、前端双门槛与静态门禁、e2e 关键路径同轮补齐 | 全链路 | `make flow` / `make check` |

约束编号在 ADR 中原样引用；不重编号、不合并。

非目标（本期不做）：

- 不按工作区逐个记忆「上次停留的模块」（那是「继续上次」语义，与「默认页排序」不同）。
- 不把「统计 / 工作区设置」纳入默认页候选（恒开放入口，避免语义纠缠）。
- 不改顶部一级导航渲染顺序、不改移动端导航形态。

## 现状影响面（已核实）

| # | 受影响能力 | 位置 | 处置 |
|---|---|---|---|
| 1 | 落地段判定唯一入口（`tables → documents → design` 硬编码） | `frontend/src/utils/workspaceModules.ts:81-86` | 增可选 `landingOrder` 参数（缺省等价现状） |
| 2 | 根路由落地 | `frontend/src/App.tsx:64-76` | 读偏好，两条查询就绪后再 `Navigate`（避免双跳闪烁） |
| 3 | 未启用模块回落 | `frontend/src/layouts/MainLayout.tsx:579-600` | 传偏好顺序 |
| 4 | 无 wid / 首个工作区兜底 | `frontend/src/layouts/MainLayout.tsx:676` | 同上 |
| 5 | 主页进工作区 3 处（新建 / 导入 / 行点击） | `frontend/src/pages/workspace/WorkspaceList.tsx:166,592,631` | 主页已有偏好查询，直接复用 |
| 6 | 切工作区回落 | `frontend/src/utils/workspaceModules.ts:100-110` | 回落段传偏好顺序 |
| 7 | per-user 偏好载体与 GET/PUT | `accounts_user.preferences`、`accounts/services/preferences.py`、`accounts/routers/preferences.py:158-222` | 新增 `landing_order` 键与 PUT 端点（零迁移） |
| 8 | 前端偏好缓存 | `frontend/src/hooks/useFavoriteViews.ts`（`PREFERENCES_QUERY_KEY`） | 落地判定消费同一缓存，不新增请求源 |
| 9 | 个人设置页签 | `pages/settings/SettingsModal.tsx:694-710`、`store/ui.ts:10` | 新增「默认页」页签 |
| 10 | 偏好 mock | `frontend/src/test/msw.ts:615` | 补 `landing_order` |

## 方案口径（关键决策）

| 决策 | 结论 | 理由 |
|---|---|---|
| 存储载体 | `accounts_user.preferences.landing_order`（JSON） | 复用既有偏好体系（ADR 0021 先例），零迁移、天然按用户隔离、天然不进工作区备份 |
| 排序粒度 | 完整三段全序 | 「谁是第一个」无法表达两模块工作区的次选；全序唯一确定且 UI 直观 |
| 作用范围 | 仅默认落地；导航顺序固定 | 一级导航是全局信息架构（0081 C4），用户级重排会与团队/协作者认知冲突，且破坏导航断言 |
| 归一化 | 去重 + 丢未知 + 尾补默认序 → 恒为完整排列；空数组 = 恢复默认 | 避免半序歧义与 422 语义负担；前端只消费全序 |
| 落点判定 | 按偏好顺序取**该工作区已启用**的第一个模块 | 复用模块门控（ADR 0080 I1），跨工作区不产生空页 |

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（2026-11-28「按推荐」）

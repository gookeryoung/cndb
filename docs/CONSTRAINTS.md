# 硬约束台账（CONSTRAINTS）

> 全仓硬约束的**唯一编号源**（设计见 [ADR 0119](adr/0119-hard-constraint-registry.md)）：[AGENTS.md](../AGENTS.md)、`.trae/rules/agent.md`、ADR、[AI_DRIVEN_DEV_FLOW.md](AI_DRIVEN_DEV_FLOW.md) 引用约束一律写 H#，台账外只允许「一句话摘要 + H#」，不复制完整口径。
> 变更规则：H 条目新增 / 修改 / 删除属口径变更，**须人工确认**，LLM 不得自行放宽；删除后编号不复用，在文末「已删除」清单记一行。
> `make constraint-check` 校验本台账：四列列头、编号唯一、来源 ADR 存在（防孤儿）、机器命令存在。

## 使用方式（LLM 必读）

- **开工前对表**：设计若触碰任一 H#，先核对口径再动手；涉及 H5 时先走方案分级（S0/S1/S2）。
- **提交前自查**：改动涉及「机器」校验的 H 条目，跑对应命令至绿；「人工」卡点条目在收工清单标注并等待确认。
- **冲突处理**：两条约束冲突时从严执行；硬约束与 ADR 口径冲突时，先改 ADR 与本台账再写码。

## 流程与门禁

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H1 | 禁止 `--no-verify`、禁止跳过 pre-commit（prek）钩子 | 人工:提交钩子 | 全局 |
| H2 | commit message 用 conventional commits（L0 `docs:`；L1 `chore:`/`ci:`/`build:`；L2 `feat:`/`fix:`/`refactor:`/`test:`） | 人工:提交信息 | 全局 |
| H3 | 门禁分级 fail-safe：混合改动按最高级执行；拿不准按 L2 | 人工:提交前自查 | 全局 |
| H4 | L2 代码改动执行链 `make check-fast` → `make test` → 文档更新 → `make push`，任一步失败修完重跑 | `make check-fast` | 全局 |
| H5 | 先方案后代码：新功能 / 行为变更按 S0/S1/S2 定级；S1 卡片确认、S2 卡片 + ADR 评审须人工拍板，AI 不得自行进入实现 | 人工:需求确认/方案评审 | 全局 |
| H6 | 不擅自修改 git config；未获明确授权不 force push、不直推 main/master、不打 tag（tag 属上线卡点） | 人工:上线 tag | 全局 |
| H7 | ADR `Proposed → Accepted` 前决策记录表无「待定」，卡片约束 C1..Cn 逐条有落点 | `make adr-check` | 全局 |
| H8 | ADR 被替代 / 需求作废即**直接删除**文件与索引行，不留 Superseded / Deprecated，编号不复用；删除前先迁移仍在生效的 H 条目 | `make adr-check` | 全局 |
| H26 | 需求原文与约束编号 C1..Cn 的唯一副本在需求卡片 `docs/requirements/NNNN-*.md`，ADR 只引用不复制；需求澄清 / 变更先改卡片再同步 ADR | 人工:需求确认 | 全局 |
| H27 | 跨需求长期生效的 ADR 不变量（I#）须在 `Proposed → Accepted` 前登记入台账，来源写 `ADR NNNN I#`；ADR 删除前先迁移 | 人工:方案评审 | 全局 |

## 覆盖率与测试

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H9 | 测试与实现**同轮**编写，不留「以后再补」 | 人工:评审 | 全局 |
| H10 | 后端覆盖率 ≥95%（`fail_under` + omit 白名单固定），前端双门槛见 `frontend/scripts/check-coverage.mjs`；不得注水（不写无断言用例、不改白名单放宽） | `make cov` | 全局 |
| H11 | e2e 是硬门禁，不得通过跳过用例规避失败（抖动由 CI retries 兜底） | `make e2e` | 全局 |
| H12 | 分层覆盖：判定层单测 / 接口层 / 迁移 / 备份往返（含旧备份兼容）/ 前端单测 / e2e | `make test` | 全局 |
| H28 | 拆分模块时 mock / monkeypatch 目标必须指向 canonical 模块；测试依赖的具名导出须在原文件用 `export { ... } from` 或 `__all__` 保留 | `make test` | 全局 |

## 数据与迁移

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H13 | 迁移幂等 + downgrade 可还原 + 存量零迁移 | `make test` | 全局 |
| H14 | 新表须纳入 `backup_io`，旧备份按缺省还原 | `make test` | 全局 |

## 设计与前端

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H24 | 列表 / 菜单 / 下拉 / 表格选中项必须使用 `--cn-bg-selected`（一级流程可 `--cn-bg-selected-strong`）；相对 `--cn-bg-container` 的 WCAG 对比度普通 ≥1.35:1、强选中 ≥1.5:1，且强选中不得低于普通；禁止回退到 `--cn-bg-subtle` 或手写低比例 `color-mix` | `make frontend-coverage` | 全局 |
| H25 | 界面线条统一 GitHub 式 1px 中性线：静态边界（卡片 / 列表 / 表格 / 方盒 / 分割线 / 按钮 / 输入 / 选择 / 日期 / 数字 / 搜索）默认 1px，线色只用 `--cn-border`（浅色 `#6e7781` / 深色 `#8b949e`），`--cn-border-soft` 同值；hover / active / focus 才可用品牌色；禁止 1.5px 静态粗描边与静态重投影（状态指示条 / focus ring / 浮层轻投影等非静态边界可例外） | `make frontend-coverage` | 全局 |
| H29 | 样式只从设计标尺与主题 token 取值：CSS 间距 / 字号 / 圆角不写裸数值（例外 `0` / `auto` / `1px` / `50%`），新增档位先加进 `tokens.ts` 与 `:root`；字号用 `var(--cn-text-*)`、字重用 `var(--cn-weight-*)`、颜色只用 `var(--cn-*)`；字体只经 npm `@fontsource` 导入 latin 子集，不引 CDN、不保留 `public/fonts` | `make frontend-coverage` | 全局 |
| H30 | 页面根容器用 `.cn-page`、空态 / 加载态用 `.cn-state`；断点只允许 `767.98px` / `575.98px`；不新增 `[style*="..."]` 兜底；代码高亮颜色只走 `--cn-code-*`，新增语言只加词法配置 | `make frontend-coverage` | 全局 |
| H31 | 首屏 / 受控 chunk 禁止静态引入重型依赖（echarts / jspdf / html2canvas-pro / nunjucks 等）与按需弹层（Dialog / Modal / Drawer / Manager / Editor），必须 lazy 到按需 chunk | `make frontend-static` | 全局 |
| H32 | `bundle-budget` 基线 / 上限只能经脚本调整：必须带 `--reason`，`--set-budget` 必须 `--only`，禁止手改 JSON；单次基线上调 >10% 须在 PR 说明 | `frontend/scripts/bundle-budget.mjs` | 全局 |

## 权限与安全

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H15 | 行级权限天花板：行级授权永不放行「表外的人」（有效行读 ⇒ 表 `READ`） | `make test` | ADR 0004 I1 |
| H16 | 存量不变：未配置任何行规则的存量表行为与升级前逐条一致 | `make test` | ADR 0004 I3 |
| H17 | 无泄露：读范围外的行不可见（列表不含）；越界单行读写按 404 处理，不做存在性提示 | `make test` | ADR 0004 I6 |
| H18 | 权限规则变更后清记录缓存，防收紧后泄漏 | `make test` | ADR 0004 |
| H19 | 原件族文档只读：`content_type` 属原件族（pdf / image / xlsx / pptx 等）不参与 Markdown 写路径，保存 / 提交 / 回滚一律 409 | `make test` | ADR 0025 I2 |
| H20 | 设计装配版本可复现：每个版本保存依赖闭包快照，历史回看按快照编译、缺依赖显式报错；编译预算按闭包累计有界 | `make test` | ADR 0086 I4/I5 |
| H33 | 文档可见性收口：草稿 / 归档仅创建者与工作区 `OWNER` / 超管可见，不可见即 404；列表 / 目录树 / 检索 / 详情 / 版本 / 差异 / 导出等全部读路径统一按同一可见性过滤 | `make test` | 全局 |
| H34 | 仅已发布文档可创建分享；草稿 / 归档或取消发布后分享链接一律失效（404） | `make test` | 全局 |
| H35 | 文档写路径 409 口径：内容未修改不可提交（`no_changes`）、直编基准过期（`stale_version`）、带未提交草稿发布（`uncommitted_draft`）均返回 409 | `make test` | 全局 |

## 发布与部署

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H21 | bundle budget 不超基线 +5% | `frontend/scripts/bundle-budget.mjs` | ADR 0116 |
| H22 | 单机部署串行（`concurrency: deploy-tencent-prod`），失败自动回滚 | `.github/workflows/deploy-tencent.yml` | 全局 |
| H23 | 门禁卡住先看 `make env-guard` 体检结论（如 `LD_LIBRARY_PATH` 注入旧 libsqlite3），不用 pytest 参数 / 超时绕过 | `make env-guard` | 全局 |
| H36 | 生产部署安全：`AUTH_ENABLED` 不可关闭；`JWT_SECRET` 必须随机非占位符；`.env` 权限 600 且不入库；`DEBUG=false`；`CORS_ORIGINS` 不得为 `*`；反代模式应用端口仅绑回环且安全组不放行 | 人工:上线安全清单 | 全局 |
| H37 | 云资源最小权限与备份：腾讯云子账号仅授 `tat:RunCommand` / `tat:DescribeInvocationTasks`；TCR / COS 私有读写；每日备份须实际验证可恢复 | 人工:上线安全清单 | 全局 |

## 质量检查

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H38 | 流水线检查只读、不改业务数据；发现物只记录定位信息（字段 / 行 ID / 引用原文），不携带单元格值与文档正文；保存期完成结构校验；同一定义同一时刻最多一个活跃运行 | `make test` | ADR 0076 |

## 工作区项目上下文（ADR 0122）

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H39 | 项目上下文边界：`project_row_id` 必须是当前工作区根表单中存在的行，查无此行一律 404（动态表行 ID 按表自增，跨表同号不可区分）；项目级读写必须带同一 `project_row_id`，不得回落到工作区级 | `make test` | ADR 0122 I1 |
| H40 | 项目生命周期唯一入口：项目阶段读取、门禁与推进只经 `lifecycle_state` / `advance_stage`，禁止业务代码直接改 `workspace_project_states` | `make test` | ADR 0122 I2 |
| H41 | 项目门禁计数口径：只统计 `scope=project` 且 `所属项目 = project_row_id` 的表单行；`scope=workspace` 表单与其他项目行不计入；文档按项目映射且存活 | `make test` | ADR 0122 I3 |
| H42 | 单项目退化：根表单只有 1 行时项目模式等价单项目工作台（自动选中、隐藏切换器），不产生第二套模板 / 路由 | `make test` | ADR 0122 I4 |
| H43 | 存量兼容：未启用项目级管理的工作区保持工作区级阶段与共享文档；启用必须显式、幂等，且不自动拆分已有文档；旧备份恢复为 `workspace` 模式 | `make test` | ADR 0122 I5 |
| H44 | 项目备份完整性：项目状态与项目文档映射必须进 `backup_io`，往返一致；旧归档缺省还原为工作区模式 | `make test` | ADR 0122 I6 |

## 已删除

| # | 原因 | 日期 |
|---|---|---|

> 当前无缺口；删除条目时在此记一行（编号 / 原因 / 日期），编号不复用。

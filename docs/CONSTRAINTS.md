# 硬约束台账（CONSTRAINTS）

> 全仓硬约束的**唯一编号源**（设计见 [ADR 0119](adr/0119-hard-constraint-registry.md)）：[AGENTS.md](../AGENTS.md)、`.trae/rules/*`、ADR、[AI_DRIVEN_DEV_FLOW.md](AI_DRIVEN_DEV_FLOW.md) 引用约束一律写 H#，台账外只允许「一句话摘要 + H#」，不复制完整口径。
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

## 覆盖率与测试

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H9 | 测试与实现**同轮**编写，不留「以后再补」 | 人工:评审 | 全局 |
| H10 | 后端覆盖率 ≥95%（`fail_under` + omit 白名单固定），前端双门槛见 `frontend/scripts/check-coverage.mjs`；不得注水（不写无断言用例、不改白名单放宽） | `make cov` | 全局 |
| H11 | e2e 是硬门禁，不得通过跳过用例规避失败（抖动由 CI retries 兜底） | `make e2e` | 全局 |
| H12 | 分层覆盖：判定层单测 / 接口层 / 迁移 / 备份往返（含旧备份兼容）/ 前端单测 / e2e | `make test` | 全局 |

## 数据与迁移

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H13 | 迁移幂等 + downgrade 可还原 + 存量零迁移 | `make test` | 全局 |
| H14 | 新表须纳入 `backup_io`，旧备份按缺省还原 | `make test` | 全局 |

## 权限与安全

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H15 | 行级权限天花板：行级授权永不放行「表外的人」（有效行读 ⇒ 表 `READ`） | `make test` | ADR 0004 I1 |
| H16 | 存量不变：未配置任何行规则的存量表行为与升级前逐条一致 | `make test` | ADR 0004 I3 |
| H17 | 无泄露：读范围外的行不可见（列表不含）；越界单行读写按 404 处理，不做存在性提示 | `make test` | ADR 0004 I6 |
| H18 | 权限规则变更后清记录缓存，防收紧后泄漏 | `make test` | ADR 0004 |
| H19 | 原件族文档只读：`content_type` 属原件族（pdf / image / xlsx / pptx 等）不参与 Markdown 写路径，保存 / 提交 / 回滚一律 409 | `make test` | ADR 0025 I2 |
| H20 | 设计装配版本可复现：每个版本保存依赖闭包快照，历史回看按快照编译、缺依赖显式报错；编译预算按闭包累计有界 | `make test` | ADR 0086 I4/I5 |

## 发布与部署

| # | 约束 | 校验 | 来源 |
|---|---|---|---|
| H21 | bundle budget 不超基线 +5% | `frontend/scripts/bundle-budget.mjs` | ADR 0116 |
| H22 | 单机部署串行（`concurrency: deploy-tencent-prod`），失败自动回滚 | `.github/workflows/deploy-tencent.yml` | 全局 |
| H23 | 门禁卡住先看 `make env-guard` 体检结论（如 `LD_LIBRARY_PATH` 注入旧 libsqlite3），不用 pytest 参数 / 超时绕过 | `make env-guard` | 全局 |

## 已删除

| # | 原因 | 日期 |
|---|---|---|

> 当前无缺口；删除条目时在此记一行（编号 / 原因 / 日期），编号不复用。

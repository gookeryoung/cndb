# AI 驱动开发流（cndb）

> 目标：需求意图 → 方案 → 代码 → 测试 → 门禁 → 发布，全程由 AI 编排、由机器门禁裁定。
> 执行契约与 L/S 分级见 [AGENTS.md](../AGENTS.md)；硬约束编号见 [CONSTRAINTS.md](CONSTRAINTS.md)；角色操作卡见 [.trae/skills/](../.trae/skills/)。

## 1. 核心原则

1. **门禁即裁判**：AI 只认命令退出码与 CI 结果，不靠“我认为做完了”。
2. **单一来源**：规则只在 AGENTS / CONSTRAINTS / 本文件 / ADR / 需求卡片各写一次，其他位置只摘要 + 链接。
3. **阶段化 + 人工卡点**：只保留 3 个人工卡点——需求确认、ADR 评审、上线 tag。
4. **失败自愈**：门禁报错 → 定位根因 → 修复 → 重跑，直到全绿；不绕过。

## 2. 流水线总览

| 阶段 | 输入 / 触发 | AI 动作 | 产出 | 客观门禁 | 人工卡点 |
|---|---|---|---|---|---|
| **A 需求** | 用户口语需求 | 逐句拆 C1..Cn；粗查影响面 | 需求卡片 `docs/requirements/NNNN-*.md` | 每句有 C 编号、未决问题清零 | ✅ 需求确认 |
| **B 方案** | 需求卡片 | 核对代码、定不变量、写决策与分期 | S2 的 ADR（Proposed） | 卡片约束逐条有落点、D 表无待定 | ✅ ADR 评审 |
| **C 实现** | 已确认方案 | 按 P0 → P1 → P2 小步实现 | 代码 / 迁移 / 前端 | `make check-fast` | — |
| **D 测试** | 与 C 同轮 | 分层补测试并跑覆盖率 | 单测 / 接口 / 迁移与备份 / 前端 / e2e | `make test` → `make cov` / `make frontend-coverage` / `make e2e` | — |
| **E 集成** | C + D 全绿 | 更新文档、回填 ADR、跑全量门禁 | CHANGELOG、文档、ADR 交接 | `make check` + 双 CI | — |
| **F 发布** | E 全绿 + 人工确认 | `make push`、bump、打 tag | 包 / Release | `release.yml` | ✅ 上线 tag |
| **G 部署** | release 成功 | 观察部署与健康 | 生产实例 | `deploy-tencent.yml` + `/health` | 失败自动回滚 |

S0 / S1 / S2 的裁剪规则以 AGENTS 第 3.1 节为准：S0 直接从 C 开始，S1 从 A 开始但不写 ADR。

## 3. 阶段执行要点

### A 需求

- 需求原句逐字保留，作为唯一原文副本。
- 逐句拆成可实施约束 C1..Cn，每条必须能落到 plugin / 表 / 字段 / 端点 / 页面 / 测试。
- 粗查受影响代码，标候选 `文件:行号`；精查留给 B。
- 产出模板：[REQUIREMENT_CARD_TEMPLATE.md](REQUIREMENT_CARD_TEMPLATE.md)。

### B 方案

- 只对 S2 产出 ADR；S1 把方案写入需求卡片即可。
- 口径表沿用 C1..Cn，只补“设计落点”，不复制原文。
- 必须写清：数据模型、判定入口、API、边界与例外、迁移（幂等 + downgrade + 存量零迁移）、前端、测试、分期。
- 决策结论只写 D1..Dn 一处；ADR 结构以 [adr/TEMPLATE.md](adr/TEMPLATE.md) 为准。

### C 实现

- 插件分层：`plugins/<name>/{models.py,routers/,schemas/,services/}`；动态表 DDL 走 SQLAlchemy Core。
- 迁移：幂等 + downgrade 可还原；新表纳入 `backup_io`（H13 / H14）。
- 前端：`frontend/src/`，API 类型与后端对齐。
- 每改完跑 `make check-fast`；每期完成回填 ADR 的“落地状态 / 交接”。

### D 测试

- 与实现同轮，按 H12 分层：判定层单测 / 接口 / 迁移 / 备份往返 / 前端单测 / e2e。
- 断言行为而非实现细节；覆盖 ADR 的边界与例外。
- 门槛：后端 ≥95%；前端双门槛；e2e 不得跳过用例（H10 / H11）。

### E 集成

- 跑 `make check`；更新 README / CONTEXT / docs / ADR 索引 / CHANGELOG。
- `make adr-check` 校验落地表、交接节、Related 与索引 Status。
- 双 CI：GitHub Actions + CodeUp；ADR Landing job 无 error。

### F 发布 / G 部署

- `make push` 推全部 remote + tags；`make bump patch|minor|major` 更新版本与 tag。
- 打 tag 前必须人工确认；tag 触发 [release.yml](../.github/workflows/release.yml)（PyPI + 原生打包 + GitHub Release）。
- release 成功后 [deploy-tencent.yml](../.github/workflows/deploy-tencent.yml) 下发部署；失败自动回滚，`/health` 为最终判据。

## 4. 角色与驱动机制

| 角色 | 负责阶段 | 输入 | 输出 / 停止条件 |
|---|---|---|---|
| `spec-writer` | A + B | 用户需求 | 需求卡片；S2 的 ADR（Proposed → 人工评审后 Accepted） |
| `implementer` | C + D | 已确认方案 / ADR | 代码 + 测试；`make check-fast` 与分层测试全绿 |
| `gate-runner` | E | 改动完成 | `make check` / CI 全绿；失败只修根因并重跑 |
| `release-manager` | F + G | 全绿 + 人工授权 | 推送 / tag / 发布 / 部署；上线卡点由人确认 |

Skill 定义在 `.trae/skills/`；工具不自动加载时，按 AGENTS 第 2 节手动读取。

## 5. 失败闭环

```
门禁失败输出 → 定位根因 → 修改代码 / 测试 / 文档 → 重跑失败项 → 跑完整链 → 全绿
```

- 禁止用 `-k` / `--ignore` / `--no-verify` / 注释断言 / 放宽门槛绕过。
- 门禁卡住先跑 `make env-guard`（H23），再查依赖 / 环境 / 代码。
- 修复后至少重跑失败项 + 一次完整级别门禁。

## 6. 上下文与交接

- 每轮开工按 AGENTS 第 2 节恢复上下文。
- ADR 是方案的唯一载体；需求原文在卡片；术语在 CONTEXT。
- 收工前回填 ADR 交接（做到哪期 / 下一步 / 已知坑），再更新 CHANGELOG 与门禁。
- 需求移除时先删 ADR 与引用，再改代码（H8）。

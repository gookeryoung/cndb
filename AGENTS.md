# AI 开发入口（cndb）

> 本文件是每轮开发的唯一入口，只写“做什么 / 何时停 / 去哪里看”。
> 阶段细则见 [AI_DRIVEN_DEV_FLOW](docs/AI_DRIVEN_DEV_FLOW.md)，硬约束编号见 [CONSTRAINTS](docs/CONSTRAINTS.md)，Trae 工具执行卡见 [.trae/rules/agent.md](.trae/rules/agent.md)。
> 同一规则只在一个文件维护；其他位置只写一句摘要 + 链接 / H#，不复制完整口径。

## 1. 唯一来源

| 内容 | 唯一来源 | 说明 |
|---|---|---|
| 执行契约 | `AGENTS.md` | 开工顺序、S/L 分级、实施与收工流程 |
| 阶段流水线 | `docs/AI_DRIVEN_DEV_FLOW.md` | 需求 → 方案 → 代码 → 测试 → 门禁 → 发布 |
| 硬约束 H1..Hn | `docs/CONSTRAINTS.md` | 违反即打回；`make constraint-check` 校验 |
| 术语 | `CONTEXT.md` | 业务 / 架构名词 |
| 决策与交接 | `docs/adr/NNNN-*.md` + `docs/adr/README.md` | 方案、不变量、落地状态、下一步、已知坑 |
| 需求原文与 C1..Cn | `docs/requirements/NNNN-*.md` | ADR 只引用，不复制 |
| 角色操作卡 | `.trae/skills/*/SKILL.md` | 4 个角色，见第 6 节 |

## 2. 开工顺序（换会话 / 换 Agent 必做）

1. 读本文件与 `.trae/rules/agent.md`。
2. 读 `CONTEXT.md` 与当前需求的 ADR（`落地状态`、`交接`）。
3. 对表 `docs/CONSTRAINTS.md`：设计触碰任一 H# 时先核对口径。
4. 跑 `make env-guard`，再跑对应基线：
   - 纯文档：`make check-docs`
   - 配置：`make check-fast`
   - 代码：`make check-fast`（必要时再 `make test`）
5. 先给任务定级（第 3 节），再决定是否写卡片 / ADR。

不要假设上一轮门禁全绿；基线失败先修基线，不把失败带进新改动。

## 3. 分级：先定性，再选流程

### 3.1 需求级（S）

| 级别 | 判定 | 产物 | 人工卡点 |
|---|---|---|---|
| **S0 小改** | bug 修复、文案 / 样式微调、单点改动，无数据 / 接口 / 权限口径变化 | 无卡片、无 ADR | 意图确认 |
| **S1 常规功能** | 跨 2+ 模块，多约束但无架构分叉 | 需求卡片（可轻量），方案并入卡片 | 需求确认 |
| **S2 重大项** | 数据 / 迁移 / 备份、权限 / 安全、架构 / 对外契约变化，或方案有实质分叉 | 需求卡片 + ADR | 需求确认 + ADR 评审 |

拿不准升一级；实现中发现设计分叉，S1 升 S2 补 ADR。

### 3.2 门禁级（L，按改动文件路径判定）

| 级别 | 范围 | 必跑 | 跳过 |
|---|---|---|---|
| **L0 文档** | 仅 `*.md` | `make check-docs` | 测试 / 前端门禁 |
| **L1 配置** | `Makefile`、依赖 / lock、`scripts/`、CI、`deploy/`、前端配置 | `make check-fast`；触及测试发现 / 依赖 / 打包 / CI 行为时加 `make test` | `cov` / `frontend-coverage` / `e2e` |
| **L2 代码** | `src/`、`tests/`、`frontend/src`、`frontend/tests`、`migrations/` 等 | `make flow`；阶段收尾 / 发版 / 改覆盖率口径时 `make check` | — |

- 混合改动按最高级执行；拿不准按 L2（fail-safe）。
- 分级只约束本地内环与提交前自查；CI 始终跑全量门禁。
- L2 执行链按 H4：`make check-fast` → `make test` → 更新文档 → `make push`；任一步失败修完重跑。

## 4. 实施循环

1. **需求 / 方案**：S1 先落需求卡片；S2 再写 ADR，`Proposed → Accepted` 前完成人工评审。
2. **小步实现**：S2 按 P0 → P1 → P2；每期一个内聚改动，禁止把多期混成一次提交。
3. **内环**：每次改完跑 `make check-fast`；红了先修，不继续堆代码。
4. **测试同轮**：单测 / 接口 / 迁移与备份 / 前端 / e2e 按 H12 分层补齐，不留“以后再补”。
5. **回填**：每期完成更新 ADR `落地状态` 与 `交接`；需求变更先改 ADR 再改代码。
6. **移除**：需求作废或被替代时，直接删除 ADR、索引行与全仓引用；不保留 Superseded / Deprecated，编号不复用（H8）。

## 5. 收工与提交

1. 按第 3.2 节跑到对应级别全绿；机器类 H 条目的命令必须绿。
2. 更新 `CHANGELOG.md`（带 `(ADR NNNN Pn)`，S0 / S1 正常写条目）与相关文档。
3. commit 用 conventional commits（H2）：L0 `docs:`，L1 `chore:` / `ci:` / `build:`，L2 `feat:` / `fix:` / `refactor:` / `test:`。
4. 禁止 `--no-verify`、禁止跳过 prek（H1）；不擅自改 git config；未授权不 force push、不直推 main/master、不打 tag（H6）。
5. 推送按 H4 / H6；打 tag 与生产部署是人工卡点，未确认不执行。

## 6. AI 驱动结构（4 个角色）

| 阶段 | 角色 Skill | 产出 | 人工卡点 |
|---|---|---|---|
| A 需求 + B 方案 | `spec-writer` | 需求卡片；S2 的 ADR | 需求确认 / ADR 评审 |
| C 实现 + D 测试 | `implementer` | 代码、迁移、测试 | — |
| E 门禁 | `gate-runner` | 全绿门禁与自愈记录 | — |
| F 发布 + G 部署 | `release-manager` | 推送、tag、发布、部署 | 上线 tag |

阶段输入 / 产出 / 门禁的完整表以 `docs/AI_DRIVEN_DEV_FLOW.md` 为准。

## 7. 红线（完整口径在 CONSTRAINTS）

- 先方案后代码：S1 / S2 未经人工确认不得进入实现（H5）。
- 门禁失败只修根因：不跳过用例、不放宽覆盖率、不注释断言、不用参数绕过（H9-H12、H23）。
- 数据 / 权限 / 导出 / 部署类改动必须同时满足 `CONSTRAINTS.md` 对应 H 条目。
- 两条规则冲突时从严执行；与 ADR 冲突时先改 ADR 与台账，再写码。
- H 条目新增 / 修改 / 删除须人工确认，LLM 不得自行放宽。

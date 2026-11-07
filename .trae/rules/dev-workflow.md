# 开发工作流（强制）

> 门禁分级（L0/L1/L2 的判定与命令）以 [AGENTS.md](../../AGENTS.md)「门禁分级」为唯一口径；硬约束编号以 [docs/CONSTRAINTS.md](../../docs/CONSTRAINTS.md) 为准。

本规则覆盖 AGENTS.md 的门禁链，任何代码改动都必须遵守：

- 改动先按 AGENTS.md 定级，混合改动取最高级，拿不准按 L2（H3）。
- L2 执行链：`make check-fast` → `make test` → 更新项目文档 → `make push`；任一步失败就修，修完重跑（H4）；`make flow` = `check-fast` + `test`。
- 每期（P0/P1/P2）落地后回填 ADR「落地状态」与「交接」（仅 S2 项），`make adr-check` 校验（已并入各门禁）。
- 换会话 / 换 agent：先读 `docs/adr/README.md` 的「落地阶段」与目标 ADR 的「落地状态」「交接」，再跑基线（代码 `make check-fast`，纯文档 / 配置 `make check-docs`）。
- 禁 `--no-verify`、禁跳过 prek（H1）；conventional commits（H2）；不改 git config、未授权不 force push / 不直推 main / 不打 tag（H6）。

# Agent 执行卡（cndb）

> 本卡只做每轮 checklist；完整口径见 [AGENTS.md](../../AGENTS.md)、[AI_DRIVEN_DEV_FLOW.md](../../docs/AI_DRIVEN_DEV_FLOW.md)、[CONSTRAINTS.md](../../docs/CONSTRAINTS.md)。

1. **先读**：AGENTS → 本卡 → 当前 ADR 的「落地状态 / 交接」 → CONSTRAINTS 相关 H#。
2. **先定级**：需求按 S0 / S1 / S2，改动按 L0 / L1 / L2；拿不准升级。
3. **先方案**：S1 写需求卡片；S2 写卡片 + ADR；需求确认 / ADR 评审由人拍板，未确认不动代码。
4. **小步做**：S2 按 P0 → P1 → P2；每期一个内聚改动，改完即跑 `make check-fast`。
5. **同轮测试**：单测 / 接口 / 迁移 / 备份 / 前端 / e2e 一起补；不得注水或跳过用例。
6. **只认门禁**：按 L 级跑 `make check-docs` / `check-fast` / `flow` / `check`；失败只修根因并重跑。
7. **回填文档**：ADR 落地状态与交接、CHANGELOG、CONTEXT / docs；ADR 失效即删除，不留 Superseded。
8. **提交规范**：conventional commits（`docs:` / `chore:` / `feat:` / `fix:` / `test:` …）；禁 `--no-verify`、禁跳 prek。
9. **授权边界**：不改 git config；未授权不 force push、不直推 main/master、不打 tag。
10. **冲突从严**：规则冲突取最严；H 条目不得自行放宽，必须先改台账并人工确认。

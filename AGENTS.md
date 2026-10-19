# 开发工作流

- 每次改完代码必须依次执行：`make check-fast` → `make test` → 项目文档更新 → `make push`
- 任一步失败就修，修完重跑，全过才算完成
- 禁止 `--no-verify`、禁止跳过 pre-commit
- commit message 用 conventional commits

## 开工前（换会话 / 换 agent 必读）

1. 先读 [docs/AI_DRIVEN_DEV_FLOW.md](docs/AI_DRIVEN_DEV_FLOW.md) 与 [.trae/rules/](.trae/rules/) 下的规则；工具不自动加载时也必须手动读。
2. 找当前任务的 ADR：看 [docs/adr/README.md](docs/adr/README.md) 的「落地阶段」，再读 ADR 的「落地状态」与「交接」。
3. 跑一次 `make check-fast` 作为基线；不要假设上一轮全绿。

## 收工前

1. 回填 ADR 的「落地状态」与「交接」（做到哪期 / 下一步 / 已知坑）。
2. 更新 CHANGELOG（条目带 `(ADR NNNN Pn)`）与相关文档。
3. `make flow`（含 `adr-check`）全绿后再提交；推送按 [.trae/rules/dev-workflow.md](.trae/rules/dev-workflow.md) 执行。

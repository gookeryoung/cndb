# 开发工作流（强制）

本规则覆盖 AGENTS.md 的门禁链，任何代码改动都必须遵守。

- 每次改完代码依次执行：`make check-fast` → `make test` → 更新项目文档 → `make push`。
- 任一步失败就修，修完重跑，全过才算完成（`make flow` = `check-fast` + `test` 的快捷入口）。
- 禁止 `--no-verify`、禁止跳过 pre-commit（prek）。
- commit message 用 conventional commits（`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`）。
- 不擅自修改 git config；提交身份缺失时向用户确认，不要自行写入。
- 不在未获明确授权时 force push、不直推 main/master、不打 tag（打 tag 属上线卡点，须人工确认）。

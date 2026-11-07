# 开发工作流

> 每类内容只写一次：门禁分级以本文件为准，方案分级见 [.trae/rules/design.md](.trae/rules/design.md)，测试见 [.trae/rules/testing.md](.trae/rules/testing.md)，硬约束编号见 [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md)，阶段流水线见 [docs/AI_DRIVEN_DEV_FLOW.md](docs/AI_DRIVEN_DEV_FLOW.md)。其他地方只写一句摘要 + 链接 / H#。

## 门禁分级（先定性，再选门禁）

提交前用 `git diff --name-only` + `git status --short` 判定改动类型，**按最高级别执行**；拿不准按 L2 处理（fail-safe，H3）。

| 级别 | 判定范围（只看文件路径） | 必跑 | 跳过 |
|---|---|---|---|
| **L0 文档** | 仅 `*.md`（`docs/`、`CONTEXT.md`、`CHANGELOG.md`、`AGENTS.md`、`.trae/rules/`、`README.md` 等） | `make check-docs`（`gitkeep-check` + `adr-check` + `constraint-check`） | 所有测试与前端门禁 |
| **L1 配置** | 仅 `Makefile`、`pyproject.toml`、`ruff.toml`、`pyrefly.toml`、`pytest.ini`、`uv.lock`、`frontend/package.json`、`frontend/tsconfig*.json`、`frontend/eslint*`、`docker-compose*.yml`、`deploy/`、`scripts/`、`.github/`、`.codeup/` | `make check-fast`；**触及测试发现 / 依赖 / 打包 / CI 行为**（`pyproject.toml`、`pytest.ini`、lock 文件、workflow、`scripts/` 里的门禁脚本）时加跑 `make test` | `cov` / `frontend-coverage` / `e2e`（除非本次显式改覆盖率或 e2e 口径） |
| **L2 代码** | 命中 `src/`、`tests/`、`frontend/src`、`frontend/tests`、`migrations/` 等 | `make flow`（`check-fast` → `test`）；阶段收尾 / 发版 / 改覆盖率口径时 `make check` | — |

- 只改文档或项目配置时不跑 `make flow`：`test` / `cov` / `e2e` 对 Markdown 与 Makefile 目标增删没有判别力。
- 但**不能因为「主要改了文档」而降级**：同一次提交里既有代码又有文档 / 配置，按 L2 走全链。
- 分级只约束本地内环与提交前自查；CI 仍跑全量门禁，不因分级放宽。
- **L2 执行链**：`make check-fast` → `make test` → 更新项目文档 → `make push`；任一步失败就修，修完重跑（H4）。
- 禁止 `--no-verify`、禁止跳过 pre-commit（prek）（H1）；commit message 用 conventional commits（H2）：L0 `docs:`，L1 `chore:` / `ci:` / `build:`，L2 按改动性质（`feat:` / `fix:` / `refactor:` / `test:`）。

## 方案分级（先定性，再选方案载体）

新功能 / 行为变更先按 S0/S1/S2 定级（判定标准、流程与人工卡点见 [.trae/rules/design.md](.trae/rules/design.md)，门禁见 H5）：

- **S0 小改**：确认意图后直接实现，无需卡片与 ADR。
- **S1 常规功能**：需求卡片（可轻量），方案并入卡片，**不强制 ADR**。
- **S2 重大项**：需求卡片 + ADR，走完整流程。
- 拿不准按上一级处理；实现中发现设计分叉，S1 升级为 S2 补 ADR。

## 硬约束

全仓硬约束的**唯一编号源**是 [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md)（H1..Hn，ADR 0119）：违反即打回的护栏，覆盖流程门禁、覆盖率与测试、数据迁移、权限不变量、发布部署。本文件与 `.trae/rules/`、ADR、`docs/AI_DRIVEN_DEV_FLOW.md` 只做「一句话 + H#」引用，不复制完整口径。

- **冲突处理**：两条约束冲突时从严执行；硬约束与 ADR 口径冲突时，先改 ADR 与台账再写码。
- **变更流程**：H 条目新增 / 修改 / 删除须人工确认（视同 S2 口径变更），LLM 不得自行放宽。
- **校验**：`make constraint-check`（已并入 `check-docs` / `check-fast`）。

## 开工前（换会话 / 换 agent 必读）

1. 读 [docs/AI_DRIVEN_DEV_FLOW.md](docs/AI_DRIVEN_DEV_FLOW.md) 与 [.trae/rules/](.trae/rules/) 下的规则；工具不自动加载时也必须手动读。
2. 对表 [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md)：设计若触碰任一 H#，先核对口径再动手。
3. 找当前任务的 ADR：看 [docs/adr/README.md](docs/adr/README.md) 的「落地阶段」，再读 ADR 的「落地状态」与「交接」。
4. 跑一次基线：代码任务 `make check-fast`，纯文档 / 配置任务 `make check-docs`；不要假设上一轮全绿。
5. 门禁卡住先看 `make env-guard` 体检结论（内置为前置，H23）；若报 sqlite3 缺 `deserialize`，多为 shell 注入了 `LD_LIBRARY_PATH`，`unset LD_LIBRARY_PATH` 后重跑，不要用 pytest 参数或超时绕过。

## 收工前

1. 有 ADR 的需求（S2）回填「落地状态」与「交接」（做到哪期 / 下一步 / 已知坑）。
2. 更新 CHANGELOG（ADR 条目带 `(ADR NNNN Pn)`）与相关文档。
3. 按「门禁分级」跑到对应级别全绿；机器校验类 H 条目命令至绿；推送按 H6 执行。

## 需求移除 / 变更

1. 有 ADR 的需求先清理 ADR 再改代码；S0 / S1 需求直接改代码与文档。
2. ADR 被替代或需求作废：**直接删除**该 ADR 文件、索引行与全仓引用，编号不复用，删除前先迁移仍生效的 H 条目（H8）。
3. 细则见 [.trae/rules/design.md](.trae/rules/design.md)；`make adr-check` 会校验索引与 Related 链接一致。

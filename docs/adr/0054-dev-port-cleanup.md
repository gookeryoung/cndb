# ADR 0054: `make dev` 启动前检查并释放开发端口

Status: Proposed（待评审）
Date: 2026-10-28
Related: `Makefile`、`scripts/free_ports.py`、`src/cndb/cli/main.py`
需求卡片: `docs/requirements/0054-dev-port-cleanup.md`

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 「参考lmstock,make dev检查和停用端口」 | `make dev` 依赖 `free-dev-ports`，启动前释放 `DEV_PORTS = $(DEV_PORT) 5173` |
| C2 | 同上 | `free_port()` 先 SIGTERM、等 2s、再 SIGKILL；任一端口释放失败则脚本退出 1，make 中止启动 |
| C3 | 同上 | `pids_on_port()` 按平台分派：Linux `/proc`、macOS `lsof`、Windows `netstat` + `taskkill /T /F` |
| C4 | 「按 Ctrl+C 停止所有服务」 | 不改 `cndb dev` 及其 `DEV_HOST` / `DEV_PORT` 覆盖；仅新增前置目标 |
| C5 | 同上 | 逻辑集中在 `scripts/free_ports.py`，`make free-dev-ports` 可单独执行 |

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | `dev:` 直接执行 `uv run cndb dev`，无端口前置检查 | `Makefile:41` | 上次遗留的 uvicorn 仍监听 8772 时后端 `[Errno 98] Address already in use` | 确认 |
| 2 | CLI `dev()` 后端端口取 `args.port`，前端固定 5173 | `src/cndb/cli/main.py:157` | 后端失败退出后前端 Vite 仍启动，形成半启动状态，需手工 kill | 确认 |
| 3 | Makefile 约定跨平台逻辑放 `scripts/` | `scripts/clean.py`、`scripts/check_gitkeep.py` | 有现成落点，无需内联 shell | 确认 |
| 4 | lmstock 已有同口径实现 | `/home/zhou/lmstock/scripts/free_ports.py` | 可直接对齐 PID 发现 / 结束策略 | 新增（参考实现） |

**核心缺陷（需求要补的）**：`make dev` 把「端口是否可用」留给子进程被动报错，半启动后现场（后端报错 + 前端已监听）不一致。

设计目标（不变量）：

- **I1 启动前释放**：`make dev` 在起任何服务前完成 `DEV_PORTS` 释放，成功才继续。
- **I2 只看监听态**：只结束处于 LISTEN 的进程，已建立的连接不算占用。
- **I3 释放失败即中止**：端口仍被占用时脚本退出非 0，不启动后半段服务。
- **I4 可单独执行且可覆盖**：`make free-dev-ports` 独立可用，`DEV_PORT` 覆盖时释放集合同步变化。

## Decision

### 1. 数据模型

无（不涉及表 / 列 / 迁移）。

### 2. 判定算法（唯一入口）

`scripts/free_ports.py`：

- `pids_on_port(port) -> set[int]`：Windows 走 `_pids_via_netstat`；存在 `/proc/net` 走 `_pids_via_proc`；否则 `lsof` 可用时走 `_pids_via_lsof`；最后剔除自身 PID。
- `free_port(port) -> bool`：无监听 → True；有监听 → 逐个 `_terminate(pid)`（SIGTERM），`_wait_released(port, 2.0)` 成功 → True；仍占用 → 对剩余 PID `_terminate(force=True)`（SIGKILL）再等 2s；仍失败 → False。
- `main(argv)`：逐个端口执行（不短路），全部成功返回 0，否则 1；无参数返回 2。

### 3. API 变更清单

无（不涉及 HTTP 端点）。

### 4. 边界与例外

1. 只能结束当前用户有权限结束的进程；`OSError` / `taskkill` 失败打印提示并视为未释放，由调用方退出非 0。
2. `/proc` 扫描只读 `tcp` / `tcp6` 的 `0A`（LISTEN）行，避免误伤连接态进程。
3. `lsof` / `netstat` 缺失或超时按「未发现占用」处理，不阻断启动。
4. 不校验进程归属：按端口结束，与参考实现 lmstock 一致；输出 PID 便于追溯。

### 5. 迁移

无（存量开发环境无需迁移；旧进程由首次 `make dev` 自动清理）。

### 6. 前端

无（Vite 启动参数不变，5173 仅作为释放目标）。

### 7. 测试清单

**判定层（单测）**：`tests/test_free_ports.py` 覆盖平台分派与自身 PID 剔除、lsof / netstat 输出解析与工具缺失、SIGTERM→SIGKILL 升级、仍占用失败、`main` 退出码与逐端口不短路、Makefile `dev` 前置接线。

**接口层**：无（不改 HTTP 接口）。

**迁移 / 备份**：无。

**e2e（前端）**：无（属本地开发脚本，不进 Playwright）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `scripts/free_ports.py` + Makefile `free-dev-ports` / `dev` 前置 + 单测 | 低：结束进程范围按监听端口，可能误杀同端口其它服务 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 端口释放放在哪一层 | 独立脚本 + Makefile 前置目标 | 符合仓库「跨平台逻辑放 scripts/」约定，且可单测、可单独执行（C5） | 写进 `cndb dev`（CLI 需再引入进程管理，且难以单独演练）；Makefile 内联 shell（跨平台不可维护） | `scripts/free_ports.py`、`Makefile:38` |
| D2 | 结束策略 | SIGTERM → 等 2s → SIGKILL | 给 uvicorn / Vite 优雅退出机会，超时才强杀 | 直接 SIGKILL（跳过监听器关闭，易留僵尸）；只 SIGTERM（无响应进程会一直占用） | `scripts/free_ports.py:115`、`:139` |
| D3 | 释放哪些端口 | `DEV_PORTS ?= $(DEV_PORT) 5173` | 与 CLI `dev()` 的后端 `--port` / 前端固定 5173 对齐（C1、C4） | 只释放后端端口（残留 Vite 仍会抢 5173）；硬编码 8772（覆盖 `DEV_PORT` 后失效） | `Makefile:15`、`src/cndb/cli/main.py:157` |
| D4 | 是否按进程归属过滤 | 不区分，按监听端口结束 | 与 lmstock 一致；跨平台取 cwd / cmdline 不可靠，且旧进程来源可能已变（C1） | 仅杀本仓库进程（可能漏掉需清理的旧进程，启动仍失败） | `scripts/free_ports.py:101` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：`make dev` 不再因上次残留进程半启动；端口检查可单独执行；释放逻辑有单测与跨平台分支。
- **负向**：多一个前置步骤（端口空闲时仅一次 `/proc` 扫描，开销可忽略）；按端口结束进程可能误杀同端口其它项目。
- **风险与缓解**：误杀风险通过输出 PID 与文档化端口约定缓解；后续如需限定进程归属，可在脚本内加 cwd / cmdline 白名单而不改调用方式。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `scripts/free_ports.py`、`Makefile` | `tests/test_free_ports.py` | 待提交 |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0（实现与单测完成，待评审回填 Status）
- 已完成：`scripts/free_ports.py`、Makefile `free-dev-ports` / `dev` 前置、`tests/test_free_ports.py`
- 下一步：人工评审 ADR，确认后 `Status: Proposed` → `Accepted`
- 已知坑：释放端口不区分进程归属；前端端口在 CLI 中仍固定 5173，若未来支持覆盖需同步 `DEV_PORTS`
- 最近一次全绿：`make flow` @ 待回填（2026-10-28）

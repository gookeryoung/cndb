# 需求卡片：`make dev` 启动前检查并释放开发端口

- 编号：0054（与 ADR `docs/adr/0054-dev-port-cleanup.md` 同号）
- 来源 / 提出人：用户（2026-10-28 会话，附 `make dev` 启动失败输出）
- 日期：2026-10-28
- 关联 ADR：`docs/adr/0054-dev-port-cleanup.md`（Proposed，待评审）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 参考lmstock,make dev检查和停用端口。按 Ctrl+C 停止所有服务
> INFO:     Will watch for changes in these directories: ['/home/zhou/cndb']
> ERROR:    [Errno 98] Address already in use
>
>   VITE v6.4.4  ready in 122 ms
>
>   ➜  Local:   http://localhost:5173/
>   ➜  Network: `http://192.168.3.88:5173/`

（后两段为 `make dev` 的实际输出：后端因端口被旧进程占用启动失败，前端 Vite 已单独起来，形成半启动状态。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「参考lmstock,make dev检查和停用端口」 | `make dev` 启动前检查后端 `DEV_PORT`（默认 8772）与前端 5173 的监听占用 | `Makefile`、`scripts/free_ports.py` | `make free-dev-ports`；`tests/test_free_ports.py` 锁 Makefile 接线 |
| C2 | 同上 | 被占用时先 SIGTERM 结束占用进程，超时未释放再 SIGKILL；释放成功才继续启动 | `scripts/free_ports.py` | 单测：优雅结束 / 强制结束 / 仍占用返回失败 |
| C3 | 同上 | 跨平台：Linux 走 `/proc`，macOS 走 `lsof`，Windows 走 `netstat` + `taskkill /T /F` | `scripts/free_ports.py` | 单测：分支分派与输出解析 |
| C4 | 「按 Ctrl+C 停止所有服务」 | 不改变现有 `cndb dev` 启动方式、默认端口与 `DEV_PORT` / `DEV_HOST` 覆盖能力；Ctrl+C 仍一起停前后端 | `Makefile`、`src/cndb/cli/main.py` | 人工 `make dev` + Ctrl+C；既有 CLI 测试不变 |
| C5 | 同上 | 端口释放逻辑不写进 Makefile 内联 shell，统一放 `scripts/` 并可单独执行 | `Makefile`、`scripts/free_ports.py` | `make free-dev-ports` 可独立运行 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `make dev` 直接启动 `cndb dev`，无端口前置检查 | `Makefile:36` | 旧进程占用即 Errno 98 |
| 2 | 后端 / 前端端口来源 | `src/cndb/cli/main.py:136` | 后端取 `--port`，前端固定 5173 |
| 3 | 跨平台脚本先例 | `scripts/clean.py`、`scripts/check_gitkeep.py` | Makefile 只做编排 |

## 未决问题

- [x] 释放端口时是否需要区分进程归属（只杀本仓库进程）？→ 不区分，按监听端口释放，与 lmstock 一致；输出 PID 便于追溯。
- [x] 后端端口可覆盖时前端 5173 是否跟随？→ 暂不跟随，CLI 前端端口仍固定 5173，释放集合与之一致。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认（待人工确认后转 Accepted）

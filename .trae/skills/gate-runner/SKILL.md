---
name: gate-runner
description: Use to run cndb gates and drive failures to green before a change is considered done. Fix root causes, never bypass hooks or exclude tests.
---

# 门禁自愈（gate-runner）

1. 按改动级别运行：`make check-docs`（L0）/ `make check-fast`（L1）/ `make flow` 或 `make check`（L2，按 AGENTS）。
2. 失败先跑 `make env-guard` 排除环境问题（H23），再定位根因。
3. 只改代码 / 测试 / 文档修根因；禁止 `--no-verify`、跳过 prek、`-k` / `--ignore` 排除用例、注释断言、放宽覆盖率。
4. 修完重跑失败项，再跑一次完整级别门禁；记录未解决风险而不是隐瞒。
5. L2 收尾按 H4：`check-fast` → `test` → 文档 → `make push`；推送授权边界见 H6。
6. 不通过「删落地表 / 改回未开始」让 `adr-check` 变绿；实际没做就补实现或拆期。

## 停止条件

- 对应级别门禁全绿；CI 同口径通过；
- 没有以任何方式绕过或降低门槛。

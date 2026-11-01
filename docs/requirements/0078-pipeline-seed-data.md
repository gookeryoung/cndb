# 需求卡片：质量检查流水线种子数据（pipelines/*.yaml）

- 编号：0078
- 来源 / 提出人：用户（"有无典型SEED数据，如果无请增加。"）
- 日期：2026-11-01
- 关联 ADR：无（复用 ADR 0076 既有设计，无架构分叉，不立项 ADR）

> 本卡片是**需求原文与约束编号的唯一副本**。

## 需求原句（逐字）

> 有无典型SEED数据，如果无请增加。

（语境：上一轮交付的流水线检查 DSL 使用文档（ADR 0076），`cndb seed` 现无质量检查种子。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 典型 SEED 数据 | `cndb seed` 注入典型流水线定义（覆盖 table 检查族、document 检查族、事件 / 定时 / 手动触发、表达式用法） | `src/cndb/cli/seed/` | `tests/test_seed_pipelines.py` |
| C2 | 结合已有工作区 | 示例只引用 examples/datasets 既有工作区与真实表 / 字段（某企业销售管理、数据源示例）；表引用在 seed 期校验，引用不存在则告警跳过 | `examples/datasets/` | 同上（真实配置用例） |
| C3 | 声明式种子载体 | 对齐 `documents/` 目录范式：每工作区 `pipelines/*.yaml`，一份 YAML = 一条定义；保存期经 `compile_workflow` 全量编译校验，非法样例跳过不落库 | `src/cndb/cli/seed/pipelines.py` | 单测：坏 YAML 跳过、合法样例落库 |
| C4 | 幂等与降级 | 同 `(workspace_id, name)` 已存在则跳过；datasets 目录缺失 / 无 pipelines/ 目录返回 0 优雅降级；只注入定义不触发运行 | `seed/runner.py` | 单测：重复注入 0 新增、缺目录 0 |
| C5 | 文档同步 | PIPELINE_DSL.md 入口节注明 seed 来源；CONTEXT.md 种子清单补一行；CHANGELOG 记录 | `docs/` | `make check-docs` |

## 现状影响面（候选，待核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `cndb seed` 编排 | `src/cndb/cli/seed/runner.py` | 末尾追加一个种子步骤，纯新增 |
| 2 | 示例数据资产 | `examples/datasets/<工作区>/` | 新增 pipelines/ 子目录，不动既有文件 |

## 未决问题

- [x] 载体选 JSON 内嵌 YAML 还是独立 yaml 文件？→ 独立 `pipelines/*.yaml`（对齐 documents/ 目录范式，YAML 可读可复制）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（用户明确指示"请增加"）

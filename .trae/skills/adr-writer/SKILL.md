---
name: adr-writer
description: Use when a requirement card or feature intent needs a design decision document in the cndb repo. Produce or update an ADR at docs/adr/NNNN-<topic>.md following docs/adr/TEMPLATE.md and the ADR 0004 house style, verifying the current state against real code with file:line references. Research and design only — do not implement.
---

# ADR 撰写（cndb）

把需求卡片 / 功能意图写成 ADR，作为实现前的唯一方案依据。此阶段只做调研与设计。

## 输入

- 需求卡片（来自 `requirement-intake`）或用户直接给出的需求
- 模板 `docs/adr/TEMPLATE.md`，范式参考 `docs/adr/0004-row-level-permission-rules.md`

## 步骤

1. 复用 ADR 0004 的「口径（先对齐需求措辞）」手法：需求原句 → 可实施约束表。
2. **逐条核对现状**：用 Grep / Read 读真实代码，标注 `文件:行号`，列出核心缺陷（现模型无法表达的那件事）。
3. 定义不变量 I1..In（安全 / 兼容 / 单一判定等）。
4. 给出 Decision、API 变更清单、数据模型与迁移（幂等 + downgrade + 存量零迁移）、边界与例外、前端改动、测试清单、分期（P0/P1/P2）。
5. 收齐决策记录表 D1..Dn（议题 / 结论 / 依据 / 被否决项）。
6. 必要时补行业对照。

## 产出

- `docs/adr/NNNN-<topic>.md`（Status: Proposed）。

## 门禁 / 卡点

- 决策记录表无「待定」项；新术语写入 `CONTEXT.md`。
- **人工卡点**：方案评审通过后，Status 才改 `Accepted`，再交给 `implementer`。
- 分批实现时，按 ADR 的 P0/P1/P2 分期推进。

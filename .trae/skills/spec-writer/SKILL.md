---
name: spec-writer
description: Use when a raw cndb requirement needs an implementable spec or an ADR. Produce the requirement card for S1/S2, then the ADR for S2; research and design only, never implement code.
---

# 需求与方案（spec-writer）

## 输入

- 用户需求原句
- `AGENTS.md`、`docs/AI_DRIVEN_DEV_FLOW.md`、`CONTEXT.md`
- 当前 ADR 索引与相关代码

## 步骤

1. **定级**：按 AGENTS 3.1 判定 S0 / S1 / S2；S0 直接交给 implementer。
2. **需求卡片（S1 / S2）**：逐字保留需求原句，逐句拆 C1..Cn；粗查受影响代码，标候选 `file:line`；未决问题清零。模板 `docs/REQUIREMENT_CARD_TEMPLATE.md`。
3. **人工确认**：S1 卡片确认后才进入实现；S2 继续写 ADR。
4. **ADR（S2）**：口径表沿用 C1..Cn，只补设计落点；核对真实代码，写不变量 I#、决策 D#、边界、迁移、测试、分期。模板 `docs/adr/TEMPLATE.md`。
5. **登记**：ADR 写入 `docs/adr/README.md` 所属功能域；新术语写入 `CONTEXT.md`。
6. **评审**：`make adr-check` 通过；人工评审后将 Status 改为 Accepted，再交给 implementer。

## 停止条件

- S1：需求卡片经人工确认。
- S2：ADR 经人工评审并 Accepted，决策记录无「待定」。
- 不写实现代码，不改业务逻辑。

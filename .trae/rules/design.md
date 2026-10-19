# 方案与设计文档规范

新功能 / 行为变更必须先出方案，再写代码。

- 需求接入：把口语需求整理为**需求卡片**（模板 `docs/REQUIREMENT_CARD_TEMPLATE.md`），逐句拆成可实施约束。
- 方案制定：产出 **ADR** 放到 `docs/adr/NNNN-<topic>.md`（模板 `docs/adr/TEMPLATE.md`，范式参考 `docs/adr/0004-row-level-permission-rules.md`）。
- ADR 必含：口径对齐表、现状逐条核对（标注 `文件:行号`）、不变量 I1..In、决策记录表（D1..Dn）、API 变更清单、边界与例外、迁移、测试清单、分期（P0/P1/P2）。
- 门禁：ADR 从 `Proposed` → `Accepted` 前，决策记录表不得有「待定」项；新术语写入 `CONTEXT.md`。
- 人工卡点：需求确认、ADR 评审两处必须由人拍板，AI 不得自行进入实现。

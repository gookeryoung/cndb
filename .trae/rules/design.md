# 方案与设计文档规范

新功能 / 行为变更必须先出方案，再写代码。

- 需求接入：把口语需求整理为**需求卡片**（模板 `docs/REQUIREMENT_CARD_TEMPLATE.md`，存 `docs/requirements/NNNN-<topic>.md`），逐句拆成可实施约束并编号 C1..Cn。
- 方案制定：产出 **ADR** 放到 `docs/adr/NNNN-<topic>.md`（模板 `docs/adr/TEMPLATE.md`，范式参考 `docs/adr/0004-row-level-permission-rules.md`）。
- **结构只以模板为准**：ADR 的章节与字段不在本规则重复列举，改模板即改规范。
- **每类内容只写一次**：需求原文与约束编号 ← 需求卡片；现状核对 / 不变量 / 设计 / 测试 / 分期 ← ADR 正文；决策结论 ← ADR「决策记录」D1..Dn。ADR 引用卡片编号而不复制原文，不另写「已确认决策」清单，Consequences 不重复否决项。
- **需求移除 / 变更时先清理 ADR**：ADR 是首要清理对象 —— 失效的口径行、现状条目、决策 D 行、测试清单与分期一并删除或改写；不保留「历史方案」「以后可能用」段落，整节不适用写「无」。ADR 被新方案替代或需求作废：**直接删除**该 ADR 文件、索引行与全仓引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。
- 门禁：ADR 从 `Proposed` → `Accepted` 前，决策记录表不得有「待定」，且卡片约束 C1..Cn 在「口径」表中逐条有落点；新术语写入 `CONTEXT.md`。
- 人工卡点：需求确认（卡片）、ADR 评审两处必须由人拍板，AI 不得自行进入实现。

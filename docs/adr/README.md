# ADR 索引

> `Status` 口径：`Proposed`（待评审）/ `Accepted`（已评审）/ `Implemented`（已落地）。
> 落地阶段以各 ADR「落地状态」表为准；进度、下一步与已知坑看「交接」节。
> `make adr-check` 校验本索引、ADR 落地表与代码 / 测试 / CHANGELOG 的对应关系。

| 编号 | 标题 | Status | 落地阶段 | 代码 | 测试 | CHANGELOG |
|---|---|---|---|---|---|---|
| [0004](0004-row-level-permission-rules.md) | 行级权限规则 | Proposed | P0-P2 已落地（待评审） | `row_access.py`、`row_permissions.py` | `tests/test_row_*.py` | [未发布](../../CHANGELOG.md) |

## 说明

- ADR 0003（视图可见性三档模型）的文档已随视图权限调整移除（commit 30790638）；0004「与既有 ADR 的关系」保留其历史结论。
- 新增 ADR 时按 `NNNN-<topic>.md` 命名，并把编号、标题、Status、落地阶段补进本表。

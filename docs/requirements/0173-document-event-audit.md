# 0173 文档事件审计（S1）

- 编号：0173
- 来源 / 提出人：用户（会话 2026-11-26「先开批次 1」；批次范围见 `BACKLOG.md`）
- 日期：2026-11-26
- 关联 ADR：无（S1，方案并入本卡片；沿用 `core/events.py` 统一事件表）

> 本卡片是需求原文与约束编号的唯一副本：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 先开批次 1。

（批次 1 在 `BACKLOG.md` 中定义为「0173 文档事件审计（CRUD / 移动 / 回滚 / 分享写
`core_event`，管理台可查）」。）

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「CRUD … 写 core_event」 | 文档创建 / 正文更新 / 删除（软删）/ 从回收站恢复 / 版本回滚 / 跨工作区移动 / 创建副本，各写一条 `document.*` 事件；动作名固定：`document.create` / `document.update_content` / `document.delete` / `document.restore` / `document.rollback` / `document.move` / `document.duplicate` | `routers/documents.py`、`services/move.py` | 单测：逐动作断言 `core_event` 行数 + action |
| C2 | （隐私 H38） | `summary` 只含标题（≤255），`detail` 只含 id / 版本号 / 目标工作区等定位信息，**不含正文** | 同上 | 单测：事件 detail 不含提交正文片段 |
| C3 | （可用性） | 事件写入尽力而为：`record_event` 内部已吞异常，不得因审计失败让主流程 500 | `core/events.py` | 单测：monkeypatch 写事件抛错，接口仍 200/201 |
| C4 | 「管理台可查」 | 复用既有 `GET /api/v1/events`（按 action / actor / 时间过滤），不新增查询端点；文档动作可在管理台审计列表筛出 | `core/events_api.py` | 接口单测：按 `document.create` 过滤能命中 |
| C5 | （测试 / 文档） | 后端单测 + CHANGELOG；本卡回填落地结果 | 测试、`CHANGELOG.md` | 定向测试全绿 |

## 现状影响面（候选）

| # | 受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 统一事件写入 | `core/events.py::record_event` | 唯一入口，`target_type="document"` |
| 2 | 文档写端点 | `routers/documents.py` | 事件落点集中在端点，避免服务层重复 |
| 3 | 跨区移动 | `services/move.py` | 已有存储快照事件，补文档域事件 |
| 4 | 审计查询 | `core/events_api.py` | C4 复用 |

## 未决问题

- [x] 是否记录正文快照（2026-11-26 结论）：不记录，避免事件表膨胀与隐私风险；需要内容对比走版本历史。

## 卡点

- [x] 每条需求句都有 C 编号约束
- [x] 未决问题有结论

## 落地结果

- 代码落点：`routers/documents.py::_audit_document`（创建 / 改正文 / 删除 / 恢复 / 回滚 / 复制、跨区移动各一条 `document.*` 事件），复用 `core/events.record_event` 与既有事件查询；`detail` 只含版本号 / 大小 / 目标工作区等定位信息。
- 测试：`tests/test_documents_event_audit.py` 3 例（增改事件且不含正文、删除/恢复/回滚/复制的动作、审计失败不阻断 201）。
- 提交 sha：52403b88。

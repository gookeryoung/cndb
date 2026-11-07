---
name: implementer
description: Use when implementing a confirmed S0/S1 requirement or an Accepted S2 ADR in cndb. Implement in phases, write tests in the same round, and keep make check-fast green.
---

# 实现与测试（implementer）

## 输入

- S0：已确认的意图；S1：需求卡片；S2：Accepted ADR
- `AGENTS.md`、`docs/AI_DRIVEN_DEV_FLOW.md`、相关 H#

## 步骤

1. **拆步**：S2 按 P0 → P1 → P2；S0 / S1 按最小内聚改动拆步。
2. **后端**：遵循 `plugins/<name>/` 分层；动态表 DDL 走 SQLAlchemy Core；迁移幂等 + downgrade + 存量零迁移；新表纳入 `backup_io`。
3. **前端**：`frontend/src/`，API 类型与后端对齐；样式遵守 `DESIGN_SYSTEM.md` 与 H24 / H25 / H29 / H30。
4. **测试同轮**：单测 / 接口 / 迁移 / 备份 / 前端 / e2e 按 H12 分层补齐，不注水。
5. **内环**：每改完跑 `make check-fast`；失败修根因后重跑。
6. **回填**：每期更新 ADR 落地状态与交接；最后更新 CHANGELOG 与相关文档。

## 停止条件

- 目标 L 级门禁全绿；
- S2 的落地表与实际代码 / 测试一致；
- 不做未授权的提交、推送、打 tag。

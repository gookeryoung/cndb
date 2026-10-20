"""数据源同步插件 —— 周期性外部数据接入（Provider × SyncJob × Cursor × Normalizer）.

M1（当前阶段）只落地领域无关的抓取管线：

- providers/  Provider 适配器（请求构造 → 响应解析 → 字段归一）
- services/   Normalizer（字段映射 + 类型归一）、抓取管线、落表 upsert

调度、同步任务表与 API 端点分属 M2 / M3，本阶段不建表、不起线程。
"""

from __future__ import annotations

__all__: list[str] = []

"""采集策略服务层（ADR 0085）.

- ``rules/``       纯函数规则引擎：表达式 / 筛选 / 去重（P0）；关键词与扩展（P1）
- ``channels.py``  渠道展开：策略声明 → 内存 ``SyncJobSpec``
- ``targets.py``   落点分发：表 upsert + 条目台账
- ``runner.py``    唯一执行入口：租约 / 轮次 / 状态机 / 留痕
- ``validation.py``保存期规则校验（错误文案直接回前端）
"""

from __future__ import annotations

__all__: list[str] = []

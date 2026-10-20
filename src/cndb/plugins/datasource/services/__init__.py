"""datasource 服务层（抓取管线 / 归一 / 落表）.

不在此做 re-export：``providers`` 与 ``services`` 互相依赖（provider 用 normalize、
registry 装配 provider），集中导入会形成循环。
"""

from __future__ import annotations

__all__: list[str] = []

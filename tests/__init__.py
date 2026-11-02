"""测试包：在任何测试模块 import sqlite3 之前清理会污染动态库的运行时变量.

Trae 会向子进程注入 ``LD_LIBRARY_PATH``，它自带的旧版 libsqlite3 不含
``sqlite3_deserialize``。``_sqlite3`` 扩展一旦链接到旧库，``import sqlite3`` 会直接卡住，
表现为 pytest 长时间无输出。Makefile 已 ``unexport LD_LIBRARY_PATH``，但直接
``uv run pytest`` 会绕过它；包导入发生在 conftest 与全部测试模块之前，在这里清掉即可覆盖。
"""

from __future__ import annotations

import os

os.environ.pop("LD_LIBRARY_PATH", None)

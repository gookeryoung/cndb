"""开发环境体检：拦截会让后端测试长时间卡死的运行时污染.

Trae 会给子进程注入 ``LD_LIBRARY_PATH``，其中自带的旧版 libsqlite3 不含
``sqlite3_deserialize``。Python 的 ``_sqlite3`` 扩展一旦链接到它，
``sqlite3.Connection.deserialize`` 就消失：轻则用例报错，重则在 ``import sqlite3``
处卡住，表现为 ``make test`` / ``make cov`` 长时间没有任何输出（不是用例慢，是进程
卡在动态库加载）。

Makefile 已用 ``unexport LD_LIBRARY_PATH`` 净化 make 启动的 recipe；本脚本把同一条防线
前移到全部门禁的入口：环境不健康时 1 秒内给出结论与修复命令，而不是让门禁跑到超时。

用法::

    python scripts/check_env.py

退出码 0 表示环境健康，1 表示必须先修复当前 shell 的环境再跑门禁。
"""

from __future__ import annotations

import os
import sys

# 会改写动态库搜索顺序的变量：命中即提示，避免下次换终端又踩同一个坑
_LIB_PATH_VARS: tuple[str, ...] = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")


def probe() -> tuple[bool, str, str]:
    """探测当前解释器的 sqlite3 是否具备 deserialize 能力.

    Returns:
        (是否可用, 失败原因（可用时为空串）, SQLite 版本).
    """
    try:
        import sqlite3
    except Exception as exc:  # 动态库加载失败时 import 本身就抛错，需要翻译成人话
        return False, f"import sqlite3 失败（{exc}）", "未知"

    version = sqlite3.sqlite_version
    if hasattr(sqlite3.Connection, "deserialize"):
        return True, "", version
    return (
        False,
        "当前 Python 链接的 libsqlite3 未启用 sqlite3_deserialize（缺少 sqlite3.Connection.deserialize）",
        version,
    )


def polluted_vars() -> dict[str, str]:
    """返回当前 shell 中非空、且会改写动态库搜索路径的变量."""
    return {name: value for name in _LIB_PATH_VARS if (value := os.environ.get(name, ""))}


def print_fix_guide(polluted: dict[str, str]) -> None:
    """打印可在当前平台直接复制的修复命令."""
    print()
    print("修复（任选其一，改完重跑本脚本确认）：")
    for name, value in polluted.items():
        print(f"  - 当前 {name}={value}")
    print("  1) bash / zsh：unset LD_LIBRARY_PATH")
    print("  2) PowerShell：Remove-Item Env:LD_LIBRARY_PATH -ErrorAction SilentlyContinue")
    print("  3) 直接走 make 目标（Makefile 已 unexport，recipe 不会继承该变量）：make flow / make test")
    print("  4) 换一个不带该变量的终端或重新打开 IDE 面板后再跑")
    print()
    print("根因：Trae 注入的旧版 libsqlite3 缺 sqlite3_deserialize，后端测试会卡在 import 阶段而不报错。")


def main() -> int:
    ok, reason, version = probe()
    polluted = polluted_vars()

    if not ok:
        print(f"[env] 环境不健康：{reason}")
        print(f"[env] 解释器：{sys.executable}")
        print(f"[env] 已加载 SQLite：{version}")
        if not polluted:
            print("[env] 未发现 LD_LIBRARY_PATH / DYLD_LIBRARY_PATH；请检查 PATH 或虚拟环境是否链接了旧版 libsqlite3。")
        print_fix_guide(polluted)
        return 1

    print(f"[env] ok：Python {sys.version.split()[0]} / SQLite {version} / deserialize 可用")
    if polluted:
        print(f"[env] 提示：{'、'.join(polluted)} 已设置，但当前 sqlite3 能力正常（Makefile 已 unexport）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

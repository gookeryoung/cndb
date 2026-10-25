"""示例资产定位（ADR 0029 §3）.

搜索顺序与 `cndb seed` 同口径：包内 `cndb/datasets` 优先（wheel 由 hatch 打包），
仓库根 `examples/datasets` 兜底（源码开发版）。本模块**不 import seed**，
目录缺失时返回 None，由路由决定「清单可读、下载 404」。
"""

from __future__ import annotations

import re
from pathlib import Path

from cndb.plugins.help.services.examples import SCENARIO_DIRECTORIES, find_example

# 只接受纯文件名：不含路径分隔符、必须以 .csv 结尾（阻断路径穿越）
_FILENAME_PATTERN = re.compile(r"^[^/\\]+\.csv$")


def _candidate_dirs() -> tuple[Path, Path]:
    """返回 (包内 datasets, 仓库根 examples/datasets) 两个候选目录."""
    here = Path(__file__).resolve()
    # src/cndb/plugins/help/services/assets.py → parents[3] = src/cndb
    packaged = here.parents[3] / "datasets"
    # 再向上两级即仓库根（src 的上层）
    repo = here.parents[5] / "examples" / "datasets"
    return packaged, repo


def datasets_dir() -> Path | None:
    """定位 datasets 根目录；两处都不存在时返回 None."""
    for candidate in _candidate_dirs():
        if candidate.is_dir():
            return candidate
    return None


def resolve_example_file(scenario: str, filename: str) -> Path | None:
    """校验白名单并返回 CSV 文件路径；不合法或文件缺失时返回 None.

    `scenario` 必须在清单内，`filename` 必须是该场景 `tables[].file` 登记过的
    纯 `.csv` 文件名——任一条不满足都不会触碰文件系统之外的内容。
    """
    example = find_example(scenario)
    if example is None or not _FILENAME_PATTERN.match(filename):
        return None
    if filename not in {table["file"] for table in example["tables"]}:
        return None

    root = datasets_dir()
    if root is None:
        return None
    path = root / SCENARIO_DIRECTORIES[scenario] / filename
    return path if path.is_file() else None


__all__ = ["datasets_dir", "resolve_example_file"]

"""datasets 目录定位与工作区命名辅助。

从原 cli/seed.py 拆出：所有 seed 子模块共用的路径解析入口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _get_datasets_dir() -> Path | None:
    """定位 datasets 目录（包内优先，fallback 仓库根，均找不到则返回 None 优雅降级）.

    搜索顺序：
    1. 包内 cndb/datasets/ —— wheel 安装版，由 hatch force-include 打包
    2. 仓库根 examples/datasets/ —— 源码开发版

    注意层级：本文件位于 <包根>/cndb/cli/seed/paths.py，故包根是 parents[2] 而非
    parent（parent 只是 cndb/cli/）。曾误写 parent，导致 wheel 安装版始终
    找不到 datasets，seed 静默降级成"只建账号、0 张数据表"。
    """
    pkg_datasets = Path(__file__).resolve().parents[2] / "datasets"
    if pkg_datasets.is_dir():
        return pkg_datasets
    # 本文件位于 src/cndb/cli/seed/paths.py，向上五级才是仓库根（包内层级较原 seed.py 深一层）
    src_root = Path(__file__).resolve().parents[4]
    candidate = src_root / "examples" / "datasets"
    if candidate.is_dir():
        return candidate
    return None


def _workspace_display_name(folder_name: str) -> str:
    """工作区文件夹名 → 显示名（剥离 "工作区-" 前缀，让前端显示更友好）."""
    if folder_name.startswith("工作区-"):
        return folder_name[len("工作区-") :]
    return folder_name


def _get_workspace_view_configs(datasets_dir: Path) -> dict[str, dict[str, Any]]:
    """扫描每个工作区文件夹下的 views.json.

    Returns:
        工作区显示名 -> 视图配置（表名 -> 视图列表）的映射.
    """
    return _scan_workspace_json(datasets_dir, "views.json", "seed-视图")


def _get_workspace_analytics_configs(datasets_dir: Path) -> dict[str, dict[str, Any]]:
    """扫描每个工作区文件夹下的 analytics.json（分析模板种子）.

    Returns:
        工作区显示名 -> 分析模板配置（表名 -> 模板列表）的映射.
    """
    return _scan_workspace_json(datasets_dir, "analytics.json", "seed-分析")


def _scan_workspace_json(datasets_dir: Path, filename: str, log_tag: str) -> dict[str, dict[str, Any]]:
    """通用扫描：工作区文件夹下的 ``filename`` → 解析为 JSON.

    Returns:
        工作区显示名 -> JSON 内容的映射（解析失败的工作区跳过并打印告警）.
    """
    result: dict[str, dict[str, Any]] = {}
    for folder in sorted(datasets_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        path = folder / filename
        if not path.is_file():
            continue
        try:
            result[_workspace_display_name(folder.name)] = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[{log_tag}] {folder.name}/{filename} 解析失败: {exc}")
    return result

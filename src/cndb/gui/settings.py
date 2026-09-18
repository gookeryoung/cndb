"""GUI 界面设置持久化（保存到 ``~/.cndb/config/gui.json``）.

将 GUI 各 Tab 的配置与主窗口几何信息（位置/尺寸）持久化到配置文件目录，
下次启动自动恢复，确保界面设置不因重启而丢失。

设计约定：
- 只依赖 ``cndb.core.config`` 提供的 CONFIG_DIR，不 import tkinter，
  便于在无显示环境（CI）下单元测试序列化逻辑。
- 字段类型限定为 ``str``/``bool``（Tk 控件的取值类型），加载时按字段当前
  类型做兼容转换，损坏/缺失字段回退到默认值。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cndb.core.config import CONFIG_DIR

# 配置文件路径（用户级）；写盘前目录由 core.config 在导入期确保存在
GUI_SETTINGS_FILE = CONFIG_DIR / "gui.json"

# 配置文件格式版本号，用于未来向后兼容迁移
_SETTINGS_FORMAT_VERSION = 1


@dataclass
class ServeConfig:
    """「启动服务」Tab 配置."""

    host: str = "127.0.0.1"
    port: str = "8000"
    reload: bool = False
    workers: str = "1"


@dataclass
class BackupConfig:
    """「备份恢复」Tab 配置."""

    output: str = ""
    mode: str = "auto"
    no_uploads: bool = False
    force: bool = False


@dataclass
class UsersConfig:
    """「用户管理」Tab 配置."""

    role: str = ""  # 列表页角色筛选值


@dataclass
class InfoConfig:
    """「系统信息」Tab 配置."""

    auto_refresh: bool = True  # 自动刷新默认开启
    interval: str = "10 秒"


@dataclass
class GuiSettings:
    """GUI 全部界面设置，持久化到 ``~/.cndb/config/gui.json``."""

    window_geometry: str = ""  # Tk geometry("WxH+X+Y")，空表示未保存过
    serve: ServeConfig = field(default_factory=ServeConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    users: UsersConfig = field(default_factory=UsersConfig)
    info: InfoConfig = field(default_factory=InfoConfig)

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典."""
        return {
            "version": _SETTINGS_FORMAT_VERSION,
            "window_geometry": self.window_geometry,
            "serve": {
                "host": self.serve.host,
                "port": self.serve.port,
                "reload": self.serve.reload,
                "workers": self.serve.workers,
            },
            "backup": {
                "output": self.backup.output,
                "mode": self.backup.mode,
                "no_uploads": self.backup.no_uploads,
                "force": self.backup.force,
            },
            "users": {
                "role": self.users.role,
            },
            "info": {
                "auto_refresh": self.info.auto_refresh,
                "interval": self.info.interval,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GuiSettings:
        """从字典还原；缺失/非法字段自动回退到默认值."""
        st = cls()
        st.window_geometry = _value_str(data.get("window_geometry"))
        _apply_section(st.serve, data.get("serve"))
        _apply_section(st.backup, data.get("backup"))
        _apply_section(st.users, data.get("users"))
        _apply_section(st.info, data.get("info"))
        return st


def _value_str(value: Any) -> str:
    """把任意值安全转成 str；None/空串归一为空串."""
    return str(value) if value not in (None, "") else ""


def _coerce(value: Any, target: type) -> Any:
    """按目标类型（str/bool）兼容转换输入值，失败返回 None."""
    try:
        if target is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if target is int:
            return int(value)
        return _value_str(value)
    except (TypeError, ValueError):
        return None


def _apply_section(obj: Any, raw: Any) -> None:
    """把字典中的合法字段合并进 dataclass 实例；raw 非 dict 时忽略."""
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        if not hasattr(obj, key):
            continue
        coerced = _coerce(value, type(getattr(obj, key)))
        if coerced is not None:
            setattr(obj, key, coerced)


def load_settings(path: Path | None = None) -> GuiSettings:
    """从配置文件读取 GUI 设置；文件缺失/损坏时返回默认设置.

    Args:
        path: 覆盖默认配置文件路径（便于测试注入临时文件）。
            传 ``None`` 使用 ``~/.cndb/config/gui.json``。
    """
    cfg_path = path or GUI_SETTINGS_FILE
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return GuiSettings()
    if not isinstance(data, dict):
        return GuiSettings()
    return GuiSettings.from_dict(data)


def save_settings(settings: GuiSettings, path: Path | None = None) -> None:
    """把 GUI 设置写入配置文件，自动补建父目录.

    Args:
        settings: 待持久化的设置对象。
        path: 覆盖默认配置文件路径（便于测试注入临时文件）。
    """
    cfg_path = path or GUI_SETTINGS_FILE
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

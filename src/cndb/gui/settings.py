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

import contextlib
import json
import logging
import os
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cndb.core.config import CONFIG_DIR

logger = logging.getLogger(__name__)

# 配置文件路径（用户级）；写盘前目录由 core.config 在导入期确保存在
GUI_SETTINGS_FILE = CONFIG_DIR / "gui.json"

# 配置文件格式版本号，用于未来向后兼容迁移
_SETTINGS_FORMAT_VERSION = 1

# 写盘重试次数与退避间隔：Windows 上文件被安全软件/同步客户端短暂占用时
# 立即重试通常就能成功，避免把可恢复的瞬时失败上报给用户
_SAVE_ATTEMPTS = 3
_SAVE_RETRY_INTERVAL_S = 0.1


@dataclass
class ServeConfig:
    """「启动服务」Tab 配置."""

    host: str = "0.0.0.0"
    port: str = "8000"


@dataclass
class BackupConfig:
    """「备份恢复」Tab 配置."""

    output: str = ""
    mode: str = "auto"
    no_uploads: bool = False
    force: bool = False


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
            },
            "backup": {
                "output": self.backup.output,
                "mode": self.backup.mode,
                "no_uploads": self.backup.no_uploads,
                "force": self.backup.force,
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


def _write_text_atomic(cfg_path: Path, payload: str) -> None:
    """原子写入文本：先写同目录临时文件，再整体替换目标文件.

    直接覆盖写在中途失败（磁盘满、进程被杀）时会留下截断的配置文件，
    下次启动解析失败即丢失全部界面设置。临时文件 + ``os.replace`` 保证
    目标文件要么是旧内容、要么是完整的新内容。
    """
    fd, tmp_name = tempfile.mkstemp(prefix=f"{cfg_path.name}.", suffix=".tmp", dir=cfg_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        tmp_path.replace(cfg_path)
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)


def _clear_readonly(cfg_path: Path) -> None:
    """清除 Windows 只读属性.

    只读文件无法被覆盖写，``open(..., "w")``/``os.replace`` 均报
    ``PermissionError: [Errno 13]``；这是该错误在 Windows 上最常见的成因。
    非 Windows 平台不做处理（POSIX 权限语义不同，避免误改文件 mode）。
    """
    if os.name != "nt" or not cfg_path.exists():
        return
    with contextlib.suppress(OSError):
        cfg_path.chmod(stat.S_IWRITE)


def save_settings(settings: GuiSettings, path: Path | None = None) -> bool:
    """把 GUI 设置写入配置文件，自动补建父目录.

    写盘失败不抛异常：先清除 Windows 只读属性并做短暂退避重试，仍失败则
    记录告警并返回 ``False``。GUI 关闭流程不能因设置持久化失败而卡死，
    最坏结果只是「本次界面调整下次启动不恢复」。

    Args:
        settings: 待持久化的设置对象。
        path: 覆盖默认配置文件路径（便于测试注入临时文件）。

    Returns:
        bool: 是否成功写入。
    """
    cfg_path = path or GUI_SETTINGS_FILE
    payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("保存 GUI 设置失败，配置目录不可写：%s（%s）", cfg_path.parent, exc)
        return False

    last_error: OSError | None = None
    for attempt in range(1, _SAVE_ATTEMPTS + 1):
        try:
            _write_text_atomic(cfg_path, payload)
            return True
        except OSError as exc:
            last_error = exc
            _clear_readonly(cfg_path)
            if attempt < _SAVE_ATTEMPTS:
                time.sleep(_SAVE_RETRY_INTERVAL_S)
    logger.warning("保存 GUI 设置失败，本次修改未持久化：%s（%s）", cfg_path, last_error)
    return False

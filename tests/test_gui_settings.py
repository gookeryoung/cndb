"""GUI 设置持久化模块（cndb.gui.settings）单测.

仅覆盖纯序列化逻辑，不依赖 Tkinter，可在无显示环境（CI）运行。
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from cndb.gui.settings import GuiSettings, load_settings, save_settings


def test_defaults_auto_refresh_enabled() -> None:
    """默认配置下系统信息自动刷新应开启."""
    s = GuiSettings()
    assert s.info.auto_refresh is True
    assert s.info.interval == "10 秒"
    assert s.serve.host == "0.0.0.0"
    assert s.serve.port == "8000"
    assert s.window_geometry == ""


def test_save_load_round_trip(tmp_path) -> None:
    """保存后应能完整还原所有字段."""
    cfg = tmp_path / "gui.json"
    src = GuiSettings()
    src.window_geometry = "1024x720+100+50"
    src.serve.host = "0.0.0.0"
    src.serve.port = "9000"
    src.backup.output = "/tmp/backup.tar.gz"
    src.backup.mode = "native"
    src.backup.no_uploads = True
    src.backup.force = True
    src.info.auto_refresh = False
    src.info.interval = "30 秒"

    save_settings(src, cfg)
    assert cfg.is_file()

    loaded = load_settings(cfg)
    assert loaded.window_geometry == "1024x720+100+50"
    assert loaded.serve == src.serve
    assert loaded.backup == src.backup
    assert loaded.info == src.info


def test_load_missing_file_returns_defaults(tmp_path) -> None:
    """配置文件不存在时返回默认设置，不抛异常."""
    loaded = load_settings(tmp_path / "nope.json")
    assert loaded.info.auto_refresh is True
    assert isinstance(loaded, GuiSettings)


def test_load_corrupt_json_returns_defaults(tmp_path) -> None:
    """配置文件损坏（非法 JSON）时返回默认设置."""
    cfg = tmp_path / "gui.json"
    cfg.write_text("{ 这不是合法的 json ", encoding="utf-8")
    loaded = load_settings(cfg)
    assert loaded == GuiSettings()


def test_load_non_dict_json_returns_defaults(tmp_path) -> None:
    """顶层不是字典的 JSON 返回默认设置."""
    cfg = tmp_path / "gui.json"
    cfg.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_settings(cfg) == GuiSettings()


def test_from_dict_unknown_fields_ignored() -> None:
    """未知字段与非法类型字段应被忽略，默认值保留."""
    s = GuiSettings.from_dict(
        {
            "window_geometry": None,
            "hacker_key": "oops",
            "serve": {"host": 8080, "bogus": "x"},
            "info": {"interval": "999 秒"},
        }
    )
    assert s.window_geometry == ""  # None → 空串
    assert s.serve.host == "8080"  # 数值按字符串字段转换
    assert s.info.interval == "999 秒"  # 字段存在即保留；合法性由 UI 层兜底


def test_save_creates_parent_dirs(tmp_path) -> None:
    """保存时自动补建嵌套父目录."""
    cfg = tmp_path / "nested" / "deep" / "gui.json"
    save_settings(GuiSettings(), cfg)
    assert cfg.is_file()


def test_save_returns_true_when_writable(tmp_path) -> None:
    """正常写盘返回 True."""
    assert save_settings(GuiSettings(), tmp_path / "gui.json") is True


def test_save_unwritable_target_returns_false(tmp_path) -> None:
    """目标不可写时返回 False 而不抛异常，且不残留临时文件.

    回归背景：Windows 上 gui.json 只读/被占用会使 write_text 抛
    PermissionError；若向上传播会阻断 GUI 关窗流程。
    """
    target = tmp_path / "gui.json"
    target.mkdir()  # 用目录占位，使替换目标必然失败
    assert save_settings(GuiSettings(), target) is False
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="只读文件属性是 Windows 语义")
def test_save_over_readonly_file_clears_attribute(tmp_path) -> None:
    """已有文件带只读属性时应自动清除后写入，而不是抛 PermissionError."""
    cfg = tmp_path / "gui.json"
    cfg.write_text("{}", encoding="utf-8")
    cfg.chmod(stat.S_IREAD)
    try:
        assert save_settings(GuiSettings(), cfg) is True
        assert json.loads(cfg.read_text(encoding="utf-8"))["version"] == 1
    finally:
        cfg.chmod(stat.S_IWRITE)

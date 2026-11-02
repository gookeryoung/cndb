"""帮助图示仓库：磁盘快照容错 / 重建回退 / 后台刷新线程（ADR 0030 §3）.

补的是「异常与生命周期」分支：索引损坏、SVG 缺失、写盘失败、单图生成失败、
刷新跳过与线程 start/stop/wake，以及 ``start_figure_refresher`` 的开关口径。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cndb.core.config import settings
from cndb.plugins.help.services.figures import store as store_mod
from cndb.plugins.help.services.figures.registry import FigureSpec
from cndb.plugins.help.services.figures.store import FigureRefresher, FigureStore


def _spec(key: str, build, *, digest: str = "v1") -> FigureSpec:
    return FigureSpec(
        key=key,
        title=f"图示 {key}",
        caption="",
        section="quick-start",
        build=build,
        data_digest=lambda: digest,
    )


@pytest.fixture()
def fake_registry(monkeypatch):
    """把仓库的图示注册表换成可控的假清单."""
    specs: list[FigureSpec] = []

    def _install() -> None:
        monkeypatch.setattr(store_mod, "FIGURE_SPECS", specs)
        monkeypatch.setattr(
            store_mod,
            "find_spec",
            lambda key: next((s for s in specs if s.key == key), None),
        )

    _install()
    return specs


def _svg(text: str = "ok") -> str:
    return f"<svg><text>{text}</text></svg>"


class TestEnsureLoaded:
    def test_ignores_removed_and_missing_snapshot(self, tmp_path: Path, fake_registry, monkeypatch) -> None:
        fake_registry[:] = [_spec("known", lambda: _svg("fresh"))]
        cache = tmp_path / "figures"
        cache.mkdir()
        (cache / "index.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": [
                        {"key": "removed", "fingerprint": "x", "generatedAt": 1},
                        {"key": "known", "fingerprint": "v1", "generatedAt": 1},  # 缺 SVG 文件
                    ],
                }
            ),
            encoding="utf-8",
        )
        store = FigureStore(cache_dir=cache)
        record = store.get("known")
        assert record is not None
        assert "fresh" in record.svg

    def test_corrupt_index_falls_back_to_rebuild(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = [_spec("known", lambda: _svg("rebuilt"))]
        cache = tmp_path / "figures"
        cache.mkdir()
        (cache / "index.json").write_text("{not json", encoding="utf-8")
        store = FigureStore(cache_dir=cache)
        assert "rebuilt" in (store.get("known") or store.get("known")).svg  # type: ignore[union-attr]

    def test_unreadable_index_type_ignored(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = [_spec("known", _svg)]
        cache = tmp_path / "figures"
        cache.mkdir()
        # items 不是列表：TypeError 走容错分支
        (cache / "index.json").write_text(json.dumps({"items": 1}), encoding="utf-8")
        store = FigureStore(cache_dir=cache)
        assert store.get("known") is not None


class TestDiskFailure:
    def test_write_failure_keeps_memory_snapshot(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = [_spec("known", _svg)]
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("", encoding="utf-8")
        store = FigureStore(cache_dir=blocker)  # mkdir 会失败 → 退化为内存快照
        record = store.get("known")
        assert record is not None
        assert store.get("known") is record


class TestRenderFallback:
    def test_build_failure_returns_stale_snapshot(self, tmp_path: Path, fake_registry) -> None:
        state = {"fail": False, "digest": "v1"}

        def _build() -> str:
            if state["fail"]:
                raise RuntimeError("画图炸了")
            return _svg("first")

        spec = _spec("known", _build)
        fake_registry[:] = [spec]
        store = FigureStore(cache_dir=tmp_path / "figures")

        first = store.get("known")
        assert first is not None
        state["fail"] = True
        state["digest"] = "v2"
        monkeypatch_spec = _spec("known", _build, digest="v2")
        fake_registry[:] = [monkeypatch_spec]
        # 指纹变化触发重建 → 失败回退到旧快照
        assert store.get("known") is first

    def test_build_failure_without_stale_raises(self, tmp_path: Path, fake_registry) -> None:
        def _boom() -> str:
            raise RuntimeError("画图炸了")

        fake_registry[:] = [_spec("known", _boom)]
        store = FigureStore(cache_dir=tmp_path / "figures")
        with pytest.raises(RuntimeError):
            store.get("known")

    def test_unknown_key_returns_none(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = []
        assert FigureStore(cache_dir=tmp_path / "figures").get("nope") is None


class TestRefresh:
    def test_skips_unchanged_and_swallows_failures(self, tmp_path: Path, fake_registry) -> None:
        def _boom() -> str:
            raise RuntimeError("画图炸了")

        fake_registry[:] = [_spec("ok", _svg), _spec("bad", _boom)]
        store = FigureStore(cache_dir=tmp_path / "figures")
        # 首轮：ok 重建 1 张，bad 失败被吞掉
        assert store.refresh() == 1
        # 次轮：指纹未变 → 跳过（0 张）
        assert store.refresh() == 0
        # force：ok 重建，bad 仍失败
        assert store.refresh(force=True) == 1

    def test_list_meta_reports_empty_fingerprint_for_failed_figure(
        self,
        tmp_path: Path,
        fake_registry,
        monkeypatch,
    ) -> None:
        fake_registry[:] = [_spec("bad", _svg)]
        # 清单与查找表不一致（历史快照 / 灰度场景）：find_spec 拿不到 → 元信息留空，不抛
        monkeypatch.setattr(store_mod, "find_spec", lambda key: None)
        store = FigureStore(cache_dir=tmp_path / "figures")
        meta = store.list_meta()
        assert meta[0]["fingerprint"] == ""
        assert meta[0]["generatedAt"] == 0.0


class TestReset:
    def test_reset_removes_disk_snapshot(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = [_spec("known", _svg)]
        cache = tmp_path / "figures"
        store = FigureStore(cache_dir=cache)
        assert store.get("known") is not None
        assert (cache / "known.svg").is_file()
        store.reset()
        assert not (cache / "known.svg").exists()
        assert not (cache / "index.json").exists()
        # reset 后可重新加载并重建
        assert store.get("known") is not None


class TestRefresher:
    def test_start_stop_and_wake(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = [_spec("known", _svg)]
        store = FigureStore(cache_dir=tmp_path / "figures")
        refresher = FigureRefresher(interval_seconds=0, startup_delay_seconds=0, store=store)
        try:
            assert refresher.running is False
            assert refresher.start() is True
            assert refresher.running is True
            # 幂等：已运行返回 False
            assert refresher.start() is False
            refresher.wake()
            refresher.stop()
            assert refresher.running is False
        finally:
            refresher.stop()

    def test_stop_waits_for_startup_delay(self, tmp_path: Path, fake_registry) -> None:
        fake_registry[:] = []
        store = FigureStore(cache_dir=tmp_path / "figures")
        refresher = FigureRefresher(interval_seconds=0, startup_delay_seconds=30, store=store)
        try:
            assert refresher.start() is True
            # stop 置位 Event 让首轮延迟等待立即返回（不阻塞 30s）
            refresher.stop(timeout=5.0)
            assert refresher.running is False
        finally:
            refresher.stop()


class TestModuleHandles:
    def test_store_and_refresher_handles(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(settings, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(settings, "HELP_FIGURES_ENABLED", False)
        try:
            store_mod.stop_figure_refresher()
            assert store_mod.get_figure_refresher() is None
            assert store_mod.start_figure_refresher() is None  # 开关关闭
            assert isinstance(store_mod.get_figure_store(), FigureStore)
        finally:
            store_mod.stop_figure_refresher()

    def test_start_refresher_enabled_is_singleton(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(settings, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(settings, "HELP_FIGURES_ENABLED", True)
        monkeypatch.setattr(settings, "HELP_FIGURES_INTERVAL_SECONDS", 0)
        monkeypatch.setattr(settings, "HELP_FIGURES_STARTUP_DELAY_SECONDS", 0)
        try:
            first = store_mod.start_figure_refresher()
            assert first is not None
            assert store_mod.get_figure_refresher() is first
            # 已在运行 → 复用同一实例
            assert store_mod.start_figure_refresher() is first
            # 后台线程起来后 stop 置位可退出
            store_mod.stop_figure_refresher()
            assert store_mod.get_figure_refresher() is None
            # 线程退出后再次启动可拿到新实例
            second = store_mod.start_figure_refresher()
            assert second is not None and second is not first
        finally:
            store_mod.stop_figure_refresher()

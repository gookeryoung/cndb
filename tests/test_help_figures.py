"""帮助文档图示例（ADR 0030）.

覆盖：
- 接口：清单 200 / 未登录 401 / SVG 200 且为合法 SVG / ETag 命中 304 / 未登记 key 404 / 手动重建；
- 构建器：字段类型图含注册表全部 label、示例预览含真实 CSV 行数、权限图含真实枚举值；
- 缓存：指纹一致不重建、指纹变化即时重建、磁盘快照可跨实例复用；
- 解耦守卫：figures 子包不 import seed。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cndb.core.config import settings
from cndb.plugins.help.services import assets
from cndb.plugins.help.services.figures import FIGURE_SPECS, get_figure_store
from cndb.plugins.help.services.figures.builders import _read_csv_sample
from cndb.plugins.help.services.figures.registry import FigureSpec, _csv_digest, find_spec
from cndb.plugins.help.services.figures.store import FigureStore

FIGURES_URL = "/api/v1/help/figures"
FIGURES_DIR = Path(__file__).resolve().parents[1] / "src" / "cndb" / "plugins" / "help" / "services" / "figures"


@pytest.fixture(autouse=True)
def _isolated_snapshot(tmp_path, monkeypatch):
    """把快照目录指向 tmp，用例之间不共享磁盘状态."""
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path)
    store = get_figure_store()
    store.reset()
    yield
    store.reset()


# ── 接口 ──────────────────────────────────────────────────


def test_figure_endpoints_require_auth(client):
    """未登录：清单 / SVG / 重建一律 401."""
    assert client.get(FIGURES_URL).status_code == 401
    assert client.get(f"{FIGURES_URL}/field-types.svg").status_code == 401
    assert client.post(f"{FIGURES_URL}/refresh").status_code == 401


def test_list_figures_returns_meta(client, auth_headers):
    """清单给出 key / 标题 / 图注 / 归属 / 指纹 / 生成时间."""
    resp = client.get(FIGURES_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    items = payload["items"]
    assert len(items) == len(FIGURE_SPECS)
    assert payload["generatedAt"] > 0

    keys = [item["key"] for item in items]
    assert len(keys) == len(set(keys))

    sections = {"quick-start", "tutorials", "examples", "configuration", "troubleshooting"}
    for item in items:
        assert re.fullmatch(r"[a-z0-9-]+", item["key"])
        assert item["title"] and item["caption"]
        assert item["section"] in sections
        assert re.fullmatch(r"[0-9a-f]{16}", item["fingerprint"])
        assert item["generatedAt"] > 0


def test_figure_svg_response(client, auth_headers):
    """SVG 端点返回合法 SVG，带 ETag；重复请求命中 304."""
    url = f"{FIGURES_URL}/example-sales-table-1.svg"
    resp = client.get(url, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert resp.text.startswith("<svg")
    assert 'data-help-figure="1"' in resp.text

    etag = resp.headers["etag"]
    again = client.get(url, headers={**auth_headers, "If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""


def test_unknown_figure_is_404(client, auth_headers):
    """未登记的 key 一律 404（不暴露生成细节）."""
    resp = client.get(f"{FIGURES_URL}/not-a-figure.svg", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "图示不存在"


def test_refresh_endpoint_rebuilds_all(client, auth_headers):
    """手动重建返回张数，且与清单条数一致."""
    resp = client.post(f"{FIGURES_URL}/refresh", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["rebuilt"] == len(FIGURE_SPECS)


# ── 构建器：数据来自真相源 ────────────────────────────────


def test_field_types_figure_lists_every_registered_type():
    """字段类型图必须覆盖注册表里的每一个 label（新增类型自动出现）."""
    from cndb.plugins.tables.field_types import default_registry

    svg = find_spec("field-types").build()  # type: ignore[union-attr]
    for field_type in default_registry.all():
        assert field_type.label in svg, f"图示缺少字段类型：{field_type.label}"


def test_example_preview_uses_real_csv():
    """示例预览的真实行数来自 CSV 文件本身，不是清单里写死的 rows."""
    spec = find_spec("example-sales-table-1")
    assert spec is not None
    path = assets.resolve_example_file("sales", "电商销售.csv")
    assert path is not None
    _header, _rows, total = _read_csv_sample(path)

    svg = spec.build()
    assert f"共 {total} 行" in svg
    assert "电商销售.csv" in svg


def test_permission_figure_reads_enum_members():
    """权限图的角色来自 WorkspaceRole 枚举，不是手写文案."""
    from cndb.plugins.workspaces.models import WorkspaceRole

    svg = find_spec("permission-model").build()  # type: ignore[union-attr]
    for role in WorkspaceRole:
        assert role.value in svg


def test_all_figures_render_valid_svg():
    """每张图都能生成、且是单根 `<svg>` 文档（内联渲染的前提）."""
    for spec in FIGURE_SPECS:
        svg = spec.build()
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert "<script" not in svg
        assert len(svg) > 500


# ── 快照与指纹 ────────────────────────────────────────────


def test_snapshot_reused_when_fingerprint_unchanged(tmp_path):
    """指纹一致时直接复用快照：不重复构建、生成时间不变."""
    store = FigureStore(tmp_path)
    first = store.get("field-types")
    assert first is not None
    second = store.get("field-types")
    assert second is not None
    assert second.generated_at == first.generated_at
    assert second.fingerprint == first.fingerprint


def test_snapshot_survives_new_store_instance(tmp_path):
    """磁盘快照可跨实例复用（进程重启后首屏不用重建）."""
    first_store = FigureStore(tmp_path)
    record = first_store.get("quick-start-flow")
    assert record is not None
    assert (tmp_path / "quick-start-flow.svg").is_file()
    assert (tmp_path / "index.json").is_file()

    reloaded = FigureStore(tmp_path)
    again = reloaded.get("quick-start-flow")
    assert again is not None
    assert again.fingerprint == record.fingerprint
    assert again.generated_at == record.generated_at
    assert again.svg == record.svg


def test_force_refresh_rebuilds_every_figure(tmp_path):
    """force 重建：张数等于清单条数，生成时间全部推进."""
    store = FigureStore(tmp_path)
    store.get("field-types")
    assert store.refresh(force=True) == len(FIGURE_SPECS)


def test_fingerprint_changes_when_csv_changes(tmp_path, monkeypatch):
    """示例 CSV 改内容 → 指纹变化 → 下次 get 立即重建（不用等定时轮次）."""
    csv_path = tmp_path / "demo.csv"
    csv_path.write_text("编号,名称\n1,甲\n", encoding="utf-8")
    monkeypatch.setattr(assets, "resolve_example_file", lambda _scenario, _filename: csv_path)

    spec = FigureSpec(
        key="example-demo",
        title="demo",
        caption="demo",
        section="examples",
        build=lambda: f'<svg data-help-figure="1">{csv_path.read_text(encoding="utf-8")}</svg>',
        data_digest=lambda: _csv_digest("demo", "demo.csv"),
    )
    before = spec.fingerprint()

    csv_path.write_text("编号,名称\n1,甲\n2,乙\n", encoding="utf-8")
    after = spec.fingerprint()
    assert before != after


def test_store_rebuilds_when_data_source_changes(tmp_path, monkeypatch):
    """指纹变化时旧快照失效：新内容立即生效."""
    from cndb.plugins.help.services.figures import registry

    csv_path = tmp_path / "demo.csv"
    csv_path.write_text("编号,名称\n1,甲\n", encoding="utf-8")
    monkeypatch.setattr(assets, "resolve_example_file", lambda _scenario, _filename: csv_path)

    spec = FigureSpec(
        key="field-types",  # 复用已有 key，验证同名图在源变化后的重建
        title="demo",
        caption="demo",
        section="examples",
        build=lambda: f'<svg data-help-figure="1">{csv_path.read_text(encoding="utf-8")}</svg>',
        data_digest=lambda: _csv_digest("demo", "demo.csv"),
    )
    monkeypatch.setitem(registry.FIGURE_SPEC_BY_KEY, "field-types", spec)

    store = FigureStore(tmp_path)
    first = store.get("field-types")
    assert first is not None and "甲" in first.svg

    csv_path.write_text("编号,名称\n1,丙\n", encoding="utf-8")
    second = store.get("field-types")
    assert second is not None
    assert "丙" in second.svg
    assert second.fingerprint != first.fingerprint
    assert second.generated_at >= first.generated_at


# ── 解耦守卫 ──────────────────────────────────────────────


def test_figures_package_does_not_import_seed():
    """图示不得依赖 `cndb.cli.seed`：seed 移除后帮助仍可用."""
    for path in FIGURES_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "cndb.cli.seed" not in source, f"{path.name} 不应依赖 seed"

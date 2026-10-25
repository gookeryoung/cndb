"""帮助文档典型示例接口（ADR 0029 P1）.

覆盖：
- 清单接口：登录 200 / 未登录 401 / 字段完整 / 清单自身约束（key 唯一、文件白名单）；
- 下载接口：登记文件 200（RFC 5987 文件名、CSV 非空）、全部登记文件均可下载；
- 404：未知场景 / 未登记文件 / 非 .csv / 路径穿越 / 资产目录缺失；
- 解耦守卫：help 插件源码不出现 seed 依赖。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from cndb.plugins.help.services import assets
from cndb.plugins.help.services.examples import HELP_EXAMPLE_MANIFEST

LIST_URL = "/api/v1/help/examples"
HELP_PLUGIN_DIR = Path(__file__).resolve().parents[1] / "src" / "cndb" / "plugins" / "help"


def _download_url(scenario: str, filename: str) -> str:
    return f"{LIST_URL}/{scenario}/files/{filename}"


# ── 清单接口 ──────────────────────────────────────────────


def test_list_examples_requires_auth(client):
    """未登录访问清单 → 401."""
    assert client.get(LIST_URL).status_code == 401


def test_list_examples_returns_manifest(client, auth_headers):
    """登录后返回三套场景，字段完整且表信息可用."""
    resp = client.get(LIST_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    assert [item["key"] for item in items] == ["sales", "research", "datasource"]
    for item in items:
        assert item["name"] and item["summary"]
        assert item["tables"] and item["highlights"] and item["steps"]
        for table in item["tables"]:
            assert table["file"].endswith(".csv")
            assert table["title"] and table["description"]
            assert table["rows"] > 0


def test_manifest_keys_and_files_are_unique():
    """清单是唯一真相源：key 唯一、文件名在场景内唯一、无重复场景名."""
    keys = [item["key"] for item in HELP_EXAMPLE_MANIFEST]
    assert len(keys) == len(set(keys))
    for item in HELP_EXAMPLE_MANIFEST:
        assert re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", item["key"])
        files = [table["file"] for table in item["tables"]]
        assert len(files) == len(set(files))


# ── 下载接口 ──────────────────────────────────────────────


def test_download_registered_file(client, auth_headers):
    """登记文件 → 200，CSV 内容非空，RFC 5987 文件名可还原."""
    resp = client.get(_download_url("sales", "电商销售.csv"), headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.content

    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
    assert match is not None
    assert unquote(match.group(1)) == "电商销售.csv"


@pytest.mark.parametrize("scenario", [item["key"] for item in HELP_EXAMPLE_MANIFEST])
def test_every_manifest_file_is_downloadable(client, auth_headers, scenario):
    """清单登记的每个文件都必须真实可下载（防止清单与资产漂移）."""
    example = next(item for item in HELP_EXAMPLE_MANIFEST if item["key"] == scenario)
    for table in example["tables"]:
        resp = client.get(_download_url(scenario, table["file"]), headers=auth_headers)
        assert resp.status_code == 200, f"{scenario}/{table['file']}: {resp.text[:200]}"
        assert resp.content


def test_download_requires_auth(client):
    """未登录下载 → 401."""
    assert client.get(_download_url("sales", "电商销售.csv")).status_code == 401


@pytest.mark.parametrize(
    ("scenario", "filename"),
    [
        ("nope", "电商销售.csv"),  # 未知场景
        ("sales", "产品开发.csv"),  # 存在但未登记
        ("sales", "电商销售.txt"),  # 非 .csv
        ("sales", "..%5C电商销售.csv"),  # 反斜杠路径穿越
        ("sales", "..%2F电商销售.csv"),  # 正斜杠路径穿越
    ],
)
def test_download_rejects_invalid_targets(client, auth_headers, scenario, filename):
    """非法目标统一 404，不泄露服务器路径."""
    resp = client.get(_download_url(scenario, filename), headers=auth_headers)
    assert resp.status_code == 404, resp.text


def test_download_404_detail_is_friendly(client, auth_headers):
    """命中白名单校验的 404 给出可读文案（而不是裸状态码）."""
    resp = client.get(_download_url("sales", "产品开发.csv"), headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "示例文件暂不可用"


# ── 资产定位 ──────────────────────────────────────────────


def test_missing_asset_dir_keeps_list_and_404_download(client, auth_headers, monkeypatch):
    """资产目录缺失：清单仍可读，下载 404 而非 500."""
    monkeypatch.setattr(assets, "datasets_dir", lambda: None)

    assert client.get(LIST_URL, headers=auth_headers).status_code == 200
    resp = client.get(_download_url("sales", "电商销售.csv"), headers=auth_headers)
    assert resp.status_code == 404


def test_datasets_dir_prefers_packaged_then_repo(tmp_path, monkeypatch):
    """包内目录优先；仅在仓库目录存在时回落到仓库目录；都不存在时 None."""
    packaged = tmp_path / "pkg"
    repo = tmp_path / "repo"
    monkeypatch.setattr(assets, "_candidate_dirs", lambda: (packaged, repo))
    assert assets.datasets_dir() is None

    repo.mkdir()
    assert assets.datasets_dir() == repo

    packaged.mkdir()
    assert assets.datasets_dir() == packaged


# ── 解耦守卫 ──────────────────────────────────────────────


def test_help_plugin_does_not_import_seed():
    """帮助插件不得依赖 cndb.cli.seed（ADR 0029 I3）."""
    offenders = [path.name for path in HELP_PLUGIN_DIR.rglob("*.py") if "cndb.cli" in path.read_text(encoding="utf-8")]
    assert offenders == []

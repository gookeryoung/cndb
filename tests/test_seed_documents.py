"""示例文档种子（examples/datasets/<工作区>/documents/）测试.

覆盖：

- 纯函数：元数据头解析、标题派生、自然排序、数据表引用符号解析、工作区名派生；
- 端到端注入：临时 datasets 目录 → 文档树落库（层级/状态/标签/作者/摘要/引用解析/幂等）；
- 真实 datasets 完整性：每个非反面示例工作区不少于 5 篇文档、表/视图引用可解析、
  双向链接目标存在、反面示例工作区（低质量数据）不生成文档。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cndb.cli.seed import (
    _DOC_TABLE_REF_RE,
    _document_entry_sort_key,
    _document_tag_color,
    _document_title_from_name,
    _get_workspace_document_dirs,
    _iter_document_entries,
    _parse_document_front_matter,
    _resolve_document_table_refs,
    _workspace_display_name,
)

# ── 1. 纯函数 ─────────────────────────────────────────────


class TestDocumentHelpers:
    """文档种子解析纯函数."""

    def test_workspace_display_name_strips_prefix(self):
        assert _workspace_display_name("工作区-科研项目管理") == "科研项目管理"
        assert _workspace_display_name("自定义工作区") == "自定义工作区"

    def test_document_title_from_name_strips_order_prefix(self):
        assert _document_title_from_name("01-销售管理总览") == "销售管理总览"
        assert _document_title_from_name("2_立项与结题流程") == "立项与结题流程"
        assert _document_title_from_name("3.经费办法") == "经费办法"
        assert _document_title_from_name("销售运营手册") == "销售运营手册"

    def test_entry_sort_key_natural_order(self, tmp_path: Path):
        names = ["10-后.md", "9-先.md", "2-更先.md"]
        paths = [tmp_path / n for n in names]
        assert [p.name for p in sorted(paths, key=_document_entry_sort_key)] == ["2-更先.md", "9-先.md", "10-后.md"]

    def test_iter_document_entries_skips_hidden_and_non_markdown(self, tmp_path: Path):
        (tmp_path / "01-文档.md").write_text("# a", encoding="utf-8")
        (tmp_path / "03-说明.markdown").write_text("# b", encoding="utf-8")
        (tmp_path / "02-文件夹").mkdir()
        (tmp_path / "note.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".hidden.md").write_text("# c", encoding="utf-8")

        entries = _iter_document_entries(tmp_path)
        assert [p.name for p in entries] == ["01-文档.md", "02-文件夹", "03-说明.markdown"]

    def test_parse_front_matter_bracket_and_bare_tags(self):
        meta, body = _parse_document_front_matter(
            "---\nstatus: draft\ntags: [数据说明, 字段字典]\nauthor: 数据组\nsummary: 摘要\n---\n# 标题\n正文\n"
        )
        assert meta == {"status": "draft", "tags": ["数据说明", "字段字典"], "author": "数据组", "summary": "摘要"}
        assert body == "# 标题\n正文\n"

        meta2, _ = _parse_document_front_matter("---\ntags: 甲, 乙\n---\n正文")
        assert meta2["tags"] == ["甲", "乙"]

    def test_parse_front_matter_without_header_keeps_content(self):
        meta, body = _parse_document_front_matter("# 无元数据头\n正文\n")
        assert meta == {}
        assert body == "# 无元数据头\n正文\n"

    def test_parse_front_matter_ignores_unknown_keys(self):
        meta, _ = _parse_document_front_matter("---\nstatus: published\nfoo: bar\n---\n正文")
        assert meta == {"status": "published"}

    def test_document_tag_color_stable_and_valid(self):
        color = _document_tag_color("销售运营")
        assert color == _document_tag_color("销售运营")
        assert len(color) == 7 and color.startswith("#")

    def test_resolve_table_refs_symbolic_to_ids(self):
        resolved = _resolve_document_table_refs(
            "{{table:电商销售|limit=10}}",
            {"电商销售": 7},
            {},
        )
        assert resolved == "{{table:7|limit=10}}"

    def test_resolve_table_refs_view_name_to_id(self):
        resolved = _resolve_document_table_refs(
            "{{table:电商销售|view=高分订单|limit=5}}",
            {"电商销售": 7},
            {("电商销售", "高分订单"): 33},
        )
        assert resolved == "{{table:7|view=33|limit=5}}"

    def test_resolve_table_refs_keeps_numeric_and_unknown(self):
        content = "{{table:12|limit=3}} {{table:不存在的表}}"
        assert _resolve_document_table_refs(content, {}, {}) == content

    def test_resolve_table_refs_drops_unknown_view_only(self):
        resolved = _resolve_document_table_refs(
            "{{table:电商销售|view=没有的视图|limit=5}}",
            {"电商销售": 7},
            {},
        )
        assert resolved == "{{table:7|limit=5}}"

    def test_resolve_table_refs_multiple_in_content(self):
        resolved = _resolve_document_table_refs(
            "前文\n\n{{table:甲}} 和 {{table:乙|limit=2}}\n\n后文",
            {"甲": 1, "乙": 2},
            {},
        )
        assert resolved == "前文\n\n{{table:1}} 和 {{table:2|limit=2}}\n\n后文"

    def test_get_workspace_document_dirs_maps_and_skips(self, tmp_path: Path):
        ws = tmp_path / "工作区-示例"
        (ws / "documents").mkdir(parents=True)
        (tmp_path / "工作区-无文档").mkdir()
        assert _get_workspace_document_dirs(tmp_path) == {"示例": ws / "documents"}


# ── 2. 端到端注入 ─────────────────────────────────────────

SALES_CSV = """日期,商品类别,销售额
2026-09-01,数码,1200
2026-09-02,家居,800
"""

VIEWS_JSON = {
    "销售明细": [
        {"name": "销售概览", "view_type": "chart", "order": 0},
    ]
}

REPORT_DOC = """---
status: published
tags: [数据说明, 分析]
author: 数据分析组
summary: 销售明细的口径说明。
---
# 销售数据说明

销售明细按日汇总，单位为元。

{{table:销售明细|view=销售概览|limit=5}}

参见 [[销售数据说明]]。
"""

DRAFT_DOC = """---
status: draft
tags: [数据说明]
summary: 口径草稿。
---
# 口径草稿

待补充。
"""


def _build_datasets_dir(tmp_path: Path) -> Path:
    """构建最小 datasets 目录：CSV + views.json + documents/ 文档树."""
    ws_dir = tmp_path / "datasets" / "工作区-销售测试"
    ws_dir.mkdir(parents=True)
    (ws_dir / "销售明细.csv").write_text(SALES_CSV, encoding="utf-8-sig")
    (ws_dir / "views.json").write_text(json.dumps(VIEWS_JSON, ensure_ascii=False), encoding="utf-8")

    docs = ws_dir / "documents"
    (docs / "01-数据说明").mkdir(parents=True)
    (docs / "01-数据说明" / "01-销售数据说明.md").write_text(REPORT_DOC, encoding="utf-8")
    (docs / "01-数据说明" / "02-口径草稿.md").write_text(DRAFT_DOC, encoding="utf-8")
    (docs / "02-使用须知.md").write_text("# 使用须知\n\n数据仅限内部使用。\n", encoding="utf-8")
    return tmp_path / "datasets"


@pytest.fixture
def document_seed(db, db_engine, tmp_path):
    """端到端：建工作区 + 表 + 视图 + 文档树，返回 (tables_map, ws_map, user, datasets_dir)."""
    from cndb.cli.seed import _seed_datasets, _seed_documents, _seed_views
    from cndb.plugins.accounts.models import User

    user = User(username="doc_seed", email="doc_seed@example.com", nickname="文档种子测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path)

    from cndb.cli.seed import paths as seed_paths

    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        _seed_views(db, user, tables_map, datasets_dir)
        _seed_documents(db, user, ws_map, tables_map, datasets_dir)
        yield tables_map, ws_map, user, datasets_dir
    finally:
        seed_paths._get_datasets_dir = original


def test_seed_documents_creates_tree(document_seed, db):
    """文档树注入：文件夹层级、标题、状态、标签、作者与摘要."""
    from cndb.plugins.documents.models import Document, Tag
    from cndb.plugins.documents.services.content import latest_version, load_content

    _tables_map, ws_map, _user, _datasets = document_seed
    ws = ws_map["销售测试"]

    docs = db.query(Document).filter(Document.workspace_id == ws.id).all()
    by_title = {d.title: d for d in docs}
    assert set(by_title) == {"数据说明", "销售数据说明", "口径草稿", "使用须知"}

    folder = by_title["数据说明"]
    assert folder.is_folder is True
    assert by_title["销售数据说明"].parent_id == folder.id
    assert by_title["口径草稿"].parent_id == folder.id
    assert by_title["使用须知"].parent_id is None

    published = by_title["销售数据说明"]
    assert published.status == "published"
    assert published.author == "数据分析组"
    assert published.summary == "销售明细的口径说明。"
    assert [t.name for t in published.tags] == ["数据说明", "分析"]
    assert db.query(Tag).filter(Tag.workspace_id == ws.id).count() == 2

    assert by_title["口径草稿"].status == "draft"

    # 元数据头必须已剥离，且内容已建立 v1 版本
    content = load_content(latest_version(db, published.id), published)
    assert not content.startswith("---")
    assert content.startswith("# 销售数据说明")
    assert published.content_size > 0


def test_seed_documents_resolves_table_and_view_refs(document_seed, db):
    """数据表引用被解析为该工作区真实的表 / 视图数字 ID."""
    from cndb.plugins.documents.models import Document
    from cndb.plugins.documents.services.content import latest_version, load_content
    from cndb.plugins.tables.models import DataView

    tables_map, ws_map, _user, _datasets = document_seed
    ws = ws_map["销售测试"]
    dt = tables_map["销售测试"]["销售明细"]
    view = db.query(DataView).filter(DataView.table_id == dt.id, DataView.name == "销售概览").one()

    doc = db.query(Document).filter(Document.workspace_id == ws.id, Document.title == "销售数据说明").one()
    content = load_content(latest_version(db, doc.id), doc)
    assert f"{{{{table:{dt.id}|view={view.id}|limit=5}}}}" in content
    assert "{{table:销售明细" not in content


def test_seed_documents_backlinks_resolve(document_seed, db):
    """正文中的 [[标题]] 可作为反向链接被检索到."""
    from cndb.plugins.documents.models import Document
    from cndb.plugins.documents.services.content import find_backlinks

    _tables_map, ws_map, _user, _datasets = document_seed
    ws = ws_map["销售测试"]
    hits = find_backlinks(db, ws.id, "销售数据说明")
    assert [d.title for d in hits] == ["销售数据说明"]
    assert db.query(Document).filter(Document.workspace_id == ws.id, Document.title == "使用须知").count() == 1


def test_seed_documents_is_idempotent(document_seed, db):
    """重复注入：同名节点跳过，不新增文档."""
    from cndb.cli.seed import _seed_documents
    from cndb.plugins.documents.models import Document

    tables_map, ws_map, user, datasets_dir = document_seed
    ws = ws_map["销售测试"]
    before = db.query(Document).filter(Document.workspace_id == ws.id).count()

    created, folders = _seed_documents(db, user, ws_map, tables_map, datasets_dir)
    assert (created, folders) == (0, 0)
    assert db.query(Document).filter(Document.workspace_id == ws.id).count() == before


def test_seed_documents_degrades_without_datasets_dir(db, db_engine):
    """datasets 目录不可用：优雅降级返回 (0, 0)，不抛异常."""
    from cndb.cli.seed import _seed_documents

    assert _seed_documents(db, None, {}, {}, None) == (0, 0)


def test_reset_fts_schema_cache_drops_ready_flag():
    """reset_fts_schema_cache 重置进程内建表缓存（seed 全量重建后调用）."""
    from cndb.plugins.documents.services import search

    search._fts_state["ready"] = True
    search.reset_fts_schema_cache()
    assert search._fts_state["ready"] is False


def test_ensure_fts_schema_cache_is_per_database():
    """FTS 建表缓存按数据库区分：同进程换库写入时必须真的建表.

    回归：进程级单一 ready 标记会让第二个库误判 ``documents_fts`` 已存在，
    文档写入报 ``no such table: documents_fts``（CI 上 seed 文档用例即因此失败）。
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from cndb.plugins.documents.services import search

    search.reset_fts_schema_cache()
    engines = [create_engine("sqlite://"), create_engine("sqlite://")]
    sessions = [sessionmaker(bind=engine)() for engine in engines]
    try:
        assert engines[0] is not engines[1]
        for session in sessions:
            search.ensure_fts_schema(session)
            assert session.execute(text("SELECT count(*) FROM documents_fts")).scalar_one() == 0
    finally:
        for session in sessions:
            session.close()
        for engine in engines:
            engine.dispose()


# ── 3. 真实 datasets 完整性 ────────────────────────────────

# 反面示例工作区：按需求不生成典型文档
NEGATIVE_WORKSPACES = {"工作区-低质量数据"}

# 硬编码业务表（seed._seed_sales_tables 注入，不属于 CSV/API 来源）
HARDCODED_TABLES: dict[str, set[str]] = {"某企业销售管理": {"部门表", "员工表"}}


def _flatten_documents(docs_root: Path) -> list[dict[str, Any]]:
    """递归扫描 documents/ 目录树，返回扁平节点列表（含层级信息）."""

    def _scan(current: Path) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for entry in _iter_document_entries(current):
            if entry.is_dir():
                nodes.append(
                    {
                        "title": _document_title_from_name(entry.name),
                        "is_folder": True,
                        "children": _scan(entry),
                    }
                )
                continue
            meta, body = _parse_document_front_matter(entry.read_text(encoding="utf-8"))
            nodes.append(
                {
                    "title": str(meta.get("title") or _document_title_from_name(entry.stem)),
                    "is_folder": False,
                    "meta": meta,
                    "body": body,
                }
            )
        return nodes

    flat: list[dict[str, Any]] = []

    def _collect(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            flat.append(node)
            if node["is_folder"]:
                _collect(node["children"])

    _collect(_scan(docs_root))
    return flat


def _declared_tables_and_views(ws_dir: Path) -> dict[str, set[str]]:
    """工作区已声明的表 → 视图名集合（CSV/XLSX/api_config/views.json/硬编码表）."""
    ws_name = _workspace_display_name(ws_dir.name)
    tables: dict[str, set[str]] = {name: set() for name in HARDCODED_TABLES.get(ws_name, set())}
    for path in ws_dir.glob("*.csv"):
        tables.setdefault(path.stem, set())
    for path in ws_dir.glob("*.xlsx"):
        if "示例报告" not in path.stem:
            tables.setdefault(path.stem, set())

    api_path = ws_dir / "api_config.json"
    if api_path.is_file():
        spec = json.loads(api_path.read_text(encoding="utf-8-sig"))
        for table in spec.get("tables", []):
            names = {v.get("name") for v in table.get("views", []) if isinstance(v, dict)}
            tables.setdefault(table["table_name"], set()).update(n for n in names if n)

    views_path = ws_dir / "views.json"
    if views_path.is_file():
        spec = json.loads(views_path.read_text(encoding="utf-8-sig"))
        for table_name, views in spec.items():
            if table_name.startswith("_") or not isinstance(views, list):
                continue
            names = {v.get("name") for v in views if isinstance(v, dict)}
            tables.setdefault(table_name, set()).update(n for n in names if n)
    return tables


@pytest.fixture(scope="module")
def datasets_dir() -> Path:
    """真实仓库 examples/datasets 目录（wheel 安装环境跳过）."""
    from cndb.cli.seed import _get_datasets_dir

    resolved = _get_datasets_dir()
    if resolved is None:
        pytest.skip("examples/datasets 目录不可用（wheel 安装环境）")
    return resolved


class TestRealDatasetDocuments:
    """真实 datasets 文档种子配置的全量完整性校验（无 DB）."""

    def _workspace_dirs(self, datasets_dir: Path) -> dict[str, Path]:
        """全部含 documents/ 的工作区显示名 → documents 目录."""
        result: dict[str, Path] = {}
        for folder in sorted(datasets_dir.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            docs = folder / "documents"
            if docs.is_dir():
                result[_workspace_display_name(folder.name)] = docs
        return result

    def test_negative_workspace_has_no_documents(self, datasets_dir: Path):
        """低质量数据等反面示例工作区不生成典型文档."""
        assert not (datasets_dir / "工作区-低质量数据" / "documents").exists()

    def test_every_positive_workspace_has_at_least_five_documents(self, datasets_dir: Path):
        """除反面示例外，每个工作区都有 documents/ 且不少于 5 篇典型文档."""
        all_workspaces = {
            _workspace_display_name(p.name) for p in datasets_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
        }
        expected = all_workspaces - {_workspace_display_name(n) for n in NEGATIVE_WORKSPACES}
        assert set(self._workspace_dirs(datasets_dir)) == expected

        counts: dict[str, int] = {}
        for ws_name, docs_root in self._workspace_dirs(datasets_dir).items():
            docs = [n for n in _flatten_documents(docs_root) if not n["is_folder"]]
            counts[ws_name] = len(docs)
            assert len(docs) >= 5, f"{ws_name} 仅 {len(docs)} 篇典型文档"
        # 反面示例工作区（低质量数据）不提供 documents/；当前带文档的示例工作区为
        # 某企业销售管理 / 科研项目管理 / 项目管理 三个，阈值随之收敛为 3。
        assert len(counts) >= 3

    def test_document_metadata_and_structure_valid(self, datasets_dir: Path):
        """节点元数据合法、标题同层唯一、正文非空且无残留元数据头."""
        for ws_name, docs_root in self._workspace_dirs(datasets_dir).items():
            nodes = _flatten_documents(docs_root)
            titles = [n["title"] for n in nodes]
            assert len(titles) == len(set(titles)), f"{ws_name} 文档标题重复: {titles}"
            for node in nodes:
                assert node["title"].strip(), f"{ws_name} 存在空标题"
                if node["is_folder"]:
                    assert node["children"], f"{ws_name}/{node['title']} 文件夹为空"
                    continue
                meta = node["meta"]
                assert meta.get("status", "published") in ("draft", "published", "archived")
                assert str(meta.get("summary", "")).strip(), f"{ws_name}/{node['title']} 缺 summary"
                assert str(meta.get("author", "")).strip(), f"{ws_name}/{node['title']} 缺 author"
                assert node["body"].strip(), f"{ws_name}/{node['title']} 正文为空"
                assert not node["body"].lstrip().startswith("---"), f"{ws_name}/{node['title']} 正文残留元数据头"

    def test_table_and_view_refs_resolve(self, datasets_dir: Path):
        """正文中的数据表/视图引用必须能在该工作区声明中解析."""
        for ws_name, docs_root in self._workspace_dirs(datasets_dir).items():
            declared = _declared_tables_and_views(datasets_dir / f"工作区-{ws_name}")
            for node in _flatten_documents(docs_root):
                if node["is_folder"]:
                    continue
                for match in _DOC_TABLE_REF_RE.finditer(node["body"]):
                    table_name = match.group(1).strip()
                    assert not table_name.isdigit(), f"{ws_name}/{node['title']} 不应写死表 ID"
                    assert table_name in declared, (
                        f"{ws_name}/{node['title']} 引用未声明的表: {table_name}（已声明: {sorted(declared)}）"
                    )
                    for part in match.group(2).lstrip("|").split("|"):
                        key, _, value = part.partition("=")
                        if key != "view":
                            continue
                        assert value in declared[table_name], (
                            f"{ws_name}/{node['title']} 表 {table_name} 引用未声明的视图: {value}"
                        )

    def test_wikilink_targets_exist(self, datasets_dir: Path):
        """正文中的 [[标题]] 必须指向同工作区已存在的文档/文件夹标题."""
        for ws_name, docs_root in self._workspace_dirs(datasets_dir).items():
            nodes = _flatten_documents(docs_root)
            titles = {n["title"] for n in nodes}
            for node in nodes:
                if node["is_folder"]:
                    continue
                for target in _wikilinks(node["body"]):
                    assert target in titles, f"{ws_name}/{node['title']} 双链目标不存在: [[{target}]]"

    def test_each_workspace_covers_draft_or_published_status(self, datasets_dir: Path):
        """文档状态取值合法，且每个工作区至少有一篇 published 文档."""
        for ws_name, docs_root in self._workspace_dirs(datasets_dir).items():
            docs = [n for n in _flatten_documents(docs_root) if not n["is_folder"]]
            statuses = {n["meta"].get("status", "published") for n in docs}
            assert statuses <= {"draft", "published", "archived"}
            assert "published" in statuses, f"{ws_name} 没有 published 文档"


def _wikilinks(content: str) -> list[str]:
    """提取正文中的双链目标标题（跳过代码围栏）."""
    targets: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for part in line.split("[["):
            if "]]" in part:
                title = part.split("]]")[0].strip()
                if title:
                    targets.append(title)
    return targets

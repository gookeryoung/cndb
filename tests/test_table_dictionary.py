"""数据表字段字典（ADR 0188）：构建 / 渲染 / 接口 / 符合度指标."""

from __future__ import annotations

import io
import json

import pytest


@pytest.fixture
def ws_table(client, auth_headers):
    """建一个工作区 + 一张表（字段由各用例自行添加）."""
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "字典工作区"})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "客户", "description": "客户主数据"},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    return wid, tid


def _add_field(client, headers, wid, tid, **payload):
    r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ── C3：业务元数据落库 ────────────────────────────────


def test_field_business_metadata_roundtrip(client, auth_headers, ws_table):
    """C3：业务元数据可写、可读、可清空."""
    wid, tid = ws_table
    field = _add_field(
        client,
        auth_headers,
        wid,
        tid,
        name="客户编号",
        field_type="text",
        business_meaning="客户唯一编号，含区域前缀",
        unit="",
        sensitivity="confidential",
        standard_ref="CRM-STD-001",
        example_value="BJ0001",
    )
    assert field["business_meaning"] == "客户唯一编号，含区域前缀"
    assert field["sensitivity"] == "confidential"
    assert field["standard_ref"] == "CRM-STD-001"
    assert field["example_value"] == "BJ0001"
    assert field["unit"] is None  # 空串归一为 None

    fid = field["id"]
    r = client.patch(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
        headers=auth_headers,
        json={"business_meaning": "  改过的口径  ", "sensitivity": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business_meaning"] == "改过的口径"
    assert body["sensitivity"] is None
    # 未出现在请求里的键不被清空（PATCH 语义）
    assert body["standard_ref"] == "CRM-STD-001"


def test_field_business_metadata_validation(client, auth_headers, ws_table):
    """C3：非法敏感级 / 不存在的责任人 → 400."""
    wid, tid = ws_table
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "A", "field_type": "text", "sensitivity": "top-secret"},
    )
    assert r.status_code == 400
    assert "敏感级" in r.json()["detail"]

    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "B", "field_type": "text", "owner_id": 999999},
    )
    assert r.status_code == 400
    assert "责任人不存在" in r.json()["detail"]


def test_field_business_metadata_owner(client, auth_headers, ws_table, db):
    """C3：指派责任人后列表返回 owner_name."""
    from cndb.plugins.accounts.models import User

    wid, tid = ws_table
    owner = db.query(User).filter(User.username == "testuser").first()
    assert owner is not None
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text", owner_id=owner.id)

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()[0]["owner_name"] == "testuser"


# ── C2：Markdown 章节骨架 ─────────────────────────────


def test_dictionary_markdown_sections(client, auth_headers, ws_table):
    """C2：Markdown 输出固定 8 节骨架，缺失内容用占位而非省略."""
    from cndb.plugins.tables.services.dictionary import SECTION_ORDER

    wid, tid = ws_table
    _add_field(
        client,
        auth_headers,
        wid,
        tid,
        name="客户等级",
        field_type="select",
        config={"options": [{"label": "A", "value": "A"}]},
    )

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=md", headers=auth_headers)
    assert r.status_code == 200, r.text
    text = r.text
    assert "客户 数据字典" in text
    for section in SECTION_ORDER:
        assert f"### {section}" in text, f"缺少章节 {section}"
    # 缺业务说明 → 占位可见
    assert "未填写" in text
    # 枚举字典里有选项
    assert "| A | A |" in text
    # 结构指纹
    assert "sha256:" in text


# ── C7：JSON 契约 ─────────────────────────────────────


def test_dictionary_json_contract(client, auth_headers, ws_table):
    """C7：JSON 契约带 kind / version / schema_hash，且默认不含内部列."""
    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text", business_meaning="客户名称")

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = json.loads(r.content)
    assert body["kind"] == "cndb-table-dictionary"
    assert body["version"] == 1
    assert body["schema_hash"].startswith("sha256:")
    assert body["tables"][0]["name"] == "客户"
    names = [f["name"] for f in body["tables"][0]["fields"]]
    assert "名称" in names
    assert "db_column_name" not in body["tables"][0]["fields"][0]
    assert "db_table_name" not in body["tables"][0]
    # 规范附录随契约输出
    assert any(item["title"] == "类型选择" for item in body["spec"])


def test_schema_hash_stable_and_sensitive(client, auth_headers, ws_table):
    """C7：同结构 hash 稳定；改字段名后变化；只改口径不变化."""
    wid, tid = ws_table
    field = _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")

    first = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json", headers=auth_headers)
    second = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json", headers=auth_headers)
    assert json.loads(first.content)["schema_hash"] == json.loads(second.content)["schema_hash"]

    # 只改业务口径 → hash 不变（改文案不该提示「结构已变更」）
    client.patch(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{field['id']}",
        headers=auth_headers,
        json={"business_meaning": "只是文案"},
    )
    third = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json", headers=auth_headers)
    assert json.loads(third.content)["schema_hash"] == json.loads(first.content)["schema_hash"]

    # 改字段名 → hash 变化
    client.patch(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{field['id']}",
        headers=auth_headers,
        json={"name": "名称2"},
    )
    fourth = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json", headers=auth_headers)
    assert json.loads(fourth.content)["schema_hash"] != json.loads(first.content)["schema_hash"]


# ── C6：内部列与脱敏 ──────────────────────────────────


def test_dictionary_include_internal(client, auth_headers, ws_table):
    """C6：include_internal 控制物理列名 / 物理表名."""
    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")

    r = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json&include_internal=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = json.loads(r.content)
    assert body["tables"][0]["db_table_name"].startswith("table_")
    assert body["tables"][0]["fields"][0]["db_column_name"].startswith("field_")


def test_dictionary_confidential_redaction(client, auth_headers, ws_table):
    """C6：机密字段在默认口径下把口径与示例值脱敏，敏感级与责任人照常输出."""
    wid, tid = ws_table
    _add_field(
        client,
        auth_headers,
        wid,
        tid,
        name="身份证",
        field_type="text",
        business_meaning="身份证号",
        example_value="110101199001011234",
        sensitivity="confidential",
    )
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json", headers=auth_headers)
    field = json.loads(r.content)["tables"][0]["fields"][0]
    assert field["business_meaning"] == "（受限）"
    assert field["example_value"] == "（受限）"
    assert field["sensitivity"] == "confidential"
    assert field["redacted"] is True

    r = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=json&include_internal=true",
        headers=auth_headers,
    )
    field = json.loads(r.content)["tables"][0]["fields"][0]
    assert field["business_meaning"] == "身份证号"


# ── C1：xlsx ──────────────────────────────────────────


def test_dictionary_xlsx(client, auth_headers, ws_table):
    """C1：xlsx 导出可解析，含字段清单 / 概览 / 设计规范 sheet."""
    from openpyxl import load_workbook

    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=xlsx", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert "字段清单" in wb.sheetnames
    assert "概览" in wb.sheetnames
    assert "设计规范" in wb.sheetnames
    assert "枚举字典" in wb.sheetnames
    assert wb["字段清单"].max_row >= 2


# ── C4：符合度指标 ────────────────────────────────────


def test_dictionary_score(client, auth_headers, ws_table):
    """C4：符合度指标与缺口字段."""
    wid, tid = ws_table
    _add_field(
        client,
        auth_headers,
        wid,
        tid,
        name="已标注",
        field_type="text",
        business_meaning="有口径",
        example_value="x",
        sensitivity="internal",
        required=True,
    )
    _add_field(client, auth_headers, wid, tid, name="未标注", field_type="text")

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary/score", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["field_count"] == 2
    meaning = body["metrics"]["business_meaning"]
    assert meaning["covered"] == 1
    assert meaning["total"] == 2
    assert meaning["missing_fields"] == ["未标注"]
    assert body["metrics"]["sensitivity"]["covered"] == 1
    assert body["metrics"]["example_value"]["covered"] == 1
    assert body["metrics"]["required"]["covered"] == 1
    assert body["schema_hash"].startswith("sha256:")


def test_dictionary_score_naming(client, auth_headers, ws_table):
    """C4：命名规范命中率识别带空格 / 标点的字段名."""
    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="规范名", field_type="text")
    _add_field(client, auth_headers, wid, tid, name="不 规范", field_type="text")

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary/score", headers=auth_headers)
    naming = r.json()["metrics"]["naming"]
    assert naming["covered"] == 1
    assert naming["missing_fields"] == ["不 规范"]


# ── C5：合订与可见性 ──────────────────────────────────


def test_dictionary_workspace_aggregate(client, auth_headers, ws_table):
    """C5：工作区合订 + 表间引用索引."""
    wid, tid = ws_table
    r = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "订单"})
    tid2 = r.json()["id"]
    _add_field(
        client,
        auth_headers,
        wid,
        tid2,
        name="客户",
        field_type="link",
        config={"target_table_id": tid, "multiple": False},
    )
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")

    r = client.get(f"/api/v1/workspaces/{wid}/tables/dictionary?format=md", headers=auth_headers)
    assert r.status_code == 200, r.text
    text = r.text
    assert "## 客户" in text and "## 订单" in text
    assert "表间引用索引" in text
    assert "## 目录" in text


def test_dictionary_table_ids_filter(client, auth_headers, ws_table):
    """C5：table_ids 只导出指定表；非整数 400."""
    wid, tid = ws_table
    client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "其他"})
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")

    r = client.get(
        f"/api/v1/workspaces/{wid}/tables/dictionary?format=json&table_ids={tid}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert [t["name"] for t in json.loads(r.content)["tables"]] == ["客户"]

    r = client.get(
        f"/api/v1/workspaces/{wid}/tables/dictionary?format=json&table_ids=abc",
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_dictionary_hidden_field_excluded(client, auth_headers, ws_table):
    """C5 / I3：viewer 不可见的字段不出现在字典里（连字段名都不出现）."""
    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="公开列", field_type="text")
    _add_field(client, auth_headers, wid, tid, name="机密列", field_type="text")
    r = client.patch(
        f"/api/v1/workspaces/{wid}/tables/{tid}/permissions",
        headers=auth_headers,
        json={"hidden_fields": {"viewer": ["机密列"]}},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/v1/accounts/auth/register",
        json={"username": "dictviewer", "email": "dv@example.com", "password": "passw0rd"},
    )
    assert r.status_code in (200, 201), r.text
    r = client.post("/api/v1/accounts/auth/login", json={"login": "dictviewer", "password": "passw0rd"})
    viewer_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.post(
        f"/api/v1/workspaces/{wid}/members",
        headers=auth_headers,
        json={"username": "dictviewer", "role": "viewer"},
    )
    assert r.status_code in (200, 201), r.text

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=md", headers=viewer_headers)
    assert r.status_code == 200, r.text
    assert "公开列" in r.text
    assert "机密列" not in r.text


# ── C1：格式与只读 ────────────────────────────────────


def test_dictionary_unknown_format(client, auth_headers, ws_table):
    """C1：非法格式 400，别名可识别."""
    wid, tid = ws_table
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=xxx", headers=auth_headers)
    assert r.status_code == 400
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=markdown", headers=auth_headers)
    assert r.status_code == 200


def test_dictionary_is_read_only(client, auth_headers, ws_table):
    """I2：字典端点只读（POST 405/404，绝无写路径）."""
    wid, tid = ws_table
    r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary", headers=auth_headers)
    assert r.status_code in (404, 405)


def test_dictionary_requires_read_permission(client, auth_headers, ws_table):
    """C5：非成员访问被拒（与行数据导出同口径：403 + 角色指引文案）."""
    wid, tid = ws_table
    r = client.post(
        "/api/v1/accounts/auth/register",
        json={"username": "dictoutsider", "email": "do@example.com", "password": "passw0rd"},
    )
    assert r.status_code in (200, 201), r.text
    r = client.post("/api/v1/accounts/auth/login", json={"login": "dictoutsider", "password": "passw0rd"})
    outsider = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=md", headers=outsider)
    assert r.status_code in (403, 404)


# ── C9：审计 ──────────────────────────────────────────


def test_dictionary_audit_event(client, auth_headers, ws_table, db):
    """C9：导出写事件，detail 不含业务文本."""
    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text", business_meaning="业务口径文本")
    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=md", headers=auth_headers)
    assert r.status_code == 200

    from cndb.core.events import query_events

    items, total = query_events(db, action="table.dictionary_export")
    assert total >= 1, "未记录字典导出事件"
    event = items[0]
    assert event.workspace_id == wid
    assert event.target_type == "table"
    assert event.target_id == str(tid)
    detail = json.dumps(event.detail or {}, ensure_ascii=False)
    # 只记定位与计数，不落字段说明 / 示例值（H38）
    assert "业务口径文本" not in detail
    assert detail.count('"md"') == 1
    assert '"field_count": 1' in detail
    assert '"table_count": 1' in detail


# ── C8：docx / pdf 走注册表 ───────────────────────────


def test_dictionary_docx_and_pdf(client, auth_headers, ws_table):
    """C8：docx / pdf 可用（渲染器由 documents 插件注册），未注册时 503."""
    from cndb.render.markdown_export import is_available

    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=docx", headers=auth_headers)
    if is_available("docx"):
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK"
    else:  # pragma: no cover - 正常启动路径下渲染器已注册
        assert r.status_code == 503

    r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=pdf", headers=auth_headers)
    if is_available("pdf"):
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"
    else:  # pragma: no cover
        assert r.status_code == 503


def test_dictionary_renderer_unavailable_returns_503(client, auth_headers, ws_table, monkeypatch):
    """C8：渲染器未注册 → 503 且提示可改用 md / xlsx / json."""
    from cndb.render.markdown_export import register_renderer, unregister_renderer

    wid, tid = ws_table
    _add_field(client, auth_headers, wid, tid, name="名称", field_type="text")

    saved = {}
    for fmt in ("docx", "pdf"):
        from cndb.render.markdown_export import _registry

        saved[fmt] = _registry.pop(fmt, None)
    try:
        r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/dictionary?format=docx", headers=auth_headers)
        assert r.status_code == 503
        assert "md / xlsx / json" in r.json()["detail"]
    finally:
        for fmt, renderer in saved.items():
            if renderer is not None:
                register_renderer(fmt, renderer)
        unregister_renderer("__never__")

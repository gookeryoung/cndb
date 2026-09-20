"""reports 插件集成测试."""

import io

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.reports.models import OutputFormat


@pytest.fixture
def auth_headers(client, db):
    """注册并登录，返回 Authorization header."""
    user = User(username="reporter", email="r@b.c", nickname="R")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    resp = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "reporter", "password": "pass1234"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestReportTemplateCRUD:
    """报告模板 CRUD 测试."""

    def test_create_template(self, client, auth_headers):
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "员工名册",
                "description": "列出所有员工姓名",
                "output_format": "docx",
                "template_content": "# 员工名册\n{% for r in records %}{{ r.name }}\n{% endfor %}",
                "parameters": [],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "员工名册"
        assert data["output_format"] == "docx"
        assert data["id"] > 0

    def test_list_templates(self, client, auth_headers):
        # 创建两个模板
        for i in range(2):
            client.post(
                "/api/v1/reports",
                headers=auth_headers,
                json={
                    "name": f"模板{i}",
                    "output_format": "docx",
                    "template_content": "{{ table_name }}",
                },
            )
        resp = client.get("/api/v1/reports", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2

    def test_get_template(self, client, auth_headers):
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "模板A",
                "output_format": "pdf",
                "template_content": "hello {{ params.msg }}",
            },
        )
        tid = create_resp.json()["id"]
        resp = client.get(f"/api/v1/reports/{tid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "模板A"

    def test_get_template_not_found(self, client, auth_headers):
        resp = client.get("/api/v1/reports/99999", headers=auth_headers)
        assert resp.status_code == 404

    def test_update_template(self, client, auth_headers):
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "旧名",
                "output_format": "docx",
                "template_content": "old",
            },
        )
        tid = create_resp.json()["id"]
        resp = client.put(
            f"/api/v1/reports/{tid}",
            headers=auth_headers,
            json={"name": "新名", "output_format": "xlsx"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名"
        assert resp.json()["output_format"] == "xlsx"

    def test_delete_template(self, client, auth_headers):
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "待删",
                "output_format": "docx",
                "template_content": "del",
            },
        )
        tid = create_resp.json()["id"]
        resp = client.delete(f"/api/v1/reports/{tid}", headers=auth_headers)
        assert resp.status_code == 204
        resp = client.get(f"/api/v1/reports/{tid}", headers=auth_headers)
        assert resp.status_code == 404


class TestReportTemplateValidation:
    """模板校验测试."""

    def test_invalid_format_create(self, client, auth_headers):
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "坏模板",
                "output_format": "zip",
                "template_content": "x",
            },
        )
        assert resp.status_code == 400
        assert "不支持的输出格式" in resp.json()["detail"]

    def test_invalid_format_update(self, client, auth_headers):
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "模板",
                "output_format": "docx",
                "template_content": "x",
            },
        )
        tid = create_resp.json()["id"]
        resp = client.put(
            f"/api/v1/reports/{tid}",
            headers=auth_headers,
            json={"output_format": "tar"},
        )
        assert resp.status_code == 400

    def test_bad_jinja_syntax_create(self, client, auth_headers):
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "坏语法",
                "output_format": "docx",
                "template_content": "{% if %}",
            },
        )
        assert resp.status_code == 400
        assert "模板语法错误" in resp.json()["detail"]

    def test_bad_jinja_syntax_update(self, client, auth_headers):
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "模板",
                "output_format": "docx",
                "template_content": "ok",
            },
        )
        tid = create_resp.json()["id"]
        resp = client.put(
            f"/api/v1/reports/{tid}",
            headers=auth_headers,
            json={"template_content": "{% xyz %}"},
        )
        assert resp.status_code == 400


class TestReportRender:
    """报告渲染测试."""

    def test_render_docx(self, client, auth_headers, db):
        # 创建 workspace + table + fields
        ws = client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={"name": "测试工作区"},
        )
        wid = ws.json()["id"]
        table_resp = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "员工表"},
        )
        tid = table_resp.json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "姓名", "field_type": "text"},
        )
        # 添加一条记录
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"data": {"姓名": "张三"}},
        )
        # 创建模板
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "docx报告",
                "output_format": "docx",
                "template_content": "hello {{ table_name }}\\n{% for r in records %}{{ r.get('姓名', '') }}\\n{% endfor %}",
            },
        )
        tpl_id = tpl.json()["id"]
        # 渲染
        resp = client.post(
            f"/api/v1/reports/{tpl_id}/render",
            headers=auth_headers,
            json={"table_id": tid, "params": {}},
        )
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats" in resp.headers["content-type"]
        assert len(resp.content) > 0

    def test_render_pdf(self, client, auth_headers, db):
        ws = client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={"name": "ws2"},
        )
        wid = ws.json()["id"]
        table_resp = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "t2"},
        )
        tid = table_resp.json()["id"]
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "pdf报告",
                "output_format": "pdf",
                "template_content": "PDF 测试 {{ table_name }}",
            },
        )
        tpl_id = tpl.json()["id"]
        resp = client.post(
            f"/api/v1/reports/{tpl_id}/render",
            headers=auth_headers,
            json={"table_id": tid, "params": {}},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert len(resp.content) > 0

    def test_render_xlsx(self, client, auth_headers, db):
        ws = client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={"name": "ws3"},
        )
        wid = ws.json()["id"]
        table_resp = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "t3"},
        )
        tid = table_resp.json()["id"]
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "xlsx报告",
                "output_format": "xlsx",
                "template_content": "col1\\tcol2\\n{{ table_name }}\\tok",
            },
        )
        tpl_id = tpl.json()["id"]
        resp = client.post(
            f"/api/v1/reports/{tpl_id}/render",
            headers=auth_headers,
            json={"table_id": tid, "params": {}},
        )
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]

    def test_render_template_not_found(self, client, auth_headers):
        resp = client.post(
            "/api/v1/reports/99999/render",
            headers=auth_headers,
            json={"table_id": 1, "params": {}},
        )
        assert resp.status_code == 404

    def test_render_table_not_found(self, client, auth_headers):
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "模板",
                "output_format": "docx",
                "template_content": "x",
            },
        )
        tpl_id = tpl.json()["id"]
        resp = client.post(
            f"/api/v1/reports/{tpl_id}/render",
            headers=auth_headers,
            json={"table_id": 99999, "params": {}},
        )
        assert resp.status_code == 404

    def test_render_template_runtime_error(self, client, auth_headers, db):
        ws = client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={"name": "ws4"},
        )
        wid = ws.json()["id"]
        table_resp = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "t4"},
        )
        tid = table_resp.json()["id"]
        # 用 StrictUndefined 渲染不存在的变量，应该 400
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "坏模板",
                "output_format": "docx",
                "template_content": "{{ undefined_var }}",
            },
        )
        tpl_id = tpl.json()["id"]
        resp = client.post(
            f"/api/v1/reports/{tpl_id}/render",
            headers=auth_headers,
            json={"table_id": tid, "params": {}},
        )
        assert resp.status_code == 400
        assert "模板渲染失败" in resp.json()["detail"]

    def test_output_format_enum_values(self):
        """OutputFormat 枚举应包含三种格式."""
        assert OutputFormat.DOCX == "docx"
        assert OutputFormat.PDF == "pdf"
        assert OutputFormat.XLSX == "xlsx"


class TestReportTemplateOwnership:
    """模板归属 table_id 校验测试."""

    def test_create_template_with_valid_table(self, client, auth_headers):
        """绑定存在的 table_id 应成功."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_own"})
        wid = ws.json()["id"]
        tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_own"})
        tid = tbl.json()["id"]
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "带归属",
                "table_id": tid,
                "output_format": "docx",
                "template_content": "x",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["table_id"] == tid

    def test_create_template_with_invalid_table(self, client, auth_headers):
        """绑定不存在的 table_id 应 404."""
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "坏归属",
                "table_id": 99999,
                "output_format": "docx",
                "template_content": "x",
            },
        )
        assert resp.status_code == 404

    def test_update_template_with_invalid_table(self, client, auth_headers):
        """更新时传入不存在的 table_id 应 404."""
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "模板",
                "output_format": "docx",
                "template_content": "x",
            },
        )
        tid = create_resp.json()["id"]
        resp = client.put(
            f"/api/v1/reports/{tid}",
            headers=auth_headers,
            json={"table_id": 99999},
        )
        assert resp.status_code == 404


def test_update_template_parameters(client, auth_headers):
    """更新 parameters 字段应正确生效."""
    create_resp = client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "name": "模板",
            "output_format": "docx",
            "template_content": "{{ params.msg }}",
            "parameters": [{"name": "msg", "type": "string", "required": True}],
        },
    )
    tid = create_resp.json()["id"]
    resp = client.put(
        f"/api/v1/reports/{tid}",
        headers=auth_headers,
        json={"parameters": [{"name": "new_param", "type": "number"}]},
    )
    assert resp.status_code == 200
    params = resp.json()["parameters"]
    assert len(params) == 1
    assert params[0]["name"] == "new_param"


def test_update_template_to_null_table_id(client, auth_headers, db):
    """已绑定 table 的模板可以解除绑定（table_id=null）."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_null"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_null"})
    tid = tbl.json()["id"]

    create_resp = client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "name": "模板",
            "table_id": tid,
            "output_format": "docx",
            "template_content": "x",
        },
    )
    rep_id = create_resp.json()["id"]
    assert create_resp.json()["table_id"] == tid

    resp = client.put(
        f"/api/v1/reports/{rep_id}",
        headers=auth_headers,
        json={"table_id": None},
    )
    assert resp.status_code == 200
    assert resp.json()["table_id"] is None


def test_plugin_register_routes_fallback(monkeypatch):
    """覆盖 ReportsPlugin.register_routes fallback 分支（direct_router 未设置时）."""
    from fastapi import APIRouter

    from cndb.plugins.reports.plugin import ReportsPlugin

    # monkeypatch APIRouter.include_router 避免空 path 校验报错
    monkeypatch.setattr(APIRouter, "include_router", lambda self, r: None)

    plugin = ReportsPlugin()
    router = APIRouter()
    plugin.register_routes(router)
    assert plugin.direct_router is not None


def test_render_unsupported_format(client, auth_headers, db):
    """如果模板格式不被渲染器支持（当前只有 docx/pdf/xlsx），应 400."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_uf"})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_uf"})
    tid = tbl.json()["id"]
    # 手动在 DB 里把 output_format 改成一个非法值（绕过 create 时的校验）
    from sqlalchemy import update as sa_update

    from cndb.plugins.reports.models import ReportTemplate

    tpl = client.post(
        "/api/v1/reports",
        headers=auth_headers,
        json={
            "name": "坏模板",
            "output_format": "docx",
            "template_content": "x",
        },
    )
    rep_id = tpl.json()["id"]
    # 直接改 DB
    db.execute(sa_update(ReportTemplate).where(ReportTemplate.id == rep_id).values(output_format="xyz"))
    db.commit()
    resp = client.post(
        f"/api/v1/reports/{rep_id}/render",
        headers=auth_headers,
        json={"table_id": tid, "params": {}},
    )
    assert resp.status_code == 400


# ── 额外引用表持久化（extra_table_ids）────────────────


def _create_ws_with_two_tables(client, auth_headers, ws_name):
    """创建工作区 + 两张表，返回 (wid, tid_a, tid_b)."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": ws_name})
    wid = ws.json()["id"]
    tbl_a = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "主表"})
    tid_a = tbl_a.json()["id"]
    tbl_b = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "副表"})
    tid_b = tbl_b.json()["id"]
    return wid, tid_a, tid_b


class TestExtraTableIdsPersistence:
    """模板持久化额外引用表测试."""

    def test_create_template_with_extra_table_ids(self, client, auth_headers):
        """create 携带 extra_table_ids 应持久化并在响应回显."""
        _wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_create")
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "带额外表",
                "output_format": "docx",
                "template_content": "x",
                "table_id": tid_a,
                "extra_table_ids": [tid_b],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["extra_table_ids"] == [tid_b]

    def test_create_template_with_invalid_extra_table(self, client, auth_headers):
        """extra_table_ids 含不存在的表 ID 应 404."""
        _wid, tid_a, _tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_bad")
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "坏额外表",
                "output_format": "docx",
                "template_content": "x",
                "table_id": tid_a,
                "extra_table_ids": [99999],
            },
        )
        assert resp.status_code == 404

    def test_create_template_extras_normalized(self, client, auth_headers):
        """create 时额外表去重保序、剔除主表自身."""
        _wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_norm")
        resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "归一化",
                "output_format": "docx",
                "template_content": "x",
                "table_id": tid_a,
                "extra_table_ids": [tid_b, tid_a, tid_b],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["extra_table_ids"] == [tid_b]

    def test_update_template_extra_table_ids(self, client, auth_headers):
        """update 显式传 extra_table_ids 应持久化."""
        _wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_update")
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={"name": "模板", "output_format": "docx", "template_content": "x", "table_id": tid_a},
        )
        rep_id = create_resp.json()["id"]
        resp = client.put(
            f"/api/v1/reports/{rep_id}",
            headers=auth_headers,
            json={"extra_table_ids": [tid_b]},
        )
        assert resp.status_code == 200
        assert resp.json()["extra_table_ids"] == [tid_b]

    def test_update_template_extras_null_clears(self, client, auth_headers):
        """update 显式传 null 视为清空额外表."""
        _wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_null")
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "模板",
                "output_format": "docx",
                "template_content": "x",
                "table_id": tid_a,
                "extra_table_ids": [tid_b],
            },
        )
        rep_id = create_resp.json()["id"]
        resp = client.put(
            f"/api/v1/reports/{rep_id}",
            headers=auth_headers,
            json={"extra_table_ids": None},
        )
        assert resp.status_code == 200
        assert resp.json()["extra_table_ids"] == []

    def test_list_response_contains_extra_table_ids(self, client, auth_headers):
        """列表接口应返回 extra_table_ids 字段."""
        _wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_list")
        client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "列表模板",
                "output_format": "docx",
                "template_content": "x",
                "table_id": tid_a,
                "extra_table_ids": [tid_b],
            },
        )
        resp = client.get("/api/v1/reports", headers=auth_headers)
        assert resp.status_code == 200
        items = [it for it in resp.json() if it["name"] == "列表模板"]
        assert len(items) == 1
        assert items[0]["extra_table_ids"] == [tid_b]

    def test_render_falls_back_to_persisted_extras(self, client, auth_headers):
        """渲染请求不带 extra_table_ids 时应回落到模板持久化的额外表（xlsx sheet 验证）."""
        wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_render")
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
            headers=auth_headers,
            json={"name": "项目名", "field_type": "text"},
        )
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "回落渲染",
                "output_format": "xlsx",
                "template_content": "回落测试",
                "table_id": tid_a,
                "extra_table_ids": [tid_b],
            },
        )
        rep_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/v1/reports/{rep_id}/render",
            headers=auth_headers,
            json={"table_id": tid_a, "params": {}},
        )
        assert resp.status_code == 200
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(resp.content))
        assert "副表" in wb.sheetnames, f"额外表 Sheet 缺失，实际 {wb.sheetnames}"

    def test_render_request_extras_override_persisted(self, client, auth_headers):
        """渲染请求显式传 extra_table_ids 时优先于模板持久化值."""
        wid, tid_a, tid_b = _create_ws_with_two_tables(client, auth_headers, "ws_extra_override")
        tbl_c = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "副表C"})
        tid_c = tbl_c.json()["id"]
        create_resp = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "覆盖渲染",
                "output_format": "xlsx",
                "template_content": "覆盖测试",
                "table_id": tid_a,
                "extra_table_ids": [tid_b],
            },
        )
        rep_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/v1/reports/{rep_id}/render",
            headers=auth_headers,
            json={"table_id": tid_a, "params": {}, "extra_table_ids": [tid_c]},
        )
        assert resp.status_code == 200
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(resp.content))
        assert "副表C" in wb.sheetnames
        assert "副表" not in wb.sheetnames


# ── row_ids 行过滤 + 渲染上下文对齐 ───────────────────


def _create_table_with_rows(client, auth_headers, ws_name, row_count):
    """创建工作区 + 含姓名字段表 + 批量插入 row_count 行，返回 (wid, tid, row_ids)."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": ws_name})
    wid = ws.json()["id"]
    tbl = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "成员表"})
    tid = tbl.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "姓名", "field_type": "text"},
    )
    names = [f"成员{i:03d}" for i in range(row_count)]
    bulk = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/bulk-create",
        headers=auth_headers,
        json={"rows": [{"values": {"姓名": n}} for n in names]},
    )
    assert bulk.status_code == 201, bulk.text
    return wid, tid, bulk.json()["ids"]


def _render_docx_text(client, auth_headers, template_id, tid, body):
    """渲染 docx 模板并返回正文文本，便于断言."""
    resp = client.post(
        f"/api/v1/reports/{template_id}/render",
        headers=auth_headers,
        json={"table_id": tid, "params": {}, **body},
    )
    assert resp.status_code == 200, resp.text
    from docx import Document

    doc = Document(io.BytesIO(resp.content))
    return "\n".join(p.text for p in doc.paragraphs)


class TestRenderRowFiltering:
    """row_ids 主表行过滤测试."""

    def test_row_ids_filters_records(self, client, auth_headers):
        """row_ids 非空时只渲染指定行."""
        _wid, tid, ids = _create_table_with_rows(client, auth_headers, "ws_rowids_1", 3)
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "行过滤",
                "output_format": "docx",
                "template_content": "共 {{ records | length }} 条",
            },
        )
        rep_id = tpl.json()["id"]
        text = _render_docx_text(client, auth_headers, rep_id, tid, {"row_ids": [ids[0], ids[2]]})
        assert "共 2 条" in text

    def test_row_ids_preserves_order(self, client, auth_headers):
        """row_ids 保持给定顺序输出."""
        _wid, tid, ids = _create_table_with_rows(client, auth_headers, "ws_rowids_2", 3)
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "行序",
                "output_format": "docx",
                "template_content": "{% for r in records %}{{ r.姓名 }}{% endfor %}",
            },
        )
        rep_id = tpl.json()["id"]
        text = _render_docx_text(client, auth_headers, rep_id, tid, {"row_ids": [ids[2], ids[0]]})
        # 成员000/001/002 对应 ids[0]/ids[1]/ids[2]
        assert "成员002成员000" in text

    def test_row_ids_missing_ids_ignored(self, client, auth_headers):
        """row_ids 含不存在的 id 应忽略，不影响渲染."""
        _wid, tid, ids = _create_table_with_rows(client, auth_headers, "ws_rowids_3", 2)
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "缺行",
                "output_format": "docx",
                "template_content": "共 {{ records | length }} 条",
            },
        )
        rep_id = tpl.json()["id"]
        text = _render_docx_text(client, auth_headers, rep_id, tid, {"row_ids": [ids[0], 999999]})
        assert "共 1 条" in text

    def test_row_ids_empty_renders_all(self, client, auth_headers):
        """row_ids 缺省/为空时渲染全部行."""
        _wid, tid, _ids = _create_table_with_rows(client, auth_headers, "ws_rowids_4", 3)
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "全量",
                "output_format": "docx",
                "template_content": "共 {{ records | length }} 条",
            },
        )
        rep_id = tpl.json()["id"]
        text = _render_docx_text(client, auth_headers, rep_id, tid, {})
        assert "共 3 条" in text


class TestRenderFullRows:
    """渲染行数上限修复 + 上下文对齐测试."""

    def test_render_over_100_rows(self, client, auth_headers):
        """超过 100 行的表应全量渲染（修复 list_rows 默认 limit=100 静默截断）."""
        _wid, tid, _ids = _create_table_with_rows(client, auth_headers, "ws_full_rows", 120)
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "全量渲染",
                "output_format": "docx",
                "template_content": "共 {{ records | length }} 条",
            },
        )
        rep_id = tpl.json()["id"]
        text = _render_docx_text(client, auth_headers, rep_id, tid, {})
        assert "共 120 条" in text, f"应渲染 120 行，实际输出: {text!r}"

    def test_records_contain_id(self, client, auth_headers):
        """渲染上下文 records 应含 id 键（与前端预览上下文对齐）."""
        _wid, tid, ids = _create_table_with_rows(client, auth_headers, "ws_ctx_id", 1)
        tpl = client.post(
            "/api/v1/reports",
            headers=auth_headers,
            json={
                "name": "上下文id",
                "output_format": "docx",
                "template_content": "id={{ records[0].id }}",
            },
        )
        rep_id = tpl.json()["id"]
        text = _render_docx_text(client, auth_headers, rep_id, tid, {})
        assert f"id={ids[0]}" in text

"""reports 插件集成测试."""

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

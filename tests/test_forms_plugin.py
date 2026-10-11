"""forms 插件冒烟测试：模型注册 + 插件发现 + 路由挂载."""

from __future__ import annotations

import pytest

from cndb.models.base import Base
from cndb.plugins.forms.models import FormDefinition


def test_formdefinition_in_metadata() -> None:
    """FormDefinition 应注册到 Base.metadata."""
    assert "forms_formdefinition" in Base.metadata.tables


def test_formdefinition_defaults(db) -> None:
    """新 FormDefinition 默认值：阈值列空 / field_config 空列表 / 未软删."""
    fd = FormDefinition(workspace_id=1, table_id=1, name="冒烟表单")
    db.add(fd)
    db.commit()
    db.refresh(fd)
    assert fd.field_config == []
    assert fd.layout == {}
    assert fd.use_role == ""
    assert fd.edit_role == ""
    assert fd.delete_role == ""
    assert fd.trashed is False
    assert fd.order == 0


def test_formdefinition_unique_table_name(db) -> None:
    """同表下表单名唯一."""
    db.add(FormDefinition(workspace_id=1, table_id=1, name="重名表单"))
    db.commit()
    db.add(FormDefinition(workspace_id=1, table_id=1, name="重名表单"))
    with pytest.raises(Exception):  # noqa: B017 - SQLAlchemy IntegrityError 包装各异
        db.commit()
    db.rollback()


def test_forms_plugin_discovered() -> None:
    """插件自动发现应加载 forms 插件."""
    from cndb.core.plugin_registry import PluginRegistry

    r = PluginRegistry()
    r.discover_and_load()
    names = {p["name"] for p in r.get_plugin_info_list()}
    assert "forms" in names


def test_forms_routes_mounted(client) -> None:
    """forms 路由应挂载到 workspaces 前缀下（未认证访问返回 401/403 而非 404）."""
    r = client.get("/api/v1/workspaces/1/forms")
    assert r.status_code in (401, 403)


__all__ = []

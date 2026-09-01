"""共享视图测试：grid 视图公开 slug 生命周期与匿名只读行端点."""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from cndb.tables import records as table_records
from cndb.tables import services
from cndb.tables.models import DataTable, DataView
from cndb.workspaces.models import Workspace


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """带文本/数值字段的共享测试表."""
    return services.create_table(
        workspace=workspace,  # type: ignore[arg-type]
        name="共享表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "数量", "field_type": "number"},
        ],
    )


def _insert(table: DataTable, rows: list[dict[str, object]]) -> list[int]:
    """校验并插入行，返回主键列表."""
    cleaned = [table_records.clean_row(table, row, partial=True) for row in rows]
    return table_records.insert_rows(table, cleaned)


class TestShareSlug:
    """slug 生命周期：grid 视图按公开共享生成与回收."""

    def test_public_grid_gets_slug(self, table: DataTable) -> None:
        """公开 grid 视图保存时自动生成 share_ 前缀 slug."""
        view = DataView.objects.create(table=table, name="共享视图", public=True)
        assert view.slug is not None
        assert view.slug.startswith("share_")
        assert len(view.slug) == len("share_") + 16

    def test_private_grid_has_no_slug(self, table: DataTable) -> None:
        """未公开的 grid 视图 slug 为 None."""
        view = DataView.objects.create(table=table, name="私有视图")
        assert view.slug is None

    def test_sharing_generates_slug(self, table: DataTable) -> None:
        """私有视图开启共享后生成 slug."""
        view = DataView.objects.create(table=table, name="转公开")
        assert view.slug is None
        view.public = True
        view.save()
        view.refresh_from_db()
        assert view.slug is not None

    def test_unsharing_revokes_slug(self, table: DataTable) -> None:
        """关闭共享即回收 slug，旧链接立即失效."""
        view = DataView.objects.create(table=table, name="转私有", public=True)
        slug = view.slug
        assert slug is not None
        view.public = False
        view.save()
        view.refresh_from_db()
        assert view.slug is None

    def test_slug_stable_across_saves(self, table: DataTable) -> None:
        """公开期间再次保存不重置 slug."""
        view = DataView.objects.create(table=table, name="稳定", public=True)
        original = view.slug
        view.name = "稳定改"
        view.save()
        view.refresh_from_db()
        assert view.slug == original

    def test_form_slug_unaffected(self, table: DataTable) -> None:
        """表单视图 slug 仍为 form_ 前缀，与共享 slug 体系互不干扰."""
        view = DataView.objects.create(table=table, name="表单", view_type=DataView.ViewType.FORM)
        assert view.slug is not None
        assert view.slug.startswith("form_")


class TestPublicRows:
    """匿名行读取：视图规则生效与存在性隐藏."""

    def _shared_view(self, table: DataTable, **kwargs: object) -> DataView:
        """建一个公开共享视图并返回."""
        return DataView.objects.create(table=table, name="共享", public=True, **kwargs)  # type: ignore[arg-type]

    def test_anonymous_reads_rows(self, api: APIClient, table: DataTable) -> None:
        """匿名客户端按 slug 读取视图行."""
        _insert(table, [{"标题": "甲", "数量": Decimal("1")}])
        view = self._shared_view(table)
        response = api.get(f"/api/views/{view.slug}/rows/")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["标题"] == "甲"

    def test_view_filters_applied(self, api: APIClient, table: DataTable) -> None:
        """视图筛选规则对公开读取生效."""
        _insert(
            table,
            [{"标题": "正式-甲", "数量": Decimal("1")}, {"标题": "试用-乙", "数量": Decimal("2")}],
        )
        view = self._shared_view(table, filters=[{"field": "标题", "op": "contains", "value": "正式"}])
        response = api.get(f"/api/views/{view.slug}/rows/")
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["标题"] == "正式-甲"

    def test_sorting_and_paging(self, api: APIClient, table: DataTable) -> None:
        """视图排序与 page/page_size 分页生效."""
        _insert(
            table,
            [
                {"标题": "甲", "数量": Decimal("3")},
                {"标题": "乙", "数量": Decimal("1")},
                {"标题": "丙", "数量": Decimal("2")},
            ],
        )
        view = self._shared_view(table, sortings=[{"field": "数量", "direction": "asc"}])
        response = api.get(f"/api/views/{view.slug}/rows/?page=1&page_size=2")
        assert response.status_code == 200
        assert response.data["count"] == 3
        assert [row["标题"] for row in response.data["results"]] == ["乙", "丙"]
        assert response.data["next"] is not None
        assert response.data["previous"] is None

    def test_unknown_slug_404(self, api: APIClient, table: DataTable, db: object) -> None:
        """未知 slug 返回 404."""
        response = api.get("/api/views/share_0000000000000000/rows/")
        assert response.status_code == 404

    def test_unshared_view_404(self, api: APIClient, table: DataTable) -> None:
        """关闭共享后的旧 slug 返回 404."""
        view = self._shared_view(table)
        slug = view.slug
        view.public = False  # type: ignore[bad-assignment]
        view.save()
        response = api.get(f"/api/views/{slug}/rows/")
        assert response.status_code == 404

    def test_form_slug_not_readable(self, api: APIClient, table: DataTable) -> None:
        """表单视图 slug 不能经共享行端点读取."""
        view = DataView.objects.create(table=table, name="表单", view_type=DataView.ViewType.FORM, public=True)
        response = api.get(f"/api/views/{view.slug}/rows/")
        assert response.status_code == 404

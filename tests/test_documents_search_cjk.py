"""文档全文检索：中文子串兜底通道测试.

背景：FTS5 的 ``unicode61`` 分词把连续中文当作**单个 token**，用户输入「销售」「管理」这类
常用词片段时命中为 0。``search_documents`` 因此在 FTS 命中为 0 时追加 LIKE 子串通道
（只增不减，不改变既有命中）。

覆盖：中文词片段 / 子串 / 前缀、仅命中正文的关键词、多词 AND、筛选与工作区隔离仍生效、
软删除排除、LIKE 通配符转义、分页与高亮排序、空查询仍 400、FTS 通道不受影响。
"""

from __future__ import annotations

import pytest

API = "/api/v1/workspaces/{wid}/documents"


@pytest.fixture
def workspace_id(client, auth_headers) -> int:
    r = client.post(
        "/api/v1/workspaces",
        json={"name": "cjk-search-ws", "description": "中文检索测试"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def doc_api(workspace_id: int) -> str:
    return API.format(wid=workspace_id)


def _create(client, doc_api: str, auth, title: str, content: str = "正文") -> dict:
    r = client.post(doc_api, json={"title": title, "content": content}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _search(client, doc_api: str, auth, q: str, **extra) -> dict:
    r = client.get(f"{doc_api}/search", params={"q": q, **extra}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


class TestCjkSubstringFallback:
    def test_two_char_common_word_hits(self, client, doc_api, auth_headers):
        """「销售」这类两字常用词必须能命中「销售管理总览」"""
        _create(client, doc_api, auth_headers, "销售管理总览", "本工作区承载经营数据")
        _create(client, doc_api, auth_headers, "无关文档", "别的正文")

        data = _search(client, doc_api, auth_headers, "销售")
        assert data["total"] == 1
        assert data["items"][0]["title"] == "销售管理总览"

    def test_middle_substring_hits(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "销售管理总览")
        assert _search(client, doc_api, auth_headers, "售管")["total"] == 1

    def test_four_char_prefix_of_longer_token_hits(self, client, doc_api, auth_headers):
        """「销售管理」是 token「销售管理总览」的前缀，FTS 无 * 不命中，兜底须命中"""
        _create(client, doc_api, auth_headers, "销售管理总览")
        assert _search(client, doc_api, auth_headers, "销售管理")["total"] == 1

    def test_keyword_only_in_content_hits(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "季度复盘", "本季度重点改进客户流失预警机制")
        _create(client, doc_api, auth_headers, "无关文档", "没有那个词")

        data = _search(client, doc_api, auth_headers, "流失预警")
        assert data["total"] == 1
        assert data["items"][0]["title"] == "季度复盘"

    def test_multi_term_uses_and_semantics(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "销售管理总览", "销售与管理")
        _create(client, doc_api, auth_headers, "销售周报", "只有销售")

        assert _search(client, doc_api, auth_headers, "销售 管理")["total"] == 1
        assert _search(client, doc_api, auth_headers, "销售 不存在的词")["total"] == 0

    def test_title_hits_rank_before_content_hits(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "无关文档", "正文里提到客户流失")
        _create(client, doc_api, auth_headers, "客户流失专题")

        items = _search(client, doc_api, auth_headers, "客户流失")["items"]
        assert next(it["title"] for it in items) == "客户流失专题"
        assert "<mark>" in items[0]["title_hit"]

    def test_highlight_wrapped_in_title(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "客户流失预警")
        item = _search(client, doc_api, auth_headers, "流失")["items"][0]
        assert "<mark>流失</mark>" in item["title_hit"]

    def test_pagination_and_total(self, client, doc_api, auth_headers):
        for i in range(5):
            _create(client, doc_api, auth_headers, f"销售文档{i}")

        page1 = _search(client, doc_api, auth_headers, "销售", limit=2, offset=0)
        page2 = _search(client, doc_api, auth_headers, "销售", limit=2, offset=2)
        assert page1["total"] == 5 == page2["total"]
        assert len(page1["items"]) == 2
        assert {it["id"] for it in page1["items"]}.isdisjoint({it["id"] for it in page2["items"]})

    def test_like_underscore_is_escaped(self, client, doc_api, auth_headers):
        """用户输入的 _ 必须按字面匹配：若未转义，`_档` 会误命中「文档」"""
        _create(client, doc_api, auth_headers, "普通文档")
        assert _search(client, doc_api, auth_headers, "_档")["total"] == 0

        # 真的存在下划线时按字面命中
        _create(client, doc_api, auth_headers, "下划线_文档")
        assert _search(client, doc_api, auth_headers, "_文")["total"] == 1

    def test_percent_query_rejected_by_existing_validation(self, client, doc_api, auth_headers):
        """纯符号查询仍按既有行为返回 400（本改动不改变校验口径）"""
        r = client.get(f"{doc_api}/search", params={"q": "%"}, headers=auth_headers)
        assert r.status_code == 400

    def test_soft_deleted_excluded(self, client, doc_api, auth_headers):
        doc = _create(client, doc_api, auth_headers, "待删除销售文档")
        assert client.delete(f"{doc_api}/{doc['id']}", headers=auth_headers).status_code == 200
        assert _search(client, doc_api, auth_headers, "销售")["total"] == 0

    def test_empty_query_still_rejected(self, client, doc_api, auth_headers):
        r = client.get(f"{doc_api}/search", params={"q": "   "}, headers=auth_headers)
        assert r.status_code == 400


class TestFallbackRespectsFilters:
    def test_workspace_isolation(self, client, auth_headers):
        wid1 = client.post("/api/v1/workspaces", json={"name": "cjk-ws-1"}, headers=auth_headers).json()["id"]
        wid2 = client.post("/api/v1/workspaces", json={"name": "cjk-ws-2"}, headers=auth_headers).json()["id"]
        client.post(API.format(wid=wid1), json={"title": "销售管理总览", "content": "正文"}, headers=auth_headers)

        r = client.get(API.format(wid=wid2) + "/search", params={"q": "销售"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_status_filter_applies(self, client, doc_api, auth_headers):
        draft = _create(client, doc_api, auth_headers, "销售草稿")
        pub = _create(client, doc_api, auth_headers, "销售已发布")
        client.patch(f"{doc_api}/{pub['id']}", json={"status": "published"}, headers=auth_headers)

        assert _search(client, doc_api, auth_headers, "销售", status="published")["total"] == 1
        assert _search(client, doc_api, auth_headers, "销售", status="draft")["total"] == 1
        assert draft["id"] != pub["id"]

    def test_tag_filter_applies(self, client, doc_api, auth_headers, workspace_id):
        tagged = _create(client, doc_api, auth_headers, "销售带标签")
        _create(client, doc_api, auth_headers, "销售无标签")
        tags_api = f"/api/v1/workspaces/{workspace_id}/document-tags"
        tag = client.post(tags_api, json={"name": "检索"}, headers=auth_headers).json()
        client.post(f"{doc_api}/{tagged['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=auth_headers)

        # 端点参数为单数 tag_id（见 routers/documents.py::search）
        data = _search(client, doc_api, auth_headers, "销售", tag_id=tag["id"])
        assert data["total"] == 1
        assert data["items"][0]["id"] == tagged["id"]


class TestFtsChannelUnaffected:
    def test_latin_token_search_unchanged(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "FastAPI 指南", "FastAPI 是最流行的 Web 框架")
        _create(client, doc_api, auth_headers, "无关文档", "hello world")

        data = _search(client, doc_api, auth_headers, "FastAPI")
        assert data["total"] == 1
        assert "<mark>" in data["items"][0]["title_hit"]

    def test_latin_prefix_still_works(self, client, doc_api, auth_headers):
        _create(client, doc_api, auth_headers, "JavaScript 教程", "JavaScript 基础")
        assert _search(client, doc_api, auth_headers, "Java*")["total"] == 1

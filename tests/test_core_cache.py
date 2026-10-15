"""进程内缓存测试：TTL/LRU/统计/失效 + 列表接口的缓存行为.

覆盖：
- TTLCache：读写、TTL 过期、LRU 淘汰、前缀失效、get_or_set、统计（命中率）、purge_expired；
- 缓存键隔离（不同用户/不同 include_trashed 不串键）；
- 接口层：工作区列表与数据表列表第二次请求命中缓存（统计可见），TTL 过后重新计算；
- **权限仍被校验**：非成员访问仍 403（缓存不绕过鉴权）。
"""

from __future__ import annotations

import time

from cndb.core.cache import TTLCache, cache_key, list_cache

TABLES_API = "/api/v1/workspaces/{wid}/tables"


class TestTTLCache:
    def test_set_get(self):
        cache = TTLCache(max_entries=4)
        cache.set("a", {"v": 1}, 60)
        assert cache.get("a") == {"v": 1}

    def test_miss_and_expiry(self):
        cache = TTLCache(max_entries=4)
        assert cache.get("nope") is None
        cache.set("a", 1, 0.05)
        time.sleep(0.06)
        assert cache.get("a") is None
        assert cache.stats().expirations == 1

    def test_zero_ttl_is_not_cached(self):
        cache = TTLCache(max_entries=4)
        cache.set("a", 1, 0)
        assert cache.get("a") is None

    def test_lru_eviction(self):
        cache = TTLCache(max_entries=2)
        cache.set("a", 1, 60)
        cache.set("b", 2, 60)
        cache.get("a")  # 命中 a → a 变最近使用
        cache.set("c", 3, 60)  # 淘汰最久未用的 b
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.stats().evictions == 1

    def test_clear_by_prefix(self):
        cache = TTLCache(max_entries=8)
        cache.set(cache_key("tables", 1, "x"), 1, 60)
        cache.set(cache_key("tables", 2, "x"), 2, 60)
        cache.set(cache_key("ws-list", 1), 3, 60)
        assert cache.clear(cache_key("tables")) == 2
        assert cache.get(cache_key("tables", 1, "x")) is None
        assert cache.get(cache_key("ws-list", 1)) == 3

    def test_get_or_set_producer_called_once(self):
        cache = TTLCache(max_entries=4)
        calls = []

        def producer() -> dict[str, int]:
            calls.append(1)
            return {"n": len(calls)}

        assert cache.get_or_set("k", 60, producer) == {"n": 1}
        assert cache.get_or_set("k", 60, producer) == {"n": 1}
        assert len(calls) == 1

    def test_stats_hit_rate(self):
        cache = TTLCache(max_entries=4)
        cache.set("a", 1, 60)
        cache.get("a")
        cache.get("miss")
        stats = cache.stats()
        assert stats.hits == 1 and stats.misses == 1
        assert stats.hit_rate == 0.5

    def test_purge_expired(self):
        cache = TTLCache(max_entries=8)
        cache.set("a", 1, 0.02)
        cache.set("b", 2, 60)
        time.sleep(0.03)
        assert cache.purge_expired() == 1
        assert cache.get("b") == 2


class TestListEndpointCaching:
    def test_workspace_list_second_call_hits_cache(self, client, auth_headers):
        list_cache.clear()
        first = client.get("/api/v1/workspaces", headers=auth_headers)
        assert first.status_code == 200
        before = list_cache.stats().hits

        second = client.get("/api/v1/workspaces", headers=auth_headers)
        assert second.status_code == 200
        assert second.json() == first.json()
        assert list_cache.stats().hits == before + 1

    def test_tables_list_second_call_hits_cache(self, client, auth_headers, db):
        list_cache.clear()
        ws = client.post("/api/v1/workspaces", json={"name": "cache-ws"}, headers=auth_headers).json()
        url = TABLES_API.format(wid=ws["id"])
        assert client.get(url, headers=auth_headers).status_code == 200
        before = list_cache.stats().hits
        assert client.get(url, headers=auth_headers).status_code == 200
        assert list_cache.stats().hits == before + 1

    def test_different_include_trashed_not_shared(self, client, auth_headers):
        list_cache.clear()
        ws = client.post("/api/v1/workspaces", json={"name": "cache-flag"}, headers=auth_headers).json()
        url = TABLES_API.format(wid=ws["id"])
        client.get(url, headers=auth_headers)
        before = list_cache.stats().misses
        client.get(url + "?include_trashed=true", headers=auth_headers)
        assert list_cache.stats().misses == before + 1

    def test_permission_not_bypassed_by_cache(self, client, auth_headers, second_client_headers):
        """缓存不得绕过工作区权限校验（跨用户仍 403）."""
        list_cache.clear()
        ws = client.post("/api/v1/workspaces", json={"name": "cache-perm"}, headers=auth_headers).json()
        url = TABLES_API.format(wid=ws["id"])
        assert client.get(url, headers=auth_headers).status_code == 200
        assert client.get(url, headers=second_client_headers).status_code == 403


import pytest  # noqa: E402


@pytest.fixture
def second_client_headers(client, db):
    """另一个用户（非该工作区成员）的认证头."""
    username, password = "cache-outsider", "passw0rd"
    client.post(
        "/api/v1/accounts/auth/register",
        json={"username": username, "email": "outsider@example.com", "password": password},
    )
    token = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}

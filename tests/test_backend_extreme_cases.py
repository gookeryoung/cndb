"""后端核心健壮性补充用例 —— 极端 / 边界情况（不改业务逻辑，仅锁定既有行为）.

靶点（此前无专门单测，详见 docs/ROBUSTNESS_RELIABILITY_PLAN.md 第 3 节）：
- core/ratelimit：滑动窗口限流的阈值边界、窗口滑出、键归一化、configure 钳制、并发；
- core/security：令牌哈希/刷新令牌的确定性与唯一性、access token 声明与失效分支；
- core/cache：TTL/LRU 缓存的删除/清空/负 TTL/producer 异常与 None/全局失效；
- core/database.db_readiness：可达未迁移 / 有迁移版本 / 不可达三条分支；
- core/errors：基类默认值与 TooManyRequestsError 默认 retry_after；
- api/deps：认证头极端形态（方案大小写、令牌首尾空白、停用账号）。
"""

from __future__ import annotations

import hashlib
import re
import threading

import pytest
from sqlalchemy import create_engine, text

from cndb.core import database as dbmod
from cndb.core import security
from cndb.core.cache import TTLCache, cache_key, invalidate_all, list_cache, meta_cache
from cndb.core.config import settings
from cndb.core.errors import CndbError, TooManyRequestsError
from cndb.core.ratelimit import LoginRateLimiter, SlidingWindowLimiter

# ── 滑动窗口限流：极端边界 ─────────────────────────────


class _Clock:
    """可手动推进的假时钟（仅替换 core.ratelimit 模块内的 time 引用）."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """冻结 core.ratelimit 的时间源（模块级替换，不影响其他模块的 time）."""
    import cndb.core.ratelimit as rl

    clock = _Clock()
    monkeypatch.setattr(rl, "time", clock)
    return clock


class TestSlidingWindowLimiterExtremes:
    """滑动窗口计数器的极端/边界行为."""

    def test_constructor_clamps_invalid_limit_and_window(self) -> None:
        """limit/window 传入 0 或负数 → 钳制为 1（避免除零/空窗口语义）."""
        lim = SlidingWindowLimiter(0, 0)
        assert lim.limit == 1
        assert lim.window == 1
        assert SlidingWindowLimiter(-5, -3).limit == 1

    def test_below_threshold_returns_zero(self) -> None:
        """未达阈值时 retry_after 恒为 0（允许请求）."""
        lim = SlidingWindowLimiter(3, 60)
        lim.record("k")
        assert lim.retry_after("k") == 0
        lim.record("k")
        assert lim.retry_after("k") == 0

    def test_at_threshold_returns_positive_wait_within_window(self, frozen_clock: _Clock) -> None:
        """恰好达到阈值即返回等待秒数，且不超过窗口长度."""
        lim = SlidingWindowLimiter(3, 60)
        for _ in range(3):
            lim.record("k")
        wait = lim.retry_after("k")
        assert wait > 0
        assert wait <= 60

    def test_exact_window_boundary_still_counted(self, frozen_clock: _Clock) -> None:
        """t0+window 时刻计数仍在窗口内（cutoff 为严格小于才淘汰）→ 仍返回等待."""
        lim = SlidingWindowLimiter(3, 60)
        for _ in range(3):
            lim.record("k")
        frozen_clock.t = 1000.0 + 60  # 边界：bucket[0]==cutoff，未滑出
        assert lim.retry_after("k") >= 1

    def test_one_past_window_slides_out_and_resets(self, frozen_clock: _Clock) -> None:
        """t0+window+1 时刻最早一次失败滑出 → retry_after 归零."""
        lim = SlidingWindowLimiter(3, 60)
        for _ in range(3):
            lim.record("k")
        frozen_clock.t = 1000.0 + 61
        assert lim.retry_after("k") == 0

    def test_reset_clears_key(self) -> None:
        """reset 清空指定 key 的计数（登录成功后复位语义）."""
        lim = SlidingWindowLimiter(2, 60)
        lim.record("k")
        lim.record("k")
        assert lim.retry_after("k") > 0
        lim.reset("k")
        assert lim.retry_after("k") == 0

    def test_configure_updates_and_clamps_thresholds(self) -> None:
        """configure 同步新阈值并保留既有计数；非法值同样钳制为 1."""
        lim = SlidingWindowLimiter(5, 100)
        lim.configure(2, 30)
        assert lim.limit == 2
        assert lim.window == 30
        lim.configure(0, 0)
        assert lim.limit == 1
        assert lim.window == 1

    def test_concurrent_records_are_thread_safe(self) -> None:
        """8 线程各写 50 次：无异常且计数确定生效（加锁完整性）."""
        lim = SlidingWindowLimiter(10, 60)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for _ in range(50):
                    lim.record("shared")
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert lim.retry_after("shared") > 0


class TestLoginRateLimiterExtremes:
    """登录限流门面：双维度阈值与键归一化."""

    def test_ip_dimension_is_four_times_user_limit(self) -> None:
        lim = LoginRateLimiter(3, 60)
        assert lim.user_limiter.limit == 3
        assert lim.ip_limiter.limit == 12

    def test_configure_syncs_both_dimensions(self) -> None:
        lim = LoginRateLimiter(5, 300)
        lim.configure(2, 30)
        assert lim.user_limiter.limit == 2
        assert lim.user_limiter.window == 30
        assert lim.ip_limiter.limit == 8
        assert lim.ip_limiter.window == 30

    def test_user_key_normalizes_case_and_whitespace(self) -> None:
        assert LoginRateLimiter.user_key("  BoB  ") == "user:bob"
        assert LoginRateLimiter.user_key("bob") == "user:bob"

    def test_ip_key_handles_missing_client(self) -> None:
        assert LoginRateLimiter.ip_key(None) == "ip:unknown"
        assert LoginRateLimiter.ip_key("") == "ip:unknown"
        assert LoginRateLimiter.ip_key("1.2.3.4") == "ip:1.2.3.4"

    def test_user_dimension_blocks_and_reset_clears_user_only(self) -> None:
        """账号维度拦截后，reset(账号) 清账号桶，但 IP 桶计数保留."""
        lim = LoginRateLimiter(2, 60)
        lim.record_failure("bob", "1.1.1.1")
        lim.record_failure("bob", "1.1.1.1")
        assert lim.retry_after("bob", "1.1.1.1") > 0

        lim.reset("bob")
        assert lim.user_limiter.retry_after(lim.user_key("bob")) == 0
        # IP 维度仅 2 次（< 4×2=8），未达阈值但计数仍在（未被 reset 清）
        assert lim.ip_limiter.retry_after(lim.ip_key("1.1.1.1")) == 0

    def test_ip_spray_blocks_ip_dimension_only(self) -> None:
        """同一来源喷洒多账号：仅 IP 维度被拦，单账号维度各自未达阈值."""
        lim = LoginRateLimiter(3, 60)
        ip = "9.9.9.9"
        for i in range(12):  # 12 == 4 × 3，刚好触达 IP 维度上限
            lim.record_failure(f"user{i}", ip)
        assert lim.ip_limiter.retry_after(lim.ip_key(ip)) > 0
        # 每个账号只失败 1 次（< 3），账号维度不越阈
        assert lim.user_limiter.retry_after(lim.user_key("user0")) == 0

    def test_reset_with_ip_clears_ip_bucket(self) -> None:
        """reset(账号, IP) 同时清账号与 IP 两个桶."""
        lim = LoginRateLimiter(1, 60)  # user 上限 1，ip 上限 4
        ip = "2.2.2.2"
        for name in ("a", "b", "c", "d"):
            lim.record_failure(name, ip)
        assert lim.ip_limiter.retry_after(lim.ip_key(ip)) > 0

        lim.reset("a", ip)
        assert lim.ip_limiter.retry_after(lim.ip_key(ip)) == 0
        assert lim.user_limiter.retry_after(lim.user_key("a")) == 0


# ── 令牌与哈希 ──────────────────────────────────────


class TestSecurityTokenExtremes:
    """core.security 的令牌/哈希工具极端分支."""

    def test_hash_token_matches_sha256_hex(self) -> None:
        assert security.hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
        assert len(security.hash_token("abc")) == 64

    def test_hash_token_deterministic_and_input_sensitive(self) -> None:
        assert security.hash_token("xyz") == security.hash_token("xyz")
        assert security.hash_token("xyz") != security.hash_token("xyZ")

    def test_create_refresh_token_shape_and_uniqueness(self) -> None:
        """刷新令牌为固定长度 urlsafe 串，且大批量无碰撞."""
        tokens = {security.create_refresh_token() for _ in range(500)}
        assert len(tokens) == 500
        sample = next(iter(tokens))
        assert len(sample) == 43
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", sample) is not None

    def test_access_token_carries_expected_claims(self) -> None:
        payload = security.decode_access_token(security.create_access_token(subject=42, extra={"username": "a"}))
        assert payload["sub"] == "42"
        assert payload["typ"] == "access"
        assert payload["tv"] == 0
        assert payload["exp"] > payload["iat"]

    def test_access_token_custom_token_version(self) -> None:
        payload = security.decode_access_token(security.create_access_token(subject=1, token_version=7))
        assert payload["tv"] == 7

    def test_decode_rejects_token_signed_with_other_secret(self) -> None:
        from jose import JWTError, jwt

        forged = jwt.encode({"sub": "1"}, "attacker-secret", algorithm=settings.JWT_ALGORITHM)
        with pytest.raises(JWTError):
            security.decode_access_token(forged)

    def test_decode_rejects_expired_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from jose import JWTError

        monkeypatch.setattr(settings, "JWT_EXPIRE_MINUTES", -1)  # 签发即过期
        expired = security.create_access_token(subject=1)
        with pytest.raises(JWTError):
            security.decode_access_token(expired)


# ── 缓存不变量 ───────────────────────────────────────


class TestCacheInvariantExtremes:
    """TTLCache 未被覆盖的方法与退化输入的锁定."""

    def test_delete_removes_entry_and_is_idempotent(self) -> None:
        cache = TTLCache(max_entries=4)
        cache.set("a", 1, 60)
        cache.delete("a")
        assert cache.get("a") is None
        cache.delete("a")  # 缺失 key 删除为无操作
        assert cache.get("a") is None

    def test_clear_without_prefix_returns_count_and_empties(self) -> None:
        cache = TTLCache(max_entries=8)
        cache.set("a", 1, 60)
        cache.set("b", 2, 60)
        assert cache.clear() == 2
        assert cache.get("a") is None

    def test_clear_missing_prefix_returns_zero(self) -> None:
        assert TTLCache(max_entries=4).clear("no-such-prefix") == 0

    def test_negative_ttl_not_cached(self) -> None:
        cache = TTLCache(max_entries=4)
        cache.set("a", 1, -5)
        assert cache.get("a") is None

    def test_producer_returning_none_is_not_cached(self) -> None:
        """producer 返回 None → 不入缓存（get 视为未命中，每次重算）."""
        cache = TTLCache(max_entries=4)
        calls: list[int] = []

        def producer() -> None:
            calls.append(1)

        assert cache.get_or_set("k", 60, producer) is None
        assert cache.get_or_set("k", 60, producer) is None
        assert len(calls) == 2

    def test_producer_exception_propagates_and_not_cached(self) -> None:
        cache = TTLCache(max_entries=4)
        calls: list[int] = []

        def boom() -> int:
            calls.append(1)
            raise RuntimeError("producer 失败")

        with pytest.raises(RuntimeError, match="producer 失败"):
            cache.get_or_set("k", 60, boom)
        # 失败未写缓存：再次读取仍会调用 producer
        with pytest.raises(RuntimeError):
            cache.get_or_set("k", 60, boom)
        assert len(calls) == 2

    def test_cache_key_joins_with_pipe(self) -> None:
        assert cache_key("records", 1, None, "x") == "records|1|None|x"

    def test_invalidate_all_clears_global_caches(self) -> None:
        list_cache.set(cache_key("tables", 1), {"x": 1}, 60)
        meta_cache.set(cache_key("meta", 2), {"y": 2}, 60)
        assert invalidate_all() >= 2
        assert list_cache.get(cache_key("tables", 1)) is None
        assert meta_cache.get(cache_key("meta", 2)) is None


# ── 就绪探测降级分支 ─────────────────────────────────


class TestDbReadinessExtremes:
    """db_readiness 的三条分支（可达未迁移 / 有版本 / 不可达）."""

    def test_reachable_without_migration_table(self, db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
        """DB 可达但缺 alembic_version（未迁移）→ db=True, 版本为 None，不算失败."""
        monkeypatch.setattr(dbmod, "engine", db_engine)
        snapshot = dbmod.db_readiness()
        assert snapshot["db"] is True
        assert snapshot["migration_current"] is None
        assert snapshot["error"] == ""

    def test_reports_migration_version(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """存在 alembic_version 行 → 回读版本号."""
        eng = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
        with eng.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('abc123')"))
            conn.commit()
        monkeypatch.setattr(dbmod, "engine", eng)
        snapshot = dbmod.db_readiness()
        assert snapshot["db"] is True
        assert snapshot["migration_current"] == "abc123"
        eng.dispose()

    def test_unreachable_engine_reports_error(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """引擎指向不存在的目录 → connect 失败，db=False 且 error 非空."""
        eng = create_engine(f"sqlite:///{tmp_path / 'missing-dir' / 'x.db'}")
        monkeypatch.setattr(dbmod, "engine", eng)
        snapshot = dbmod.db_readiness()
        assert snapshot["db"] is False
        assert snapshot["error"] != ""
        eng.dispose()


# ── 错误契约默认值 ───────────────────────────────────


class TestErrorContractExtremes:
    """CndbError 基类默认值与限流异常默认 retry_after."""

    def test_base_defaults(self) -> None:
        exc = CndbError("明细")
        assert exc.status_code == 400
        assert exc.code == "cndb_error"
        assert exc.to_payload() == {"detail": "明细", "code": "cndb_error"}

    def test_constructor_overrides_code_and_status(self) -> None:
        exc = CndbError("明细", code="custom_code", status_code=418)
        assert exc.status_code == 418
        assert exc.to_payload()["code"] == "custom_code"

    def test_too_many_requests_default_retry_after(self) -> None:
        exc = TooManyRequestsError("慢点")
        assert exc.status_code == 429
        assert exc.code == "too_many_requests"
        assert exc.retry_after == 60
        assert exc.to_payload() == {"detail": "慢点", "code": "too_many_requests"}


# ── 认证头极端形态（HTTP）─────────────────────────────


class TestAuthHeaderExtremes:
    """get_current_user 对认证头极端形态的处理."""

    def _raw_token(self, auth_headers: dict[str, str]) -> str:
        return auth_headers["Authorization"].split(" ", 1)[1]

    def test_scheme_case_insensitive(self, client, auth_headers: dict[str, str]) -> None:
        """认证方案大小写不敏感：BEARER / bearer 均放行."""
        tok = self._raw_token(auth_headers)
        for scheme in ("BEARER", "bearer", "BeArEr"):
            r = client.get("/api/v1/workspaces", headers={"Authorization": f"{scheme} {tok}"})
            assert r.status_code == 200, r.text

    def test_token_surrounding_whitespace_trimmed(self, client, auth_headers: dict[str, str]) -> None:
        """令牌首尾空白被裁剪后仍可放行（避免前端拼接空格导致误拒）."""
        tok = self._raw_token(auth_headers)
        r = client.get("/api/v1/workspaces", headers={"Authorization": f"Bearer   {tok}   "})
        assert r.status_code == 200, r.text

    def test_bearer_without_token_rejected(self, client) -> None:
        """仅有方案无令牌 → 401（parts 长度为 1 的格式非法分支）."""
        r = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer"})
        assert r.status_code == 401

    def test_inactive_user_token_rejected(self, client, db) -> None:
        """令牌签名有效但账号被停用 → 401（deps 的 is_active 过滤）."""
        from cndb.core.security import create_access_token
        from cndb.plugins.accounts.models import User

        user = User(username="inactive-extreme", nickname="停用", is_active=False)
        user.set_password("passw0rd")
        db.add(user)
        db.commit()

        token = create_access_token(subject=user.id, token_version=user.token_version)
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

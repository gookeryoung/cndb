"""按段落编辑锁 + 段落级三方合并测试.

覆盖：
- 纯函数：段落切分/位置键、变更段定位、三方合并（互不重叠 → 合并成功；同段 → 冲突）；
- 段落锁注册表：获取/续期、同段他人冲突、批量原子性、释放、按文档列出、TTL 过期；
- 端点：GET/POST/DELETE 段落锁、409 带持锁人、实时 `para.lock` 广播；
- 保存合并：两个用户改**不同段落**都能保存且结果同时包含双方改动；改**同一段落**后者 409；
  未传 base_content 时保持原有乐观锁语义。
"""

from __future__ import annotations

import time

import pytest

from cndb.core.errors import ConflictError
from cndb.core.realtime import MSG_PARA_LOCK, realtime_hub, workspace_room
from cndb.plugins.documents.services.paragraph_lock import (
    ParagraphLockRegistry,
    changed_paragraph_indices,
    key_to_index,
    merge_incoming,
    paragraph_keys,
    remap_positions,
    split_paragraphs,
)

DOC_TPL = "# 标题\n\n第一段\n\n第二段\n\n第三段\n"


class TestParagraphSplitting:
    def test_split_by_blank_lines(self):
        parts = split_paragraphs("A\n\nB\n\nC")
        assert parts == ["A", "B", "C"]

    def test_handles_crlf_and_multiple_blanks(self):
        assert split_paragraphs("A\r\n\r\n\r\nB\r\n") == ["A", "B"]

    def test_keeps_inner_newlines(self):
        assert split_paragraphs("line1\nline2\n\nnext") == ["line1\nline2", "next"]

    def test_empty_text(self):
        assert split_paragraphs("") == []
        assert split_paragraphs("   \n\n  ") == []

    def test_paragraph_keys_are_positional(self):
        assert paragraph_keys(DOC_TPL) == ["p1", "p2", "p3", "p4"]

    def test_key_to_index(self):
        assert key_to_index("p3") == 3
        assert key_to_index("x") is None
        assert key_to_index("p0") is None


class TestChangedIndices:
    def test_detects_changed_paragraph(self):
        base = "# T\n\nA\n\nB"
        incoming = "# T\n\nA2\n\nB"
        assert changed_paragraph_indices(base, incoming) == {2}

    def test_detects_appended_paragraph(self):
        base = "# T\n\nA"
        assert changed_paragraph_indices(base, "# T\n\nA\n\nB") == {3}

    def test_no_change(self):
        assert changed_paragraph_indices(DOC_TPL, DOC_TPL) == set()


class TestMerge:
    def test_disjoint_changes_merge(self):
        base = DOC_TPL
        latest = "# 标题\n\n第一段（别人改）\n\n第二段\n\n第三段\n"
        incoming = "# 标题\n\n第一段\n\n第二段\n\n第三段（我改）\n"
        out = merge_incoming(base, latest, incoming)
        assert out.merged is True
        assert out.conflicts == set()
        assert "第一段（别人改）" in out.text
        assert "第三段（我改）" in out.text

    def test_same_paragraph_conflicts(self):
        base = DOC_TPL
        latest = "# 标题\n\n第一段（别人改）\n\n第二段\n\n第三段\n"
        incoming = "# 标题\n\n第一段（我也改）\n\n第二段\n\n第三段\n"
        out = merge_incoming(base, latest, incoming)
        assert out.merged is False
        assert out.conflicts == {2}
        assert out.conflict_keys == ["p2"]
        assert out.text == latest  # 冲突时不落库，返回最新供提示

    def test_only_my_change_keeps_latest_of_others(self):
        base = DOC_TPL
        latest = "# 标题\n\n第一段（别人改）\n\n第二段\n\n第三段\n"
        out = merge_incoming(base, latest, base)
        assert out.merged is True
        assert out.incoming_changes == set()
        assert out.text == latest

    def test_my_deletion_applies(self):
        base = DOC_TPL
        latest = DOC_TPL
        incoming = "# 标题\n\n第一段\n\n第三段\n"  # 删掉第二段
        out = merge_incoming(base, latest, incoming)
        assert out.merged is True
        assert "第二段" not in out.text
        assert "第三段" in out.text


class TestParagraphLockRegistry:
    @pytest.fixture
    def registry(self) -> ParagraphLockRegistry:
        return ParagraphLockRegistry()

    def test_acquire_and_list(self, registry):
        registry.acquire_many(1, ["p2"], user_id=7, username="alice")
        locks = registry.locks_for_document(1)
        assert len(locks) == 1
        assert locks[0].key == "p2"
        assert locks[0].user_id == 7

    def test_same_user_reacquire_renews(self, registry):
        first = registry.acquire_many(1, ["p1"], user_id=7, username="alice")[0]
        time.sleep(0.01)
        second = registry.acquire_many(1, ["p1"], user_id=7, username="alice")[0]
        assert second.acquired_at >= first.acquired_at
        assert len(registry.locks_for_document(1)) == 1

    def test_other_user_conflict(self, registry):
        registry.acquire_many(1, ["p1"], user_id=7, username="alice")
        with pytest.raises(ConflictError) as exc:
            registry.acquire_many(1, ["p1"], user_id=8, username="bob")
        assert exc.value.code == "paragraph_locked"
        assert "alice" in exc.value.detail

    def test_batch_acquire_is_atomic(self, registry):
        registry.acquire_many(1, ["p3"], user_id=7, username="alice")
        with pytest.raises(ConflictError):
            registry.acquire_many(1, ["p2", "p3"], user_id=8, username="bob")
        # p2 不应被部分获取
        assert {lock.key for lock in registry.locks_for_document(1)} == {"p3"}

    def test_different_documents_do_not_collide(self, registry):
        registry.acquire_many(1, ["p1"], user_id=7, username="alice")
        registry.acquire_many(2, ["p1"], user_id=8, username="bob")
        assert len(registry.locks_for_document(1)) == 1
        assert len(registry.locks_for_document(2)) == 1

    def test_release(self, registry):
        registry.acquire_many(1, ["p1", "p2"], user_id=7, username="alice")
        assert registry.release_many(1, ["p1"], 7) == 1
        assert {lock.key for lock in registry.locks_for_document(1)} == {"p2"}
        # 释放别人的锁无效
        assert registry.release_many(1, ["p2"], 8) == 0

    def test_release_all_for_user(self, registry):
        registry.acquire_many(1, ["p1", "p2"], user_id=7, username="alice")
        registry.acquire_many(1, ["p4"], user_id=8, username="bob")
        assert registry.release_all_for_user(1, 7) == 2
        assert {lock.key for lock in registry.locks_for_document(1)} == {"p4"}

    def test_conflicts_for_indices(self, registry):
        registry.acquire_many(1, ["p2"], user_id=8, username="bob")
        assert registry.conflicts_for_indices(1, {2, 3}, user_id=7)
        assert registry.conflicts_for_indices(1, {3}, user_id=7) == []

    def test_ttl_expiry(self):
        registry = ParagraphLockRegistry(ttl_seconds=0)
        registry.acquire_many(1, ["p1"], user_id=7, username="alice")
        time.sleep(0.01)
        assert registry.locks_for_document(1) == []
        # 过期后他人可获取
        registry.acquire_many(1, ["p1"], user_id=8, username="bob")


@pytest.fixture
def workspace_id(client, auth_headers) -> int:
    r = client.post("/api/v1/workspaces", json={"name": "para-lock"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def doc_api(workspace_id: int) -> str:
    return f"/api/v1/workspaces/{workspace_id}/documents"


@pytest.fixture
def second_headers(client, workspace_id, db) -> dict[str, str]:
    """第二个账号（加入同一工作区并登录），返回其认证头."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import WorkspaceMember

    username, password = "para-user-2", "passw0rd"
    client.post(
        "/api/v1/accounts/auth/register",
        json={"username": username, "email": "para2@example.com", "password": password},
    )
    login = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    user = db.query(User).filter(User.username == username).one()
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="EDITOR"))
    db.commit()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _clean_registry():
    from cndb.plugins.documents.services import paragraph_lock as mod

    mod.paragraph_lock_registry.reset()
    realtime_hub.reset()
    yield
    mod.paragraph_lock_registry.reset()
    realtime_hub.reset()


class TestParagraphLockEndpoints:
    def test_acquire_list_release(self, client, doc_api, auth_headers):
        doc = client.post(
            doc_api, json={"title": "段落锁", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()

        r = client.post(f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p2"]}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["locks"][0]["key"] == "p2"

        listed = client.get(f"{doc_api}/{doc['id']}/paragraph-locks", headers=auth_headers)
        assert listed.status_code == 200
        assert [lock["key"] for lock in listed.json()["locks"]] == ["p2"]

        released = client.delete(f"{doc_api}/{doc['id']}/paragraph-locks", headers=auth_headers)
        assert released.status_code == 200
        assert released.json()["released"] == 1
        assert client.get(f"{doc_api}/{doc['id']}/paragraph-locks", headers=auth_headers).json()["locks"] == []

    def test_conflict_returns_409_with_holder(self, client, doc_api, auth_headers, second_headers):
        doc = client.post(
            doc_api, json={"title": "竞争", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()
        assert (
            client.post(
                f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p1"]}, headers=auth_headers
            ).status_code
            == 200
        )

        r = client.post(f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p1"]}, headers=second_headers)
        assert r.status_code == 409
        assert r.json()["code"] == "paragraph_locked"

        # 不同段落仍可获取（并发编辑不同段落）
        assert (
            client.post(
                f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p3"]}, headers=second_headers
            ).status_code
            == 200
        )

    def test_acquire_broadcasts_para_lock(self, client, doc_api, auth_headers, workspace_id, db):
        from cndb.core.realtime import Connection, make_message

        conn = Connection(None, user_id=99, username="watcher", room=workspace_room(workspace_id), loop=None)  # type: ignore[arg-type]
        conn.loop = None
        # 广播只入队，不依赖事件循环
        realtime_hub.register(conn)
        doc = client.post(
            doc_api, json={"title": "广播", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()

        client.post(f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p2", "p3"]}, headers=auth_headers)
        msgs = []
        while not conn.queue.empty():
            msgs.append(conn.queue.get_nowait())
        para_msgs = [m for m in msgs if m["type"] == MSG_PARA_LOCK]
        assert para_msgs, [m["type"] for m in msgs]
        assert len(para_msgs[-1]["payload"]["locks"]) == 2
        assert make_message  # 保持导入使用


class TestMergedSave:
    def test_two_users_edit_different_paragraphs_both_persist(self, client, doc_api, auth_headers, second_headers):
        doc = client.post(
            doc_api, json={"title": "并发", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()
        base = DOC_TPL

        # 两个用户各自拿到不同段落锁
        assert (
            client.post(
                f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p2"]}, headers=auth_headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p4"]}, headers=second_headers
            ).status_code
            == 200
        )

        a_text = base.replace("第一段", "第一段（A改）")
        b_text = base.replace("第三段", "第三段（B改）")

        # A 先保存
        ra = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": a_text, "base_content": base, "change_summary": "A 改第 2 段"},
            headers=auth_headers,
        )
        assert ra.status_code == 200, ra.text

        # B 基于旧 base 保存 → 段落级合并应成功，且两份改动都在
        rb = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": b_text, "base_content": base, "change_summary": "B 改第 4 段"},
            headers=second_headers,
        )
        assert rb.status_code == 200, rb.text
        assert rb.json().get("merged") is True

        current = client.get(f"{doc_api}/{doc['id']}/content", headers=auth_headers).json()
        text = current.get("content", "")
        assert "第一段（A改）" in text
        assert "第三段（B改）" in text

    def test_same_paragraph_save_conflicts(self, client, doc_api, auth_headers, second_headers):
        doc = client.post(
            doc_api, json={"title": "同段", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()
        base = DOC_TPL

        # A 与 B 都锁住第 2 段（B 先释放以模拟"B 抢不到但仍尝试保存"）
        client.post(f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p2"]}, headers=auth_headers)
        a_text = base.replace("第一段", "第一段（A改）")
        assert (
            client.put(
                f"{doc_api}/{doc['id']}/content",
                json={"content": a_text, "base_content": base},
                headers=auth_headers,
            ).status_code
            == 200
        )

        b_text = base.replace("第一段", "第一段（B改）")
        rb = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": b_text, "base_content": base},
            headers=second_headers,
        )
        assert rb.status_code == 409
        assert rb.json()["code"] == "paragraph_conflict"
        assert "第 2 段" in rb.json()["detail"]

        # 正文未被 B 覆盖
        text = client.get(f"{doc_api}/{doc['id']}/content", headers=auth_headers).json()["content"]
        assert "第一段（A改）" in text
        assert "第一段（B改）" not in text

    def test_without_base_content_keeps_optimistic_lock(self, client, doc_api, auth_headers, second_headers):
        """不传 base_content 时仍是原有乐观锁语义（409 conflict）."""
        doc = client.post(
            doc_api, json={"title": "旧语义", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()
        # 用明确过期的版本戳，避免"同一秒内 updated_at 未变"造成的假通过
        r = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": "# 标题\n\nB\n", "base_updated_at": "2020-01-01T00:00:00"},
            headers=second_headers,
        )
        assert r.status_code == 409
        assert r.json()["code"] == "conflict"

    def test_no_change_returns_current(self, client, doc_api, auth_headers):
        doc = client.post(
            doc_api, json={"title": "无改动", "content": DOC_TPL, "status": "published"}, headers=auth_headers
        ).json()
        r = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": DOC_TPL, "base_content": DOC_TPL},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["version_number"] >= 1


class TestRemapPositions:
    """段落锁位置重映射：锁跟着段落走（中间插入/删除不再漂移）."""

    def test_insert_above_shifts_lock_target(self):
        old = "# T\n\nA\n\nB\n\nC"
        new = "# T\n\n新段落\n\nA\n\nB\n\nC"
        mapping = remap_positions(old, new)
        assert mapping == {1: 1, 2: 3, 3: 4, 4: 5}

    def test_edited_paragraph_maps_to_none(self):
        old = "# T\n\nA\n\nB"
        new = "# T\n\nA（改过）\n\nB"
        mapping = remap_positions(old, new)
        assert mapping[2] is None  # 被改写的段落：其锁释放
        assert mapping[3] == 3

    def test_deleted_paragraph_maps_to_none(self):
        old = "# T\n\nA\n\nB"
        new = "# T\n\nB"
        mapping = remap_positions(old, new)
        assert mapping[2] is None
        assert mapping[3] == 2

    def test_duplicate_paragraphs_pair_in_order(self):
        old = "A\n\nA\n\nB"
        new = "A\n\nA\n\nA\n\nB"
        mapping = remap_positions(old, new)
        assert mapping[1] == 1 and mapping[2] == 2 and mapping[3] == 4


class TestRegistryRemap:
    def test_lock_moves_with_paragraph(self):
        registry = ParagraphLockRegistry()
        registry.acquire_many(1, ["p3"], user_id=7, username="alice")
        out = registry.remap(1, {1: 1, 2: 3, 3: 4, 4: 5})
        assert out["moved"] == 1
        locks = registry.locks_for_document(1)
        assert [(lock.key, lock.username) for lock in locks] == [("p4", "alice")]

    def test_lock_released_when_paragraph_rewritten(self):
        registry = ParagraphLockRegistry()
        registry.acquire_many(1, ["p2"], user_id=7, username="alice")
        out = registry.remap(1, {1: 1, 2: None})
        assert out["released"] == 1
        assert registry.locks_for_document(1) == []

    def test_keeps_lock_when_target_occupied_by_other(self):
        registry = ParagraphLockRegistry()
        registry.acquire_many(1, ["p2"], user_id=7, username="alice")
        registry.acquire_many(1, ["p3"], user_id=8, username="bob")
        out = registry.remap(1, {2: 3, 3: 3})
        assert out["kept"] == 1
        keys = {(lock.key, lock.username) for lock in registry.locks_for_document(1)}
        assert keys == {("p2", "alice"), ("p3", "bob")}


class TestRemapOnSave:
    def test_insert_paragraph_keeps_other_users_lock_on_same_paragraph(
        self, client, doc_api, auth_headers, second_headers
    ):
        """B 在第 1 段后插入新段落并保存 → A 对原第 2 段的锁应移动到第 3 段."""
        base = "# 标题\n\n第一段\n\n第二段\n\n第三段\n"
        doc = client.post(
            doc_api, json={"title": "重映射", "content": base, "status": "published"}, headers=auth_headers
        ).json()

        # A 锁住第 2 段（"第一段"）
        assert (
            client.post(
                f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p2"]}, headers=auth_headers
            ).status_code
            == 200
        )

        # B 在标题后插入一段并保存（内容变化 → 位置平移）
        after = "# 标题\n\n插入段\n\n第一段\n\n第二段\n\n第三段\n"
        r = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": after, "base_content": base},
            headers=second_headers,
        )
        assert r.status_code == 200, r.text

        locks = client.get(f"{doc_api}/{doc['id']}/paragraph-locks", headers=auth_headers).json()["locks"]
        mine = [lock for lock in locks if lock["username"] == "testuser"]
        assert mine, locks
        # 锁跟着"第一段"走到了第 3 段
        assert mine[0]["key"] == "p3"

    def test_rewritten_paragraph_releases_lock(self, client, doc_api, auth_headers, second_headers):
        base = "# 标题\n\n第一段\n\n第二段\n"
        doc = client.post(
            doc_api, json={"title": "释放", "content": base, "status": "published"}, headers=auth_headers
        ).json()
        client.post(f"{doc_api}/{doc['id']}/paragraph-locks", json={"keys": ["p2"]}, headers=auth_headers)

        # 改写第 2 段（A 自己的锁）→ 保存后该锁释放
        rewritten = "# 标题\n\n第一段（改写）\n\n第二段\n"
        assert (
            client.put(
                f"{doc_api}/{doc['id']}/content",
                json={"content": rewritten, "base_content": base},
                headers=auth_headers,
            ).status_code
            == 200
        )
        locks = client.get(f"{doc_api}/{doc['id']}/paragraph-locks", headers=auth_headers).json()["locks"]
        assert [lock["key"] for lock in locks if lock["username"] == "testuser"] == []

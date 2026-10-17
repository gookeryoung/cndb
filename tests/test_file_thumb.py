"""缩略图下载 + 字段级上传校验（P2）.

覆盖：
- ``GET /files/{key}?thumb=N`` 返回 WebP 缩略图（最长边 ≤ N），并落盘缓存；
- 非图片 / svg 等不可栅格化类型回退原图；
- 删除附件时清理缩略图缓存；
- 上传带 ``field_id`` 时按字段配置校验大小 / MIME / 图片类型。
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

FILES = "/api/v1/workspaces/{ws}/files"
TABLES = "/api/v1/workspaces/{ws}/tables"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = User(username="thumb_owner", nickname="thumb_owner")
        self.owner.set_password("passw0rd")
        db.add(self.owner)
        db.flush()
        self.ws = Workspace(name="ThumbWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.commit()


def _png_bytes(width: int = 200, height: int = 120) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(
    client: TestClient,
    env: Env,
    *,
    name: str,
    content: bytes,
    mime: str,
    extra: dict[str, str] | None = None,
) -> tuple[int, dict]:
    r = client.post(
        FILES.format(ws=env.ws.id),
        files={"file": (name, content, mime)},
        data=extra or {},
        headers=_login(client, env.owner.username),
    )
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _create_image_field(client: TestClient, env: Env, *, config: dict | None = None) -> tuple[int, int]:
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": "缩略图表", "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
        json={
            "name": "照片",
            "field_type": "image",
            "order": 0,
            "config": config or {},
        },
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text
    return tid, int(r.json()["id"])


class TestThumbnail:
    def test_thumb_returns_webp_and_downscales(self, client, db):
        env = Env(db)
        status, body = _upload(client, env, name="photo.png", content=_png_bytes(200, 120), mime="image/png")
        assert status == 201, body

        r = client.get(
            f"{FILES.format(ws=env.ws.id)}/{body['file_key']}?thumb=64",
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/webp")
        image = Image.open(io.BytesIO(r.content))
        assert image.format == "WEBP"
        assert max(image.size) <= 64

        # 缩略图落盘缓存：只断言本文件的缓存（同 worker 其它用例可能有同工作区残留）
        cache_dir = settings.UPLOAD_DIR / ".thumbs" / str(env.ws.id)
        assert list(cache_dir.glob(f"{body['file_key']}*.webp"))

    def test_thumb_falls_back_for_non_image(self, client, db):
        env = Env(db)
        payload = b"hello thumbnail"
        status, body = _upload(client, env, name="a.txt", content=payload, mime="text/plain")
        assert status == 201, body

        r = client.get(
            f"{FILES.format(ws=env.ws.id)}/{body['file_key']}?thumb=64",
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 200
        assert r.content == payload
        assert r.headers["content-type"].startswith("text/plain")

    def test_thumb_falls_back_for_svg(self, client, db):
        env = Env(db)
        payload = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        status, body = _upload(client, env, name="icon.svg", content=payload, mime="image/svg+xml")
        assert status == 201, body

        r = client.get(
            f"{FILES.format(ws=env.ws.id)}/{body['file_key']}?thumb=64",
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 200
        assert r.content == payload

    def test_thumb_size_out_of_range_rejected(self, client, db):
        env = Env(db)
        status, body = _upload(client, env, name="photo.png", content=_png_bytes(), mime="image/png")
        assert status == 201, body

        r = client.get(
            f"{FILES.format(ws=env.ws.id)}/{body['file_key']}?thumb=8",
            headers=_login(client, env.owner.username),
        )
        assert r.status_code == 422

    def test_delete_clears_thumb_cache(self, client, db):
        env = Env(db)
        auth = _login(client, env.owner.username)
        status, body = _upload(client, env, name="photo.png", content=_png_bytes(), mime="image/png")
        assert status == 201, body
        key = body["file_key"]
        client.get(f"{FILES.format(ws=env.ws.id)}/{key}?thumb=64", headers=auth)
        cache_dir = settings.UPLOAD_DIR / ".thumbs" / str(env.ws.id)
        # 只断言本文件的缓存（同 worker 内其它用例可能留下同工作区其它文件的缩略图）
        assert list(cache_dir.glob(f"{key}*.webp"))

        r = client.delete(f"{FILES.format(ws=env.ws.id)}/{key}", headers=auth)
        assert r.status_code == 204
        assert not list(cache_dir.glob(f"{key}*.webp"))


class TestFieldUploadValidation:
    def test_valid_png_accepted(self, client, db):
        env = Env(db)
        tid, fid = _create_image_field(client, env, config={"max_size_mb": 1, "allowed_mime_types": ["image/png"]})
        status, body = _upload(
            client,
            env,
            name="ok.png",
            content=_png_bytes(20, 20),
            mime="image/png",
            extra={"table_id": str(tid), "field_id": str(fid)},
        )
        assert status == 201, body

    def test_oversized_file_rejected_by_field_config(self, client, db):
        env = Env(db)
        tid, fid = _create_image_field(client, env, config={"max_size_mb": 1})
        status, body = _upload(
            client,
            env,
            name="big.png",
            content=b"x" * (1024 * 1024 + 10),
            mime="image/png",
            extra={"table_id": str(tid), "field_id": str(fid)},
        )
        assert status == 413, body
        assert "字段" in body.get("detail", "")

    def test_disallowed_mime_rejected_by_field_config(self, client, db):
        env = Env(db)
        tid, fid = _create_image_field(client, env, config={"allowed_mime_types": ["image/png"]})
        status, body = _upload(
            client,
            env,
            name="anim.gif",
            content=b"GIF89a",
            mime="image/gif",
            extra={"table_id": str(tid), "field_id": str(fid)},
        )
        assert status == 415, body
        assert "字段" in body.get("detail", "")

    def test_non_image_upload_rejected_for_image_field(self, client, db):
        env = Env(db)
        tid, fid = _create_image_field(client, env)
        status, body = _upload(
            client,
            env,
            name="note.txt",
            content=b"plain text",
            mime="text/plain",
            extra={"table_id": str(tid), "field_id": str(fid)},
        )
        assert status == 415, body
        assert "只允许上传图片" in body.get("detail", "")

    def test_field_id_without_table_id_rejected(self, client, db):
        env = Env(db)
        _tid, fid = _create_image_field(client, env)
        status, body = _upload(
            client,
            env,
            name="ok.png",
            content=_png_bytes(10, 10),
            mime="image/png",
            extra={"field_id": str(fid)},
        )
        assert status == 400, body

    def test_unknown_field_id_rejected(self, client, db):
        env = Env(db)
        tid, _fid = _create_image_field(client, env)
        status, body = _upload(
            client,
            env,
            name="ok.png",
            content=_png_bytes(10, 10),
            mime="image/png",
            extra={"table_id": str(tid), "field_id": "999999"},
        )
        assert status == 404, body

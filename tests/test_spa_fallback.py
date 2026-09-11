"""SPA fallback 中间件测试.

覆盖：
- should_spa_fallback 纯函数的全部分支
- middleware 行为（静态文件命中 / fallback / 不 fallback）
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

from cndb.app import should_spa_fallback

# ── should_spa_fallback 纯函数 ──────────────────────────────


class TestShouldSpaFallback:
    """should_spa_fallback 分支全覆盖."""

    def test_api_path_never_fallback(self) -> None:
        """/api/* 永远不回退——即使 Accept 是 text/html."""
        assert should_spa_fallback("/api/health", "text/html") is False
        assert should_spa_fallback("/api/v1/tables", "*/*") is False

    def test_assets_path_never_fallback(self) -> None:
        """/assets/* 永远不回退——避免把缺失的 JS chunk 回成 HTML."""
        assert should_spa_fallback("/assets/chunk-xxx.js", "text/html") is False
        assert should_spa_fallback("/assets/style.css", "*/*") is False

    def test_html_accept_fallback(self) -> None:
        """普通页面路由 + Accept 含 text/html → 应该回退."""
        assert should_spa_fallback("/w/1/tables", "text/html") is True
        assert should_spa_fallback("/public/share/abc", "text/html,application/xhtml+xml") is True
        assert should_spa_fallback("/", "text/html") is True

    def test_non_html_accept_no_fallback(self) -> None:
        """AJAX 请求 / XHR 等 Accept 不含 text/html → 不回退."""
        assert should_spa_fallback("/w/1/tables", "application/json") is False
        assert should_spa_fallback("/w/1/tables", "*/*") is False
        assert should_spa_fallback("/w/1/tables", "") is False

    def test_api_root_is_fallback(self) -> None:
        """/api 不以 /api/ 开头——fallback 无害（/api 不是有效 API 路由）."""
        assert should_spa_fallback("/api", "text/html") is True
        # /apis/* 也误匹配，但这不是有效 API 前缀，安全可接受
        assert should_spa_fallback("/apis/xxx", "text/html") is True


# ── 集成测试：middleware 行为 ──────────────────────────────


def _make_app(static_dir: Path) -> FastAPI:
    """构建带 SPA fallback 的临时 FastAPI app."""
    app = FastAPI()

    @app.get("/exists")
    async def exists():
        return {"ok": True}

    assets_dir = static_dir / "assets"
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.middleware("http")
    async def spa_fallback(request: Request, call_next):
        response = await call_next(request)
        if response.status_code != 404:
            return response
        path = request.url.path
        fp = static_dir / path.lstrip("/")
        if fp.is_file():
            return FileResponse(str(fp))
        if should_spa_fallback(path, request.headers.get("accept", "")):
            return FileResponse(str(static_dir / "index.html"))
        return response

    return app


class TestSpaFallbackMiddleware:
    """middleware 端到端行为验证."""

    HTML_ACCEPT = "text/html,application/xhtml+xml"

    @staticmethod
    def _prepare(tmp_path: Path) -> tuple[Path, Path]:
        """创建 static + assets 目录骨架，写入最小 index.html."""
        static_dir = tmp_path / "static"
        assets_dir = static_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (static_dir / "index.html").write_text("<html>SPA</html>")
        return static_dir, assets_dir

    def test_explicit_route_ok(self, tmp_path: Path) -> None:
        """已注册路由 → 200，不经过 fallback."""
        static_dir, _ = self._prepare(tmp_path)
        client = TestClient(_make_app(static_dir))

        r = client.get("/exists", headers={"accept": self.HTML_ACCEPT})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_html_request_fallback(self, tmp_path: Path) -> None:
        """普通页面路由 + Accept: text/html → fallback 到 index.html."""
        static_dir, _ = self._prepare(tmp_path)
        client = TestClient(_make_app(static_dir))

        r = client.get("/w/1/tables", headers={"accept": self.HTML_ACCEPT})
        assert r.status_code == 200
        assert "<html>SPA</html>" in r.text

    def test_json_request_no_fallback(self, tmp_path: Path) -> None:
        """JSON 请求不走 fallback → 404."""
        static_dir, _ = self._prepare(tmp_path)
        client = TestClient(_make_app(static_dir))

        r = client.get("/w/1/tables", headers={"accept": "application/json"})
        assert r.status_code == 404

    def test_api_path_no_fallback(self, tmp_path: Path) -> None:
        """/api/* 不走 fallback → 404."""
        static_dir, _ = self._prepare(tmp_path)
        client = TestClient(_make_app(static_dir))

        r = client.get("/api/nope", headers={"accept": self.HTML_ACCEPT})
        assert r.status_code == 404

    def test_assets_missing_no_fallback(self, tmp_path: Path) -> None:
        """/assets/ 下不存在的 chunk → 404（不应回成 HTML）."""
        static_dir, _ = self._prepare(tmp_path)
        client = TestClient(_make_app(static_dir))

        r = client.get("/assets/nonexistent.js", headers={"accept": self.HTML_ACCEPT})
        assert r.status_code == 404

    def test_top_level_static_file_hit(self, tmp_path: Path) -> None:
        """顶层静态文件（如 favicon.svg）直接命中 → 200."""
        static_dir, _ = self._prepare(tmp_path)
        (static_dir / "favicon.svg").write_text("<svg />")
        client = TestClient(_make_app(static_dir))

        r = client.get("/favicon.svg")
        assert r.status_code == 200
        assert "<svg />" in r.text

    def test_assets_file_hit(self, tmp_path: Path) -> None:
        """/assets/ 下存在的文件直接命中 → 200."""
        static_dir, assets_dir = self._prepare(tmp_path)
        (assets_dir / "main.js").write_text("console.log('hi')")
        client = TestClient(_make_app(static_dir))

        r = client.get("/assets/main.js")
        assert r.status_code == 200
        assert "console.log" in r.text

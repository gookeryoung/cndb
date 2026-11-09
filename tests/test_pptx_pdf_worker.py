"""ADR 0129 P1：pdf-worker 单测（伪造 soffice，不依赖真实 LibreOffice）.

覆盖 ADR §8 测试清单的 worker 部分：token 校验 / 健康探测 / 体积上限 / 超时 /
非零退出 / 缺输出文件 / 并发排队 / 临时目录清理 / 环境变量解析。
"""

from __future__ import annotations

import http.client
import tempfile
import threading
from pathlib import Path

import pytest

from cndb.plugins.documents.services.preview import pdf_worker

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
PPTX_BYTES = b"PK\x03\x04fake-pptx-payload"
TOKEN = "test-token"

#: 伪造 soffice：按环境变量切换成功 / 超时 / 非零退出 / 不产出文件
FAKE_SOFFICE = """#!/usr/bin/env python3
import os
import pathlib
import sys
import time

mode = os.environ.get("FAKE_SOFFICE_MODE", "ok")
if mode == "timeout":
    time.sleep(30)
    sys.exit(0)
if mode == "fail":
    sys.exit(1)
if mode == "nooutput":
    sys.exit(0)

args = sys.argv[1:]
if os.environ.get("FAKE_SOFFICE_CHECK_PROFILE") == "1":
    profile_arg = next(a for a in args if a.startswith("-env:UserInstallation="))
    profile = pathlib.Path(profile_arg.split("file://", 1)[1])
    text = (profile / "user" / "registrymodifications.xcu").read_text(encoding="utf-8")
    if "MacroSecurityLevel" not in text or "<value>3</value>" not in text:
        sys.exit(3)

outdir = pathlib.Path(args[args.index("--outdir") + 1])
source = pathlib.Path(args[-1])
(outdir / f"{source.stem}.pdf").write_bytes(os.environ["FAKE_SOFFICE_PDF"].encode("latin-1"))
"""


@pytest.fixture
def start_worker(tmp_path, monkeypatch):
    """启动一个监听随机端口的 worker；用例结束统一停止."""
    script = tmp_path / "soffice"
    script.write_text(FAKE_SOFFICE, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("FAKE_SOFFICE_PDF", PDF_BYTES.decode("latin-1"))

    servers: list[pdf_worker.ThreadingHTTPServer] = []

    def _start(**overrides) -> pdf_worker.WorkerConfig:
        config = pdf_worker.WorkerConfig(
            host="127.0.0.1",
            port=0,
            token=overrides.pop("token", TOKEN),
            max_bytes=overrides.pop("max_bytes", 1024 * 1024),
            timeout_seconds=overrides.pop("timeout_seconds", 10),
            soffice_bin=str(script),
        )
        server = pdf_worker.build_server(config, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return config, server

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


def _request(
    server,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=60)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def _convert(server, *, token: str | None = TOKEN, body: bytes = PPTX_BYTES):
    headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(body))}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return _request(server, "POST", "/convert", body=body, headers=headers)


class TestConfig:
    def test_defaults(self, monkeypatch):
        for name in (
            "PPTX_PDF_WORKER_HOST",
            "PPTX_PDF_WORKER_PORT",
            "PPTX_PDF_WORKER_TOKEN",
            "PPTX_PDF_WORKER_MAX_BYTES",
            "PPTX_PDF_WORKER_TIMEOUT_SECONDS",
            "SOFFICE_BIN",
        ):
            monkeypatch.delenv(name, raising=False)
        config = pdf_worker.WorkerConfig.from_env()
        assert config.port == pdf_worker.DEFAULT_PORT
        assert config.max_bytes == pdf_worker.DEFAULT_MAX_BYTES
        assert config.timeout_seconds == pdf_worker.DEFAULT_TIMEOUT_SECONDS
        assert config.token == ""
        assert config.soffice_bin == "soffice"

    def test_env_overrides_and_invalid_port_falls_back(self, monkeypatch):
        monkeypatch.setenv("PPTX_PDF_WORKER_PORT", "not-a-number")
        monkeypatch.setenv("PPTX_PDF_WORKER_TOKEN", " secret ")
        monkeypatch.setenv("PPTX_PDF_WORKER_MAX_BYTES", "2048")
        monkeypatch.setenv("SOFFICE_BIN", "/opt/libreoffice/soffice")
        config = pdf_worker.WorkerConfig.from_env()
        assert config.port == pdf_worker.DEFAULT_PORT
        assert config.token == "secret"
        assert config.max_bytes == 2048
        assert config.soffice_bin == "/opt/libreoffice/soffice"


class TestHealthAndAuth:
    def test_health_needs_no_token(self, start_worker):
        _, server = start_worker()
        status, headers, body = _request(server, "GET", "/health")
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        assert b'"ok"' in body

    def test_unknown_path_404(self, start_worker):
        _, server = start_worker()
        assert _request(server, "GET", "/convert")[0] == 404
        assert _request(server, "POST", "/health")[0] == 404

    def test_missing_or_wrong_token_rejected(self, start_worker):
        _, server = start_worker()
        assert _convert(server, token=None)[0] == 401
        assert _convert(server, token="wrong")[0] == 401

    def test_empty_token_disables_auth(self, start_worker):
        _, server = start_worker(token="")
        status, _, body = _convert(server, token=None)
        assert status == 200
        assert body.startswith(b"%PDF-")


class TestConvert:
    def test_success_returns_pdf(self, start_worker):
        _, server = start_worker()
        status, headers, body = _convert(server)
        assert status == 200
        assert headers["Content-Type"] == "application/pdf"
        assert headers["Content-Length"] == str(len(PDF_BYTES))
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert body == PDF_BYTES

    def test_payload_too_large_413(self, start_worker):
        _, server = start_worker(max_bytes=8)
        status, _, _ = _convert(server, body=b"x" * 64)
        assert status == 413

    def test_timeout_504(self, start_worker, monkeypatch):
        monkeypatch.setenv("FAKE_SOFFICE_MODE", "timeout")
        _, server = start_worker(timeout_seconds=1)
        status, _, body = _convert(server)
        assert status == 504
        assert b"timeout" not in body  # 错误体不返回 stderr 细节

    def test_nonzero_exit_422(self, start_worker, monkeypatch):
        monkeypatch.setenv("FAKE_SOFFICE_MODE", "fail")
        _, server = start_worker()
        assert _convert(server)[0] == 422

    def test_missing_output_422(self, start_worker, monkeypatch):
        monkeypatch.setenv("FAKE_SOFFICE_MODE", "nooutput")
        _, server = start_worker()
        assert _convert(server)[0] == 422

    def test_profile_forces_high_macro_security(self, start_worker, monkeypatch):
        """每次转换的独立 profile 必须写入宏安全级别 3（非常高）."""
        monkeypatch.setenv("FAKE_SOFFICE_CHECK_PROFILE", "1")
        _, server = start_worker()
        assert _convert(server)[0] == 200

    def test_busy_returns_429_with_retry_after(self, start_worker):
        _, server = start_worker()
        assert pdf_worker._CONCURRENCY.acquire(blocking=False)
        try:
            status, headers, _ = _convert(server)
        finally:
            pdf_worker._CONCURRENCY.release()
        assert status == 429
        assert headers["Retry-After"] == "5"


class TestCleanup:
    def test_convert_leaves_no_temp_dirs(self, tmp_path, monkeypatch):
        """临时目录（原件 / 输出 / profile）在返回前整体删除."""
        root = tmp_path / "work"
        root.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(root))
        script = tmp_path / "soffice"
        script.write_text(FAKE_SOFFICE, encoding="utf-8")
        script.chmod(0o755)
        monkeypatch.setenv("FAKE_SOFFICE_PDF", PDF_BYTES.decode("latin-1"))

        config = pdf_worker.WorkerConfig(soffice_bin=str(script))
        result = pdf_worker.convert_bytes(PPTX_BYTES, config)

        assert result == PDF_BYTES
        assert list(root.iterdir()) == []

    def test_failure_also_cleans_temp_dirs(self, tmp_path, monkeypatch):
        root = tmp_path / "work"
        root.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(root))
        script = tmp_path / "soffice"
        script.write_text(FAKE_SOFFICE, encoding="utf-8")
        script.chmod(0o755)
        monkeypatch.setenv("FAKE_SOFFICE_MODE", "fail")

        config = pdf_worker.WorkerConfig(soffice_bin=str(script))
        with pytest.raises(pdf_worker.ConversionError) as excinfo:
            pdf_worker.convert_bytes(PPTX_BYTES, config)

        assert excinfo.value.status_code == 422
        assert list(root.iterdir()) == []

    def test_missing_binary_maps_to_500(self, tmp_path):
        config = pdf_worker.WorkerConfig(soffice_bin=str(tmp_path / "not-exist"))
        with pytest.raises(pdf_worker.ConversionError) as excinfo:
            pdf_worker.convert_bytes(PPTX_BYTES, config)
        assert excinfo.value.status_code == 500


def test_convertible_command_isolates_profile(tmp_path: Path):
    command = pdf_worker.convertible_command(
        "soffice", tmp_path / "source.pptx", tmp_path / "out", tmp_path / "profile"
    )
    assert command[0] == "soffice"
    assert "--headless" in command
    assert "--convert-to" in command
    assert command[command.index("--convert-to") + 1] == "pdf"
    assert any(item.startswith("-env:UserInstallation=file://") for item in command)
    assert command[-1] == str(tmp_path / "source.pptx")

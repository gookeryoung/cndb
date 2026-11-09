"""pdf-worker：独立容器内唯一的 PPTX → PDF 转换入口（ADR 0129 P1）.

设计口径（与 ADR 0129 §4 / §8 对应）：

- **只做一件事**：``POST /convert`` 收原件字节返回 PDF 字节，``GET /health`` 供容器探活；
  不读数据库、不碰工作区文件，转换结果只留在内存与本次请求的临时目录；
- **隔离**：不可信 PPTX 只在本容器交给 LibreOffice 解析，容器无外网、非 root、只读根、
  ``tmpfs`` 可写；API 进程永远不执行 ``soffice``；
- **有界**：请求体大小、转换超时、并发数（1）都有硬上限，队满直接 429 让 API 快速降级；
- **无状态**：每次转换使用独立临时目录与 ``-env:UserInstallation`` profile，
  避免 LibreOffice 用户配置锁冲突；请求结束即删除，不落盘。

错误码约定（``pdf_converter`` 客户端据此区分可重试 / 永久失败）：

- ``401`` token 不匹配；``411`` 缺 Content-Length；``413`` 超出体积上限；
- ``429`` 已有转换在执行（可重试）；``504`` 转换超时（可重试）；
- ``422`` 损坏 / 加密 / 未生成 PDF（永久失败）；``500`` 转换器自身不可用（可重试）。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, override

logger = logging.getLogger("cndb.pdf_worker")

DEFAULT_PORT = 8100
DEFAULT_HOST = "0.0.0.0"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 180
READ_CHUNK_BYTES = 64 * 1024

#: 全局只允许一个转换（LibreOffice 内存 / CPU 开销大，单机必须防止并发打满）
_CONCURRENCY = threading.BoundedSemaphore(1)

#: LibreOffice 宏安全级别 3 = 非常高（仅受信任位置可执行宏）；
#: 不可信 PPTX 即使内嵌宏也不会被执行（ADR 0129 C8 / H46）。
MACRO_SECURITY_LEVEL = 3
_PROFILE_REGISTRY = f"""<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>{MACRO_SECURITY_LEVEL}</value></prop></item>
</oor:items>
"""


def _env_int(name: str, default: int, *, minimum: int) -> int:
    """读取整数环境变量；非法值回落默认，避免容器因配置笔误起不来."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("pdf_worker 环境变量 %s=%r 不是整数，使用默认 %s", name, raw, default)
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class WorkerConfig:
    """worker 运行时配置（全部来自环境变量，无落盘配置）."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str = ""
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    soffice_bin: str = "soffice"

    @classmethod
    def from_env(cls) -> WorkerConfig:
        return cls(
            host=(os.environ.get("PPTX_PDF_WORKER_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST,
            port=_env_int("PPTX_PDF_WORKER_PORT", DEFAULT_PORT, minimum=1),
            token=(os.environ.get("PPTX_PDF_WORKER_TOKEN") or "").strip(),
            max_bytes=_env_int("PPTX_PDF_WORKER_MAX_BYTES", DEFAULT_MAX_BYTES, minimum=1),
            timeout_seconds=_env_int("PPTX_PDF_WORKER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, minimum=1),
            soffice_bin=(os.environ.get("SOFFICE_BIN") or "soffice").strip() or "soffice",
        )


class ConversionError(Exception):
    """转换失败（``status_code`` 直接作为 HTTP 响应码）."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def convertible_command(soffice_bin: str, source: Path, outdir: Path, profile: Path) -> list[str]:
    """组装 LibreOffice 转换命令（独立 profile + 无界面 + 不恢复文档）."""
    return [
        soffice_bin,
        "--headless",
        "--invisible",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(outdir),
        str(source),
    ]


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """超时后杀掉整个进程组：soffice 会派生 soffice.bin，只杀父进程会留下孤儿."""
    with suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)  # pyrefly: ignore[missing-attribute]
    with suppress(Exception):
        process.communicate(timeout=5)


def _prepare_profile(profile: Path) -> None:
    """写入用户 profile 配置：强制宏安全级别为「非常高」."""
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(_PROFILE_REGISTRY, encoding="utf-8")


def convert_bytes(data: bytes, config: WorkerConfig) -> bytes:
    """把一份 PPTX 字节转换成 PDF 字节.

    临时目录内含原件、输出目录与独立用户 profile，函数返回前整体删除。

    Raises:
        ConversionError: 转换器不可用（500）、超时（504）、转换失败 / 无输出（422）。
    """
    workdir = Path(tempfile.mkdtemp(prefix="pptx-pdf-"))
    try:
        source = workdir / "source.pptx"
        source.write_bytes(data)
        outdir = workdir / "out"
        outdir.mkdir()
        profile = workdir / "profile"
        profile.mkdir()
        _prepare_profile(profile)

        # HOME / TMPDIR 指向本次临时目录：只读根文件系统下 LibreOffice 仍可写配置与缓存
        env = {**os.environ, "HOME": str(workdir), "TMPDIR": str(workdir)}
        command = convertible_command(config.soffice_bin, source, outdir, profile)
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            raise ConversionError(500, "转换器不可用") from exc

        try:
            _, stderr = process.communicate(timeout=config.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _kill_process_group(process)
            raise ConversionError(504, "转换超时") from exc

        if process.returncode != 0:
            logger.warning(
                "pdf_worker soffice 退出码=%s stderr=%s",
                process.returncode,
                stderr.decode("utf-8", "replace")[-500:],
            )
            raise ConversionError(422, "转换失败")

        output = outdir / f"{source.stem}.pdf"
        if not output.is_file():
            raise ConversionError(422, "转换未生成 PDF")
        result = output.read_bytes()
        if not result.startswith(b"%PDF-"):
            raise ConversionError(422, "转换结果不是 PDF")
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


class PdfWorkerHandler(BaseHTTPRequestHandler):
    """最小 HTTP 处理器：只认 ``GET /health`` 与 ``POST /convert``."""

    server_version = "cndb-pdf-worker"
    protocol_version = "HTTP/1.1"
    config: ClassVar[WorkerConfig] = WorkerConfig()

    @override
    def log_message(self, format: str, *args: Any) -> None:
        logger.info("pdf_worker %s", format % args)

    # ── 路由 ──

    def do_GET(self) -> None:
        if self._path() != "/health":
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(200, {"status": "ok"})

    def do_POST(self) -> None:
        if self._path() != "/convert":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._send_json(411, {"error": "length required"})
            return
        if length <= 0:
            self._send_json(400, {"error": "empty body"})
            return
        if length > self.config.max_bytes:
            self._send_json(413, {"error": "payload too large"})
            return
        if not _CONCURRENCY.acquire(blocking=False):
            self._send_json(429, {"error": "busy"}, headers={"Retry-After": "5"})
            return

        started = time.monotonic()
        try:
            data = self._read_body(length)
            if data is None:
                return
            pdf = convert_bytes(data, self.config)
        except ConversionError as exc:
            logger.warning(
                "pdf_worker result=failed status=%s bytes_in=%s duration_ms=%s detail=%s",
                exc.status_code,
                length,
                int((time.monotonic() - started) * 1000),
                exc.detail,
            )
            self._send_json(exc.status_code, {"error": exc.detail})
        except Exception:  # pragma: no cover - 兜底，避免线程异常导致连接悬挂
            logger.exception("pdf_worker result=failed status=500 bytes_in=%s", length)
            self._send_json(500, {"error": "internal error"})
        else:
            logger.info(
                "pdf_worker result=ok bytes_in=%s bytes_out=%s duration_ms=%s",
                len(data),
                len(pdf),
                int((time.monotonic() - started) * 1000),
            )
            self._send_bytes(pdf)
        finally:
            _CONCURRENCY.release()

    # ── 内部 ──

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def _authorized(self) -> bool:
        token = self.config.token
        if not token:
            return True
        header = self.headers.get("Authorization") or ""
        return hmac.compare_digest(header, f"Bearer {token}")

    def _read_body(self, length: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(READ_CHUNK_BYTES, remaining))
            if not chunk:
                self._send_json(400, {"error": "incomplete body"})
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send_json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def build_server(
    config: WorkerConfig,
    *,
    host: str | None = None,
    port: int | None = None,
) -> ThreadingHTTPServer:
    """创建 HTTP 服务；测试传 ``port=0`` 让系统分配空闲端口."""
    handler = type("ConfiguredPdfWorkerHandler", (PdfWorkerHandler,), {"config": config})
    server = ThreadingHTTPServer((host or config.host, config.port if port is None else port), handler)
    server.daemon_threads = True
    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # 容器根文件系统只读，HOME 指向 tmpfs：镜像里的目录会被 tmpfs 覆盖，启动时补建
    home = os.environ.get("HOME")
    if home:
        with suppress(OSError):
            Path(home).mkdir(parents=True, exist_ok=True)
    config = WorkerConfig.from_env()
    if config.token:
        logger.info("pdf_worker token 校验已启用")
    else:
        logger.warning("pdf_worker 未设置 PPTX_PDF_WORKER_TOKEN，仅依赖内网隔离")
    if shutil.which(config.soffice_bin) is None:
        logger.warning("pdf_worker 未找到可执行文件 %s，转换将全部失败", config.soffice_bin)

    server = build_server(config)
    logger.info("pdf_worker listening on %s:%s", config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - 容器停机
        pass
    finally:
        server.server_close()


if __name__ == "__main__":  # pragma: no cover - 入口
    main()

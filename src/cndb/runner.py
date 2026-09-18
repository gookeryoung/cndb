"""cndb 命令行入口（cndb）.

子命令：
- serve              启动 uvicorn 服务器
- dev                开发模式：同时启动前后端（需源码目录）
- build              构建前后端（需源码目录）
- info               打印版本/配置/运行环境

实现策略：argparse 标准库（避免引入 typer/click），子命令通过函数分发。
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from cndb.backup import backup_command
from cndb.restore import restore_command
from cndb.seed import seed as seed_command

# 源码根目录（仅开发命令可用；wheel 安装后不存在）
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


def _ensure_dev_env() -> None:
    """开发命令前置检查：确认处于源码仓库."""
    if not FRONTEND_DIR.is_dir():
        print(
            "[error] 此命令需在 cndb 源码仓库内运行。\n"
            f"   未找到 frontend/ 目录（期望位置: {FRONTEND_DIR}）\n"
            "   安装版仅支持 `cndb` / `cndb serve` 启动服务器。",
            file=sys.stderr,
        )
        sys.exit(1)


def _silence_proactor_reset_noise() -> None:
    """抑制 Windows ProactorEventLoop 的连接重置噪音（gh-83580 / bpo-39010）.

    客户端强制断开（RST）后，_ProactorBasePipeTransport._call_connection_lost
    回调内的 sock.shutdown(SHUT_RDWR) 会对已重置的连接再抛
    ConnectionResetError(WinError 10054)。连接本就在关闭，属无害噪音，
    但会污染 e2e（Playwright 并发 abort 连接时高频触发）与生产日志。
    包装该回调吞掉重置类异常；非 win32 为 no-op。
    """
    if sys.platform != "win32":
        return
    from asyncio.proactor_events import _ProactorBasePipeTransport

    # 私有属性未进 typeshed stubs，经 Any 动态读写绕过静态检查
    transport_cls: Any = _ProactorBasePipeTransport
    original = transport_cls._call_connection_lost

    def _quiet_call_connection_lost(self: Any, exc: BaseException | None) -> None:
        try:  # noqa: SIM105
            original(self, exc)
        except (ConnectionResetError, ConnectionAbortedError):
            # 对端已强制断开，连接本就在关闭，无需上抛
            pass

    transport_cls._call_connection_lost = _quiet_call_connection_lost


def serve(args: argparse.Namespace) -> None:
    """启动 uvicorn 服务器（生产可用，不依赖源码目录）."""
    try:
        import uvicorn
    except ImportError:
        print("[error] uvicorn 未安装，请执行 `uv sync`", file=sys.stderr)
        sys.exit(1)

    _silence_proactor_reset_noise()
    uvicorn.run(
        "cndb.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1 if args.reload else args.workers,
    )


def dev(args: argparse.Namespace) -> None:
    """同时启动前后端开发服务器（需源码目录）."""
    _ensure_dev_env()
    processes: list[subprocess.Popen[Any]] = []

    def _cleanup(_sig=None, _frame=None):
        for p in processes:
            if sys.platform == "win32":
                _ = subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(p.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                p.terminate()  # pragma: no cover - POSIX 分支
        sys.exit(0)

    _ = signal.signal(signal.SIGINT, _cleanup)
    if sys.platform == "win32":
        _ = signal.signal(signal.SIGBREAK, _cleanup)

    backend_port = args.port
    frontend_port = 5173

    print(f"[run] 启动后端服务 (port {backend_port})...")
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "cndb.app:app",
            "--host",
            args.host,
            "--port",
            str(backend_port),
            "--reload",
        ],
        cwd=ROOT_DIR,
    )
    processes.append(backend)

    print(f"[run] 启动前端开发服务器 (port {frontend_port})...")
    frontend_kwargs: dict[str, Any] = {"cwd": FRONTEND_DIR}
    if sys.platform == "win32":
        frontend_kwargs["shell"] = True
        frontend_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        frontend_cmd = f"npx vite --host {args.host} --port {frontend_port}"
    else:
        frontend_cmd = ["npx", "vite", "--host", args.host, "--port", str(frontend_port)]
    frontend = subprocess.Popen(frontend_cmd, **frontend_kwargs)
    processes.append(frontend)

    print()
    print(f"  后端:   http://{args.host}:{backend_port}")
    print(f"  前端:   http://{args.host}:{frontend_port}")
    print(f"  API文档: http://{args.host}:{backend_port}/docs")
    print()
    print("按 Ctrl+C 停止所有服务")

    try:
        backend.wait()
    except KeyboardInterrupt:
        _cleanup()


def build(_args: argparse.Namespace) -> None:
    """构建前后端（需源码目录）."""
    _ensure_dev_env()
    print("[build] 构建前端...")
    cmd = ["npm", "run", "build"]
    if sys.platform == "win32":
        result = subprocess.run(cmd, cwd=FRONTEND_DIR, check=False, shell=True)
    else:
        result = subprocess.run(cmd, cwd=FRONTEND_DIR, check=False)
    if result.returncode != 0:
        print("[error] 前端构建失败")
        sys.exit(result.returncode)
    print("[ok] 前端构建完成 → frontend/dist")

    # 同步到 src/cndb/static/（供 wheel 打包和服务端 SPA 使用）
    dist_dir = FRONTEND_DIR / "dist"
    static_dir = ROOT_DIR / "src" / "cndb" / "static"
    if dist_dir.is_dir():
        if static_dir.exists():
            shutil.rmtree(static_dir)
        shutil.copytree(dist_dir, static_dir)
        print(f"[ok] 前端产物已同步 → {static_dir.relative_to(ROOT_DIR)}")

    print()
    print("[ok] 全部构建完成！")


def info_command() -> int:
    """打印版本/配置/运行环境."""
    import platform

    from cndb.core.config import BASE_DIR, DATA_DIR, _is_frozen, settings

    print(f"{settings.APP_NAME}  v{settings.APP_VERSION}")
    print("-" * 40)
    print(f"  Python:       {sys.version}")
    print(f"  Platform:     {platform.platform()}")
    print(f"  Frozen:       {_is_frozen()}")
    print(f"  BASE_DIR:     {BASE_DIR}")
    print(f"  DATA_DIR:     {DATA_DIR}")
    print(f"  ├─ config:    {settings.CONFIG_DIR}")
    print(f"  ├─ data:      {settings.DATABASE_DIR}")
    print(f"  ├─ uploads:   {settings.UPLOAD_DIR}")
    print(f"  ├─ plugins:   {settings.PLUGINS_DIR}")
    print(f"  ├─ backups:   {settings.BACKUP_DIR}")
    print(f"  ├─ cache:     {settings.CACHE_DIR}")
    print(f"  └─ logs:      {settings.LOG_DIR}")
    print(f"  DEBUG:        {settings.DEBUG}")
    print(f"  DATABASE_URL: {settings.DATABASE_URL}")
    print(f"  API_PREFIX:   {settings.API_V1_PREFIX}")
    print(f"  AUTH_ENABLED: {settings.AUTH_ENABLED}")
    print(f"  SYSLIB:       {sys.executable}")
    return 0


def main() -> None:
    """cndb CLI 入口."""
    parser = argparse.ArgumentParser(
        prog="cndb",
        description="cndb - FastAPI + SQLAlchemy + Plugin 架构脚手架",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="启动 uvicorn 服务器")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument("--workers", type=int, default=1)

    p_dev = sub.add_parser("dev", help="开发模式：同时启动前后端")
    p_dev.add_argument("--host", default="127.0.0.1")
    p_dev.add_argument("--port", type=int, default=8772, help="后端端口（默认 8772，与 Vite 代理对齐）")

    sub.add_parser("build", help="构建前后端（需源码目录）")
    sub.add_parser("info", help="打印版本/配置/运行环境")
    sub.add_parser("seed", help="向数据库注入演示数据")

    # backup 子命令
    p_backup = sub.add_parser("backup", help="备份数据库和附件（输出到 .tar.gz 归档或文件夹）")
    p_backup.add_argument(
        "-o",
        "--output",
        help="输出路径 — .tar.gz 文件（归档）或文件夹（目录模式，需配合 --dir）. 默认 backup-<timestamp>.tar.gz",
    )
    p_backup.add_argument(
        "--dir",
        action="store_true",
        help="目录模式：将备份内容直接输出到文件夹（manifest.json + database/ + uploads/），不做压缩",
    )
    p_backup.add_argument(
        "--mode",
        choices=["auto", "native", "sqlalchemy"],
        default="auto",
        help="备份模式：auto=SQLite 用 native 其他用 sqlalchemy；native 直接复制 db 文件最快；sqlalchemy 跨数据库兼容",
    )
    p_backup.add_argument(
        "--no-uploads",
        action="store_true",
        help="不包含 uploads 目录的附件文件（仅备份数据库）",
    )

    # restore 子命令
    p_restore = sub.add_parser("restore", help="从 .tar.gz 归档或文件夹恢复数据（自动识别源类型）")
    p_restore.add_argument(
        "archive",
        help="备份源路径 — .tar.gz 归档文件或包含 manifest.json 的文件夹",
    )
    p_restore.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已有数据（默认拒绝有数据的目标库）",
    )
    p_restore.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查备份源完整性并预览内容，不实际恢复",
    )

    # users 子命令组
    from cndb.cli_users import register_users_subparser

    register_users_subparser(sub)

    args = parser.parse_args()

    if args.command is None:
        args.host = "127.0.0.1"
        args.port = 8000
        args.reload = False
        args.workers = 1
        serve(args)
        return

    if args.command == "serve":
        serve(args)
    elif args.command == "dev":
        dev(args)
    elif args.command == "build":
        build(args)
    elif args.command == "seed":
        seed_command(args)
    elif args.command == "backup":
        backup_command(args)
    elif args.command == "restore":
        restore_command(args)
    elif args.command == "info":
        sys.exit(info_command())
    elif args.command == "users":
        from cndb.cli_users import users_command

        users_command(args)
    else:
        parser.print_help()  # pragma: no cover - argparse 默认分支
        sys.exit(1)


if __name__ == "__main__":
    main()

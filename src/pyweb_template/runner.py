"""pyweb_template 命令行入口（pywt）.

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

# 源码根目录（仅开发命令可用；wheel 安装后不存在）
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


def _ensure_dev_env() -> None:
    """开发命令前置检查：确认处于源码仓库."""
    if not FRONTEND_DIR.is_dir():
        print(
            "[error] 此命令需在 pyweb-template 源码仓库内运行。\n"
            f"   未找到 frontend/ 目录（期望位置: {FRONTEND_DIR}）\n"
            "   安装版仅支持 `pywt` / `pywt serve` 启动服务器。",
            file=sys.stderr,
        )
        sys.exit(1)


def serve(args: argparse.Namespace) -> None:
    """启动 uvicorn 服务器（生产可用，不依赖源码目录）."""
    try:
        import uvicorn
    except ImportError:
        print("[error] uvicorn 未安装，请执行 `uv sync`", file=sys.stderr)
        sys.exit(1)

    uvicorn.run(
        "pyweb_template.app:app",
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
                p.terminate()
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
            "pyweb_template.app:app",
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
    frontend_kwargs: dict[str, Any] = {"cwd": FRONTEND_DIR, "shell": True}
    if sys.platform == "win32":
        frontend_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    frontend = subprocess.Popen(
        ["npx", "vite", "--host", args.host, "--port", str(frontend_port)],
        **frontend_kwargs,
    )
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
    result = subprocess.run(["npm", "run", "build"], cwd=FRONTEND_DIR, shell=True, check=False)
    if result.returncode != 0:
        print("[error] 前端构建失败")
        sys.exit(result.returncode)
    print("[ok] 前端构建完成 → frontend/dist")

    # 同步到 src/pyweb_template/static/（供 wheel 打包和服务端 SPA 使用）
    dist_dir = FRONTEND_DIR / "dist"
    static_dir = ROOT_DIR / "src" / "pyweb_template" / "static"
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

    from pyweb_template.core.config import settings

    print(f"{settings.APP_NAME}  v{settings.APP_VERSION}")
    print("-" * 40)
    print(f"  Python:       {sys.version}")
    print(f"  Platform:     {platform.platform()}")
    print(f"  DEBUG:        {settings.DEBUG}")
    print(f"  DATABASE_URL: {settings.DATABASE_URL}")
    print(f"  API_PREFIX:   {settings.API_V1_PREFIX}")
    print(f"  AUTH_ENABLED: {settings.AUTH_ENABLED}")
    print(f"  PLUGINS_DIR:  {settings.PLUGINS_DIR}")
    print(f"  SYSLIB:       {sys.executable}")
    return 0


def main() -> None:
    """pywt CLI 入口."""
    parser = argparse.ArgumentParser(
        prog="pywt",
        description="pyweb-template - FastAPI + SQLAlchemy + Plugin 架构脚手架",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="启动 uvicorn 服务器")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument("--workers", type=int, default=1)

    p_dev = sub.add_parser("dev", help="开发模式：同时启动前后端")
    p_dev.add_argument("--host", default="127.0.0.1")
    p_dev.add_argument("--port", type=int, default=8000, help="后端端口（默认 8000）")

    sub.add_parser("build", help="构建前后端（需源码目录）")

    sub.add_parser("info", help="打印版本/配置/运行环境")

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
    elif args.command == "info":
        sys.exit(info_command())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

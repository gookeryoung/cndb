"""cndbw GUI 主窗口（Tkinter + ttk）.

提供 CLI 主要功能的图形化入口：
- 启动服务   serve（host/port/workers）
- 备份恢复   backup + restore
- 系统信息   info

用户管理（users create/delete/list/import）仅保留 CLI 方式，不在 GUI 提供。

设计原则：
- UI 只负责参数采集 + 日志展示，实际逻辑调用 cndb 已有模块（backup/restore/cli_users），
  避免重复实现业务代码
- 耗时操作放 daemon 线程跑，stdout/stderr 重定向到 Text 组件，主线程定时 flush
- uvicorn server 用 subprocess.Popen 独立进程启动，窗口关闭时自动终止
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, override

from cndb.gui.log_handler import QueueStdout, redirect_output, run_in_thread, schedule_log_flush
from cndb.gui.settings import GuiSettings, load_settings, save_settings

# ── 日志文本 Tag 配置（终端风格配色）──
LOG_TAGS: dict[str, tuple[str, str]] = {
    "info": ("#333333", ""),
    "ok": ("#1a7f37", ""),
    "warn": ("#d4760a", ""),
    "error": ("#cf222e", ""),
}


def _default_backup_dir() -> Path:
    """GUI 默认备份输出路径（~/.cndb/backups）.

    复用 core.config 的 settings.BACKUP_DIR 约定，避免在 GUI 内重复定义路径常量。
    """
    from cndb.core.config import settings

    return settings.BACKUP_DIR


def _make_backup_name() -> str:
    """生成归档默认文件名，命名约定与 backup.create_backup 一致."""
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"backup-{ts}.tar.gz"


def _detect_tag(line: str) -> str:
    """根据行首关键字判定 tag，降级为 info."""
    lower = line.lstrip()
    if lower.startswith("[ok]"):
        return "ok"
    if lower.startswith("[warn]"):
        return "warn"
    if lower.startswith("[error]"):
        return "error"
    return "info"


def _backup_mtime(p: Path) -> float:
    """备份文件/目录的修改时间（排序键）."""
    return p.stat().st_mtime


def _scan_backup_files() -> list[Path]:
    """扫描默认备份目录，返回按修改时间倒序排列的备份文件.

    识别 ``.tar.gz`` / ``.tgz`` 归档文件与 ``backup-`` 前缀目录（目录模式备份），
    最新（修改时间最大）的排在列表首位。
    """
    from cndb.core.config import settings

    backup_dir = settings.BACKUP_DIR
    backups: list[Path] = []
    if backup_dir.is_dir():
        for p in backup_dir.iterdir():
            name = p.name.lower()
            is_archive = p.is_file() and (name.endswith(".tar.gz") or name.endswith(".tgz"))
            is_backup_dir = p.is_dir() and p.name.startswith("backup-")
            if is_archive or is_backup_dir:
                backups.append(p)
    backups.sort(key=_backup_mtime, reverse=True)
    return backups


# ── 窗口几何恢复 ──

# Tk geometry 字符串：`WxH+X+Y`（宽 x 高 + 水平偏移 + 垂直偏移）
_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def _apply_window_geometry(root: tk.Tk, geometry: str) -> None:
    """恢复主窗口位置/尺寸；已完全滑出屏幕（显示器变更等）时忽略，回退默认.

    Tk 的 geometry() 一直会记录左上角坐标；若用户外接屏移除后坐标变为负值，
    强行恢复会导致窗口无法拖回，故做一次屏幕边界校验。
    """
    match = _GEOMETRY_RE.match(geometry)
    if not match:
        return
    _, _, x, y = (int(g) for g in match.groups())
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    if x >= screen_w or y >= screen_h:  # 左上角已到屏幕外，忽略已保存位置
        return
    root.geometry(geometry)


# ═══════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════


class CndbMainWindow:
    """cndbw 主窗口容器，管理 Notebook + 状态栏 + 全局日志队列."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("cndbw — cndb 桌面管理台")
        self.root.minsize(800, 520)

        # 加载持久化的 GUI 设置，恢复主窗口几何信息（若有）
        self.settings = load_settings()
        _apply_window_geometry(root, self.settings.window_geometry)

        # 全局日志队列
        self.log_queue = QueueStdout()

        # server 进程句柄
        self._server_proc: subprocess.Popen[Any] | None = None
        self._server_thread: threading.Thread | None = None

        self._build_style()
        self._build_toolbar()
        self._build_notebook()
        self._build_statusbar()

        # 关闭钩子
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 布局 ──

    def _build_style(self) -> None:
        style = ttk.Style()
        # 尝试现代主题，不可用就用默认
        for theme in ("clam", "vista", "aqua"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("TNotebook.Tab", padding=(14, 6))
        style.configure("Header.TLabel", font=("", 12, "bold"))
        style.configure("Status.TLabel", anchor="w")

    def _build_toolbar(self) -> None:
        """顶部工具栏（版本号 + 打开文档链接）."""
        from cndb.core.config import settings

        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(
            bar,
            text=f"cndb v{settings.APP_VERSION}  桌面管理台",
            style="Header.TLabel",
        ).pack(side=tk.LEFT)

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        self.tab_serve = ServeTab(self.notebook, self)
        self.tab_backup = BackupTab(self.notebook, self)
        self.tab_info = InfoTab(self.notebook, self)

        self.notebook.add(self.tab_serve.frame, text="启动服务")
        self.notebook.add(self.tab_backup.frame, text="备份恢复")
        self.notebook.add(self.tab_info.frame, text="系统信息")

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="就绪")
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)

    # ── 全局 ──

    def set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _on_close(self) -> None:
        """关闭窗口：持久化所有界面设置与窗口位置，再停止并销毁."""
        self._persist_settings()
        if self._server_proc is not None:
            with contextlib.suppress(Exception):
                self._server_proc.terminate()
        self.root.destroy()

    def _persist_settings(self) -> None:
        """把主窗口几何与各 Tab 界面设置收集进 settings 并写入配置文件."""
        with contextlib.suppress(Exception):
            self.settings.window_geometry = self.root.geometry()
        for tab in (self.tab_serve, self.tab_backup, self.tab_info):
            tab.persist(self.settings)
        save_settings(self.settings)

    def run(self) -> None:
        # 切换到主窗口的 stdout/stderr（只在 GUI 运行期间重定向，避免影响子进程）
        import sys

        sys.stdout = self.log_queue
        sys.stderr = self.log_queue
        schedule_log_flush(self.root, self.log_queue, self.tab_serve.log_text)
        self.root.mainloop()


def _make_text_copyable(text: scrolledtext.ScrolledText) -> None:
    """让只读日志 Text 支持复制：Ctrl+C / Ctrl+A 快捷键 + 右键菜单.

    日志区为 state=DISABLED 的只读 Text（不可编辑但允许选中），
    这里补齐复制快捷键与右键菜单，便于用户拷贝日志排查故障。
    """

    def _selected() -> str | None:
        """取当前选中文本，无选中时返回 None."""
        try:
            return text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return None

    def _copy_selection(_event: object | None = None) -> str:
        """复制选中文本到剪贴板（无选中时不动）."""
        content = _selected()
        if content:
            text.clipboard_clear()
            text.clipboard_append(content)
        return "break"

    def _copy_all(_event: object | None = None) -> str:
        """复制全部日志内容到剪贴板."""
        text.clipboard_clear()
        text.clipboard_append(text.get("1.0", tk.END))
        return "break"

    def _select_all(_event: object | None = None) -> str:
        """全选日志文本."""
        text.tag_add(tk.SEL, "1.0", tk.END)
        text.mark_set(tk.INSERT, "1.0")
        return "break"

    def _show_menu(event: tk.Event[Any]) -> None:
        """右键弹出复制菜单；无选中时禁用「复制」项."""
        menu.entryconfig("复制", state=tk.NORMAL if _selected() else tk.DISABLED)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # 大写变体兼容 Caps Lock 开启时的按键序列
    for seq in ("<Control-c>", "<Control-C>"):
        text.bind(seq, _copy_selection)
    for seq in ("<Control-a>", "<Control-A>"):
        text.bind(seq, _select_all)

    menu = tk.Menu(text, tearoff=0)
    menu.add_command(label="复制", command=_copy_selection)
    menu.add_command(label="复制全部", command=_copy_all)
    menu.add_separator()
    menu.add_command(label="全选", command=_select_all)
    text.bind("<Button-3>", _show_menu)


# ═══════════════════════════════════════════════════════════════
# Tab 基类
# ═══════════════════════════════════════════════════════════════


class _BaseTab:
    """Tab 公共骨架：frame + 日志 Text + 标签化."""

    def __init__(self, parent: ttk.Notebook, app: CndbMainWindow) -> None:
        self.parent = parent
        self.app = app
        self.frame = ttk.Frame(parent, padding=10)
        self._build_layout()

    def _build_layout(self) -> None:
        """子类覆写：构建布局 + 调 self._build_log_text()."""
        raise NotImplementedError

    def _build_log_text(self, parent: ttk.Widget) -> scrolledtext.ScrolledText:
        """创建统一风格的日志 Text 组件（只读，支持选中复制）."""
        text = scrolledtext.ScrolledText(parent, height=14, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        for name, (fg, bg) in LOG_TAGS.items():
            kwargs: dict[str, str] = {"foreground": fg}
            if bg:
                kwargs["background"] = bg
            text.tag_configure(name, **kwargs)
        text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        _make_text_copyable(text)
        return text

    def persist(self, settings: GuiSettings) -> None:
        """把当前界面取值写入 settings（默认无状态 Tab 为 no-op）."""
        del settings


# ═══════════════════════════════════════════════════════════════
# Tab: 启动服务
# ═══════════════════════════════════════════════════════════════


class ServeTab(_BaseTab):
    """启动 uvicorn 服务器（独立子进程，避免主线程阻塞）."""

    @override
    def _build_layout(self) -> None:
        # 配置区
        cfg = ttk.LabelFrame(self.frame, text="启动配置", padding=10)
        cfg.pack(fill=tk.X)

        ttk.Label(cfg, text="Host:").grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        self.host_var = tk.StringVar(value=self.app.settings.serve.host)
        ttk.Entry(cfg, textvariable=self.host_var, width=16).grid(row=0, column=1, sticky=tk.W, padx=2)

        ttk.Label(cfg, text="Port:").grid(row=0, column=2, sticky=tk.W, padx=2, pady=2)
        self.port_var = tk.StringVar(value=self.app.settings.serve.port)
        ttk.Entry(cfg, textvariable=self.port_var, width=8).grid(row=0, column=3, sticky=tk.W, padx=2)

        self.reload_var = tk.BooleanVar(value=self.app.settings.serve.reload)
        ttk.Checkbutton(cfg, text="开发模式 (reload)", variable=self.reload_var).grid(
            row=0, column=4, sticky=tk.W, padx=12
        )

        ttk.Label(cfg, text="Workers:").grid(row=0, column=5, sticky=tk.W, padx=2)
        self.workers_var = tk.StringVar(value=self.app.settings.serve.workers)
        ttk.Entry(cfg, textvariable=self.workers_var, width=6).grid(row=0, column=6, sticky=tk.W, padx=2)

        # 环境检查监视区（端口占用 + 静态产物就绪）
        env = ttk.LabelFrame(self.frame, text="环境检查", padding=10)
        env.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(env, text="端口占用:").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        self.port_status_var = tk.StringVar(value="未检测")
        ttk.Label(env, textvariable=self.port_status_var, foreground="#888").grid(row=0, column=1, sticky=tk.W, padx=6)
        ttk.Label(env, text="静态文件:").grid(row=1, column=0, sticky=tk.W, padx=(0, 6))
        self.static_status_var = tk.StringVar(value="未检测")
        ttk.Label(env, textvariable=self.static_status_var, foreground="#888").grid(
            row=1, column=1, sticky=tk.W, padx=6
        )
        self.env_check_btn = ttk.Button(env, text="重新检查", command=self.refresh_env)
        self.env_check_btn.grid(row=0, column=2, rowspan=2, sticky=tk.E)

        # 按钮区
        btn_row = ttk.Frame(self.frame)
        btn_row.pack(fill=tk.X, pady=(10, 4))
        self.start_btn = ttk.Button(btn_row, text="启动服务", command=self.start_server)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(btn_row, text="停止服务", command=self.stop_server, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.open_btn = ttk.Button(btn_row, text="在浏览器打开", command=self.open_browser, state=tk.DISABLED)
        self.open_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.status_label = ttk.Label(btn_row, text="服务未启动", foreground="#888")
        self.status_label.pack(side=tk.RIGHT)

        # 日志区
        log_frame = ttk.LabelFrame(self.frame, text="运行日志", padding=(4, 4))
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = self._build_log_text(log_frame)

        # 构建 Tab 时立即刷新一次环境状态
        self.refresh_env()

    # ── actions ──

    def refresh_env(self) -> None:
        """后台刷新端口占用与静态产物状态，渲染到「环境检查」监视区."""
        self._env_busy = True
        self.env_check_btn.configure(state=tk.DISABLED)
        self.port_status_var.set("检测中...")
        self.static_status_var.set("检测中...")

        def _run() -> None:
            from cndb.gui import checks

            port = int(self.port_var.get().strip() or "8000")
            info = checks.port_status(port)
            st = checks.static_status()
            if info.used:
                port_label = f"端口 {port} 已被占用"
                if info.pid:
                    port_label += f" (PID {info.pid})"
                if info.process_name:
                    port_label += f" ({info.process_name})"
            else:
                port_label = f"端口 {port} 空闲，可启动"
            static_text = "就绪" if st.ready else ("缺失: " + ", ".join(st.missing) if st.missing else "未构建")
            self.app.root.after(0, lambda: self._render_env(port_label, static_text, st.ready))

        run_in_thread(_run)

    def _render_env(self, port_label: str, static_text: str, static_ok: bool) -> None:
        """把后台采集到的环境检查结果渲染到监视区（主线程回调）."""
        del static_ok
        self._env_busy = False
        self.env_check_btn.configure(state=tk.NORMAL)
        self.port_status_var.set(port_label)
        self.static_status_var.set(f"静态文件 {static_text}")

    def _preflight(self, host: str, port: int) -> None:
        """启动前环境预检：停止占用端口 + 自动构建缺失的静态产物.

        Args:
            host: 服务绑定主机。
            port: 服务端口。

        Raises:
            RuntimeError: 自动构建静态产物失败时（端口清理失败同样上抛）。
        """
        from cndb.gui import checks

        # 1) 端口占用先清理，避免 uvicorn 绑定失败
        if checks.check_port(host, port):
            self.app.log_queue.write(f"[warn] 端口 {host}:{port} 已被占用，正在停止占用进程...\n")
            message = checks.stop_port_occupant(port)
            self.app.log_queue.write(f"[ok] {message}\n")
            time.sleep(0.5)  # 留出内核释放端口的时间

        # 2) 前端静态产物缺失时自动构建，避免访问 SPA 报 404 / 仅返回 API
        st = checks.static_status()
        if not st.ready:
            self.app.log_queue.write("[info] 前端静态产物缺失，自动构建...\n")
            checks.build_static(log=lambda msg: self.app.log_queue.write(msg + "\n"))
            self.app.log_queue.write("[ok] 前端静态产物构建完成\n")

    def start_server(self) -> None:
        if self.app._server_proc is not None:
            messagebox.showinfo("提示", "服务已在运行")
            return

        host = self.host_var.get().strip() or "127.0.0.1"
        port = int(self.port_var.get().strip() or "8000")
        reload = self.reload_var.get()
        workers = 1 if reload else int(self.workers_var.get().strip() or "1")

        # ── 启动前环境预检：停止占用端口 + 确保静态产物就绪 ──
        try:
            self._preflight(host, port)
        except Exception as exc:
            messagebox.showerror("启动前检查失败", str(exc))
            self.app.log_queue.write(f"[error] 启动前检查失败: {exc}\n")
            return

        # === 定位 dist 根目录（fspack 打包根） ===
        # fspack launcher 模式下 sys.executable = cndbw.exe（launcher 自身），
        # 不是 runtime/pythonw.exe！必须从 __file__ 往上找 runtime/python.exe
        # 作为锚点——这是打包环境唯一稳定的定位方式（开发环境无 runtime/ 目录）。
        def _find_dist_root() -> Path | None:
            here = Path(__file__).resolve()
            for parent in here.parents:
                if (parent / "runtime" / "python.exe").exists():
                    return parent
            return None  # 开发环境

        _dist_root = _find_dist_root()

        # 子进程解释器与引导命令
        # - 打包环境：用 runtime/python.exe（控制台子系统）+ bootstrap 注入路径
        # - 开发环境：sys.path 已正确，直接用 sys.executable -m uvicorn
        if _dist_root is not None:
            _py_bin = _dist_root / "runtime" / "python.exe"
            _pkg_entry_root = _dist_root / "src" / "src"
            _bootstrap = (
                f"import sys; sys.path.insert(0, r'{_pkg_entry_root}'); "
                "import uvicorn; "
                f"uvicorn.run('cndb.app:app', host={host!r}, port={port}, "
                f"reload={reload!r}, workers={workers})"
            )
            cmd: list[str] = [str(_py_bin), "-c", _bootstrap]
        else:
            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "cndb.app:app",
                "--host",
                host,
                "--port",
                str(port),
            ]
            if reload:
                cmd.append("--reload")
            elif workers > 1:
                cmd.extend(["--workers", str(workers)])

        # Windows GUI 程序（pythonw 无 console）下 stdin 是无效句柄，
        # Popen 内部 _make_inheritable 会触发 WinError 6；显式设 DEVNULL 规避。
        # CREATE_NO_WINDOW + STARTUPINFO SW_HIDE 双保险绝对不弹黑窗。
        creationflags = 0
        startupinfo = None
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        try:
            self.app._server_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
        except FileNotFoundError as e:
            _hint = str(e) or "找不到要执行的解释器或命令"
            messagebox.showerror(
                "启动失败", f"找不到 Python 可执行文件：{_hint}\n\n请检查安装目录下是否存在 runtime\\python.exe"
            )
            return

        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.open_btn.configure(state=tk.NORMAL)
        self.status_label.configure(text=f"运行中 http://{host}:{port}", foreground="#1a7f37")
        self.app.set_status(f"服务运行中  http://{host}:{port}")

        # 异步读子进程输出 → 写入队列
        proc = self.app._server_proc
        assert proc is not None

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                # 直接写 QueueStdout 队列（UI 线程定时 flush 到 log_text）
                self.app.log_queue.write(line)

            # 进程退出
            def _after() -> None:
                self.start_btn.configure(state=tk.NORMAL)
                self.stop_btn.configure(state=tk.DISABLED)
                self.open_btn.configure(state=tk.DISABLED)
                self.status_label.configure(text="服务已停止", foreground="#888")
                self.app.set_status("服务已停止")
                self.app._server_proc = None

            self.app.root.after(0, _after)

        self.app._server_thread = threading.Thread(target=_reader, daemon=True)
        self.app._server_thread.start()

    def stop_server(self) -> None:
        proc = self.app._server_proc
        if proc is None:
            return
        # Windows 下 terminate() 也能用（等价 SIGTERM），统一调用即可
        with contextlib.suppress(Exception):
            proc.terminate()
        self.app._server_proc = None
        self.status_label.configure(text="正在停止...", foreground="#d4760a")
        self.app.set_status("正在停止服务...")

    def open_browser(self) -> None:
        import webbrowser

        url = f"http://{self.host_var.get().strip() or '127.0.0.1'}:{self.port_var.get().strip() or '8000'}"
        webbrowser.open(url)

    @override
    def persist(self, settings: GuiSettings) -> None:
        settings.serve.host = self.host_var.get().strip() or "127.0.0.1"
        settings.serve.port = self.port_var.get().strip() or "8000"
        settings.serve.reload = self.reload_var.get()
        settings.serve.workers = self.workers_var.get().strip() or "1"


# ═══════════════════════════════════════════════════════════════
# Tab: 备份/恢复
# ═══════════════════════════════════════════════════════════════


class BackupTab(_BaseTab):
    """备份/恢复操作界面.

    布局约定（对齐最佳实践）：
    - 分组使用 LabelFrame，顶部两个操作区并排的首要信息（输出路径/归档文件）
      以「标签 + 输入框 + 行内按钮」排成一行
    - 控制列（column=1）拉伸占满剩余宽度，保证不同分辨率下整齐
    - 所有操作按钮统一右对齐，避免散落
    """

    _BACKUP_MODES: tuple[str, ...] = ("auto", "native", "sqlalchemy")

    @override
    def _build_layout(self) -> None:
        saved = self.app.settings.backup

        # ── 上半：创建备份 ──
        back_frame = ttk.LabelFrame(self.frame, text="创建备份", padding=(12, 10))
        back_frame.pack(fill=tk.X)
        back_frame.columnconfigure(1, weight=1)  # 输入/选择列占满剩余宽度

        ttk.Label(back_frame, text="输出路径:").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.out_var = tk.StringVar(value=saved.output or str(_default_backup_dir()))
        ttk.Entry(back_frame, textvariable=self.out_var).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Button(back_frame, text="浏览", command=self._pick_output, width=8).grid(
            row=0, column=2, padx=(8, 0), pady=4
        )

        ttk.Label(back_frame, text="模式:").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.mode_var = tk.StringVar(value=(saved.mode if saved.mode in self._BACKUP_MODES else "auto"))
        ttk.Combobox(
            back_frame, textvariable=self.mode_var, values=list(self._BACKUP_MODES), state="readonly", width=14
        ).grid(row=1, column=1, sticky=tk.W, pady=4)

        self.no_uploads_var = tk.BooleanVar(value=saved.no_uploads)
        ttk.Checkbutton(back_frame, text="不包含附件 (uploads)", variable=self.no_uploads_var).grid(
            row=1, column=2, sticky=tk.W, padx=(12, 0), pady=4
        )

        self.backup_btn = ttk.Button(back_frame, text="立即备份", command=self.do_backup)
        self.backup_btn.grid(row=2, column=2, sticky=tk.E, pady=(10, 0))

        # 进度条 + 结果反馈（备份/恢复/预演共用）
        prog_row = ttk.Frame(back_frame)
        prog_row.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))
        self.progress = ttk.Progressbar(prog_row, mode="determinate", maximum=1, value=0, length=200)
        self.progress.pack(side=tk.LEFT)
        self.op_status = ttk.Label(prog_row, text="就绪", foreground="#888")
        self.op_status.pack(side=tk.LEFT, padx=(10, 0))

        # ── 下半：恢复 ──
        rest_frame = ttk.LabelFrame(self.frame, text="从归档恢复", padding=(12, 10))
        rest_frame.pack(fill=tk.X, pady=(10, 0))
        rest_frame.columnconfigure(1, weight=1)

        ttk.Label(rest_frame, text="归档文件:").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.archive_var = tk.StringVar()
        self.archive_box = ttk.Combobox(rest_frame, textvariable=self.archive_var, state="readonly")
        self.archive_box.grid(row=0, column=1, sticky=tk.EW, pady=4)
        # 归档行内操作按钮集合（成组，视觉紧凑）
        archive_btns = ttk.Frame(rest_frame)
        archive_btns.grid(row=0, column=2, padx=(8, 0), pady=4)
        ttk.Button(archive_btns, text="浏览", command=self._pick_archive, width=6).pack(side=tk.LEFT)
        ttk.Button(archive_btns, text="刷新列表", command=self._refresh_archives).pack(side=tk.LEFT, padx=(6, 0))

        self.force_var = tk.BooleanVar(value=saved.force)
        ttk.Checkbutton(rest_frame, text="强制覆盖已有数据", variable=self.force_var).grid(
            row=1, column=0, columnspan=2, sticky=tk.W, padx=(0, 8), pady=4
        )

        # 操作按钮统一右对齐
        op_row = ttk.Frame(rest_frame)
        op_row.grid(row=2, column=2, sticky=tk.E, pady=(10, 0))
        self.dry_run_btn = ttk.Button(op_row, text="预演 (dry-run)", command=self.do_restore_dry_run)
        self.dry_run_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.restore_btn = ttk.Button(op_row, text="立即恢复", command=self.do_restore)
        self.restore_btn.pack(side=tk.LEFT)

        # 日志区
        log_frame = ttk.LabelFrame(self.frame, text="操作日志", padding=(4, 4))
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.log_text = self._build_log_text(log_frame)

        # 初始填充归档列表：最新备份作为默认选项
        self._refresh_archives()

    @override
    def persist(self, settings: GuiSettings) -> None:
        settings.backup.output = self.out_var.get().strip()
        settings.backup.mode = self.mode_var.get() or "auto"
        settings.backup.no_uploads = self.no_uploads_var.get()
        settings.backup.force = self.force_var.get()

    def _refresh_archives(self) -> None:
        """扫描默认备份目录刷新归档下拉列表，最新备份自动作为默认选项."""
        values = [str(p) for p in _scan_backup_files()]
        self.archive_box.configure(values=values)
        current = self.archive_var.get().strip()
        if values and (not current or current not in values):
            self.archive_var.set(values[0])
        elif not values:
            self.archive_var.set("")

    def _begin_op(self, status: str) -> None:
        """开始一个耗时操作：显示进度条、更新状态文本."""
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self.op_status.configure(text=status, foreground="#1a7f37")

    def _finish_op(self, btn: ttk.Button, success: bool, status: str) -> None:
        """结束一个耗时操作：停止进度条、恢复按钮、更新状态."""
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        btn.configure(state=tk.NORMAL)
        fg = "#1a7f37" if success else "#d1242f"
        self.op_status.configure(text=status, foreground=fg)

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="备份输出路径",
            initialdir=_default_backup_dir(),
            defaultextension=".tar.gz",
            filetypes=[("归档", "*.tar.gz"), ("全部", "*.*")],
        )
        if path:
            self.out_var.set(path)

    def _pick_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="选择备份归档",
            filetypes=[("归档", "*.tar.gz *.tgz"), ("全部", "*.*")],
        )
        if not path:
            return
        # 手动选择的文件并入下拉列表并设为当前项（不要求位于默认备份目录）
        values = list(self.archive_box.cget("values"))
        if path not in values:
            values.insert(0, path)
            self.archive_box.configure(values=values)
        self.archive_var.set(path)

    def do_backup(self) -> None:
        out = self.out_var.get().strip()
        mode = self.mode_var.get()
        include_uploads = not self.no_uploads_var.get()
        # 输出路径留空时默认写入备份目录，便于「归档文件」列表直接识别
        if not out:
            import datetime as dt

            from cndb.core.config import settings

            ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
            out = str(settings.BACKUP_DIR / f"backup-{ts}.tar.gz")

        # 输出路径为目录时，追加时间戳文件名；否则直接使用给定路径
        out_path = Path(out).expanduser().resolve()
        if out_path.is_dir():
            out_path = out_path / _make_backup_name()

        self.backup_btn.configure(state=tk.DISABLED)
        self._begin_op("正在备份...")

        def _run() -> None:
            from cndb.cli.backup import BackupError, create_backup

            try:
                result = create_backup(output=out_path, mode=mode, include_uploads=include_uploads)
                print(f"[ok] 备份成功: {result}")
                # 备份完成后刷新归档列表，新备份自动成为默认选项
                self.app.root.after(0, self._refresh_archives)
                self.app.root.after(0, self._finish_op, self.backup_btn, True, "备份完成")
            except BackupError as exc:
                with redirect_output(self.app.log_queue):
                    print(f"[error] {exc}", file=sys.stderr)
                self.app.root.after(0, self._finish_op, self.backup_btn, False, "备份失败")
            except Exception as exc:
                with redirect_output(self.app.log_queue):
                    print(f"[error] 备份失败: {exc}", file=sys.stderr)
                self.app.root.after(0, self._finish_op, self.backup_btn, False, "备份失败")

        run_in_thread(_run)

    def do_restore(self) -> None:
        archive = self.archive_var.get().strip()
        if not archive:
            messagebox.showwarning("缺少参数", "请先选择归档文件")
            return
        if not messagebox.askyesno("确认恢复", "恢复将覆盖现有数据，确认继续？"):
            return

        self.restore_btn.configure(state=tk.DISABLED)
        self._begin_op("正在恢复...")

        def _run() -> None:
            from cndb.cli.restore import RestoreError, restore_backup

            try:
                with redirect_output(self.app.log_queue):
                    restore_backup(Path(archive), force=self.force_var.get())
                    print("[ok] 恢复完成")
                self.app.root.after(0, self._finish_op, self.restore_btn, True, "恢复完成")
            except RestoreError as exc:
                with redirect_output(self.app.log_queue):
                    print(f"[error] {exc}", file=sys.stderr)
                self.app.root.after(0, self._finish_op, self.restore_btn, False, "恢复失败")
            except Exception as exc:
                with redirect_output(self.app.log_queue):
                    print(f"[error] 恢复失败: {exc}", file=sys.stderr)
                self.app.root.after(0, self._finish_op, self.restore_btn, False, "恢复失败")

        run_in_thread(_run)

    def do_restore_dry_run(self) -> None:
        archive = self.archive_var.get().strip()
        if not archive:
            messagebox.showwarning("缺少参数", "请先选择归档文件")
            return

        self.dry_run_btn.configure(state=tk.DISABLED)
        self._begin_op("正在预演...")

        def _run() -> None:
            from cndb.cli.restore import RestoreError, inspect_backup

            try:
                with redirect_output(self.app.log_queue):
                    info = inspect_backup(Path(archive))
                    print("[info] 归档有效")
                    print(info.summary)
                self.app.root.after(0, self._finish_op, self.dry_run_btn, True, "预演完成")
            except RestoreError as exc:
                with redirect_output(self.app.log_queue):
                    print(f"[error] {exc}", file=sys.stderr)
                self.app.root.after(0, self._finish_op, self.dry_run_btn, False, "预演失败")

        run_in_thread(_run)


# ═══════════════════════════════════════════════════════════════
# Tab: 系统信息
# ═══════════════════════════════════════════════════════════════


class InfoTab(_BaseTab):
    """系统信息：手动刷新 + 定时自动刷新.

    - 手动刷新：点击「立即刷新」随时拉取最新系统信息
    - 自动刷新：勾选「自动刷新」后按所选间隔定时刷新，切换间隔即时生效，
      关闭勾选即停止定时器；刷新在后台线程采集，避免阻塞 UI
    """

    # 自动刷新间隔选项：显示文案 → 毫秒（0 表示关闭）
    AUTO_REFRESH_OPTIONS: dict[str, int] = {
        "关闭": 0,
        "5 秒": 5000,
        "10 秒": 10000,
        "30 秒": 30000,
        "60 秒": 60000,
    }

    @override
    def _build_layout(self) -> None:
        top = ttk.Frame(self.frame)
        top.pack(fill=tk.X)

        saved = self.app.settings.info
        self._refreshing = False
        self._after_id: str | None = None

        # 自动刷新默认开启（可被持久化的配置覆盖）
        self.auto_var = tk.BooleanVar(value=saved.auto_refresh)
        ttk.Checkbutton(top, text="自动刷新", variable=self.auto_var, command=self._on_auto_toggle).pack(side=tk.LEFT)

        # 间隔取持久化值，不合法时回退默认
        interval = saved.interval if saved.interval in self.AUTO_REFRESH_OPTIONS else "10 秒"
        self.interval_var = tk.StringVar(value=interval)
        self.interval_box = ttk.Combobox(
            top,
            textvariable=self.interval_var,
            values=list(self.AUTO_REFRESH_OPTIONS),
            state="readonly",
            width=8,
        )
        self.interval_box.pack(side=tk.LEFT, padx=(6, 0))
        self.interval_box.bind("<<ComboboxSelected>>", self._on_interval_change)

        ttk.Button(top, text="立即刷新", command=self.refresh).pack(side=tk.LEFT, padx=(12, 0))

        self.last_var = tk.StringVar(value="尚未刷新")
        ttk.Label(top, textvariable=self.last_var, foreground="#888").pack(side=tk.RIGHT)

        self.text = scrolledtext.ScrolledText(self.frame, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED)
        self.text.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        _make_text_copyable(self.text)

        # 启动即开启自动刷新：立即取一次信息并排定定时器
        if self.auto_var.get():
            self.refresh()
            self._schedule_next()

    @override
    def persist(self, settings: GuiSettings) -> None:
        settings.info.auto_refresh = self.auto_var.get()
        settings.info.interval = self.interval_var.get() or "10 秒"

    # ── 刷新 ──

    def refresh(self) -> None:
        """后台采集系统信息并渲染到文本区（自动/手动刷新共用入口）."""
        if self._refreshing:
            return
        self._refreshing = True

        def _run() -> None:
            import io
            import sys

            from cndb.cli.main import info_command

            buf = io.StringIO()
            old = sys.stdout
            sys.stdout = buf
            try:
                info_command()
            finally:
                sys.stdout = old
            self.app.root.after(0, lambda: self._render(buf.getvalue()))

        run_in_thread(_run)

    def _render(self, output: str) -> None:
        self._refreshing = False
        self.last_var.set(f"上次刷新: {time.strftime('%H:%M:%S')}")
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", output)
        self.text.configure(state=tk.DISABLED)

    # ── 自动刷新 ──

    def _on_auto_toggle(self) -> None:
        if self.auto_var.get():
            self.refresh()  # 开启后立即刷新一次
            self._schedule_next()
        else:
            self._cancel_timer()

    def _on_interval_change(self, _event: object | None = None) -> None:
        # 切换间隔即时生效：自动刷新开启时按新间隔重排定时器
        if self.auto_var.get():
            self._schedule_next()

    def _schedule_next(self) -> None:
        self._cancel_timer()
        ms = self.AUTO_REFRESH_OPTIONS.get(self.interval_var.get(), 0)
        if ms <= 0:
            return
        self._after_id = self.app.root.after(ms, self._on_timer)

    def _cancel_timer(self) -> None:
        if self._after_id is not None:
            with contextlib.suppress(Exception):
                self.app.root.after_cancel(self._after_id)
            self._after_id = None

    def _on_timer(self) -> None:
        self._after_id = None
        if not self.auto_var.get():
            return
        self.refresh()
        self._schedule_next()


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """cndbw CLI 入口."""
    root = tk.Tk()
    app = CndbMainWindow(root)
    app.run()


if __name__ == "__main__":
    main()

"""cndbw GUI 主窗口（Tkinter + ttk）.

提供 CLI 全部功能的图形化入口：
- 启动服务   serve（host/port/workers）
- 备份恢复   backup + restore
- 用户管理   users create/delete/list/import
- 演示数据   seed
- 系统信息   info

设计原则：
- UI 只负责参数采集 + 日志展示，实际逻辑调用 cndb 已有模块（backup/restore/cli_users/seed），
  避免重复实现业务代码
- 耗时操作放 daemon 线程跑，stdout/stderr 重定向到 Text 组件，主线程定时 flush
- uvicorn server 用 subprocess.Popen 独立进程启动，窗口关闭时自动终止
"""

from __future__ import annotations

import argparse
import contextlib
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, override

from cndb.gui.log_handler import QueueStdout, run_in_thread, schedule_log_flush

# ── 日志文本 Tag 配置（终端风格配色）──
LOG_TAGS: dict[str, tuple[str, str]] = {
    "info": ("#333333", ""),
    "ok": ("#1a7f37", ""),
    "warn": ("#d4760a", ""),
    "error": ("#cf222e", ""),
}


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


# ═══════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════


class CndbMainWindow:
    """cndbw 主窗口容器，管理 Notebook + 状态栏 + 全局日志队列."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("cndbw — cndb 桌面管理台")
        self.root.geometry("960x640")
        self.root.minsize(800, 520)

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
        self.tab_users = UsersTab(self.notebook, self)
        self.tab_seed = SeedTab(self.notebook, self)
        self.tab_info = InfoTab(self.notebook, self)

        self.notebook.add(self.tab_serve.frame, text="启动服务")
        self.notebook.add(self.tab_backup.frame, text="备份恢复")
        self.notebook.add(self.tab_users.frame, text="用户管理")
        self.notebook.add(self.tab_seed.frame, text="演示数据")
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
        """关闭窗口前停服务."""
        if self._server_proc is not None:
            with contextlib.suppress(Exception):
                self._server_proc.terminate()
        self.root.destroy()

    def run(self) -> None:
        # 切换到主窗口的 stdout/stderr（只在 GUI 运行期间重定向，避免影响子进程）
        import sys

        sys.stdout = self.log_queue
        sys.stderr = self.log_queue
        schedule_log_flush(self.root, self.log_queue, self.tab_serve.log_text)
        self.root.mainloop()


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
        """创建统一风格的日志 Text 组件."""
        text = scrolledtext.ScrolledText(parent, height=14, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        for name, (fg, bg) in LOG_TAGS.items():
            kwargs: dict[str, str] = {"foreground": fg}
            if bg:
                kwargs["background"] = bg
            text.tag_configure(name, **kwargs)
        text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        return text


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
        self.host_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(cfg, textvariable=self.host_var, width=16).grid(row=0, column=1, sticky=tk.W, padx=2)

        ttk.Label(cfg, text="Port:").grid(row=0, column=2, sticky=tk.W, padx=2, pady=2)
        self.port_var = tk.StringVar(value="8000")
        ttk.Entry(cfg, textvariable=self.port_var, width=8).grid(row=0, column=3, sticky=tk.W, padx=2)

        self.reload_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="开发模式 (reload)", variable=self.reload_var).grid(
            row=0, column=4, sticky=tk.W, padx=12
        )

        ttk.Label(cfg, text="Workers:").grid(row=0, column=5, sticky=tk.W, padx=2)
        self.workers_var = tk.StringVar(value="1")
        ttk.Entry(cfg, textvariable=self.workers_var, width=6).grid(row=0, column=6, sticky=tk.W, padx=2)

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

    # ── actions ──

    def start_server(self) -> None:
        if self.app._server_proc is not None:
            messagebox.showinfo("提示", "服务已在运行")
            return

        host = self.host_var.get().strip() or "127.0.0.1"
        port = int(self.port_var.get().strip() or "8000")
        reload = self.reload_var.get()
        workers = 1 if reload else int(self.workers_var.get().strip() or "1")

        cmd: list[str] = [
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

        try:
            self.app._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
        except FileNotFoundError:
            messagebox.showerror("启动失败", "找不到 Python 或 uvicorn，请先执行 `uv sync`")
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


# ═══════════════════════════════════════════════════════════════
# Tab: 备份/恢复
# ═══════════════════════════════════════════════════════════════


class BackupTab(_BaseTab):
    @override
    def _build_layout(self) -> None:
        # 上半：备份
        back_frame = ttk.LabelFrame(self.frame, text="创建备份", padding=10)
        back_frame.pack(fill=tk.X)

        ttk.Label(back_frame, text="输出路径:").grid(row=0, column=0, sticky=tk.W)
        self.out_var = tk.StringVar()
        ttk.Entry(back_frame, textvariable=self.out_var, width=48).grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Button(back_frame, text="浏览", command=self._pick_output).grid(row=0, column=2, padx=4)

        ttk.Label(back_frame, text="模式:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.mode_var = tk.StringVar(value="auto")
        ttk.Combobox(
            back_frame,
            textvariable=self.mode_var,
            values=["auto", "native", "sqlalchemy"],
            width=14,
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.W, pady=(6, 0))

        self.no_uploads_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(back_frame, text="不包含附件 (uploads)", variable=self.no_uploads_var).grid(
            row=1, column=2, sticky=tk.W, pady=(6, 0)
        )

        ttk.Button(back_frame, text="立即备份", command=self.do_backup).grid(
            row=2, column=0, columnspan=3, pady=(10, 0), sticky=tk.E
        )

        # 中间：恢复
        rest_frame = ttk.LabelFrame(self.frame, text="从归档恢复", padding=10)
        rest_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(rest_frame, text="归档文件:").grid(row=0, column=0, sticky=tk.W)
        self.archive_var = tk.StringVar()
        ttk.Entry(rest_frame, textvariable=self.archive_var, width=48).grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Button(rest_frame, text="浏览", command=self._pick_archive).grid(row=0, column=2, padx=4)

        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(rest_frame, text="强制覆盖已有数据", variable=self.force_var).grid(
            row=1, column=1, sticky=tk.W, pady=(6, 0)
        )

        btn_row = ttk.Frame(rest_frame)
        btn_row.grid(row=2, column=0, columnspan=3, pady=(10, 0), sticky=tk.E)
        ttk.Button(btn_row, text="预演 (dry-run)", command=self.do_restore_dry_run).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="立即恢复", command=self.do_restore).pack(side=tk.LEFT)

        # 日志区
        log_frame = ttk.LabelFrame(self.frame, text="操作日志", padding=(4, 4))
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.log_text = self._build_log_text(log_frame)

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="备份输出路径",
            defaultextension=".tar.gz",
            filetypes=[("归档", "*.tar.gz"), ("全部", "*.*")],
        )
        if path:
            self.out_var.set(path)

    def _pick_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="选择备份归档",
            filetypes=[("归档", "*.tar.gz"), ("全部", "*.*")],
        )
        if path:
            self.archive_var.set(path)

    def do_backup(self) -> None:
        out = self.out_var.get().strip() or None
        mode = self.mode_var.get()
        include_uploads = not self.no_uploads_var.get()

        def _run() -> None:
            from cndb.backup import BackupError, create_backup

            try:
                path = Path(out).resolve() if out else None
                result = create_backup(output=path, mode=mode, include_uploads=include_uploads)
                print(f"[ok] 备份成功: {result}")
            except BackupError as exc:
                print(f"[error] {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"[error] 备份失败: {exc}", file=sys.stderr)

        run_in_thread(_run)

    def do_restore(self) -> None:
        archive = self.archive_var.get().strip()
        if not archive:
            messagebox.showwarning("缺少参数", "请先选择归档文件")
            return
        if not messagebox.askyesno("确认恢复", "恢复将覆盖现有数据，确认继续？"):
            return

        def _run() -> None:
            from cndb.restore import RestoreError, restore_backup

            try:
                restore_backup(Path(archive), force=self.force_var.get())
                print("[ok] 恢复完成")
            except RestoreError as exc:
                print(f"[error] {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"[error] 恢复失败: {exc}", file=sys.stderr)

        run_in_thread(_run)

    def do_restore_dry_run(self) -> None:
        archive = self.archive_var.get().strip()
        if not archive:
            messagebox.showwarning("缺少参数", "请先选择归档文件")
            return

        def _run() -> None:
            from cndb.restore import RestoreError, inspect_backup

            try:
                info = inspect_backup(Path(archive))
                print("[info] 归档有效")
                print(info.summary)
            except RestoreError as exc:
                print(f"[error] {exc}", file=sys.stderr)

        run_in_thread(_run)


# ═══════════════════════════════════════════════════════════════
# Tab: 用户管理
# ═══════════════════════════════════════════════════════════════


class UsersTab(_BaseTab):
    @override
    def _build_layout(self) -> None:
        # 子 Tab：create / list / delete / import
        sub = ttk.Notebook(self.frame)
        sub.pack(fill=tk.BOTH, expand=True)

        sub_create = ttk.Frame(sub, padding=8)
        sub_list = ttk.Frame(sub, padding=8)
        sub_delete = ttk.Frame(sub, padding=8)
        sub_import = ttk.Frame(sub, padding=8)
        sub.add(sub_create, text="创建")
        sub.add(sub_list, text="列表")
        sub.add(sub_delete, text="删除")
        sub.add(sub_import, text="导入")

        self._build_create(sub_create)
        self._build_list(sub_list)
        self._build_delete(sub_delete)
        self._build_import(sub_import)

        # 全局日志
        log_frame = ttk.LabelFrame(self.frame, text="操作日志", padding=(4, 4))
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.log_text = self._build_log_text(log_frame)

    # ── create ──
    def _build_create(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X)

        fields: list[tuple[str, str]] = [
            ("用户名 *", "username"),
            ("密码（留空自动生成）", "password"),
            ("邮箱", "email"),
            ("昵称", "nickname"),
        ]
        self.create_vars: dict[str, tk.StringVar] = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky=tk.W, padx=4, pady=4)
            var = tk.StringVar()
            self.create_vars[key] = var
            ttk.Entry(grid, textvariable=var, width=32).grid(row=i, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(grid, text="角色").grid(row=len(fields), column=0, sticky=tk.W, padx=4, pady=4)
        self.role_var = tk.StringVar(value="user")
        ttk.Combobox(
            grid,
            textvariable=self.role_var,
            values=["system_admin", "security_admin", "audit_admin", "user"],
            state="readonly",
            width=16,
        ).grid(row=len(fields), column=1, sticky=tk.W, padx=4, pady=4)

        self.su_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(grid, text="同时设为 superuser", variable=self.su_var).grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky=tk.W, padx=4, pady=4
        )

        ttk.Button(grid, text="创建用户", command=self._do_create).grid(
            row=len(fields) + 2, column=1, sticky=tk.E, padx=4, pady=(10, 0)
        )

    def _do_create(self) -> None:
        u = self.create_vars["username"].get().strip()
        if not u:
            messagebox.showwarning("缺少参数", "用户名必填")
            return

        args = argparse.Namespace(
            username=u,
            password=self.create_vars["password"].get().strip() or None,
            email=self.create_vars["email"].get().strip() or None,
            nickname=self.create_vars["nickname"].get().strip() or None,
            role=self.role_var.get(),
            is_superuser=self.su_var.get(),
        )

        def _run() -> None:
            from cndb.cli_users import cmd_create, print_create_result

            try:
                result = cmd_create(args)
                print_create_result(result)
            except SystemExit as exc:
                print(f"[error] {exc}", file=sys.stderr)

        run_in_thread(_run)

    # ── list ──
    def _build_list(self, parent: ttk.Frame) -> None:
        filter_row = ttk.Frame(parent)
        filter_row.pack(fill=tk.X)

        ttk.Label(filter_row, text="角色筛选:").pack(side=tk.LEFT)
        self.list_role_var = tk.StringVar(value="")
        ttk.Combobox(
            filter_row,
            textvariable=self.list_role_var,
            values=["", "system_admin", "security_admin", "audit_admin", "user"],
            state="readonly",
            width=16,
        ).pack(side=tk.LEFT, padx=4)

        self.list_active_var = tk.BooleanVar(value=False)
        self.list_inactive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_row, text="仅激活", variable=self.list_active_var).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(filter_row, text="仅停用", variable=self.list_inactive_var).pack(side=tk.LEFT, padx=4)

        ttk.Button(filter_row, text="查询", command=self._do_list).pack(side=tk.RIGHT)

        # 结果表
        cols = ("id", "username", "role", "nickname", "active", "superuser", "email")
        self.list_tree = ttk.Treeview(parent, columns=cols, show="headings", height=12)
        widths = {"id": 60, "username": 140, "role": 130, "nickname": 160, "active": 70, "superuser": 70, "email": 180}
        for c in cols:
            self.list_tree.heading(c, text=c)
            self.list_tree.column(c, width=widths[c], anchor=tk.W)
        self.list_tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    def _do_list(self) -> None:
        args = argparse.Namespace(
            role=self.list_role_var.get() or None,
            active=self.list_active_var.get(),
            inactive=self.list_inactive_var.get(),
        )

        def _run() -> None:
            from cndb.cli_users import cmd_list

            try:
                users = cmd_list(args)

                def _fill() -> None:
                    for item in self.list_tree.get_children():
                        self.list_tree.delete(item)
                    for u in users:
                        self.list_tree.insert(
                            "",
                            tk.END,
                            values=(
                                u.id,
                                u.username,
                                u.role,
                                u.nickname or "",
                                "yes" if u.is_active else "no",
                                "Y" if u.is_superuser else "",
                                u.email or "",
                            ),
                        )

                self.app.root.after(0, _fill)
            except SystemExit as exc:
                print(f"[error] {exc}", file=sys.stderr)

        run_in_thread(_run)

    # ── delete ──
    def _build_delete(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X)

        ttk.Label(grid, text="用户名或 ID").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.del_target_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.del_target_var, width=24).grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        self.del_cascade_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(grid, text="级联删除 OWNER 工作区", variable=self.del_cascade_var).grid(
            row=1, column=0, columnspan=2, sticky=tk.W, padx=4
        )

        btn_row = ttk.Frame(grid)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky=tk.E)
        ttk.Button(btn_row, text="安全检查", command=self._do_delete_check).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="删除", command=self._do_delete).pack(side=tk.LEFT)

    def _do_delete_check(self) -> None:
        target = self.del_target_var.get().strip()
        if not target:
            return
        args = argparse.Namespace(target=target)

        def _run() -> None:
            from cndb.cli_users import cmd_delete_check, print_delete_check

            check = cmd_delete_check(args)
            print_delete_check(check)

        run_in_thread(_run)

    def _do_delete(self) -> None:
        target = self.del_target_var.get().strip()
        if not target:
            return
        if not messagebox.askyesno("确认", f"确定删除用户 '{target}'？此操作不可逆。"):
            return
        args = argparse.Namespace(
            target=target,
            cascade=self.del_cascade_var.get(),
            yes=True,
        )

        def _run() -> None:
            from cndb.cli_users import cmd_delete, print_delete_result

            try:
                result = cmd_delete(args)
                print_delete_result(result)
            except SystemExit as exc:
                print(f"[error] {exc}", file=sys.stderr)

        run_in_thread(_run)

    # ── import ──
    def _build_import(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)

        ttk.Label(row, text="源文件 (.csv / .xlsx):").pack(side=tk.LEFT)
        self.import_file_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.import_file_var, width=48).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="浏览", command=self._pick_import_file).pack(side=tk.LEFT)

        self.import_dry_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="预演模式（只校验不写入，推荐先跑）", variable=self.import_dry_var).pack(
            anchor=tk.W, pady=4
        )
        ttk.Button(parent, text="执行导入", command=self._do_import).pack(anchor=tk.E)

    def _pick_import_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择用户数据文件",
            filetypes=[("表格", "*.csv *.xlsx *.xls"), ("全部", "*.*")],
        )
        if path:
            self.import_file_var.set(path)

    def _do_import(self) -> None:
        fp = self.import_file_var.get().strip()
        if not fp:
            messagebox.showwarning("缺少参数", "请选择源文件")
            return
        args = argparse.Namespace(file=fp, dry_run=self.import_dry_var.get())

        def _run() -> None:
            from cndb.cli_users import cmd_import, print_import_report

            try:
                report = cmd_import(args)
                print_import_report(report, Path(fp), dry_run=args.dry_run)
            except SystemExit as exc:
                print(f"[error] {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"[error] {exc}", file=sys.stderr)

        run_in_thread(_run)


# ═══════════════════════════════════════════════════════════════
# Tab: 演示数据
# ═══════════════════════════════════════════════════════════════


class SeedTab(_BaseTab):
    @override
    def _build_layout(self) -> None:
        top = ttk.Frame(self.frame)
        top.pack(fill=tk.X)

        ttk.Label(
            top,
            text="向数据库注入演示数据（会 drop_all 后重建，每次全新）:\n"
            "  • examples/datasets/* 各工作区 CSV + 视图\n"
            "  • 三员演示账号 admin / sec_admin / audit_admin + 普通用户 demo",
            foreground="#d4760a",
            justify=tk.LEFT,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(top, text="执行 seed", command=self.do_seed).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(self.frame, text="seed 日志", padding=(4, 4))
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.log_text = self._build_log_text(log_frame)

    def do_seed(self) -> None:
        if not messagebox.askyesno(
            "确认",
            "seed 会清空当前数据库再重建所有表和数据，\n若已部署，请先执行「备份恢复」创建备份。\n\n继续？",
        ):
            return

        def _run() -> None:
            from cndb.seed import seed

            try:
                seed(argparse.Namespace())
            except Exception as exc:
                print(f"[error] {exc}", file=sys.stderr)

        run_in_thread(_run)


# ═══════════════════════════════════════════════════════════════
# Tab: 系统信息
# ═══════════════════════════════════════════════════════════════


class InfoTab(_BaseTab):
    @override
    def _build_layout(self) -> None:
        top = ttk.Frame(self.frame)
        top.pack(fill=tk.X)
        ttk.Button(top, text="刷新", command=self.refresh).pack(side=tk.RIGHT)

        self.text = scrolledtext.ScrolledText(self.frame, wrap=tk.NONE, font=("Consolas", 10), state=tk.DISABLED)
        self.text.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    def refresh(self) -> None:
        import io
        import sys

        from cndb.runner import info_command

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            info_command()
        finally:
            sys.stdout = old

        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", buf.getvalue())
        self.text.configure(state=tk.DISABLED)


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

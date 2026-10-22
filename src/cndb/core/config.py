"""cndb 应用配置.

基于 pydantic-settings，支持从环境变量和 .env 文件加载。
所有字段均可通过环境变量覆盖（自动转换为大写+下划线风格）。

路径约定：
- BASE_DIR：代码/静态资源目录（只读），定位 pyproject.toml 或 alembic.ini。
- HOME_DIR: 用户主目录（~），全局持久化数据根目录。
- DATA_DIR：用户可写数据根目录（统一为 ~/.cndb）。
  支持通过环境变量 CNDB_DATA_DIR 整体覆盖（e2e 测试与用户数据隔离等场景），
  覆盖后其下所有子目录与默认 DATABASE_URL 一并切换。
  下分子目录职责：
  - CONFIG_DIR:  配置文件（.env 等）
  - DATABASE_DIR: SQLite 数据库文件
  - UPLOAD_DIR:  用户上传的附件（按 workspace_id 隔离）
  - PLUGINS_DIR: 插件自动发现目录
  - BACKUP_DIR:  备份归档默认输出目录
  - CACHE_DIR:   运行时缓存（临时文件、API 响应缓存等）
  - LOG_DIR:     日志文件
- STATIC_DIR:  前端静态资源（只读，指向包内 cndb/static）
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


def _find_project_root() -> Path:
    """从当前文件向上递归查找项目根目录.

    场景兼容：
    - 开发 editable install：src layout → 找到 pyproject.toml
    - wheel 安装：site-packages/cndb → 找不到 pyproject.toml，兜底到包父目录
    - fspack 打包：dist/src/src/cndb/core/ → 找不到 pyproject.toml，
      向上找 dist/src/（那里有 alembic.ini）
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    # 兜底策略：向上找第一个包含 alembic.ini 的目录
    # fspack 打包后 dist/src/ 会命中；wheel 安装时回退到 here.parent.parent
    for candidate in (here, *here.parents):
        if (candidate / "alembic.ini").is_file():
            return candidate
    return here.parent.parent


def _is_frozen() -> bool:
    """检测是否处于打包安装模式（非开发模式）.

    判断依据：BASE_DIR 下没有 pyproject.toml。
    - 开发模式：有 pyproject.toml → False
    - 打包安装（fspack/wheel）：无 pyproject.toml → True
    """
    return not (BASE_DIR / "pyproject.toml").is_file()


# ── 路径常量 ──────────────────────────────────────────────────

BASE_DIR = _find_project_root()
HOME_DIR = Path.home()

# cndb 包自身所在目录（core/ 的上一级）。与 BASE_DIR 语义不同：
# BASE_DIR 指向"项目根"（pyproject.toml / alembic.ini 所在处），
# _PACKAGE_DIR 指向"包目录"，静态资源永远随包分发，不随项目根移动。
_PACKAGE_DIR = Path(__file__).resolve().parent.parent

# 统一的用户数据根目录（跨平台一致，不再区分开发/打包模式）。
# 环境变量 CNDB_DATA_DIR 可整体覆盖（e2e 隔离等场景），子目录与默认
# DATABASE_URL 均由此派生，保证数据库/上传/日志等一并切换。
DATA_DIR = Path(os.environ.get("CNDB_DATA_DIR") or (HOME_DIR / ".cndb"))

# 子目录
CONFIG_DIR = DATA_DIR / "config"
DATABASE_DIR = DATA_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PLUGINS_DIR = DATA_DIR / "plugins"
BACKUP_DIR = DATA_DIR / "backups"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"

# 只读静态资源（前端打包产物）
#
# 必须从包目录（cndb/）推导，不能用 BASE_DIR：
#   - 开发模式：src/cndb/static
#   - wheel 安装：site-packages/cndb/static
#   - fspack 打包：dist/src/src/cndb/static
# BASE_DIR 在 wheel 模式下会被 _find_project_root() 兜底解析成 site-packages，
# 导致 STATIC_DIR 指向不存在的 site-packages/static（真实文件在其下的 cndb/ 里）。
# 该常量是 settings 的对外配置项，也是 CI 冒烟检查的断言对象 ——
# 解析错误会让"前端产物已打进 wheel"的校验变成假通过。
#
# 与 app.py 的 _STATIC、gui/checks.py 的 APP_STATIC_DIR 保持同一算法。
STATIC_DIR = _PACKAGE_DIR / "static"

# 首次启动时自动创建必要的可写目录（打包模式 / 开发模式均需创建）
for _d in (DATA_DIR, CONFIG_DIR, DATABASE_DIR, UPLOAD_DIR, PLUGINS_DIR, BACKUP_DIR, CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _get_version() -> str:
    """解析应用版本号.

    优先从 importlib.metadata 读取已安装分发的元数据（wheel / editable install
    的真实版本）；打包运行（fspack/Nuitka）未随包分发 ``cndb-*.dist-info``，
    该查询必然抛 PackageNotFoundError，此时回退到包内常量 ``cndb.__version__``
    ——它与 pyproject.toml 由 bump-my-version 同步维护，随源码/字节码一起分发。

    回归背景：旧实现在此处回退到硬编码占位串 ``"0.1.0.dev"``，于是打包版
    GUI 标题 / ``cndb info`` / ``/api/v1/system/about`` 一律报 0.1.0，
    与实际版本（0.4.9）不符。
    """
    try:
        return importlib.metadata.version("cndb")
    except importlib.metadata.PackageNotFoundError:
        import cndb

        return cndb.__version__


class Settings(BaseSettings):
    """应用配置，支持从环境变量和 .env 文件加载.

    所有字段均可通过环境变量覆盖，环境变量名 = 字段名的大写形式。
    例如：`DEBUG=false` 可覆盖默认值。

    路径约定：
    - BASE_DIR（代码/静态资源）→ 只读，指向 pyproject.toml / alembic.ini 所在目录
    - DATA_DIR（用户数据根）→ 可写，统一为 ~/.cndb
    - CONFIG_DIR / DATABASE_DIR / UPLOAD_DIR / PLUGINS_DIR / BACKUP_DIR / CACHE_DIR / LOG_DIR
      → 均为 DATA_DIR 的子目录，启动时自动创建
    - STATIC_DIR（前端静态资源）→ 只读，指向包内 cndb/static（随包分发）
    """

    APP_NAME: str = "cndb"
    APP_VERSION: str = _get_version()
    DEBUG: bool = True

    # 数据库配置（默认 SQLite，迁移到生产时可替换为 PostgreSQL/MySQL）
    # 同时接受 DATABASE_URL 与 CNDATABASE_URL 两种环境变量名。
    # 原因：compose / .env 模板 / 部署文档统一用 CNDB_ 前缀（与 CNDB_DATA_DIR 一致），
    # 而 pydantic-settings 默认按字段名取变量，只认 DATABASE_URL。
    # 若不加此alias，CNDATABASE_URL 会被静默忽略 —— 容器照常启动但始终连 SQLite，
    # 且日志无任何异常，属最难排查的一类配置陷阱。
    DATABASE_URL: str = Field(
        default=f"sqlite:///{DATABASE_DIR / 'cndb.db'}",
        validation_alias=AliasChoices("DATABASE_URL", "CNDATABASE_URL"),
        description="数据库连接串；CNDATABASE_URL 为兼容别名",
    )

    # CORS 配置（开发期放开 Vite 默认端口）
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    # 会话 / 授权生命周期：
    # - JWT_REFRESH_EXPIRE_DAYS：刷新令牌有效期（天）
    # - LOGIN_MAX_FAILURES / LOGIN_WINDOW_SECONDS：登录失败限流（进程内滑窗，单机足够）
    JWT_REFRESH_EXPIRE_DAYS: int = 30
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_WINDOW_SECONDS: int = 300

    # 导入任务单阶段超时（秒）：解析/校验/执行任一阶段超时即判失败并给出可读原因，
    # 避免"进度卡在 5% 且无报错"（历史上 WPS 导出文件的虚假行范围会触发）
    IMPORT_TASK_TIMEOUT_SECONDS: int = 600

    # 数据分析单次扫描行数上限（保护内存）：超出即 truncated，统计只覆盖扫到的行。
    # 时序表建议配合请求里的 filters（时间区间 / 标的等值）缩小扫描面，而不是直接调大这个值。
    ANALYTICS_MAX_SCAN_ROWS: int = 20000

    # 观测（core/observability.py）：
    # - ACCESS_LOG_ENABLED：是否记录每请求访问日志（慢请求无论开关都会记录）
    # - SLOW_REQUEST_MS：超过该耗时的请求按 WARNING 记录并标注 slow=true
    # - SLOW_QUERY_MS：超过该耗时的 SQL 按 WARNING 记录（只记语句，不记参数）
    ACCESS_LOG_ENABLED: bool = True
    SLOW_REQUEST_MS: int = 500
    SLOW_QUERY_MS: int = 200

    # ── 大模型能力平台（ADR 0020 P0）─────────────────────────
    # 单用户每分钟调用上限（进程内滑窗；多副本部署时按副本独立限流）
    LLM_CALLS_PER_MINUTE: int = 20
    # SSRF 白名单：显式放行的主机名（内网 / 本机模型网关），默认空 = 严格拦截；
    # 仅作用于大模型客户端，不影响数据源 / 导入的 SSRF 语义
    LLM_PRIVATE_HOST_ALLOWLIST: list[str] = []
    # llm_run 调用记录保留天数（`cndb llm prune` 使用；本期不自动清理）
    LLM_RUN_RETENTION_DAYS: int = 90

    # API 前缀
    API_V1_PREFIX: str = "/api/v1"
    # 运行时文件目录（全部位于 ~/.cndb 下）
    DATA_DIR: Path = DATA_DIR
    CONFIG_DIR: Path = CONFIG_DIR
    DATABASE_DIR: Path = DATABASE_DIR
    UPLOAD_DIR: Path = UPLOAD_DIR
    STATIC_DIR: Path = STATIC_DIR
    BACKUP_DIR: Path = BACKUP_DIR
    CACHE_DIR: Path = CACHE_DIR
    LOG_DIR: Path = LOG_DIR

    # ── 认证授权（bcrypt/python-jose 已在主依赖中，始终可用）─────────
    JWT_SECRET: str = "cndb-dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 默认 24 小时
    AUTH_ENABLED: bool = True  # 默认开启，生产环境必须认证

    # 字段级加密密钥（凭证会话的 secrets 列，见 core/crypto.py）：
    # 留空则回退到 JWT_SECRET 派生 —— 单独配置可让「换 JWT 密钥」不等于「全部密文失效」。
    # 注意：一旦有密文入库，**改这个值会让已有密文无法解密**，需重新保存会话密钥。
    DATASOURCE_SECRET_KEY: str = ""

    # 单机模式（仅本地单机使用）：免登录自动映射内置本地用户；
    # 强制仅回环绑定（127.0.0.1/localhost/::1，各启动入口校验）；
    # 模式内禁用注册/登录/公开分享。
    # 与 AUTH_ENABLED 无关：LOCAL_MODE 下认证依赖直接返回本地用户。
    LOCAL_MODE: bool = Field(
        default=False,
        validation_alias=AliasChoices("LOCAL_MODE", "CNDB_LOCAL_MODE"),
        description="单机模式开关；关闭时行为与多用户网络模式完全一致",
    )

    # ── 插件自动发现目录 ─────────────────────────────────────
    PLUGINS_AUTO_DISCOVER: bool = True
    PLUGINS_DIR: Path = PLUGINS_DIR

    # ── 配置文件加载 ─────────────────────────────────────
    model_config = {"env_file": str(CONFIG_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()

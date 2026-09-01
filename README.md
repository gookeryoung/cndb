# cndb

> 通用数据库管理平台。

[![PyPI](https://img.shields.io/pypi/v/cndb)](https://pypi.org/project/cndb/)
[![CI](https://github.com/gookeryoung/cndb/actions/workflows/ci.yml/badge.svg)](https://github.com/gookeryoung/cndb/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Coverage](https://img.shields.io/badge/coverage-%E2%89%A595%25-brightgreen.svg)

## 特性

- **技术栈**：Django 5.2 + DRF + PostgreSQL（开发/测试可用 SQLite）
- **元数据驱动**：数据表/字段定义存元数据库，字段类型系统插件式扩展
- **工作区隔离**：用户/工作区/成员角色（owner/admin/editor/commenter/viewer）
- **构建工具链**：hatchling + uv + ruff + pyrefly + pytest + coverage（覆盖率阈值 95%）
- **CI/CD**：GitHub Actions（lint + typecheck + 多版本测试）

## 快速上手

```bash
# 安装依赖（开发环境默认 SQLite）
uv sync --extra dev

# 初始化数据库并启动开发服务器
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

REST API 入口：`/api/auth/`、`/api/workspaces/`，管理后台：`/admin/`。

切换 PostgreSQL：设置 `CNDB_DB=postgres` 及 `CNDB_DB_NAME/CNDB_DB_USER/CNDB_DB_PASSWORD` 等环境变量。

## 开发

```bash
# 安装开发依赖
uv sync --extra dev

# 运行测试（含覆盖率，阈值 95%）
uv run pytest -m "not slow" --cov=cndb --cov-fail-under=95

# 类型检查
uv run pyrefly check .

# 代码风格
uv run ruff check src tests
uv run ruff format --check src tests
```

### Make 快捷命令

项目提供 Makefile 封装常用操作，运行 `make help` 查看全部命令：

```bash
make sync     # 安装开发依赖
make check    # 全套门禁 (lint + typecheck + cov)
make build    # 构建分发包
make clean    # 清理构建产物
make bump PART=patch  # 版本号 bump
```


## 文档

文档由 Sphinx 构建，托管在 ReadTheDocs：

```bash
# 本地构建文档
make doc
```


## 多版本测试

使用 tox 在多个 Python 版本（py311, py312, py313, py314）下运行测试：

```bash
make tox
```

## 许可证

MIT

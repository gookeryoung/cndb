# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.12] — 未发布

### 移除

- 空壳包 `cndb.services` / `cndb.schemas`（模板脚手架遗留，无任何引用）
- Sphinx 文档骨架 `docs/` 与 `.readthedocs.yaml`、pyproject `docs` extra（文档入口以 FastAPI `/docs` 为准）
- `tox.ini` 与 Makefile `tox` / `doc` / `check-fast-par` 死目标（门禁统一由 `make check` 承载）

### 变更

- `httpx` 从运行时依赖移至 `test` extra（源码仅使用 `httpx2`；httpx 仅供 starlette TestClient 测试使用）
- 显式声明 `requests` 运行时依赖（wechat_auth 插件实际使用，此前靠 docs extra 的 sphinx 传递引入）
- ruff/pyrefly 配置收敛：移除不存在目录的排除项，修正 UP045 注释中的 typer 表述（CLI 实际用 argparse）

### 修复

- `docker-compose.yml` 源码部署构建上下文 `context: ..` → `context: .`（compose 文件位于仓库根目录）
- README 失实内容：npm → pnpm、`make bench` 改为脚本调用、移除不存在的 `.env.example` 指引、项目结构树对齐实际目录

> 注：历史条目止于 0.1.2，0.1.3–0.1.11 未回填。

## [0.1.2] — 2026-09-11

### 新增

- **Playwright E2E 测试**：smoke（登录 → Grid → 退出）+ critical（行 CRUD 全链路），配置见 `frontend/playwright.config.ts`
- **生产部署定型**：多阶段 `deploy/Dockerfile`（前端构建 + uvicorn）+ `deploy/nginx.conf` 反代 + `docker-compose.yml` 生产编排（SQLite/PostgreSQL 双形态）
- **示例数据集**：`examples/datasets/` 5 个 CSV（学生成绩 / 电商销售 / 房价预测 / 客户流失 / 气温天气）
- **`.env.example`**：部署环境变量模板

### 变更

- docker-compose.yml 从开发形态更新为生产形态（nginx 入口 + app 容器 + pg profile）
- `.gitignore` 添加 Playwright 产物目录

## [0.1.1] — 2026-09-11

### 新增

- 前端完成 F1–F9：登录注册 / 工作区 / Grid inline 编辑 / 视图 Tab / 导入导出 / 成员管理 / 主题切换 / 关系图 / 报表 / 公开分享页
- SPA fallback：`app.py` 中间件自动处理前端路由回退
- 前端构建产物挂载到 `src/cndb/static/`，uvicorn 统一提供

### 变更

- RowResponse 类型对齐后端扁平结构（移除嵌套 values 字段）

## [0.1.0] — 2026-09-10

### 新增

- 后端 P0–P4 完成：框架基础 + 6 插件 + 95%+ 测试覆盖率
- 插件架构：accounts / workspaces / tables / reports / health
- 动态数据表：SQLAlchemy Core 运行时 DDL
- link 字段多对多存储与查询
- 审计日志 + 回收站闭环
- 字段类型补齐至 11 种

# cndb

> 通用数据库管理平台。

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A595%25-brightgreen.svg)](#开发)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#许可证)

## 特性

- **插件化架构**：accounts / workspaces / tables / reports / health，可独立部署
- **动态数据表**：SQLAlchemy Core 运行时建表 / 改字段，运行中即可扩 schema
- **多维字段类型**：text / longtext / number / float / boolean / date / datetime / select / multiselect / link（跨表关联）
- **行级协作**：编辑评论 / 审计日志 / 回收站 / 公开分享
- **link 字段关系图**：`GET /workspaces/{id}/tables/graph` 返回所有表间依赖
- **异步导入**：CSV / JSON / XLSX 异步导入 + 进度轮询
- **Jinja2 报告模板**：沙箱环境，绑定表的模板直接出 Word/PDF
- **权限体系**：viewer / editor / admin / owner 四级，表级 + 工作区级双重校验

## 快速上手

```bash
# 克隆 + 依赖
uv sync --extra dev

# 建表 + 注入演示数据
uv run python -m cndb.seed

# 启动服务（默认 http://localhost:8000）
uv run cndb serve

# 登录账号：demo / demo1234
# 然后用 Postman / curl 或前端调用 API
```

### Docker 部署（生产形态）

本项目提供两种 Docker 部署方案，按需选择：

#### 方案一：Wheel 部署（推荐，单容器精简）

先在本地或 CI 构建 wheel 包（前端 + 后端一并打包），Docker 仅做安装：

```bash
# 1. 构建 wheel（含前端静态 + 后端代码 + seed 数据）
make build

# 2. 构建镜像并启动（SQLite 零配置）
docker compose -f docker-compose.wheel.yml up -d --build

# 3. 注入演示数据（首次启动可选）
docker compose -f docker-compose.wheel.yml exec app cndb seed
```

入口为 `http://localhost:8000`，FastAPI 直接托管前端静态资源，无需额外 nginx 容器。

使用 PostgreSQL：

```bash
# 带 PostgreSQL 容器启动（可选 profile）
docker compose -f docker-compose.wheel.yml --profile pg up -d --build
docker compose -f docker-compose.wheel.yml exec app cndb seed
```

自定义端口 / 数据库密码（编辑 `.env`）：

```env
CNDB_PORT=9000
CNDATABASE_URL=sqlite:////data/cndb.db
# 或 PostgreSQL：
# CNDATABASE_URL=postgresql+psycopg://cndb:your_pass@postgres:5432/cndb
CNDB_DB_PASSWORD=your_pass
```

#### 方案二：源码部署（双容器 + Nginx 反代）

适合需要 nginx 的 gzip/缓存/SSL 的生产场景，Docker 内部完成前端构建：

```bash
# SQLite 快速启动：nginx:80 → app:8000
docker compose up -d --build

# PostgreSQL（可选 profile）
docker compose --profile pg up -d --build

# 注入演示数据
docker compose exec app uv run cndb seed
```

入口为 `http://localhost`（nginx 80 端口），动态请求转发 uvicorn。

#### 两种方案对比

| | Wheel 部署 | 源码部署 |
|---|---|---|
| 前置步骤 | `make build` 构建 wheel | 无（Docker 内自动构建） |
| 容器数量 | 1（仅 app） | 2（app + nginx） |
| 构建速度 | 快（wheel 直接安装） | 慢（含 node 前端构建） |
| 镜像体积 | 小 | 较大（含 nginx） |
| nginx 特性 | 无 | 有（gzip / 缓存 / SSL） |
| 适用场景 | 快速上线、单机部署 | 需要 nginx 高级特性 |

#### 常用运维命令

```bash
# 查看容器状态与日志
docker compose -f docker-compose.wheel.yml ps
docker compose -f docker-compose.wheel.yml logs -f

# 数据库迁移 / 初始化数据
docker compose -f docker-compose.wheel.yml exec app cndb seed

# 停止并保留数据卷
docker compose -f docker-compose.wheel.yml down

# 停止并清除全部（含数据卷，谨慎使用）
docker compose -f docker-compose.wheel.yml down -v

# 更新版本（重新 build wheel → 重新构建镜像 → 重启）
make build
docker compose -f docker-compose.wheel.yml up -d --build
```

### 前端开发

```bash
cd frontend
pnpm install
pnpm dev       # Vite dev server（默认 http://localhost:5173，代理到后端 8000）
pnpm build     # 构建到 src/cndb/static/（后端自动挂载）
```

### E2E 测试（Playwright）

```bash
# 1. 启动后端 + 注入数据
uv run cndb serve --host 127.0.0.1 --port 8000  # 后台运行
uv run cndb seed

# 2. 安装 Playwright 浏览器
cd frontend && npx playwright install chromium

# 3. 运行测试
npm run e2e:setup       # 一次登录 → 持久化 StorageState
npm run e2e:smoke       # smoke 测试（登录 → Grid → 退出）
npm run e2e:critical    # critical 测试（行 CRUD 全链路）
npm run e2e             # 全部
```

## 项目结构

```
src/cndb/
├── api/              # 认证依赖 (get_current_user)
├── core/             # 配置 / 数据库 / 安全 / 健康检查 (system_api.py)
├── plugins/
│   ├── accounts/     # 用户注册 / 登录 / JWT
│   ├── workspaces/   # 工作区 + 成员 + 角色
│   ├── tables/       # 动态表 / 字段 / 记录 / DDL / 查询
│   ├── reports/      # 报告模板 (Jinja2 sandbox)
│   └── wechat_auth/  # 微信登录
├── seed.py           # 演示数据注入（幂等）
└── runner.py         # 启动入口 `cndb serve`
```

## API 概览

| 模块 | 前缀 | 说明 |
|------|------|------|
| 认证 | `/api/v1/accounts/auth` | register / login / me |
| 工作区 | `/api/v1/workspaces` | CRUD + 成员管理 |
| 表 | `/api/v1/workspaces/{wid}/tables` | CRUD / reorder / graph / copy / move |
| 字段 | `/api/v1/workspaces/{wid}/tables/{tid}/fields` | CRUD |
| 记录 | `/api/v1/workspaces/{wid}/tables/{tid}/records` | CRUD + filter + sort |
| 批量 | `/api/v1/workspaces/{wid}/tables/{tid}/bulk` | batch upsert / delete |
| 导入 | `/api/v1/workspaces/{wid}/tables/{tid}/import` | 同步 / 异步 CSV·JSON·XLSX |
| 视图 | `/api/v1/workspaces/{wid}/tables/{tid}/views` | 保存筛选条件命名视图 |
| 权限 | `/api/v1/workspaces/{wid}/tables/{tid}/permissions` | 表级权限 |
| 分享 | `/api/v1/tables/{tid}/share` | 匿名公开分享 |
| 报告 | `/api/v1/reports` | 模板 CRUD + 渲染 |
| 健康 | `/health` | 服务存活 |

完整文档：启动后访问 `http://localhost:8000/docs`（FastAPI 自动生成）

## 开发

```bash
make sync          # 安装依赖
make check         # 全套门禁：lint + typecheck + cov
make push          # 推送全部 remote
```

性能基准（10k 行导入 + 查询）：

```bash
uv run python scripts/bench_10k_rows.py
```

覆盖门禁阈值 95%，任何 PR 低于该值自动拒绝。

## 许可证

MIT — 见 [LICENSE](LICENSE)

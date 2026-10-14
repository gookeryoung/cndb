# cndb

> 通用数据管理平台。

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A595%25-brightgreen.svg)](#开发)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#许可证)

## 特性

- **插件化架构**：accounts / workspaces / tables / documents / issues / change_requests，可独立部署
- **动态数据表**：SQLAlchemy Core 运行时建表 / 改字段，运行中即可扩 schema
- **17 种字段类型**：text / longtext / email / url / phone / json / number / float / percentage / boolean / date / datetime / timestamp / select / multiselect / link（跨表关联）/ attachment
- **7 种视图**：表格（Grid）/ 看板 / 日历 / 甘特图 / WBS / 矩阵 / 图表，视图级筛选、排序、字段显隐与配置持久化
- **文档管理**：工作区 Markdown 文档树、双向链接 `[[标题]]`、数据表动态引用 `{{table:表名}}`、版本历史与全文检索、回收站与恢复、断链检测与修复
- **行级协作**：编辑评论 / 审计日志 / 回收站 / 公开分享
- **link 字段关系图**：`GET /workspaces/{id}/tables/graph` 返回所有表间依赖
- **异步导入**：CSV / JSON / XLSX / API 抓取异步导入 + 进度轮询
- **Jinja2 报告模板**：沙箱环境，绑定表的模板直接出 Word / PDF / Excel / HTML
- **权限体系**：工作区三级角色 owner / editor / viewer，叠加全局角色（system_admin / security_admin / audit_admin / 超级管理员），表级 + 工作区级双重校验
- **备份恢复**：`cndb backup` / `cndb restore` 全库归档（.tar.gz），跨机器迁移
- **桌面 GUI**：`cndbw` 启动 Tkinter 管理面板（启动服务 / 备份恢复 / Windows 后台服务管理）

## 快速上手

```bash
# 克隆 + 依赖
uv sync --extra dev

# 建表 + 注入演示数据（含典型数据表 / 视图 / 文档，幂等）
uv run cndb seed

# 启动服务（默认绑定 0.0.0.0，http://localhost:8000）
uv run cndb serve

# 登录账号：demo / demo1234
# 浏览器访问 http://localhost:8000 即用前端界面，或用 Postman / curl 调用 API
```

### Docker 部署（生产形态）

打 tag 触发：CI 同步构建产物到服务器，服务器本地构建镜像并部署，失败自动回滚（镜像不经 COS/仓库中转）。

```bash
git tag v0.3.1 && git push origin v0.3.1    # 同步产物 → 服务器构建 → 自动部署
```

部署链路、服务器准备、TCR 凭证配置、定时备份与 PostgreSQL 迁移：
详见 **[docs/DEPLOY_TENCENT.md](docs/DEPLOY_TENCENT.md)**。

相关文件：

| 文件 | 作用 |
|---|---|
| `docker-compose.prod.yml` | 生产编排（单容器 + 数据卷 + 日志轮转） |
| `deploy/Dockerfile.prod` | 生产镜像（预授权数据目录 + 健康检查 + 中文字体） |
| `deploy/deploy.sh` | 服务器端部署（本地构建 / 预备份 / 健康探测 / 失败回滚） |
| `deploy/backup.sh` | 定时备份，可选上传 COS |
| `deploy/.env.prod.example` | 生产环境变量模板 |
| `.github/workflows/deploy-tencent.yml` | tag 触发的同步产物与部署流水线 |

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
cd frontend && pnpm exec playwright install chromium

# 3. 运行测试
pnpm e2e:setup       # 一次登录 → 持久化 StorageState
pnpm e2e:smoke       # smoke 测试（登录 → Grid → 退出）
pnpm e2e:critical    # critical 测试（行 CRUD 全链路）
pnpm e2e             # 全部
```

## 项目结构

```
src/cndb/
├── api/              # 认证依赖 (get_current_user)
├── alembic/          # 数据库迁移脚本
├── cli/              # 命令行入口
│   ├── main.py       #   cndb 主命令（serve/dev/build/info）
│   ├── seed.py       #   演示数据注入（幂等）
│   ├── backup.py     #   备份（.tar.gz 归档）
│   ├── restore.py    #   恢复
│   ├── users.py      #   用户管理
│   └── service.py    #   Windows 后台服务
├── core/             # 配置 / 数据库 / 安全 / 健康检查 (system_api.py)
├── gui/              # Tkinter 桌面管理面板（`cndbw` 入口）
├── models/           # SQLAlchemy 声明式基类
├── plugins/
│   ├── accounts/     # 用户注册 / 登录 / JWT
│   ├── workspaces/   # 工作区 + 成员 + 角色
│   ├── tables/       # 动态表 / 字段 / 记录 / DDL / 查询 / 视图
│   ├── documents/    # 文档树 / 版本 / 标签 / 分享 / 全文检索 / Word·PDF·Markdown 导出
│   ├── issues/       # 数据表级问题反馈 + 评论/状态流水
│   └── change_requests/ # 表级变更申请（双轨制写入的载体）
├── app.py            # FastAPI 应用装配 + SPA 静态托管
└── static/           # 前端构建产物（pnpm build 输出，同源托管）
```

## CLI 命令

`cndb --help` 查看全部子命令：

| 命令 | 说明 |
|------|------|
| `cndb serve` | 启动 uvicorn 服务器（默认绑定 0.0.0.0，`--host 127.0.0.1` 仅本机） |
| `cndb dev` | 开发模式：同时启动前后端 |
| `cndb build` | 构建前后端（需源码目录） |
| `cndb info` | 打印版本 / 配置 / 运行环境 |
| `cndb seed` | 注入演示数据（幂等） |
| `cndb backup` | 备份数据库和附件为 .tar.gz 归档或文件夹 |
| `cndb restore` | 从归档或文件夹恢复（自动识别源类型） |
| `cndb users` | 用户管理（create / delete / list / import） |
| `cndb service` | Windows 开机自启后台服务（enable / disable / status / stop / run） |
| `cndb docs` | 文档数据运维：`gc` 外存孤儿文件体检与回收（默认 dry-run，`--apply` 删除，`--json` 输出） |
| `cndbw` | 启动 Tkinter 桌面管理面板 |

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
| 文档导出 | `/api/v1/workspaces/{wid}/documents/{doc_id}/export` | Markdown / Word / PDF 文件下载 |
| 健康 | `/health` | 服务存活 |

完整文档：启动后访问 `http://localhost:8000/docs`（FastAPI 自动生成）

## 开发

```bash
make sync          # 安装依赖
make seed          # 注入演示数据（幂等）
make dev           # 开发模式：同时启动后端 8772 + 前端 5173（Ctrl+C 一起停）
make check         # 全套门禁：lint + typecheck + cov
make push          # 推送全部 remote
```

`make dev` 支持覆盖绑定地址与后端端口：`make dev DEV_HOST=127.0.0.1 DEV_PORT=8000`。

性能基准（10k 行导入 + 查询）：

```bash
uv run python scripts/bench_10k_rows.py
```

覆盖门禁阈值 95%，任何 PR 低于该值自动拒绝。

## 许可证

MIT — 见 [LICENSE](LICENSE)

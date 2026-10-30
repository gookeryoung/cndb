# 晶格协同 CNDB（cndb）

> 晶格协同 —— 通用数据管理平台。数据如晶格般规整排列、彼此关联。

[![Python](https://img.shields.io/badge/python-3.12%E2%80%933.14-blue.svg)](https://www.python.org)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A595%25-brightgreen.svg)](#开发)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#许可证)

> **Python 支持矩阵**：3.12 ~ 3.14。其中 Windows 仅 3.12（Win7/8 兼容的依赖钉版只在该版本验证）；Linux / macOS 无平台钉版。

> **浏览器基线**：Chrome / Edge **81+**（Chromium 81+ 内核；360、QQ 等按内核版本对齐）。不承诺 Firefox / Safari。
> 构建目标、静态门禁与老内核冒烟共用同一常量（`frontend/scripts/browser-baseline.mjs`），口径见 [ADR 0026](docs/adr/0026-chrome81-compat.md)。
> 注意：前端栈为 React 19 + antd 6（[ADR 0074](docs/adr/0074-react19-antd6-upgrade.md)），两者官方仅承诺现代浏览器；Chrome 81 兼容由本仓库自有兼容层（`StyleProvider` 降级 / polyfill / flex-gap shim）+ 定时真机冒烟保障，antd 6 小版本升级须重跑冒烟。

## 特性

- **插件化架构**：accounts / workspaces / tables / documents / issues / change_requests / analytics / files，可独立部署
- **动态数据表**：SQLAlchemy Core 运行时建表 / 改字段，运行中即可扩 schema
- **19 种字段类型**：text / longtext / email / url / phone / json / number / float / percentage / boolean / date / datetime / timestamp / select / multiselect / link（跨表关联）/ lookup（跨表引用）/ attachment / image
- **9 种视图**：表格（Grid）/ 树形（Tree）/ 看板 / 日历 / 甘特图 / WBS / 矩阵 / 图表 / 流程（Flow），视图级筛选、排序、字段显隐与配置持久化
- **文档管理**：工作区 Markdown 文档树、双向链接 `[[标题]]`、数据表动态引用 `{{table:表名}}`、版本历史与全文检索、回收站与恢复、断链检测与修复、**Obsidian 文档库导入 / 导出**（目录层级 + front-matter 标签 + 附件互转 + 双链锚点/别名保真 + Canvas/Base 转文档）
- **行级协作**：编辑评论 / 审计日志 / 回收站
- **link 字段关系图**：`GET /workspaces/{id}/tables/graph` 返回所有表间依赖
- **异步导入**：CSV / JSON / XLSX / API 抓取异步导入 + 进度轮询
- **数据分析**：工作区级分析模板（公式引擎 + 图表 + 分组汇总/透视）与字段智能推荐，一键生成典型分析示例
- **权限体系**：工作区三级角色 owner / editor / viewer，叠加全局角色（system_admin / security_admin / audit_admin / 超级管理员），表级 + 工作区级双重校验
- **工作区类型**：新增与修改时可选 数据 + 文档（默认）/ 数据 / 文档 三类，按类型开放数据表、数据分析与文档功能（仅数据隐藏文档、仅文档隐藏数据表与数据分析）
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

#### 离线打包与部署（无外网隔离环境）

服务器无法访问 Docker Hub / PyPI / TCR 时，改用「本地构建 → 导出交付包 → 离线加载」三段式，
镜像全程不经网络：

```bash
# ① 联网构建机：构建镜像（版本默认取 pyproject，输出本地名 cndb:<version>）
make docker-build VERSION=0.4.11

# ② 导出离线交付包 → dist/offline/cndb-0.4.11-offline-bundle.tar.gz
make docker-export VERSION=0.4.11
#   不需要 nginx 反代镜像时：WITH_NGINX=0 bash deploy/export-image.sh 0.4.11

# ③ 传到离线服务器 → 解包 → 校验 → 加载并部署
tar -xzf cndb-0.4.11-offline-bundle.tar.gz && cd cndb-0.4.11-offline
sha256sum -c SHA256SUMS               # 校验镜像 tar / 编排文件完整性
cp deploy/.env.prod.example .env      # CNDB_IMAGE=cndb:0.4.11；JWT_SECRET=openssl rand -hex 32
OFFLINE=1 ./deploy/deploy.sh 0.4.11   # sha256sum -c → docker load → 预备份 → 重建 → 健康探测 → 失败回滚
```

交付包内容：应用镜像 tar、nginx 镜像 tar（`WITH_NGINX=1` 时）、`docker-compose.prod.yml`、
`deploy/` 脚本与 `.env` 模板、`SHA256SUMS`、包内 `OFFLINE-README.txt`。

注意：镜像限构建机架构（跨架构须在目标架构机上重新执行 `docker-build` + `docker-export`）；
`deploy/*.sh` 以 644 入库，本地用 `bash deploy/xxx.sh`（或 `make docker-*`）调用，交付包内已补执行位可直接 `./deploy/...`。

完整链路（服务器准备、TCR 凭证、反代与 HTTPS、`OFFLINE_DIR` 等）见
[docs/DEPLOY_TENCENT.md](docs/DEPLOY_TENCENT.md) 第八节「离线部署」。

相关文件：

| 文件 | 作用 |
|---|---|
| `docker-compose.prod.yml` | 生产编排（单容器 / 可选 nginx 反代 + 数据卷 + 日志轮转） |
| `docker-compose.dev.yml` | 开发编排（容器内全栈热重载，`make docker-dev` 使用） |
| `deploy/Dockerfile.base` | 依赖基础镜像（系统字体 + 锁定依赖，按指纹复用） |
| `deploy/Dockerfile.prod` | 应用镜像（基于依赖基础镜像，只装 wheel） |
| `deploy/Dockerfile.dev` | 开发镜像（只装依赖，源码运行时 bind mount，热重载） |
| `deploy/deploy.sh` | 服务器端部署（依赖镜像复用/构建 / 预备份 / 健康探测 / 失败回滚；`OFFLINE=1` 为离线模式） |
| `deploy/build-image.sh` | 本地构建镜像（联网机执行，供离线导出；复用同一 Dockerfile 与依赖指纹） |
| `deploy/export-image.sh` | 导出离线交付包（应用/nginx 镜像 tar + compose + deploy 脚本 + .env 模板 + SHA256SUMS） |
| `deploy/backup.sh` | 定时备份，可选上传 COS |
| `deploy/.env.prod.example` | 生产环境变量模板 |
| `deploy/nginx/` | 内置反向代理配置（模板 + HTTP/HTTPS 共用片段 + 可选扩展） |
| `.github/workflows/deploy-tencent.yml` | 部署流水线（由 Release 在 pypi 成功后调用，也可手动触发） |

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
│   ├── main.py       #   cndb 主命令分发（serve/dev/build/info/seed/backup/restore/users/docs/views）
│   ├── seed/         #   演示数据注入（幂等，按职责拆分）
│   ├── restore/      #   恢复（自动识别 .tar.gz 归档 / 文件夹）
│   ├── users/        #   用户管理（create / delete / list / import）
│   ├── backup.py     #   备份（.tar.gz 归档）
│   ├── docs.py       #   文档数据运维（gc：外存孤儿文件体检与回收）
│   ├── views.py      #   视图运维（prune-orphans：孤儿视图体检与回收）
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
│   ├── change_requests/ # 表级变更申请（双轨制写入的载体）
│   ├── analytics/    # 工作区分析：公式引擎 / 图表 / 分组汇总 / 字段智能推荐
│   └── files/        # 附件 / 图片存储与缩略图
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
| `cndb views` | 视图运维：`prune-orphans` 孤儿视图体检与回收（默认 dry-run，`--apply` 删除，`--workspace` 必填、`--table` 可选） |
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
| 视图 | `/api/v1/workspaces/{wid}/tables/{tid}/views` | 保存筛选条件命名视图 + 可见性三档（`table`/`shared`/`private`）与共享名单 |
| 权限 | `/api/v1/workspaces/{wid}/tables/{tid}/permissions` | 表级权限 |
| 修改申请 | `/api/v1/workspaces/{wid}/tables/{tid}/change-requests` | 表级修改申请（双轨制写入载体） |
| 问题 | `/api/v1/workspaces/{wid}/tables/{tid}/issues` | 数据表级问题反馈 + 评论/状态流水 |
| 文档 | `/api/v1/workspaces/{wid}/documents` | 文档树 / 正文 / 版本 / 个人草稿 / 全文检索 / 分享 / 标签 |
| 文档修改申请 | `/api/v1/workspaces/{wid}/document-change-requests` | 文档级修改申请（列表 / 详情 / merge / close / update-base） |
| 文档问题 | `/api/v1/workspaces/{wid}/document-issues` | 文档级问题清单 + 评论/状态流水 |
| 文档导出 | `/api/v1/workspaces/{wid}/documents/{doc_id}/export` | Markdown / Word / PDF 文件下载 |
| Obsidian 库 | `/api/v1/workspaces/{wid}/documents/import[/analyze]`、`/documents/export/vault` | 库 zip 导入（预览 → 落库）/ 整库导出 |
| 分析 | `/api/v1/workspaces/{wid}/analytics` | 分析模板 / 运行 / 字段智能推荐 |
| 健康 | `/health` | 服务存活 |

完整文档：启动后访问 `http://localhost:8000/docs`（FastAPI 自动生成）

## 开发

```bash
make help          # 查看全部目标
make sync          # 安装后端依赖 + pre-commit 钩子（前端依赖由 dev / 前端目标按需自动安装）
make seed          # 注入演示数据（幂等）
make dev           # 开发模式：同时启动后端 8772 + 前端 5173（Ctrl+C 一起停）
make docker-dev    # Docker 开发模式：容器内跑同样的前后端（源码挂载 + 热重载）
make docker-dev-down  # 停止 Docker 开发模式（保留数据卷）
make check-fast    # 轻量静态门禁：gitkeep + ADR + ruff + pyrefly + tsc/eslint（实现期内环）
make flow          # 代码改动门禁：check-fast + 全量后端测试
make check         # 全套门禁：并行跑 lint / 类型 / 前端静态 + 覆盖率 / 后端 cov
make push          # 推送全部 remote（含 tags）
```

`make dev` 支持覆盖绑定地址与后端端口：`make dev DEV_HOST=127.0.0.1 DEV_PORT=8000`。

`make docker-dev` 用 [docker-compose.dev.yml](docker-compose.dev.yml) 在容器内起后端（uvicorn `--reload`，:8772）
与前端（Vite，:5173）—— 仓库根 bind mount 进容器，改源码即热更，适合本机未装 Python / Node
或想隔离运行环境的场景。开发数据落独立命名卷 `cndb-dev-data`（不碰宿主 `~/.cndb`），前端依赖落
`cndb-dev-node-modules` 卷（容器重建不重复下载）。容器内需要演示数据时：
`docker compose -f docker-compose.dev.yml exec backend cndb seed`。

镜像构建源由 `deploy/docker-sources.sh` 统一解析，`make docker-build` / `docker-dev` / `docker-export`
共用同一 profile：

```bash
# 本机 / CodeUp / 腾讯服务器：默认 cn（无需额外配置）
#   ｜基础镜像 docker.m.daocloud.io ｜apt 腾讯云 ｜pip+uv 腾讯云 PyPI ｜pnpm npmmirror ｜
make docker-dev

# GitHub Actions / 海外机器：自动 global（GITHUB_ACTIONS=true），也可显式指定
CNDB_SOURCES=global make docker-dev
CNDB_SOURCES=cn make docker-build

# 单项覆盖仍生效，优先级高于 profile（显式空串 = 用官方源）
CNDB_APT_MIRROR= \
CNDB_PIP_INDEX=https://pypi.org/simple \
CNDB_UV_INDEX=https://pypi.org/simple \
CNDB_PYTHON_IMAGE=python:3.12-slim \
CNDB_NODE_IMAGE=node:22-alpine \
CNDB_NPM_REGISTRY=https://registry.npmjs.org/ \
make docker-dev
```

GitHub workflow（CI / Release）已置 `CNDB_SOURCES=global`；腾讯部署 workflow 与 CodeUp
流水线给 TAT 命令显式写 `CNDB_SOURCES=cn`，不会把 runner 的海外源带到服务器。
基础镜像构建失败时会用官方源整体重试一次，日志会打印实际 profile。

WSL2 等环境下 Docker 会把宿主解析器（如 `10.255.255.254`）拷进容器，该地址在容器网络内
不可达，`pnpm` / corepack 拉包会报 `dns error`；`docker-compose.dev.yml` 默认给前后端容器
注入公共解析器（`223.5.5.5` / `119.29.29.29`），可覆盖：

```bash
CNDB_DNS_PRIMARY=1.1.1.1 CNDB_DNS_SECONDARY=8.8.8.8 make docker-dev
```

性能基准（10k 行导入 + 查询）：

```bash
uv run python scripts/bench_10k_rows.py
```

覆盖门禁阈值 95%，任何 PR 低于该值自动拒绝。

AI 自动驱动开发流（需求意图 → 方案 → 代码 → 测试 → 部署）见 [docs/AI_DRIVEN_DEV_FLOW.md](docs/AI_DRIVEN_DEV_FLOW.md)。

## 许可证

MIT — 见 [LICENSE](LICENSE)

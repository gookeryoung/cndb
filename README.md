# cndb

> 轻量级多人协作数据库，Django → FastAPI 迁移版

[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org)
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

### Docker 部署

```bash
# 构建 + 启动
docker compose up -d --build

# 服务访问 http://localhost:8000
# SQLite 数据持久化在 docker volume `cndb-data`
```

## 项目结构

```
src/cndb/
├── api/              # 认证依赖 (get_current_user)
├── core/             # 配置 / 数据库 / 安全
├── plugins/
│   ├── accounts/     # 用户注册 / 登录 / JWT
│   ├── workspaces/   # 工作区 + 成员 + 角色
│   ├── tables/       # 动态表 / 字段 / 记录 / DDL / 查询
│   ├── reports/      # 报告模板 (Jinja2 sandbox)
│   └── health/       # /health 健康检查
├── schemas/          # 通用 Pydantic schema
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
make bench         # 性能基准：10k 行导入 + 查询
make push          # 推送全部 remote
```

覆盖门禁阈值 95%，任何 PR 低于该值自动拒绝。

## 许可证

MIT — 见 [LICENSE](LICENSE)

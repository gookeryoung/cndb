# 腾讯云生产部署指南

面向**轻量应用服务器 / CVM 单机**形态：GitHub Actions 构建镜像 → 推 TCR → SSH 服务器自动部署，失败自动回滚。

---

## 一、架构与链路

```
git push tag v0.3.0
      │
      ▼
GitHub Actions (.github/workflows/deploy-tencent.yml)
      │  ① pnpm build        前端产物 → src/cndb/static
      │  ② uv build          → dist/cndb-0.3.0-py3-none-any.whl（含前端静态）
      │  ③ docker build      deploy/Dockerfile.prod → 装 wheel
      │  ④ docker push       → <TCR_REGISTRY>/cndb:0.3.0
      │
      ▼ ⑤ SSH
腾讯云服务器 /opt/cndb
      │  deploy.sh:
      │    预备份数据库 → docker login TCR → pull
      │    → 更新 .env → up -d --force-recreate
      │    → 轮询 /api/health（180s）
      │    → 失败：自动回滚到上一个 tag
      ▼
   http://<服务器IP>:8000
```

**数据持久化**：唯一数据卷 `cndb-data` 挂在 `/data`，数据库、用户附件、备份归档全在里面。换版本只换镜像，卷不动。

---

## 二、一次性准备

### 1. 开 TCR 镜像仓库

个人版（免费，适合单人/小团队）：

1. 控制台 → 容器镜像服务 TCR → 开通**个人版**
2. 访问凭证 → 获取长期访问凭证，记下**服务器地址 + 用户名 + 密码**
   - 个人版地址形如 `xxxxxxxx.tencentcloudcr.com`
3. 新建命名空间（命名空间名即镜像路径的一段）

企业版（多实例/高可用/内网拉取）：新建实例 → 命名空间 → 服务账号。

> **GitHub Actions 专用服务账号**：在 TCR 控制台创建服务账号，权限只勾目标命名空间的 **读写**。  
> 用户名形如 `tcr$deploy`，**必须改成 `tcr@deploy`** —— 腾讯云官方明确说明部分 CI 平台无法正确处理 `$`，  
> 后端默认兼容 `@`。直接用 `tcr$` 会在 push 时报认证失败。

### 2. 准备服务器

轻量应用服务器建议 **2核4G / 60G SSD**（SQLite + 少量并发足够；内存 <2G 跑构建会 OOM）。

```bash
# 安装 Docker（腾讯云镜像通常已预装，先确认）
docker --version && docker compose version

# 若未安装
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 建部署目录
mkdir -p /opt/cndb/deploy /opt/cndb/backups
cd /opt/cndb
```

安全组放行：`8000`（或你的反代端口）。**不要放行 2375**。

### 3. 配置 .env

```bash
cd /opt/cndb
cp deploy/.env.prod.example .env
chmod 600 .env

# 生成 JWT 密钥替换占位符
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# 填 TCR 地址
vim .env   # 改 CNDB_IMAGE 和 CORS_ORIGINS
```

必填项：

| 变量             | 说明                                                     |
| -------------- | ------------------------------------------------------ |
| `CNDB_IMAGE`   | `<tcr域名>/<命名空间>/cndb:v0.3.0`，**版本号随意**，deploy.sh 会自动覆写 |
| `JWT_SECRET`   | `openssl rand -hex 32`，CI 会校验是否还是占位符                   |
| `CORS_ORIGINS` | JSON 数组格式：`["https://cndb.example.com"]`；同域访问填 `[]`    |

> ⚠️ `CORS_ORIGINS` **必须写成 JSON 数组**。应用里它是 `list[str]` 类型，  
> pydantic-settings 对复杂类型环境变量按 JSON 解析，写成逗号分隔字符串会  
> 抛 `SettingsError` 让容器启动即崩。

### 4. 配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret            | 值                                         |
| ----------------- | ----------------------------------------- |
| `TCR_REGISTRY`    | `xxxxxxxx.tencentcloudcr.com`（**不含命名空间**） |
| `TCR_USERNAME`    | `tcr@deploy`（注意 `@`）                      |
| `TCR_PASSWORD`    | 服务账号密码                                    |
| `SSH_HOST`        | 服务器公网 IP                                  |
| `SSH_PORT`        | `22`（若改过）                                 |
| `SSH_USERNAME`    | `root`                                    |
| `SSH_PRIVATE_KEY` | SSH 私钥全文（推荐，免明文密码）                        |
| `SERVER_URL`      | 访问地址，用于部署后跳转                              |

生成专用部署密钥（比复用个人密钥安全）：

```bash
ssh-keygen -t ed25519 -C "cndb-deploy" -f ~/.ssh/cndb_deploy -N ""
cat ~/.ssh/cndb_deploy          # 贴到 SSH_PRIVATE_KEY
cat ~/.ssh/cndb_deploy.pub      # 追加到服务器 ~/.ssh/authorized_keys
```

首次手动部署一次：

```bash
cd /opt/cndb && ./deploy/deploy.sh v0.3.0
```

---

## 三、日常发布

```bash
# 版本号在 pyproject.toml 与 CHANGELOG.md 同步更新后
git tag v0.3.1 && git push origin v0.3.1
```

推 tag 即触发：构建 → 推 TCR → 自动部署。约 5-8 分钟。

GitHub Actions 页面可看实时进度；失败会自动回滚并在日志中标明原因。

**手动重跑**（不改代码重新部署）：

```
Actions → Deploy to Tencent Cloud → Run workflow → 填入目标版本（如 v0.3.0）
```

**手动回滚**：

```bash
cd /opt/cndb && ./deploy/deploy.sh v0.3.0   # 直接指定历史版本
```

---

## 四、定时备份

```bash
# 装 coscmd（仅需上传 COS 时）
pip install coscmd
coscmd config -a <SecretId> -s <SecretKey> -r ap-guangzhou
chmod 600 ~/.cos.conf

# 本地先跑一次验证
cd /opt/cndb && ./deploy/backup.sh

# 每日 03:17 定时（错开整点，避开同机 IO 峰值）
crontab -e
# 加入：
17 3 * * * /opt/cndb/deploy/backup.sh >> /opt/cndb/backups/backup.log 2>&1
```

启用 COS 上传：在 `.env` 里设 `COS_ENABLE=true` 并填 `COS_BUCKET` / `COS_REGION`。

备份策略：

- 每次部署前自动预备份一份（`pre-deploy-<版本>-<时间戳>.tar.gz`）
- 每日定时备份，产物 0 字节或异常时告警退出，不会静默失败
- 本地保留 14 天（`KEEP_DAYS` 可调），过期的自动清理
- COS 上传失败**不删本地副本** —— 本地那份仍是有效备份

**恢复**：

```bash
cd /opt/cndb
# archive 是位置参数；--force 用于覆盖已有数据的库（不带会拒绝执行）
# 建议先 --dry-run 预检，确认归档完整后再实际恢复
docker compose --env-file .env -f docker-compose.prod.yml exec app \
  cndb restore /data/backups/cndb-20261009-031700.tar.gz --dry-run

docker compose --env-file .env -f docker-compose.prod.yml exec app \
  cndb restore /data/backups/cndb-20261009-031700.tar.gz --force
```

> 恢复会覆盖当前库，**先用 `--dry-run` 确认目标文件无误**。恢复后应用启动时自动跑  
> `upgrade head`，旧备份可在新版本上恢复。

---

## 五、迁移到 PostgreSQL

数据量增长或需要高可用时，**无需改代码**，只改 `.env`：

```env
CNDATABASE_URL=postgresql+psycopg://cndb:密码@内网地址:5432/cndb
```

1. 腾讯云创建 TencentDB for PostgreSQL，选与服务器**同地域同 VPC**（走内网，不计流量费）
2. 用 `cndb backup --mode sqlalchemy` 从 SQLite 导出（跨库备份需显式指定该模式）：

```bash
cd /opt/cndb
docker compose --env-file .env -f docker-compose.prod.yml exec app \
  cndb backup -o /data/backups/pg-migrate.tar.gz --mode sqlalchemy
```

1. 停应用，把归档取到本地（`docker cp cndb:/data/backups/pg-migrate.tar.gz .`），  
   解包后将 `dump.json` 导入 PostgreSQL：

```bash
docker compose --env-file .env -f docker-compose.prod.yml down   # 必须先停应用
# 改 .env 的 CNDATABASE_URL 为 postgresql+psycopg://...
docker compose --env-file .env -f docker-compose.prod.yml up -d  # 启动即自动 alembic upgrade head
```

1. 登录验证数据完整后，删除 SQLite 库文件

> 应用**没有独立的 `cndb migrate` 子命令**——schema 迁移在 FastAPI 启动时  
> 自动执行（`lifespan` 调 `ensure_db_migrated`），启动日志里会打印  
> `alembic upgrade head 执行成功` 或走 create_all 兜底。

> 切库前务必先做一次完整备份并**实际验证能恢复**。数据库迁移是本方案里  
> 唯一不可回滚的操作。

---

## 六、排查

### 部署后打不开

```bash
docker ps -a --filter name=cndb          # 看状态：Up / Restarting / Exited
docker logs --tail 100 cndb              # 关键日志
docker inspect cndb --format '{{json .State.Health}}'
curl -v http://127.0.0.1:8000/api/health # 绕过外网定位问题
```

| 现象                   | 原因与处理                                                     |
| -------------------- | --------------------------------------------------------- |
| 一直 `Restarting`      | 启动即崩，多为 `JWT_SECRET` 未配或 `CORS_ORIGINS` 格式错，看日志首行报错       |
| `unhealthy`          | 首次启动要跑迁移，`start_period` 60s 内属正常；超时则查迁移异常                 |
| 本机 curl 通、外网不通       | 安全组未放行端口，或 `.env` 里 `CNDB_BIND` 绑到了 `127.0.0.1`           |
| 日志刷 `no such column` | schema 漂移。应用启动时会自愈补列；若持续报错，备份后重建库                         |
| 附件 404               | 卷挂载异常，`docker volume inspect cndb-data` 确认 Mountpoint 有数据 |

### 版本回滚后仍异常

```bash
cd /opt/cndb
grep CNDB_IMAGE .env                              # 确认当前指向的版本
docker compose --env-file .env -f docker-compose.prod.yml up -d --force-recreate
```

### 磁盘满

镜像和日志是主要占用：

```bash
docker system df                                   # 查看占用分布
docker image prune -a                              # 清理悬空镜像（deploy.sh 已自动保留最近 5 个）
docker volume ls                                   # 确认无误后再清理卷——卷里有你的数据
```

`docker-compose.prod.yml` 已配 `json-file` 日志轮转（20m × 5 = 100MB 上限），  
不配的话日志会无限增长把盘写满。

---

## 七、安全清单

上线前逐项确认：

- [ ] `JWT_SECRET` 已替换为 `openssl rand -hex 32` 的随机值（CI 会校验占位符）
- [ ] `.env` 权限 `600`，且**不在 git 追踪中**（`.gitignore` 已含 `.env`）
- [ ] `DEBUG=false`
- [ ] 安全组只放行业务端口，SSH 端口限制来源 IP
- [ ] `CORS_ORIGINS` 收敛到自己的域名，不填 `*`（`allow_credentials=True` 时浏览器会直接拒绝）
- [ ] 定时备份已生效，且**实际验证过能恢复**
- [ ] TCR 命名空间设为私有

> `AUTH_ENABLED=true` 是默认值且**不可关闭**（关闭意味着任何人都能读写全部数据）。  
> 首次部署后立刻登录并**修改默认账号密码** —— `cndb seed` 注入的 `demo/demo1234`  
> 是公开凭据，生产环境若跑过 seed 必须改掉。

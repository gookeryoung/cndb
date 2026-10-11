# 腾讯云生产部署指南

面向**轻量应用服务器 / CVM 单机**形态：GitHub Actions 构建镜像 → 经 COS 中转 → SSH 服务器自动部署，失败自动回滚。

> **为什么镜像不走 GitHub 直推 TCR**：跨境 `docker push` 是逐层 blob 的
> HTTPS 上传，跨境链路丢包率高时连接停滞且无超时，表现为流水线卡死到
> 撞上超时上限。现改为 `docker save | gzip` 上传 COS 全球加速域名
> （针对境外→国内优化），服务器从 COS **内网**下载（同地域免流量费），
> 跨境大流量只剩经过专门优化的一段。TCR 退为回滚备用源（历史版本仍可 pull）。

---

## 一、架构与链路

```
git push tag v0.3.0
      │
      ▼
GitHub Actions (.github/workflows/deploy-tencent.yml)
      │  ① pnpm build         前端产物 → src/cndb/static
      │  ② uv build           → dist/cndb-0.3.0-py3-none-any.whl（含前端静态）
      │  ③ docker build       deploy/Dockerfile.prod → 装 wheel
      │  ④ docker save | gzip → 上传 COS 全球加速域名
      │  ⑤ coscmd signurl     → 生成预签名 URL（有效期 1 小时）
      │
      ▼ ⑥ SSH（传预签名 URL）
腾讯云服务器 /opt/cndb
      │  deploy.sh:
      │    预备份数据库
      │    → 预签名 URL 换 COS 默认域名（同地域自动走内网）→ 下载 → docker load
      │    → 更新 .env → up -d --force-recreate
      │    → 轮询 /api/health（180s）
      │    → 失败：自动回滚到上一个 tag
      ▼
   http://<服务器IP>:8000
```

**数据持久化**：唯一数据卷 `cndb-data` 挂在 `/data`，数据库、用户附件、备份归档全在里面。换版本只换镜像，卷不动。

---

## 二、一次性准备

### 1. 开 COS 桶（镜像中转，必选）

1. 控制台 → 对象存储 COS → 创建存储桶
   - **地域必须与服务器相同**（如都在 ap-guangzhou）——同地域 CVM 访问 COS 默认域名自动走内网，下载免公网流量费
   - 权限选**私有读写**
2. 控制台 → 存储桶 → 全球加速：开启加速（获得 `accelerate.tencentcos.com` 域名，供境外 CI 上传优化）
3. 访问管理 CAM → 新建子用户（仅编程访问），授予该桶的数据读写最小权限，记下 `SecretId` / `SecretKey`
4. 建议配置生命周期规则：对 `cndb/` 前缀对象设 7 天过期自动删除，避免历史镜像包堆积占用存储

> 桶名格式 `BucketName-APPID`（如 `cndb-1250000000`），Secrets 里的
> `COS_BUCKET` 必须填**含 APPID 后缀的完整格式** —— deploy.sh 要用它拼内网域名。

### 2. 开 TCR 镜像仓库（可选，仅用于手动回滚）

CI 不再向 TCR 推镜像，但镜像仍以 TCR 地址**命名**（与历史版本同名，保证手动回滚 `docker pull` 可命中旧包）。已开通过的可保持现状；新项目可以不开。

个人版（免费）：

1. 控制台 → 容器镜像服务 TCR → 开通**个人版**
2. 访问凭证 → 获取长期访问凭证，记下**服务器地址 + 用户名 + 密码**
   - 个人版地址形如 `ccr.ccs.tencentyun.com`
3. 新建命名空间（命名空间名即镜像路径的一段）

> **本项目实际使用的仓库**：`ccr.ccs.tencentyun.com/pydev/cndb`
> 即 `TCR_REGISTRY=ccr.ccs.tencentyun.com`、`TCR_GROUP=pydev`，仓库名固定为 `cndb`。
>
> ⚠️ `TCR_REGISTRY` 必须是**纯域名不含命名空间** —— `docker login` 不接受带路径的
> registry 参数。命名空间必须放在 `TCR_GROUP` 这个独立 Secret 里。

> **GitHub Actions 专用服务账号**（仅手动回滚用）：权限只勾目标命名空间的**读写**。
> 用户名形如 `tcr$deploy`，**必须改成 `tcr@deploy`** —— 腾讯云官方明确说明部分 CI 平台
> 无法正确处理 `$`，后端默认兼容 `@`。直接用 `tcr$` 会在 pull 时报认证失败。

### 3. 准备服务器

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

### 4. 配置 .env

推荐用自带脚本，一条命令完成（可重复运行，**只补缺失项，不覆盖已有配置**）：

```bash
cd /opt/cndb
# deploy/bootstrap-server.sh 由 CI 的 scp 步骤自动同步过来，首次需手工传一次
bash deploy/bootstrap-server.sh --with-cron   # --with-cron 顺带装每日定时备份
```

脚本会：建目录 → 生成 `.env`（含随机 `JWT_SECRET`，不回显明文）→ 检查端口/磁盘 → 可选装 cron。

手工方式等价：

```bash
cd /opt/cndb
cp deploy/.env.prod.example .env
chmod 600 .env

# 生成 JWT 密钥替换占位符
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# 填 TCR 地址（版本号随意，deploy.sh 会自动覆写）
vim .env   # 改 CNDB_IMAGE 和 CORS_ORIGINS
```

必填项：

| 变量             | 说明                                                     |
| -------------- | ------------------------------------------------------ |
| `CNDB_IMAGE`   | `ccr.ccs.tencentyun.com/pydev/cndb:v0.3.0`，**版本号随意**，deploy.sh 会自动覆写 |
| `JWT_SECRET`   | `openssl rand -hex 32`，CI 会校验是否还是占位符                   |
| `CORS_ORIGINS` | JSON 数组格式：`["https://cndb.example.com"]`；同域访问填 `[]`    |

> ⚠️ `CORS_ORIGINS` **必须写成 JSON 数组**。应用里它是 `list[str]` 类型，  
> pydantic-settings 对复杂类型环境变量按 JSON 解析，写成逗号分隔字符串会  
> 抛 `SettingsError` 让容器启动即崩。
>
> 改镜像地址时注意：服务器 `.env` 的 `CNDB_IMAGE` 必须与流水线拼出的地址一致，
> 不一致会导致部署时拉不到镜像。仓库名改动需同步 3 处：`deploy/.env.prod.example`、
> 服务器 `.env`、GitHub Secret。

### 5. 配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret            | 值                                         |
| ----------------- | ----------------------------------------- |
| `COS_BUCKET`      | `cndb-1250000000`（**含 APPID 后缀的完整桶名**） |
| `COS_REGION`      | `ap-guangzhou`（与服务器同地域）              |
| `COS_SECRET_ID`   | 子用户 SecretId（仅授目标桶读写）             |
| `COS_SECRET_KEY`  | 对应 SecretKey                             |
| `TCR_REGISTRY`    | `ccr.ccs.tencentyun.com`（**纯域名，不含命名空间**；仅作镜像命名与手动回滚） |
| `TCR_GROUP`       | `pydev`（命名空间，本项目实际使用）              |
| `TCR_USERNAME`    | `tcr@deploy`（注意 `@`；仅手动回滚走 TCR pull 时需要） |
| `TCR_PASSWORD`    | 服务账号密码                                  |
| `SSH_HOST`        | 服务器公网 IP                                  |
| `SSH_PORT`        | `22`（若改过）                                 |
| `SSH_USERNAME`    | `root`                                    |
| `SSH_PRIVATE_KEY` | SSH 私钥全文（推荐，免明文密码）                   |
| `SERVER_URL`      | 访问地址，用于部署后跳转                          |

> `TCR_REGISTRY` 与 `TCR_GROUP` 必须拆开：镜像名合法性校验按纯域名处理，
> 命名空间混进 registry 会导致拼出的镜像名不合法。完整镜像地址由流水线拼成
> `<TCR_REGISTRY>/<TCR_GROUP>/cndb:<version>`，与 TCR 历史版本同名。

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

### CI 上传 / 服务器下载 COS 失败

```bash
# 服务器上手动验证 COS 内网可达（同地域应秒回）
curl -sI --max-time 10 https://<COS_BUCKET>.cos.<COS_REGION>.myqcloud.com/ -o /dev/null -w '%{http_code} %{time_total}s\n'
# 观察部署日志中的下载报错
docker logs --tail 50 cndb 2>/dev/null; journalctl -u ssh 2>/dev/null | tail -20
```

| 现象                                  | 原因与处理                                                       |
| ----------------------------------- | ----------------------------------------------------------- |
| CI `Upload to COS` 403              | 子用户密钥无该桶写权限；`COS_BUCKET` 未带 `-APPID` 后缀                     |
| CI 上传慢或超时                           | 加速域名未生效：确认桶已开启全球加速；加速域名全球仅部分地域出口，看 Probe 步骤的耗时数字            |
| 服务器下载 403 `SignatureExpired`        | 预签名 URL 超过 1 小时有效期（多见于手动重跑 deploy job）——重跑整个 workflow 即可     |
| 服务器下载 404 / NoSuchKey               | build job 上传失败或对象路径不匹配；在 COS 控制台确认 `cndb/cndb-image.tar.gz` 存在 |
| 服务器下载走公网（流量计费）                      | 服务器与桶不同地域。把桶迁到与服务器同地域，或接受公网流量费（不影响功能）                       |
| `docker load` 失败 / gzip 报错           | 下载不完整。重新跑一次 deploy（CI 会重新上传并生成新 URL），并检查服务器磁盘剩余空间           |

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
- [ ] TCR 命名空间设为私有（若仍保留 TCR 用于回滚）
- [ ] COS 桶为私有读写；子用户密钥仅授目标桶读写，且已开启 `cndb/` 前缀生命周期清理

> `AUTH_ENABLED=true` 是默认值且**不可关闭**（关闭意味着任何人都能读写全部数据）。  
> 首次部署后立刻登录并**修改默认账号密码** —— `cndb seed` 注入的 `demo/demo1234`  
> 是公开凭据，生产环境若跑过 seed 必须改掉。

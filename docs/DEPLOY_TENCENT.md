# 腾讯云生产部署指南

面向**轻量应用服务器 / CVM 单机**形态：GitHub Actions 把部署配置与 wheel 地址经 TAT 下发 → 服务器端构建镜像并自动部署，失败自动回滚。

> **为什么镜像在服务器端构建**：原链路（CI 构建 → `docker save | gzip` →
> 上传 COS 全球加速 → 预签名 URL → 服务器 COS 内网下载 → `docker load`）
> 环节多、任一环节抖动即部署失败，且 COS 存储/流量持续计费。现改为配置文件
> 内联进 TAT 命令、wheel 由服务器自己从 PyPI / 国内镜像取，`deploy.sh` 在服务器上
> `docker build` —— 镜像不过网，构建完直接部署。TCR 退为回滚备用源
> （历史版本仍可 pull）。
>
> **为什么不走 SSH**：GitHub 托管 runner 的出口 IP 在美国，用 SSH 直连
> 22 端口会让腾讯云主机安全持续报「异地登录 root」高危告警；把 runner IP
> 加白也不可行（GitHub 的 CIDR 池是变动的）。改用 TAT（自动化助手）下发后
> 全程没有入站连接，不产生登录审计，22 端口可以对公网关掉。详见第三节。
>
> **发布提速（0.4.7+）**：① 部署不再与 Release 并行抢跑，改由 `release.yml`
> 在 pypi job 成功后调用（省掉等 PyPI 元数据的最多 3 分钟）；② wheel 下载从
> 「腾讯镜像 → 官方源」扩展为「腾讯 / 阿里 / 清华镜像 → 官方源」，镜像同步延迟
> 不再直接掉到跨境约 14KB/s 的官方源；③ 镜像拆成「依赖基础镜像 + 应用层」两段，
> 依赖未变时服务器只重建 20-40s 的 wheel 薄层，Docker 层缓存被清也不会再触发
> 5-15 分钟冷启动。常态上机段约 1-2 分钟（详见第三节）。

---

## 一、架构与链路

```
git push tag v0.3.0
      │
      ▼
GitHub Actions (.github/workflows/release.yml)
      │  ① pnpm build         前端产物 → src/cndb/static
      │  ② uv build + publish → dist/cndb-0.3.0-py3-none-any.whl 发布 PyPI
      │  └─ pypi job 成功后调用 deploy-tencent.yml（workflow_call）
      ▼
GitHub Actions (deploy-tencent.yml，被 Release 调用)
      │  ③ 解析 wheel 地址    取官方 URL、国内镜像 URL 与 sha256（不下载）
      │  ④ uv export          产出 dist/requirements.lock.txt（锁定依赖）
      │  ⑤ 打包载荷           compose + deploy/ + 锁定清单 → tar.gz → base64
      ▼
腾讯云 TAT（自动化助手）
      │  ⑥ RunCommand 下发    命令进云端队列，实例 agent 主动拉取执行（无入站连接）
      ▼
腾讯云服务器 /opt/cndb
      │  ⑦ 解包配置 → curl 下载 wheel（腾讯/阿里/清华镜像轮询，最后官方源）→ sha256 校验
      │  deploy.sh (SERVER_BUILD=1):
      │    依赖基础镜像（系统字体 + 锁定依赖；按指纹复用，uv.lock 变化才重建）
      │    → 应用镜像（只装 wheel，常态 20-40s）
      │    → 冒烟验证（cndb 可导入 + 前端 assets 非空）
      │    → 预备份数据库
      │    → 更新 .env → up -d --force-recreate
      │    → 轮询 /api/health（180s）
      │    （启用反代时：再拉起 nginx 容器，并做代理冒烟）
      │    → 失败：自动回滚到上一个 tag
      ▼
   单容器模式： http://<服务器IP>:8000
   反代模式：   http(s)://<域名> ──> 容器 nginx ──> app:8000
                （HTTP 统一入口，见 4.1）
```

**数据持久化**：唯一数据卷 `cndb-data` 挂在 `/data`，数据库、用户附件、备份归档全在里面。换版本只换镜像，卷不动。

**TAT 的两个硬限制**（`scripts/build_tat_command.py` 已做预检）：

| 限制 | 值 | 现在的做法 |
|---|---|---|
| 单条命令 Content | 64 KiB（base64 后） | 配置载荷约 24 KB → Content 约 49 KB，余量 15 KB；超限直接失败并提示拆命令 |
| 单个任务超时 | 最长 86400s | CI 传 3600s，本地最多等 3300s（job 上限 70 分钟） |

**服务器需要具备**：`docker` + `curl`（下载 wheel 用）。命令开头会显式检查 `curl`，缺失直接报错退出。

---

## 二、一次性准备

### 1. 开 COS 桶（可选，仅数据备份用）

镜像部署已不走 COS。仅当需要把每日备份归档异地上传 COS 时才开（`deploy/backup.sh` 的可选功能，`.env` 里 `COS_ENABLE=true` 启用）：

1. 控制台 → 对象存储 COS → 创建存储桶（地域建议与服务器相同，内网上传免流量费）
2. 权限选**私有读写**
3. 访问管理 CAM → 新建子用户（仅编程访问），授予该桶的数据读写最小权限
4. 建议配置生命周期规则：对备份前缀对象设过期自动删除，避免归档堆积

> 桶名格式 `BucketName-APPID`（如 `cndb-1250000000`）。这组密钥只填在**服务器
> `.env`**（`backup.sh` 使用），无需再配到 GitHub Secrets。

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

轻量应用服务器建议 **2核4G / 60G SSD**（SQLite + 少量并发足够；依赖基础镜像构建时，内存 <2G 跑 pip 依赖安装会 OOM，磁盘需容纳基础镜像 + 应用层 + 依赖缓存 + 数据卷）。

```bash
# 安装 Docker（腾讯云镜像通常已预装，先确认）
docker --version && docker compose version

# 若未安装
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 国内服务器拉 Docker Hub 超时的解法（三选一，推荐 a）：
# a) 配置 registry mirror（腾讯云 CVM 内网可用，对 docker pull/build 透明加速）
sudo tee /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://mirror.ccs.tencentyun.com"] }
EOF
sudo systemctl restart docker
# b) 不改 daemon：服务器端构建默认 CNDB_SOURCES=cn（基础镜像走 docker.m.daocloud.io），无需配置
# c) 仍要指定别的镜像：GitHub Secrets 配 BUILD_BASE_IMAGE 单项覆盖（见下文）

# 建部署目录
mkdir -p /opt/cndb/deploy /opt/cndb/backups
cd /opt/cndb
```

安全组放行：

- **单容器模式**：`8000`
- **反代模式**（`CNDB_ENABLE_PROXY=1`）：`80`（+ 可选的 `443`），**不要放行 8000** ——
  应用会绑到 `127.0.0.1`，公网直连既没必要，也会让客户端 IP 可伪造（登录失败限流被绕过）

**不要放行 2375**（Docker 守护进程端口，等于把服务器控制权交出去）。

### 4. 配置 .env

推荐用自带脚本，一条命令完成（可重复运行，**只补缺失项，不覆盖已有配置**）：

```bash
cd /opt/cndb
# 全新机器首次初始化：此时 /opt/cndb 下还没有脚本，
# 先把仓库里的 deploy/ 传上去（scp 一次即可，或用控制台「自动化助手」发送命令落盘）
bash deploy/bootstrap-server.sh --with-cron   # --with-cron 顺带装每日定时备份
```

> 之后每次 CI 部署都会把 `deploy/` 随载荷重新落一遍，不需要再手工同步。

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

### 4.1 反向代理（可选）

默认部署是**单容器**（FastAPI 直接托管前端）。需要域名 / HTTPS / 统一入口时，启用内置 nginx 反代容器：

```bash
cd /opt/cndb
vim .env
#   CNDB_ENABLE_PROXY=1
#   CNDB_BIND=127.0.0.1:8000      # 关键：应用端口不再对公网直连（否则可绕过代理、伪造客户端 IP）
#   CNDB_SERVER_NAME=_            # 取值见下方「CNDB_SERVER_NAME 该填什么」
#   CNDB_HTTP_BIND=80
#   CNDB_HTTPS_BIND=443
#   CNDB_NGINX_IMAGE=mirror.ccs.tencentyun.com/library/nginx:1.27-alpine   # 拉不到 Docker Hub 时换源，见 4.1.1
./deploy/deploy.sh v0.3.12       # 脚本自动带 --profile proxy，并在末尾做代理冒烟验证
```

安全组只需放行 `80`（与可选的 `443`）—— 放行清单见「3. 准备服务器」。

**代理做了什么**：nginx 将全部 HTTP 请求转发到应用容器（`cndb:8000`），
统一暴露域名、处理 TLS 与上传体积限制；Agent 在启用代理时会经代理容器请求
`/api/health`，确认「nginx → 应用」的上游链路可用。

#### 4.1.1 前置检查：端口占用、镜像换源与配置自检

反代模式下 nginx 容器要独占宿主机 `80`/`443`，**切换前先确认端口空闲**：

```bash
ss -lntp | grep -E ':(80|443) '                   # 有输出就是被占用了
systemctl list-units --type=service | grep -i nginx
```

若服务器上已跑着**宿主机原生 nginx**（很常见：早期用它做过反代或 HTTPS），
容器 nginx 会因 `address already in use` 起不来；而 `deploy.sh` 此时已重建过应用容器，
回滚也只回滚镜像、**不会把系统 nginx 拉回来** —— 结果是 80/443 直接不可用。迁移步骤：

```bash
# 1) 证书从系统目录搬到容器挂载目录（-L 解引用软链，否则挂进去是断链）
mkdir -p /opt/cndb/certs /opt/cndb/certbot-www
cp -L /etc/letsencrypt/live/<域名>/fullchain.pem /opt/cndb/certs/
cp -L /etc/letsencrypt/live/<域名>/privkey.pem  /opt/cndb/certs/
chmod 600 /opt/cndb/certs/privkey.pem

# 2) 停用系统 nginx 释放 80/443（disable 防止重启后又把端口抢回去）
systemctl stop nginx && systemctl disable nginx

# 3) 再执行 ./deploy/deploy.sh <版本>
```

> 应急回退：`systemctl start nginx` 即可恢复。应用此时绑在 `127.0.0.1:8000`，
> 系统 nginx 原有的 `proxy_pass http://127.0.0.1:8000` 照样能通。

**nginx 镜像换源**：服务器端 `deploy.sh` 默认 `CNDB_SOURCES=cn`，会自动使用
`docker.m.daocloud.io/library/nginx:1.27-alpine`。若服务器上旧的 `.env` 里还留着
`CNDB_NGINX_IMAGE=nginx:1.27-alpine`，该行会被视为显式覆盖（继续用官方镜像），
换成国内源请注释掉它。要指定别的源时用 `CNDB_NGINX_IMAGE` 覆盖，
并**在切流前先单独拉一次**，免得切换窗口里才发现拉不下来：

```env
CNDB_NGINX_IMAGE=mirror.ccs.tencentyun.com/library/nginx:1.27-alpine   # 腾讯云内网源，同地域最快
# 或 CNDB_NGINX_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine
```

```bash
docker pull "$(grep -oP '(?<=^CNDB_NGINX_IMAGE=).*' /opt/cndb/.env)"
```

**配置自检（不占端口、不影响线上）**：用同一镜像 + 相同挂载先跑一次 `nginx -t`，
把配置渲染、证书路径、语法问题提前暴露出来。注意必须接到 compose 网络上，
否则上游 `app:8000` 解析不了，会误报 `host not found in upstream`：

```bash
cd /opt/cndb
NGINX_IMG="$(grep -oP '(?<=^CNDB_NGINX_IMAGE=).*' .env)"
docker run --rm --network cndb_default \
  -e CNDB_SERVER_NAME=_ -e CNDB_APP_UPSTREAM=app:8000 -e CNDB_MAX_BODY_SIZE=512m \
  -v "$PWD/deploy/nginx/templates:/etc/nginx/templates:ro" \
  -v "$PWD/deploy/nginx/snippets:/etc/nginx/snippets:ro" \
  -v "$PWD/deploy/nginx/extra:/etc/nginx/extra:ro" \
  -v "$PWD/certs:/etc/nginx/certs:ro" \
  "$NGINX_IMG" nginx -t
```

> ⚠️ **`${VAR}` 只在 templates 目录里有效**：官方 nginx 镜像的 envsubst 只渲染
> `/etc/nginx/templates/*.template`。`snippets/` 与 `extra/*.conf` 是**静态文件**，
> 里面写 `${VAR}` 不会被替换，变量名会原样进入配置并让 nginx **启动即失败**
> （典型报错 `"client_max_body_size" directive invalid value`）。
> 这就是 `snippets/cndb-proxy.conf` 里上传上限写**常量**而不是 `${CNDB_MAX_BODY_SIZE}`
> 的原因 —— 该片段被静态的 `extra/ssl.conf` 共用，无法传参。改上传上限请改**仓库里**这一行
> 并重新部署（`deploy/` 目录每次部署都会被 CI 覆盖同步，只改服务器会被冲掉）。

#### 4.1.2 HTTPS

1. 证书放宿主机 `./certs/`，文件名固定为 `fullchain.pem` / `privkey.pem`
   （compose 已挂载为 `/etc/nginx/certs`）：

   ```bash
   cp -L /etc/letsencrypt/live/<域名>/fullchain.pem /opt/cndb/certs/
   cp -L /etc/letsencrypt/live/<域名>/privkey.pem  /opt/cndb/certs/
   chmod 600 /opt/cndb/certs/privkey.pem
   ```

2. 从示例生成 `ssl.conf` 并替换域名。该文件同时提供 `443` 的 server 块与
   `80 → 443` 的跳转块，且**复用同一份反代片段**，WS 规则不会漏配：

   ```bash
   cd /opt/cndb
   sed 's/YOUR_DOMAIN/<域名>/g' deploy/nginx/extra/ssl.conf.example > deploy/nginx/extra/ssl.conf
   ```

3. 让配置生效（重新部署，或只重载 nginx）：

   ```bash
   ./deploy/deploy.sh <当前版本>
   # 或：docker exec cndb-nginx nginx -t && docker exec cndb-nginx nginx -s reload
   ```

> 📌 `deploy/nginx/extra/ssl.conf` 与 `certs/` 属于**服务器本地文件**：CI 只同步
> `deploy/nginx/templates`、`snippets` 和 `extra/ssl.conf.example`，不会覆盖你生成的
> `ssl.conf`，也不会动 `certs/`。换服务器时需手工重做本节两步。
>
> 同理 **`deploy/nginx/extra/*.conf` 里任何自建片段都是服务器本地文件**（CI 只覆盖它自己带的那几个文件名），
> 换服务器时需一并手工补齐。

#### 4.1.3 同机并存其他应用（以 StockMaster 为例）

本机 80/443 被 cndb 的 nginx 容器独占，同机其他服务要对外提供 HTTPS 只能**借道**这个 nginx：

1. 被借道的服务**不要**把端口映射到 `0.0.0.0`。改为只绑回环，并接入 cndb 的网络：

   ```yaml
   # 其他应用的 compose
   services:
     app:
       ports: ["127.0.0.1:8770:8770"]   # 只绑回环，公网不可达
       networks: [default, cndb_net]
   networks:
     cndb_net:
       external: true
       name: cndb_default                # cndb 的 compose 项目网络
   ```

2. 在 `deploy/nginx/extra/` 下新增一个**只含 server 块**的片段，上游写**容器名**，
   并用 `resolver` + 变量形式回源（这样对端容器没起来时 nginx 仍能启动，不会连带 cndb 一起挂）：

   ```nginx
   location / {
       resolver 127.0.0.11 valid=10s ipv6=off;
       set $backend stockmaster:8770;
       proxy_pass http://$backend;
   }
   ```

3. 防火墙**不要**放行该应用端口；对外只留 `80`/`443`。

> 早期做法是把应用端口发布到 `0.0.0.0`、再从容器经 `172.18.0.1`（docker 网桥网关）回连宿主。
> 那样端口一直挂在公网上（靠防火墙兜底），且网段一变就断。现已统一改为「只绑回环 + 容器名回源」。


> **`CNDB_SERVER_NAME` 该填什么**：`ssl.conf` 的 `80` 跳转块里也写了 `server_name <域名>`，
> 而 `templates/default.conf.template` 的 `80` server 用的是 `CNDB_SERVER_NAME`。
> 两处同名时 nginx 会忽略后定义的那个并告警 `conflicting server name` ——
> 结果就是 **HTTP 不再跳转 HTTPS**。所以启用 `ssl.conf` 的跳转块时，把
> `CNDB_SERVER_NAME` 留作 `_`：域名请求精确命中跳转块、其它 Host 落到默认块，
> 跳转与「无告警」兼得。（只配 `443`、不要 `80` 跳转块时，填真实域名亦可。）

**证书自动续期（certbot）**：容器 nginx 的 ACME 校验目录是 `/var/www/certbot`
（compose 挂到宿主机 `./certbot-www`），与宿主机 nginx 时代的 `/var/www/html`
**不是同一个目录** —— 不调整的话续期会静默失败。两处改动：

```bash
# 1) renewal 的 webroot 指到容器 webroot
sed -i 's|/var/www/html|/opt/cndb/certbot-www|g' /etc/letsencrypt/renewal/<域名>.conf

# 2) 续期后同步新证书进 certs/ 并热加载容器 nginx
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/cndb-nginx.sh <<'EOF'
#!/bin/bash
set -e
SRC=/etc/letsencrypt/live/<域名>
DST=/opt/cndb/certs
cp -L "$SRC/fullchain.pem" "$DST/fullchain.pem"
cp -L "$SRC/privkey.pem"  "$DST/privkey.pem"
chmod 644 "$DST/fullchain.pem"
chmod 600 "$DST/privkey.pem"
docker exec cndb-nginx nginx -s reload 2>/dev/null || true
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/cndb-nginx.sh
```

验证（走 Let's Encrypt staging，**不会真的签发**）：

```bash
certbot renew --dry-run
```

`certbot.timer` 由系统包自带，无需另外配 cron。

**反代启用后的两点注意**

- `CORS_ORIGINS` 要填代理对外的地址（如 `["https://cndb.example.com"]`）；
- 代理用真实对端地址**覆盖** `X-Forwarded-For`（而不是追加），避免客户端伪造 IP 绕过登录失败限流；
  应用侧 `--proxy-headers` 直接读到可信值。

### 5. 配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret            | 值                                         |
| ----------------- | ----------------------------------------- |
| `TENCENTCLOUD_SECRET_ID` | 子账号 API 密钥 ID（**不要用主账号密钥**，权限见下） |
| `TENCENTCLOUD_SECRET_KEY` | 子账号 API 密钥 Key |
| `CNDB_INSTANCE_ID` | Lighthouse 实例 ID，如 `lhins-8k8ahx8m`（控制台实例详情可见） |
| `CNDB_REGION`     | 实例所在地域，如 `ap-shanghai`（**必须与实例实际地域一致**，否则 RunCommand 报实例不存在） |
| `TCR_REGISTRY`    | `ccr.ccs.tencentyun.com`（**纯域名，不含命名空间**；仅作镜像命名与手动回滚） |
| `TCR_GROUP`       | `pydev`（命名空间，本项目实际使用）              |
| `TCR_USERNAME`    | `tcr@deploy`（注意 `@`；仅手动回滚走 TCR pull 时需要） |
| `TCR_PASSWORD`    | 服务账号密码                                  |
| `SERVER_URL`      | 访问地址，用于部署后跳转                          |
| `BUILD_BASE_IMAGE` | 可选。单项覆盖基础镜像（优先级高于 `CNDB_SOURCES`），如 `docker.m.daocloud.io/library/python:3.12-slim` |
| `BUILD_PIP_INDEX_URL` | 可选。单项覆盖构建依赖基础镜像时的 pip 源。默认由 `CNDB_SOURCES` 决定（服务器为 `cn`，走腾讯云内网源），失败会自动用官方源整体重试 |
| `CNDB_SOURCES` | 可选。构建源 profile（`auto` / `cn` / `global`）；TAT 命令默认显式写 `cn`，不会继承 GitHub runner 的 `global` |

> **`SSH_HOST` / `SSH_PORT` / `SSH_USERNAME` / `SSH_PRIVATE_KEY` 已不再使用**，可以删掉。
> 改 TAT 下发后流水线没有任何 SSH 登录，服务器也不需要为部署保留公网 22 端口。

> 镜像部署已不再需要 `COS_*` 系列 Secrets（原 CI→COS→服务器链路已移除）。
> 数据备份上传 COS 的密钥只填服务器 `.env`（`backup.sh` 使用）。

> `TCR_REGISTRY` 与 `TCR_GROUP` 必须拆开：镜像名合法性校验按纯域名处理，
> 命名空间混进 registry 会导致拼出的镜像名不合法。完整镜像地址由流水线拼成
> `<TCR_REGISTRY>/<TCR_GROUP>/cndb:<version>`，与 TCR 历史版本同名。

**子账号最小权限**（访问管理 → 用户 → 新建子用户 → 编程访问 → 自定义策略）：

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": ["tat:RunCommand", "tat:DescribeInvocationTasks"],
      "resource": ["*"]
    }
  ]
}
```

只给这两条：`RunCommand` 下发命令、`DescribeInvocationTasks` 轮询结果。
不要给它 CVM/Lighthouse 的启停或删改权限 —— 部署只需要"在既有实例上跑一条命令"。

首次手动部署一次（在服务器上执行，不经过 CI）：

```bash
cd /opt/cndb && ./deploy/deploy.sh 0.3.0
```

**怎么确认自动化助手在线**：控制台 → 自动化助手 → 执行命令 → 选择实例，
能正常选到该实例即可（未装 agent 或 agent 掉线的实例会显示为不可用）。
若不可用，在实例上安装 agent 后重试，或改用控制台「发送命令」验证一次。

---

## 三、日常发布

> 启用反向代理后，发布流程不变：`deploy.sh` 会用 `--profile proxy` 一起更新应用与 nginx，并在部署末尾验证代理链路。

```bash
# 版本号在 pyproject.toml 与 CHANGELOG.md 同步更新后
git tag v0.3.1 && git push origin v0.3.1
```

推 tag 即触发 Release；`pypi` job 成功后自动调用部署 workflow（不再需要另起一条并行流水线抢跑）。
CI 打包配置载荷 → TAT 下发 → 服务器拉 wheel 并构建镜像 → 自动部署。

耗时预期：

- **常态发布**：上机段约 1-2 分钟（复用依赖基础镜像，只重建 wheel 薄层 + 健康探测），整体约 3-5 分钟；
- **首次部署 / `uv.lock` 变化**：多一次依赖基础镜像构建（约 1-3 分钟，只发生一次，后续版本继续复用）；
- 如果 TAT 日志里看到「重新构建依赖基础镜像」每次都在跑，说明依赖指纹没有稳定命中，
  检查 `dist/requirements.lock.txt` 是否被上游改成了非确定性内容（如带时间戳）。

GitHub Actions 页面可看实时进度（TAT 会把 `deploy.sh` 的日志回传到 job 日志里）；
失败会自动回滚并在日志中标明原因。

> 本仓库同时向 CodeUp 与 GitHub 推 tag，两条 release 流水线都会发布同一版本并各自
> 走 TAT 部署：`uv publish --check-url` 让后到的一方跳过重复上传；GitHub 的 deploy job
> 即使发现 pypi job 因重复发布而失败，也会继续从 PyPI 解析已发布的 wheel 完成部署。
> CodeUp 侧 `deploy_tencent` job 以 `needs: pypi` 串在发布之后，所用全局变量与 GitHub
> Secrets 同名同值（清单见 `.codeup/pipelines/release.yml` 头部注释）。
>
> ⚠️ 两条流水线各自部署同一台服务器，而服务器端 `deploy.sh` 没有互斥锁：同一 tag 下
> 二者可能并发执行、相互覆盖镜像与 `.env`。建议二选一只保留一侧的 deploy job，或给
> `deploy.sh` 加 flock 串行化。

**手动重跑**（不改代码重新部署）：

```
Actions → 左侧选择 "Deploy to Tencent Cloud" → Run workflow → 填入目标版本（必填，如 v0.3.0）
```

> 部署已改为由 Release 调用，正常发版只需要关注 `Release` 这一条流水线；
> `Deploy to Tencent Cloud` 仍保留手动入口，用于重跑或回滚到指定版本。

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
| 本机 curl 通、外网不通       | 安全组未放行端口；或单容器模式下 `.env` 的 `CNDB_BIND` 绑到了 `127.0.0.1`（反代模式下这是**预期值**，应转去排查 nginx 容器） |
| 日志刷 `no such column` | schema 漂移。应用启动时会自愈补列；若持续报错，备份后重建库                         |
| 附件 404               | 卷挂载异常，`docker volume inspect cndb-data` 确认 Mountpoint 有数据 |

### 反向代理起不来 / 80·443 打不开

```bash
docker ps -a --filter name=cndb-nginx     # 状态是 Up 还是 Exited
docker logs --tail 100 cndb-nginx         # 容器内 nginx 的启动报错
docker exec cndb-nginx nginx -t           # 配置语法自检
docker exec cndb-nginx tail -50 /var/log/nginx/error.log
ss -lntp | grep -E ':(80|443) '           # 端口是否被别的进程占着
```

| 现象 | 原因与处理 |
| --- | --- |
| `bind: address already in use`，容器起不来 | 宿主机已跑着原生 nginx 或别的 web 服务占着 80/443。按 4.1.1 停用它再部署（`systemctl stop nginx && systemctl disable nginx`） |
| 容器反复 `Exited (1)`，日志报 `directive invalid value` | 配置里写了**不会被 envsubst 替换**的 `${VAR}`（只对 `templates/*.template` 生效）。见 4.1.1 末尾说明 |
| 镜像拉不动 / `manifest unknown` | Docker Hub 不可达。用 `CNDB_NGINX_IMAGE` 换镜像源后重跑 `deploy.sh` |
| `certbot renew --dry-run` 失败 | webroot 没指到 `/opt/cndb/certbot-www`，或 80 端口未对 Let's Encrypt 开放（见 4.1.2） |
| 上了 HTTPS 后 HTTP 不再跳转 | `CNDB_SERVER_NAME` 填了域名，与 `ssl.conf` 的 80 跳转块撞名。改成 `_`（见 4.1.2 的说明） |

### 部署命令下发失败（TAT）

| 现象 | 原因与处理 |
| --- | --- |
| `FailedOperation.AgentNotInstalled` / agent offline | 实例没装自动化助手 agent 或已掉线。控制台「自动化助手」里确认该实例可用 |
| `InvalidParameterValue.InstanceIdNotFound` | `CNDB_INSTANCE_ID` 写错，或 `CNDB_REGION` 与实例实际地域不一致 |
| `AuthFailure` / `UnauthorizedOperation` | 子账号密钥错误，或策略缺 `tat:RunCommand` / `tat:DescribeInvocationTasks` |
| `命令内容超过 64 KiB` | 配置载荷过大。`scripts/build_tat_command.py` 会打印实际字节数；先看 `deploy/` 是否混入了 build 产物或备份文件 |
| 任务长时间 `RUNNING`，CI 等到 3300s | 服务器正在构建依赖基础镜像（首次或 `uv.lock` 变化，约 1-3 分钟）或正在下载 wheel。**CI 停止轮询不会中断实例上的任务**，任务仍会跑完；超过 10 分钟再上机看 `docker ps` / `docker images` |
| 实例输出被截断（日志里有 `Dropped` 字节数） | TAT 回传有长度上限。完整日志上机看：`docker logs --tail 200 cndb` |

### 服务器端构建失败

```bash
# 服务器上确认基础镜像可拉取（国内直连 Docker Hub 超时的常见根因）
time docker pull python:3.12-slim
# 看依赖基础镜像是否已就位（tag 形如 <仓库>-base:deps-<12位指纹>）
docker images --filter "reference=*cndb-base*"
# 手动复现构建（与 CI 等价，产物已在 /opt/cndb/dist）
cd /opt/cndb && SERVER_BUILD=1 IMAGE_REPO_OVERRIDE=ccr.ccs.tencentyun.com/pydev/cndb ./deploy/deploy.sh <版本号>
```

| 现象                                        | 原因与处理                                                     |
| ----------------------------------------- | ----------------------------------------------------------- |
| 构建卡在 `FROM docker.m.daocloud.io/...` 拉取（依赖基础镜像构建阶段） | 国内镜像代理不可达/滞后。配 registry-mirror（见「准备服务器」），或配 Secret `BUILD_BASE_IMAGE` 换源；脚本会自动用官方源整体重试一次 |
| 依赖基础镜像 pip / apt 安装 404 / 超时              | 镜像源滞后或缺包。默认 cn 走腾讯云源，失败自动用官方源整体重试；也可配 Secret `BUILD_PIP_INDEX_URL` 强制指定（避免阿里云等滞后源） |
| 应用镜像构建报依赖缺失 / `--no-index` 失败     | 基础镜像与锁定清单不一致（极少见）。删掉对应 `cndb-base:deps-*` 镜像后重跑，会重新构建基础镜像 |
| `缺少 dist/cndb-*.whl`                     | wheel 没下载下来。看 TAT 日志里「下载 wheel」那几行：国内镜像与官方源都失败通常是网络或版本未发布 |
| 构建 OOM（进程被 kill 137）                 | 服务器内存 <2G。加 swap 或升配                                   |
| 磁盘不足                                   | `docker system df` 看占用；deploy.sh 成功后自动回收：应用镜像保留最近 5 个 / 依赖基础镜像 3 个（`KEEP_APP_IMAGES`、`KEEP_BASE_IMAGES` 可调），另清悬空镜像并把 buildkit 缓存压到 3GB 内（`BUILD_CACHE_KEEP`），收尾打印系统盘水位（超 `DISK_WARN_PCT` 默认 80% 告警） |
| 冒烟验证失败（assets 为空）                  | wheel 未内嵌前端产物 —— 确认 release.yml 的前端构建成功后再重跑        |

### 版本回滚后仍异常

```bash
cd /opt/cndb
grep CNDB_IMAGE .env                              # 确认当前指向的版本
docker compose --env-file .env -f docker-compose.prod.yml up -d --force-recreate
```

### 磁盘满

镜像和日志是主要占用：

```bash
docker system df                                   # 查看占用分布（镜像 / 容器 / 卷 / 构建缓存）
docker image prune -f                              # 只删悬空镜像，安全
docker builder prune -f --keep-storage 3GB         # 压构建缓存，保留 3GB
docker volume ls                                   # 确认无误后再清理卷——卷里有你的数据
```

⚠️ 不要用 `docker image prune -a`：它会删除**所有**未被容器引用的镜像（含带 tag 的历史版本），
一回滚就找不到镜像了。deploy.sh 成功后已自动做上面三步的前两步，手动清理只在盘真的吃紧时补一刀。

`docker-compose.prod.yml` 已配 `json-file` 日志轮转（20m × 5 = 100MB 上限），  
不配的话日志会无限增长把盘写满。

---

## 七、安全清单

上线前逐项确认：

- [ ] `JWT_SECRET` 已替换为 `openssl rand -hex 32` 的随机值（CI 会校验占位符）
- [ ] `.env` 权限 `600`，且**不在 git 追踪中**（`.gitignore` 已含 `.env`）
- [ ] `DEBUG=false`
- [ ] 安全组只放行业务端口（反代模式为 `80`/`443`）；**部署已走 TAT，`22` 可以整条删掉**，只在需要人工维护时临时开、用完关
- [ ] 反代模式下应用端口**不对公网暴露**：`.env` 的 `CNDB_BIND` 为 `127.0.0.1:8000`，且安全组未放行 8000
- [ ] `CORS_ORIGINS` 收敛到自己的域名，不填 `*`（`allow_credentials=True` 时浏览器会直接拒绝）
- [ ] 定时备份已生效，且**实际验证过能恢复**
- [ ] TCR 命名空间设为私有（若仍保留 TCR 用于回滚）
- [ ] COS 桶（若启用了备份上传）为私有读写；子用户密钥仅授目标桶读写，且已配置生命周期清理
- [ ] CI 用的腾讯云子账号**只授 `tat:RunCommand` / `tat:DescribeInvocationTasks`**，不授实例启停与删除
- [ ] 主机安全的「异地登录」告警恢复为可信信号：确认近 30 天没有来自非本人 IP 的登录记录（改 TAT 后不应再产生告警）

> `AUTH_ENABLED=true` 是默认值且**不可关闭**（关闭意味着任何人都能读写全部数据）。  
> 首次部署后立刻登录并**修改默认账号密码** —— `cndb seed` 注入的 `demo/demo1234`  
> 是公开凭据，生产环境若跑过 seed 必须改掉。

---

## 八、离线部署（无外网隔离环境）

以上第一~七节都是**联网形态**：服务器自行 `docker build` 或 `docker pull`。若目标服务器
**无外网**（内网隔离、等保环境、无法访问 Docker Hub / PyPI / TCR），改用「本地构建 + 导出
交付包 + 离线加载」三段式，镜像全程不经网络：

```
联网构建机                          离线服务器
  build-image.sh   ──┐
  （本地构建镜像）     │  导出 dist/offline/cndb-<version>-offline-bundle.tar.gz
  export-image.sh  ──┘  （镜像 tar + compose + deploy/ + .env 模板 + SHA256SUMS）
                        │
                        ▼   scp / U 盘
                    tar -xzf cndb-<version>-offline-bundle.tar.gz
                    cd cndb-<version>-offline
                    OFFLINE=1 ./deploy/deploy.sh <version>
                        │  sha256sum -c → docker load → 预备份 → 重建 → 健康探测 → 失败回滚
                        ▼
                    单容器 / 反代模式（与联网部署完全一致）
```

### 8.1 在联网构建机：构建 + 导出

**前置产物**：`dist/cndb-<version>-*.whl` 与 `dist/requirements.lock.txt`
（在仓库根执行 `make build` 生成 wheel；锁定清缺失时脚本会尝试用 `uv` 生成）。

```bash
# 1) 本地构建：依赖基础镜像（字体 + 锁定依赖）+ 应用镜像；默认本地名 cndb:<version>
bash deploy/build-image.sh 0.3.0

# 2) 导出离线交付包（含 nginx 反代镜像；不需要时 WITH_NGINX=0）
bash deploy/export-image.sh 0.3.0
```

> 也可用 `make docker-build VERSION=0.3.0` / `make docker-export VERSION=0.3.0`。
> 仓库内 `deploy/*.sh` 以 644 入库（在线链路由 TAT 运行时 chmod），故本地一律用
> `bash deploy/xxx.sh` 调用；交付包内已由导出脚本补上执行位，离线机可直接 `./deploy/...`。

产出 `dist/offline/cndb-0.3.0-offline-bundle.tar.gz`，解包目录结构：

| 内容 | 说明 |
|---|---|
| `cndb-0.3.0-image.tar.gz` | 应用镜像（含依赖基础层，`docker load` 即得完整运行镜像） |
| `nginx-image.tar.gz` | nginx 反代镜像（`WITH_NGINX=1` 时；离线机启用 `--profile proxy` 用） |
| `docker-compose.prod.yml` | 生产编排（离线机直接复用） |
| `deploy/` | 部署脚本 + nginx 配置 + `.env` 模板 |
| `SHA256SUMS` | 关键载荷校验清单（`sha256sum -c`） |
| `OFFLINE-README.txt` | 包内快速上手说明 |

- 若要与在线镜像**同名**（用 registry 前缀），构建与导出两处都传同一个 `IMAGE_REPO`：

  ```bash
  IMAGE_REPO=ccr.ccs.tencentyun.com/pydev/cndb ./deploy/build-image.sh 0.3.0
  IMAGE_REPO=ccr.ccs.tencentyun.com/pydev/cndb ./deploy/export-image.sh 0.3.0
  ```

- 构建源码与服务器端构建**同一套** `deploy/Dockerfile.base` / `Dockerfile.prod`，依赖基础镜像
  指纹一致；离线机不需要重新构建，因此交付包**不单独导出基础镜像**（应用镜像已含其全部层）。

### 8.2 在离线服务器：加载 + 部署

离线服务器需具备 `docker`（含 `docker compose` v2），无需 `curl` / pip / 外网。

```bash
tar -xzf cndb-0.3.0-offline-bundle.tar.gz
cd cndb-0.3.0-offline

# 配置（CNDB_IMAGE 指向本地镜像名）
cp deploy/.env.prod.example .env
#   CNDB_IMAGE=cndb:0.3.0
#   JWT_SECRET=...（openssl rand -hex 32）
#   启用反代时：CNDB_ENABLE_PROXY=1、CNDB_BIND=127.0.0.1:8000、CNDB_NGINX_IMAGE=nginx:1.27-alpine

# 离线部署（脚本先校验 SHA256SUMS、docker load，再走预备份/重建/健康探测/失败回滚）
OFFLINE=1 ./deploy/deploy.sh 0.3.0
```

- `OFFLINE_DIR` 默认即交付包根目录（镜像 tar 与 `deploy/` 同级）；从别处执行可用
  `OFFLINE_DIR=/path/to/cndb-0.3.0-offline` 指定。
- 目标镜像 tag 由 `<version>` 参数决定，**须与导出的版本一致**（如导出 `cndb:0.3.0` 就传 `0.3.0`）。
- 无 `SHA256SUMS` 时跳过完整性校验（会有告警）；建议始终携带并先校验。

### 8.3 边界与注意

- **架构一致**：导出镜像限**构建机架构**（amd64 / arm64）。跨架构须在目标架构的机器上
  重新执行 `build-image.sh` + `export-image.sh`；本流程不做多架构镜像。
- **包体**：含依赖基础层与 nginx 镜像，数百 MB 量级，离线机与传输介质需预留空间。
- **同源演进**：`build-image.sh` 复用服务器端同一 `Dockerfile` 与依赖指纹，两者随版本
  同步演进；脚本只做编排，不重复定义构建。

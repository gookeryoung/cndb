# CNB 迁移落地手册

从 GitHub Actions 迁移到 CNB 云原生构建的配置说明与操作步骤。
配置入口：`.cnb.yml` + `.cnb/Dockerfile.ci`。

---

## 一、触发矩阵

| 触发 | 流水线内容 | 规格 | 目的 |
|---|---|---|---|
| `$.pull_request` | gitkeep + ruff + pyrefly + 前端 typecheck/lint/test | 2 核 | PR 快速反馈 |
| `main.push` | 快速门禁 + pytest 覆盖率(95%) + 前端 build + bundle budget | 4 核 | 合并前全量 |
| `v*.*.*.tag_push` | 前端 build → wheel → 推镜像(TCR+CNB) → 冒烟 → SSH 部署 | 2 核 | 打 tag 上线 |
| `$.api_trigger_e2e` | Playwright 全量 E2E | 4 核 | 手动，按需 |

手动触发 E2E：

```bash
curl -X POST "https://api.cnb.cool/gkzhou/cndb/-/runners/trigger?branch=main" \
  -H "Authorization: Bearer $CNB_TOKEN" \
  -d '{"pipelineName":"api_trigger_e2e"}'
```

---

## 二、省机时的四个决策

计费 ≈ `cpus × 容器存活时长`。

**1. 降配** — ruff / pyrefly / tsc 是单线程密集型，2 核足够，加核只涨账单不缩时间。
只有 pytest 覆盖率真正吃 CPU，给满 4 核（`-n 4` 匹配）。
E2E 从 GitHub 的「4 分片并行 + continue-on-error」降为**手动触发单容器不分片**：
分片要多起 4 个容器、且各自重复下载 150MB chromium，比串行更贵。

**2. 合并容器** — CNB 每个 pipeline 起一个容器、stage 串行。
装依赖与跑检查放同一容器，避免为装依赖单独付一次启动成本。
前后端门禁**故意串行而非并行**：串行失败立即中断，不会出现「前端白跑 5 分钟才发现后端挂了」。

**3. 缓存** — `docker.volumes` 的 `copy-on-write` 缓存 uv / pnpm store / ms-playwright，
依赖安装从 ~90s 降到 ~10s。镜像层缓存用 buildx `--cache-from/--cache-to type=registry`。

**4. 降频** — tag 流水线**不跑测试**。惯例是 main 全量门禁通过后才打 tag，
重复跑一遍纯属浪费机时。若团队习惯直接打 tag，需自行补一次门禁状态校验。

---

## 三、落地步骤

### 1. 创建主仓库并推送

```bash
git remote add cnb https://cnb.cool/gkzhou/cndb.git
git push cnb main
```

### 2. 创建密钥仓库（必须）

TCR 与 SSH 凭证**不能**写进主仓库——任何能读代码的人（含 fork、CI 日志、git 历史）都能拿到生产凭证。

1. CNB 上创建仓库 `gkzhou/cndb-secrets`
2. 复制 `deploy/cnb-secrets.example.yml` 内容进去，改名 `deploy-env.yml`，填真实值
3. 提交到 `main` 分支
4. 验证可读（imports 要求目标可匿名拉取）：

```bash
curl -sL https://cnb.cool/gkzhou/cndb-secrets/-/raw/main/deploy-env.yml
```

需要配置的变量：

```
TCR_REGISTRY     TCR 域名（不含命名空间，不带 https://）
TCR_GROUP        命名空间
TCR_USERNAME     tcr@cndb-deploy    ← 必须是 @ 不是 $
TCR_PASSWORD     服务账号密码
SSH_HOST         服务器公网 IP
SSH_PORT         SSH 端口，默认 22
SSH_USERNAME     登录用户，默认 root
SSH_PRIVATE_KEY  整段私钥原文（含 BEGIN/END 两行）
```

服务器 `/opt/cndb/.env` 里的 `CNDB_IMAGE` / `JWT_SECRET` / `CNDB_VOLUME`
**不放这里**——由 `deploy.sh` 在服务器本地原子更新，流水线只校验 `JWT_SECRET` 不是 `CHANGE_ME`。

### 3. 服务器初始化（仅首次）

```bash
mkdir -p /opt/cndb/deploy /opt/cndb/backups
cd /opt/cndb
cp <从主仓库取得的> deploy/.env.prod.example .env
vim .env        # 填 CNDB_IMAGE 与 openssl rand -hex 32 生成的 JWT_SECRET
```

流水线会拒绝在 `.env` 缺失或 `JWT_SECRET` 仍是 `CHANGE_ME` 时部署。

### 4. 服务器免密登录

```bash
ssh-keygen -t ed25519 -C cndb-deploy -f ~/.ssh/cndb_deploy -N ""
cat ~/.ssh/cndb_deploy.pub >> <服务器>/root/.ssh/authorized_keys
```

私钥内容填入密钥仓库的 `SSH_PRIVATE_KEY`。

---

## 四、配置中已处理的关键问题

| 问题 | 处理 |
|---|---|
| `$` 兜底分支块重复定义 | `pull_request` 与 `api_trigger_e2e` 合并到同一个 `$` 下。YAML 同名顶层键后者覆盖前者，分成两块会让 PR 门禁**静默消失** |
| 镜像构建重复 | 单次 `buildx build` 挂三个 tag（版本 / latest / CNB 制品库），原先为第二个仓库重跑一遍构建层 |
| buildx 导 cache 报 404 | 旧版 buildkit 已知问题，`--cache-to` 补 `image-manifest=true,oci-mediatypes=true` |
| 凭证误提交 | `.gitignore` 兜底忽略 `deploy-env.yml`，只放行 `.example` |
| 前端产物缺失导致线上白屏 | `main.push` 校验 `src/cndb/static/assets` 非空；tag 流水线推镜像后做容器内冒烟（`STATIC_DIR` 存在且 assets 非空） |
| 部署失败打挂线上 | 复用 `deploy/deploy.sh`：预备份 → pull → 重建 → 轮询 `/api/health` → 失败自动回滚到上一版本 |

---

## 五、已知限制

- **CNB 派发到 3 个构建节点**，节点本地缓存命中率约 1/3。
  若实际命中率低，可把缓存做成跨节点镜像（用 `.cnb/Dockerfile.ci` +
  内置 `docker:cache` 任务，`by: [uv.lock, frontend/pnpm-lock.yaml]`）。
- tag 流水线**不做测试**，依赖「main 全量门禁通过后才打 tag」的流程约定。
- 密钥仓库需公开可读才能被 `imports` 拉取；CNB 若支持密钥仓库授权模式，可改用私有 + 授权。
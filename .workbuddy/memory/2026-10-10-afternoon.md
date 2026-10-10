# 2026-10-10（下午）

## 决策：放弃 CNB，回到 GitHub Actions

**用户判断正确。** CNB 迁移一天暴露的问题，是复杂度本身带来的：

- 认证全靠裸 shell：`imports` 官方示例路径是错的（`/-/blob/` 返回 HTML），
  `docker login` 从 Actions 的封装迁移过来时整段丢失
- 密钥必须放**公开仓库**（私有仓库 `imports` 拿不到，实测 404）
- 流水线报错不可读：要把 runner 日志下载到本地文件才能分析

**GH 的不可替代优势**：公开仓库 Actions 免费；`docker/login-action`、
`scp-action`、`ssh-action` 等封装把认证/传输都做好了；Secrets UI 逐条可见。

### 清理清单

已删除：`.cnb.yml`、`.cnb/Dockerfile.ci`、`deploy/cnb-secrets.example.yml`、
`docs/CNB.md`、`.gitignore` 里的 deploy-env.yml 规则、`cnb` git remote。

保留：`deploy/bootstrap-server.sh`（与 CI 平台无关，服务器初始化仍需要）、
`.workbuddy/memory/` 里的 CNB 技术备忘录（避坑记录，有复用价值）。

### 顺手修掉的 GitHub Actions 真实缺陷

**`deploy-tencent.yml` 对个人版 TCR 会推镜像失败**：
原写法 `${{ secrets.TCR_REGISTRY }}/cndb`，若 registry 填 `ccr.ccs.tencentyun.com`
则拼出 `ccr.ccs.tencentyun.com/cndb`，**少了命名空间 `pydev`**。

修法（两段解析）：
```
Resolve TCR host   → HOST="${TCR_REGISTRY%%/*}"，login 只用主机名
Resolve image ref  → PREFIX="${TCR_REGISTRY}/${TCR_GROUP}/cndb"，三处统一引用
```
`TCR_GROUP` 为空时立即报错，不让坏地址流到 buildx。

> 用户自己加的 `Resolve TCR host` 方向比我原方案好：不另设 Secret，
> 域名只填一处避免不一致。但它原本的校验 `[ "$HOST" = "$TCR_REGISTRY" ]` 有 bug ——
> 纯域名填法（不带路径）会被**直接判为错误拦下**。已改为两种填法都接受。

另修：`Sync deploy scripts` 漏了 `bootstrap-server.sh`（首次初始化靠它）；
同步列表从逗号分隔字符串改为数组（scp-action 多源路径扁平化行为有版本差异）。

### GitHub Secrets 现状

```
TCR_REGISTRY     = ccr.ccs.tencentyun.com      # 纯域名，也接受带 /pydev 的形式
TCR_GROUP        = pydev                        # 命名空间（新 secret）
TCR_USERNAME     = tcr@xxx# @ 不是 $
TCR_PASSWORD     = ***
SSH_HOST/PORT/USERNAME/PRIVATE_KEY
SERVER_URL
```

## 迁移到 CNB 的经验教训（下次如需迁移再用）

1. **`imports` URL 必须是 `/-/git/raw/<ref>/<path>`** —— 官方示例的 `/-/blob/`
   和直觉的 `/-/raw/` 都返回 HTML 页面。判定法：`curl <url> | head -c 200`
   看到 `<!DOCTYPE html>` 就是错了。
2. **CNB 密钥仓库必须公开可读**，私有报 `Secret repos do not support token access`。
3. **从 Actions 迁移最易丢的是认证步骤** —— action 封装了 login，裸 shell 不会自动补。
4. **`runner.cpus` 生效可见**：构建记录 `labels` 里有 `ARCH=amd64,cpus=4,memory=8`
   （内存 = cpus × 2GB）。计费 ≈ cpus × 容器存活时长，`prepare` 阶段排队不计费。
5. **`docker.build` 会真正构建 Dockerfile**，不像 Actions 那样容错。
   本次连续 3 次失败都在 Dockerfile 层，且都无法靠 YAML 校验发现。
6. **CDN 缓存会骗人**：文件刚推上去时 curl 仍返回旧的 404 HTML。
   判断文件是否真在远端用 `cnb git get-content`（走 API 不走 CDN）。
7. **同一提交会触发 `issue.comment@npc`** —— CNB 的 NPC AI 助手自动跑一条 8 核流水线，
   不在配置范围内，纯浪费。要在网页端关闭。

## 环境限制（本机）

- `cnb.cool:22` 不可达，只能 HTTPS；本机 CA 链不完整，需 `GIT_SSL_NO_VERIFY=true`
- 大仓库 push 很慢（10817 objects / 13.45 MiB），120s/200s 均 SIGTERM。
  可靠做法：`GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30` + timeout 280s
- CNB token 缺 `group-resource:rw`，无法用 API 建仓
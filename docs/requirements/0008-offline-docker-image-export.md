# 需求卡片：离线部署镜像导出

- 编号：0008（与 ADR `docs/adr/0008-offline-docker-image-export.md` 同号，卡片存 `docs/requirements/0008-offline-docker-image-export.md`）
- 来源 / 提出人：项目负责人（工作区需求）
- 日期：2026-10-20
- 关联 ADR：[ADR 0008](../adr/0008-offline-docker-image-export.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请完善项目Docker配置，并增加导出本地镜像的脚本，用于后续离线部署。

> 需求澄清（2026-10-20，需求方逐项确认，本卡唯一副本）：
> ① 构建与导出走**本地脚本**（联网开发机/构建机），不依赖 CI；
> ② 离线交付包含**应用镜像 tar + nginx 反代镜像 + compose + deploy 脚本 + .env 模板 + sha256 校验清单**；
> ③ 离线服务器部署入口**扩展现有 `deploy/deploy.sh`**（离线模式），不新增独立部署脚本。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 增加导出本地镜像的脚本 | 提供联网机器可执行的脚本：本地构建 cndb 应用镜像（依赖基础层 + 应用层，**复用** `deploy/Dockerfile.base` / `deploy/Dockerfile.prod`），再 `docker save` 导出为压缩 tar | `deploy/build-image.sh`、`deploy/export-image.sh` | 本地执行产出 tar；`bash -n` 语法自检；解包后 `docker load` 可加载 |
| C2 | 用于后续离线部署 | 导出的镜像在**无出网**服务器上 `docker load` 后即可运行，全程不依赖 registry / pip / Docker Hub | `docker-compose.prod.yml`、`deploy/deploy.sh` | 断网演练：仅 `docker load` + `up -d` 起服务并通过 `/api/health` |
| C3 | 交付包内容（需求澄清 ②，原文外补充） | 离线交付包 = 应用镜像 tar + nginx 反代镜像 tar + `docker-compose.prod.yml` + `deploy/` 脚本 + `.env` 模板 + `SHA256SUMS` 校验清单 | `deploy/export-image.sh` | 解包目录清单核对；`sha256sum -c` 通过 |
| C4 | 完善项目Docker配置 | `deploy.sh` 增加**离线模式**：镜像源为本地已 load 镜像时跳过 registry 地址校验与 `docker pull`，仍走预备份 / 重建 / 健康探测 / 失败回滚 | `deploy/deploy.sh` | 离线模式部署成功且失败可回滚；在线模式行为回归不变 |
| C5 | 完善项目Docker配置 | 镜像命名支持**无 registry 前缀**的本地 tag（如 `cndb:0.3.0`）；compose 的 `${CNDB_IMAGE}` 与 nginx 镜像地址可指向本地名 | `docker-compose.prod.yml`、`deploy/.env.prod.example` | 用本地 tag 的 `.env` 能起容器 |
| C6 | 完善项目Docker配置 | 本地构建复用仓库根 `.dockerignore` 作为构建上下文过滤，不再生成临时覆盖文件（避免双份漂移与遗漏） | `.dockerignore`、`deploy/build-image.sh` | 构建上下文内容符合预期，仓库 `.dockerignore` 未被改写 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 镜像获取仅两条**联网**路径（服务器本地构建 / TCR pull） | `deploy/deploy.sh:349` | 离线服务器两条均不可用 → 无法部署 |
| 2 | registry 地址强校验（要求含 `/`） | `deploy/deploy.sh:108` | 本地 tag（`cndb:0.3.0`）被直接拒绝 |
| 3 | 依赖基础镜像按指纹复用 / 构建 | `deploy/deploy.sh:253` | 需被本地构建路径复用 |
| 4 | 构建上下文临时覆盖 `.dockerignore` | `deploy/deploy.sh:310` | 与仓库 `.dockerignore` 形成双份，易漂移 |
| 5 | compose 镜像引用已参数化 | `docker-compose.prod.yml:28` | 已支持 `${CNDB_IMAGE}` / nginx `${CNDB_NGINX_IMAGE}`（:81），离线只需 `.env` 指向本地名 |
| 6 | 无本地构建入口 | `Makefile`（无 docker 目标） | 需新增脚本入口 |
| 7 | 文档仅描述联网部署 | `docs/DEPLOY_TENCENT.md`、`README.md:43` | 缺离线章节 |

## 未决问题

- [x] ~~构建 / 导出在哪执行~~ → 需求方确认：本地脚本，本轮不走 CI
- [x] ~~交付包内容~~ → 需求方确认：应用镜像 + nginx 镜像 + compose + deploy 脚本 + .env 模板 + sha256 清单
- [x] ~~离线部署入口形态~~ → 需求方确认：扩展 `deploy.sh`（离线模式），不新增独立部署脚本
- [x] ~~是否纳入 CI / 自动化~~ → 本轮不纳入；后续如需可复用同一脚本在 CI 产出 Release 资产（ADR D1 被否决项留档）

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

# ADR 0008: 离线部署镜像导出

Status: Accepted
Date: 2026-10-20
Related: `docs/DEPLOY_TENCENT.md`、`README.md`（`deploy/Dockerfile.base`、`deploy/Dockerfile.prod`、`docker-compose.prod.yml`、`deploy/deploy.sh`、`deploy/.env.prod.example`）
需求卡片: `docs/requirements/0008-offline-docker-image-export.md`（需求原文与约束编号的唯一副本）

> 需求变更时**先改本 ADR 再改代码**：删去失效的口径行 / 现状条目 / 决策 D 行 / 测试与分期，不留「历史方案」「以后备用」段落；整节不适用写「无」。ADR 被新方案替代或需求作废时**直接删除本文件**，同步删除 `docs/adr/README.md` 索引行与代码 / 文档中的引用（git 历史可追溯），不在仓库保留 `Superseded` / `Deprecated` 文档；编号不复用。

## 口径（需求 → 设计落点）

需求原文：见需求卡片 §需求原句（逐字，ADR 不复制第二份）。

卡片约束沿用各自编号（C1..Cn），本表只补「设计怎么落地」，不重新拆句：

| 卡片约束 # | 需求片段（引用） | 本设计的落地 |
|---|---|---|
| C1 | 增加导出本地镜像的脚本 | 新增 `deploy/build-image.sh`（联网机本地构建：依赖基础镜像 + 应用镜像）与 `deploy/export-image.sh`（`docker save` → 离线交付包） |
| C2 | 用于后续离线部署 | 离线机 `docker load` 本地 tar 后，`deploy.sh` 离线模式起服务；全程零出网（不 pull、不 pip、不连 Docker Hub） |
| C3 | 交付包内容（需求澄清 ②） | `export-image.sh` 产出 `cndb-<version>-offline-bundle.tar.gz`，内含应用镜像 tar + nginx 镜像 tar + `docker-compose.prod.yml` + `deploy/` + `.env.prod.example` + `SHA256SUMS` |
| C4 | 完善项目Docker配置（离线模式） | `deploy.sh` 增加 `OFFLINE=1`：跳过 registry 校验（:108-121）与 `docker pull`（:360-384），直接用本地镜像，保留预备份 / 健康探测 / 回滚 |
| C5 | 完善项目Docker配置（本地命名） | 镜像 tag 支持无 registry 前缀（默认 `cndb:<version>`）；compose 的 `${CNDB_IMAGE}` / `${CNDB_NGINX_IMAGE}` 指向本地名即可，文件无需改 |
| C6 | 完善项目Docker配置（构建上下文） | `build-image.sh` 复用仓库根 `.dockerignore`，不再像 `deploy.sh:310` 那样生成临时覆盖文件 |

决策结论只在「决策记录」写一次；本节与正文不再罗列「已确认决策」。

## Context

现状逐条核对（以代码为准，标注 `文件:行号`）。沿用卡片「现状影响面」的编号，逐条给结论。

| # | 现状 | 位置 | 影响 | 与卡片的关系 |
|---|---|---|---|---|
| 1 | 镜像获取只有两条路径：`SERVER_BUILD=1` 服务器本地构建，或 TCR `docker pull` | `deploy/deploy.sh:349`、`deploy/deploy.sh:360` | 两者都要求目标服务器**能出网**（pip / Docker Hub / TCR），隔离环境无法部署 | 确认 |
| 2 | `BASE_REPO` 强校验必须含 `/`（否则会被解析成 `docker.io/library/cndb` 而报错退出） | `deploy/deploy.sh:108` | 本地 tag `cndb:0.3.0` 会被拒，离线无法用本地名 | 确认 |
| 3 | 依赖基础镜像按 `requirements.lock.txt` + `Dockerfile.base` 指纹复用 / 构建，应用层只装 wheel | `deploy/deploy.sh:253` | 该两段式构建应被本地构建路径**原样复用**，避免第二套定义 | 确认 |
| 4 | 构建时用 `printf` 生成临时 `.dockerignore` 覆盖仓库根同名文件 | `deploy/deploy.sh:310` | 与仓库 `.dockerignore`（已较完整）形成双份，易漂移；本地构建若沿用会污染工作区 | 确认 |
| 5 | compose 镜像地址均为变量注入：应用 `${CNDB_IMAGE}`、nginx `${CNDB_NGINX_IMAGE}` | `docker-compose.prod.yml:28`、`docker-compose.prod.yml:81` | 已参数化，离线只需 `.env` 指向本地名，**无需改本文件** | 排除（无需改） |
| 6 | 无本地构建入口（`Makefile` 无 docker 相关目标；`deploy.sh` 面向服务器执行） | `Makefile` | 需新增联网机可执行的脚本入口 | 确认 |
| 7 | 文档只描述联网部署链路 | `docs/DEPLOY_TENCENT.md`、`README.md:43` | 缺离线部署章节与交付包说明 | 新增 |

**核心缺陷（需求要补的）**：现有模型只有「服务器本地构建」与「TCR pull」两种取镜像方式，两者都要求目标服务器能出网；对无外网的隔离环境**没有任何取镜像通道**。

设计目标（不变量）：

- **I1 离线零出网**：离线服务器仅凭 `docker load` 本地 tar 即可完成部署，不触发任何出网动作。
- **I2 同源同构**：离线镜像与在线镜像来自同一 `Dockerfile.base` / `Dockerfile.prod` 与同一依赖指纹机制，不是第二套构建定义。
- **I3 增量不改存量**：在线链路（`SERVER_BUILD=1` / TCR pull）的行为与产物不变，离线能力为纯增量。

## Decision

### 1. 数据模型

无（本需求为部署工具链改动，不涉及 cndb 包内数据模型 / 表 / 迁移）。

### 2. 判定算法（唯一入口）

无。

### 3. API 变更清单

无。

### 4. 边界与例外

1. **本地 tag 放行**：`OFFLINE=1` 时跳过 `BASE_REPO` 含 `/` 的校验（现状 #2）；镜像 tag 允许 `cndb:<version>` 形式。
2. **proxy 依赖**：启用 `CNDB_ENABLE_PROXY=1` 但本地无 nginx 镜像 → 明确报错退出并提示先 `docker load` nginx 镜像；不静默失败。
3. **架构一致性**：导出镜像仅限**构建机架构**（amd64/arm64）。跨架构目标须在目标架构机重新构建导出；不做 `buildx` 多架构（本轮范围外）。
4. **完整性校验**：离线机 `load` 前先 `sha256sum -c SHA256SUMS`，校验失败即中止。
5. **磁盘**：交付包含基础层，包体较大（数百 MB），文档提示预留空间。

### 5. 迁移

无（不涉及数据库迁移）。

### 6. 前端

无。

### 7. 测试清单

不涉及 cndb 包内代码，**不进后端覆盖率口径**（`make cov` 只统计 `cndb` 包）。脚本验收方式：

**静态**：`bash -n deploy/build-image.sh deploy/export-image.sh deploy/deploy.sh`（语法自检）。

**端到端演练（本地有 docker 环境时人工执行）**：
- 构建 → 导出：`build-image.sh` 产出应用镜像；`export-image.sh` 产出 `offline-bundle.tar.gz` 与 `SHA256SUMS`。
- 传输模拟 → 加载：解包后 `sha256sum -c` 通过；`docker load` 成功且镜像 tag 与 `.env` 一致。
- 离线部署：`OFFLINE=1 ./deploy/deploy.sh <version>` 起容器，`/api/health` 返回 200。
- 失败回滚：故意指向不存在的本地镜像，验证回滚到上一版本。

**回归**：非 `OFFLINE` 路径（`SERVER_BUILD=1` / TCR pull）行为不变（CI 触发或人工复跑一次部署）。

### 8. 分期

| 期 | 内容 | 风险 |
|---|---|---|
| **P0** | `deploy/build-image.sh`（本地构建基础 + 应用镜像）+ `deploy/export-image.sh`（导出离线交付包 + `SHA256SUMS`） | 低 |
| **P1** | `deploy.sh` 离线模式（`OFFLINE=1`）：跳过 registry 校验 / pull，加载校验，保留预备份 / 健康探测 / 回滚 | 中 |
| **P2** | 文档：`docs/DEPLOY_TENCENT.md` 离线章节 + `README.md` 相关文件表新增行 | 低 |

## 决策记录（唯一决策台账）

| # | 议题 | 结论 | 依据 | 被否决项（及理由） | 代码落点 |
|---|---|---|---|---|---|
| D1 | 整体方案：镜像在哪构建、如何到达离线机 | 联网机**本地脚本**构建 + `docker save` 导出 tar → 离线机 `docker load` | 离线机无出网；需求方指定本地脚本 | ① CI 产出 Release 资产（未选：需求方本轮只要本地脚本）② COS 中转传镜像（环节多、计费；历史已弃用，见 DEPLOY_TENCENT.md 头部） | `deploy/build-image.sh`、`deploy/export-image.sh` |
| D2 | 离线交付包内容 | 应用镜像 tar + nginx 镜像 tar + compose + `deploy/` + `.env` 模板 + `SHA256SUMS` | 需求方确认（澄清 ②）；自含包避免离线机再靠外部同步文件 | 仅应用镜像（`--profile proxy` 反代无法离线启用） | `deploy/export-image.sh` |
| D3 | 离线部署入口形态 | 扩展 `deploy.sh`：新增 `OFFLINE=1` 分支 | 复用其预备份 / 健康探测 / 失败回滚，避免逻辑重复 | 新增独立 `offline-deploy.sh`（与 `deploy.sh` 重复维护） | `deploy/deploy.sh` |
| D4 | 是否单独导出依赖基础镜像 | 否 | 应用镜像的 `docker save` 已含其全部基础层，离线机不重建基础镜像 | 同时导出 base（增大包体且离线机不会用到） | `deploy/export-image.sh` |
| D5 | 构建上下文过滤 | 复用仓库根 `.dockerignore`，不生成临时覆盖 | 消除双份定义漂移；本地构建不污染工作区 | 沿用 `deploy.sh:310` 的临时覆盖写法 | `.dockerignore`、`deploy/build-image.sh` |
| D6 | 镜像命名 | 支持无 registry 本地 tag（默认 `cndb:<version>`），仍可传 `IMAGE_REPO` 生成 registry 名与在线同名 | 离线机无 registry | 强制 registry 前缀（离线场景无意义） | `deploy/build-image.sh`、`deploy/deploy.sh` |

门禁：`Proposed` → `Accepted` 前本表不得有「待定」；结论只在本书出现，别处只引用编号。

## Consequences

- **正向**：隔离 / 无外网环境获得完整部署通道；交付包自含（镜像 + 编排 + 脚本 + 校验清单），离线机「解包即部署」。
- **负向**：多一条需人工维护的导出链路，须随 `deploy.sh` 演进同步；包体较大（含依赖基础层 + nginx 镜像，数百 MB）。
- **风险与缓解**：跨架构镜像不可直接复用 → 在目标架构机构建 / 导出；脚本与 `deploy.sh` 逻辑漂移 → 复用同一 `Dockerfile` 与依赖指纹，脚本只做编排；脚本无 shellcheck/lint 门禁 → 以 `bash -n` + 人工端到端演练把关。

被否决的替代方案见「决策记录」对应行，此处不重复。

## 与既有 ADR 的关系（可选）

无。

## 落地状态（随实现更新）

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `deploy/build-image.sh`、`deploy/export-image.sh` | `tests/test_deploy_scripts.py` | — |
| P1 | 已落地 | `deploy/deploy.sh` | `tests/test_deploy_scripts.py` | — |
| P2 | 已落地 | `docs/DEPLOY_TENCENT.md`、`README.md`、`Makefile` | `tests/test_deploy_scripts.py` | — |

> 状态只取「未开始 / 进行中 / 已落地」。标「已落地」的期必须有代码落点与测试文件；全期落地后由人确认 `Status` 是否改 `Accepted` / `Implemented`。`make adr-check` 会校验本表与代码、测试、CHANGELOG 的对应关系。

## 交接（会话结束更新）

- 当前阶段：P0-P2 已落地，ADR 已由需求方评审通过（`Accepted`）
- 已完成：需求卡片与本 ADR；`deploy/build-image.sh`（本地构建）、`deploy/export-image.sh`（导出离线交付包）、`deploy/deploy.sh` 的 `OFFLINE=1` 离线加载；`Makefile` 的 `docker-build` / `docker-export`；`docs/DEPLOY_TENCENT.md` 第八节「离线部署」；`.dockerignore` 排除 `dist/offline`；脚本回归测试 `tests/test_deploy_scripts.py`
- 下一步：人工在联网机执行一次「构建 → 导出 → 解包 → 离线 `OFFLINE=1` 部署」端到端演练并回填提交 sha
- 已知坑：脚本不在 cndb 包覆盖率口径内（`make cov` 只统计 `cndb` 包），由 `bash -n` 静态检查 + `tests/test_deploy_scripts.py` 假 docker 桩 + 人工演练把关；导出镜像受构建机架构限制（跨架构需在目标架构机重建）；离线机磁盘需容纳数百 MB 交付包
- 最近一次全绿：`make check-fast`（含 `adr-check`）@ 待评审后回填（YYYY-MM-DD）

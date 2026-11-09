# 需求卡片：示例工作区包（本地/私有部署自助演示）

- 编号：0106
- 来源 / 提出人：用户（2026-11-05）
- 日期：2026-11-05
- 关联 ADR：沿用 `docs/adr/0029-help-docs-refactor.md`（帮助示例底座）与 `docs/adr/0075-workspace-full-backup.md`（归档导入）；本期为 S1，无新 ADR

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 项目 make seed 每次要覆盖用户已有数据，有无更好的方法实现演示功能。是融入帮助文档提供示例数据包，还是提供演示用户账号？

补充确认（2026-11-05）：演示功能面向**本地/私有部署用户自助试用**，不用于线上公开演示站。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | `make seed` 每次要覆盖用户已有数据 | `seed` 退回开发 / e2e 夹具：目标库已有任何用户或工作区时默认拒绝执行并提示改用帮助示例；仅显式 `--force` 才重建。开发 / e2e 环境（空库）行为不变 | `src/cndb/cli/seed/runner.py`、`src/cndb/cli/main.py`、`Makefile` | 单测：空库可 seed、非空库退出码非 0、`--force` 可覆盖 |
| C2 | 融入帮助文档提供示例数据包 | 以 `examples/datasets` 的销售 / 科研两套场景生成**完整工作区归档**（表 + 字段 + 视图 + 文档 + 分析模板 + 流水线 + 结构设计），随 wheel / fspack 发布；归档不含数据源密钥 | `examples/demo-packs/`、`pyproject.toml`、`scripts/` | 归档可被 `parse_workspace_archive` 解析；构建脚本可复现生成 |
| C3 | 提供示例数据包而非账号 | 帮助页「典型示例」提供「创建示例工作区」：登录用户在**自己名下新建**工作区，不修改、不覆盖任何既有工作区；同名重复创建自动加后缀区分 | `src/cndb/plugins/help/`、`frontend/src/pages/help/content/ExamplesSection.tsx` | 接口测试：创建后 owner 为当前用户、既有工作区行数不变；重复创建名称不冲突 |
| C4 | 还是提供演示用户账号 | 本地 / 私有部署**不新增演示账号**；`demo` 账号不随示例包创建。独立线上演示站另议，不纳入本期 | `src/cndb/cli/seed/runner.py` | 代码审查：示例工作区创建路径不建用户 |
| C5 | 演示功能 | 零数据模型 / 迁移变更；归档导入复用 ADR 0075 的 `parse_workspace_archive` + `import_backup_into_workspace`（表 / 字段 / 行 / 文档 ID 重映射），不新建第二套导入链路 | `src/cndb/plugins/workspaces/services/`、`src/cndb/plugins/help/` | 复用现有 `tests/test_workspace_backup_v9.py` 往返口径；新接口测试 |
| C6 | 数据包可用性 | 归档资产缺失（wheel 裁剪 / 本地删文件）时：示例清单仍可读，创建接口返回明确 404 与可读提示，不 500；资产只按清单白名单读取 | `src/cndb/plugins/help/services/assets.py` | 接口测试：删资产后清单 200、创建 404 |
| C7 | 演示功能 | 仅登录用户可创建；归档名 / 场景 key 白名单校验；不透出服务器路径；创建失败整体回滚，不残留半成品工作区 | `src/cndb/plugins/help/routers/examples.py`、`workspaces` 导入服务 | 接口测试：未登录 401、未知场景 404、导入失败无残留工作区 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | `seed` 第一段整库 `drop_all` + `create_all`，天然破坏 | `src/cndb/cli/seed/runner.py:35-42` | 用户演示误用的根因 |
| 2 | `make seed` 目标是默认数据库，不区分环境 | `Makefile:53`、`src/cndb/core/config.py:151-154` | `CNDB_DATA_DIR` 可切换，但无数据保护 |
| 3 | 帮助示例只有 CSV 下载，无完整工作区 | `src/cndb/plugins/help/routers/examples.py`、`services/assets.py` | 缺视图 / 文档 / 分析 / 模板，演示价值低 |
| 4 | ADR 0029 D7 明确「不做一键导入」，C6 口径为「图文 + CSV 下载」 | `docs/adr/0029-help-docs-refactor.md:21,207` | 本期扩展须同步清理该口径，改为由 0106 承接 |
| 5 | 工作区归档导入已实现且重映射 ID，前端「导入为新工作区」可用 | `src/cndb/plugins/workspaces/routers/workspaces.py:574-653`、`services/backup_io.py:107-118` | 直接复用，不新建链路 |
| 6 | 打包只包含 `examples/datasets`，未包含归档资产目录 | `pyproject.toml:88`、`:112`、`:120` | 需补 `examples/demo-packs` |
| 7 | 帮助示例前端只渲染清单与下载链接 | `frontend/src/pages/help/content/ExamplesSection.tsx` | 需新增创建入口与结果反馈 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 归档生成时机：发布前由 `scripts/build_demo_packs.py` 生成并提交到 `examples/demo-packs/`，随 wheel / fspack 打包；日常开发不重新生成 —— **已确认**
- [x] seed 防误伤判定口径：目标库已有任意用户或工作区即视为「有数据」，默认拒绝；空库（首次 / e2e 临时库）直接执行 —— **已确认**
- [x] 创建后的落点：接口返回新工作区 ID，前端提示成功并跳转到该工作区 —— **已确认**
- [x] 是否保留 CSV 下载：保留，供用户只想要原始数据时使用；示例包是完整版补充 —— **已确认**

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

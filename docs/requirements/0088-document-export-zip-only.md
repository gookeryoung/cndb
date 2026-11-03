# 需求卡片：文档树导出只保留压缩包（.zip），移除文件夹方式

- 编号：0088
- 来源 / 提出人：用户（会话 2026-11-03）
- 日期：2026-11-03
- 关联 ADR：无（S1，方案并入本卡片；上游需求 0072）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。
> 本需求收窄了 0072 的范围：0072 的「文件夹（纯 Markdown）」导出方式作废，只保留压缩包导出。

## 需求原句（逐字）

> 导出文档，应当首先支持压缩包文件，默认.zip格式；移除文件夹选项。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「应当首先支持压缩包文件，默认.zip格式」 | 文档树导出只产出 `.zip`：`<库名>/<文件夹>/<标题>.md` + front-matter + `attachments/` + 最小 `.obsidian/` 配置；文件名 `{工作区名}-obsidian-{YYYYMMDD-HHMM}.zip`（`Content-Disposition` 给 `filename*`） | `documents/services/obsidian.py`、`documents/routers/vault.py` | 后端单测：zip 结构 / 文件名格式 / 空工作区 400 |
| C2 | 「移除文件夹选项」 | 移除「文件夹（纯 Markdown）」导出方式（无 front-matter、无 `.obsidian/`）与后端 `style` 参数分支；导出按钮不再弹窗选方式，点击即下载 zip | `documents/routers/vault.py`、`frontend/src/api/documents.ts`、`frontend/src/pages/documents/DocumentsPage.tsx` | 前端单测：点导出直接请求 `/export/vault`（不带 `style`）、下载名取自响应头、无选择弹窗；后端单测：多余 `style` 参数不再改变产物 |
| C3 | （清理口径） | 死代码与文档同步：`EXPORT_STYLES` / `style` 分支 / 「文件夹（Markdown）」弹窗与用例全部删除；需求 0072 卡片收窄为「压缩包导出（Obsidian 库格式）」，CONTEXT 术语与 CHANGELOG 更新；`GET /export/vault` 不带 `style` 时行为不变 | `docs/requirements/0072-document-export-dialog.md`、`CONTEXT.md`、`CHANGELOG.md`、前后端测试 | `make check-docs` / `make flow` |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 导出方式弹窗（文件夹 / Obsidian 库） | `frontend/src/pages/documents/DocumentsPage.tsx`（导出 Modal） | C2 删除整块，按钮直接下载 |
| 2 | 导出 API 封装带 `style` 参数 | `frontend/src/api/documents.ts`（`vaultExport`） | C2 去掉参数 |
| 3 | 后端导出 `style` 分支与文件名 `kind` | `src/cndb/plugins/documents/services/obsidian.py`（`EXPORT_STYLES` / `export_vault`） | C1/C2 收敛为单一格式 |
| 4 | 导出路由 `style` 查询参数 | `src/cndb/plugins/documents/routers/vault.py` | C2 删除参数（未知查询参数被忽略） |
| 5 | 既有 0072 用例（folder style / 未知 style 400） | `tests/test_documents_obsidian_vault.py`、`frontend/src/api/documents.vault.test.ts`、`frontend/src/pages/documents/DocumentsPage.test.tsx` | C2/C3 同步改写 |

## 未决问题（已确认）

- [x] ① 是否同时删除后端 `style=folder` 能力：**结论**删除（不再有调用方，保留即死代码）；外部带 `style` 参数仍成功导出 obsidian 格式，不报错。
- [x] ② 是否保留导出弹窗：**结论**不保留（只剩一种格式，弹窗无选择意义），按钮点击即下载。
- [x] ③ 方案分级：**结论**S1（跨前后端的行为收窄 + 死代码清理，无数据 / 权限口径变化）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-03 用户口述需求，按最小改动实现）

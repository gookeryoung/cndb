# 需求卡片：文档树压缩包导出（原「导出方式选择弹窗」）

- 编号：0072
- 来源 / 提出人：用户（会话 2026-10-30）
- 日期：2026-10-30
- 关联 ADR：无（S1，方案见本卡片「口径」节）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐句）

> 文档导出，弹出对话框选择导出方式，包括文件夹和Obsidian库（实际为对应压缩包）。导出压缩文件的命名请参考其他导入导出的统一风格。

**2026-11-03 需求变更（需求 0088）**：导出方式改为「压缩文档（默认，纯文档树）」与「Obsidian 库（front-matter + `.obsidian/`）」两种，均为 `.zip`；原「文件夹（纯 Markdown）」方式作废。同时修正原件族被导出为空 Markdown 的缺陷——PDF / Office / 图片 / MHTML 等按原件字节与原始扩展名导出。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 导出压缩包（两种方式） | 文档页「导出」弹窗提供「压缩文档（默认，纯文档树）」与「Obsidian 库（front-matter + 最小 `.obsidian/`）」两种，均为 `.zip`；确认后下载 | frontend `DocumentsPage.tsx`、`api/documents.ts` | 前端单测（默认压缩文档 / 切换 obsidian / 下载命名） |
| C2 | 原件族原样导出 | PDF / Excel / Word 存档 / PPT / 图片 / MHTML 按原件字节与原始扩展名写入压缩包，不转空 Markdown；缺失原件跳过 | backend `services/obsidian.py` | 后端单测（原字节回读 / 无空 md / 同名共存） |
| C3 | 文档树结构 | `<工作区名>/<文件夹>/<标题>.md` + `attachments/`；压缩文档无 front-matter / 无 `.obsidian/`，Obsidian 库带；可见性裁剪与正文一致 | backend `services/obsidian.py`、`routers/vault.py` | 后端单测（两种方式结构 / 回环导入 / 空文档报错） |
| C4 | 命名参考其他导入导出的统一风格 | zip 文件名由后端生成：`{工作区名}-documents-{YYYYMMDD-HHMM}.zip`（压缩文档）/ `{工作区名}-obsidian-{YYYYMMDD-HHMM}.zip`（库）；前端从 `Content-Disposition` 的 `filename*=UTF-8''` 解析文件名，失败回退 `documents-{ts}.zip` | backend 命名 + frontend 下载命名 | 前端单测（解析 Content-Disposition）+ 后端单测（文件名格式） |

## 口径（S1 方案，2026-11-03 修订）

- 后端：`GET /{wid}/documents/export/vault?style=archive|obsidian`（默认 archive）；`export_vault(style)` 只区分 front-matter 与 `.obsidian/`，原件族一律按原件导出。
- 前端：导出弹窗两项，默认「压缩文档」；下载文件名统一走 Content-Disposition 解析（`parseContentDispositionFilename`）。

## 现状影响面（候选，待实现时核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 整库 Obsidian 导出 | `src/cndb/plugins/documents/services/obsidian.py` | 唯一导出格式（需求 0088） |
| 2 | 导出路由 | `src/cndb/plugins/documents/routers/vault.py` | 无 `style` 参数 |
| 3 | 前端导出按钮与下载命名 | `frontend/src/pages/documents/DocumentsPage.tsx` | 点击直下、命名改解析响应头 |

## 未决问题

- [x] 压缩文档是否含 front-matter / `.obsidian/`：不含（纯文档树）；Obsidian 库带（需求 0088）
- [x] 空文档树报错行为沿用现有「当前工作区没有可导出的文档」

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（用户已确认口径，2026-10-30；2026-11-03 收窄为仅压缩包导出，见需求 0088）

# 需求卡片：文档导出方式选择弹窗

- 编号：0072
- 来源 / 提出人：用户（会话 2026-10-30）
- 日期：2026-10-30
- 关联 ADR：无（S1，方案见本卡片「口径」节）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐句）

> 文档导出，弹出对话框选择导出方式，包括文件夹和Obsidian库（实际为对应压缩包）。导出压缩文件的命名请参考其他导入导出的统一风格。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 弹出对话框选择导出方式 | 文档页「导出」按钮改为打开 Modal，内含两种方式：文件夹 / Obsidian 库，确认后触发下载 | frontend `DocumentsPage.tsx` | 前端单测（弹窗交互 + 两种方式各触发对应请求） |
| C2 | 文件夹（实际为压缩包） | 新增「文件夹」导出：按文档树层级输出 `<工作区名>/<文件夹>/<标题>.md`，改写站内图片为 `attachments/`，**不含** `.obsidian/` 配置与 front-matter；可见性裁剪与现有整库导出一致 | backend `services/obsidian.py`、`routers/vault.py` | 后端单测（zip 结构、无 .obsidian、无 front-matter、空文档报错） |
| C3 | Obsidian 库（实际为压缩包） | Obsidian 库导出维持现有 `GET /export/vault` 行为不变（front-matter + `.obsidian/`） | backend（无改动） | 既有测试回归 |
| C4 | 命名参考其他导入导出的统一风格 | zip 文件名统一由后端生成：`{工作区名}-obsidian-{YYYYMMDD-HHMM}.zip` / `{工作区名}-folder-{YYYYMMDD-HHMM}.zip`；前端从 `Content-Disposition` 的 `filename*=UTF-8''` 解析文件名，替换现有硬编码 `obsidian-vault-${ts}.zip` | backend 命名 + frontend 下载命名 | 前端单测（解析 Content-Disposition）+ 后端单测（文件名格式） |

## 口径（S1 方案）

- 后端：`export_vault` 增加 `style: "obsidian" | "folder"` 参数（默认 obsidian），folder 分支跳过 front-matter 渲染与 `.obsidian/` 写入；路由加 `style` 查询参数。不做独立新端点。
- 前端：新 `ExportDialog`（Modal + Radio.Group 两种方式），复用现有 `vaultExportMut` 改为带 `style`；下载文件名统一走 Content-Disposition 解析（新增小工具函数）。

## 现状影响面（候选，待实现时核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 整库 Obsidian 导出 | `src/cndb/plugins/documents/services/obsidian.py:1323` | 增加参数需保持默认行为不变 |
| 2 | 导出路由 | `src/cndb/plugins/documents/routers/vault.py:110` | 加查询参数 |
| 3 | 前端导出按钮与下载命名 | `frontend/src/pages/documents/DocumentsPage.tsx:217-233` | 弹窗替代直下、命名改解析响应头 |

## 未决问题

- [x] 文件夹导出是否含 front-matter / `.obsidian/`：不含（纯 Markdown 文件夹，与 Obsidian 库形成差异，本卡片口径）
- [x] 空文档树报错行为沿用现有「当前工作区没有可导出的文档」

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（用户已确认口径，2026-10-30）

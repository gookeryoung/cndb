# 需求卡片：MHTML 原件在线预览

- 编号：0064（与 ADR `docs/adr/0064-*.md` 同号，卡片存 `docs/requirements/0064-mhtml-preview.md`）
- 来源 / 提出人：需求方（会话）
- 日期：2026-10-28
- 关联 ADR：<立项后回填>

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 导入的mhtml无法直接查看，请完善功能支持在线查看。

方案口径（需求方已确认）：MHTML 原件在线预览采用「后端生成自包含 HTML 预览端点 + 前端沙箱 iframe 渲染」；预览保留根 HTML 内联样式（独立 CSS part 仍按导入链路 D6 丢弃）；分级 S1（不强制 ADR）。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 支持在线查看 | 新增预览端点：按文档 ID 取 MHTML 原件字节，复用 `parse_mhtml` 解析，产出**自包含 HTML**（根 HTML + 图片内联为 `data:` URI，保留 CSS）返回 `text/html`；无 HTML part 或解析失败返回 422 | documents plugin `routers/`、`services/importers/mhtml.py` | 后端单测：正常存档 / 含 base64 与 quoted-printable 图片 / 解析失败三类 |
| C2 | 支持在线查看 | 预览 HTML 中的资源引用按 ADR 0049 匹配链路解析（`Content-Location` 精确 → `cid:` → 唯一 basename），未命中图片保留原 URL 或占位，不阻塞预览 | `services/importers/mhtml.py`、`html.py` | 后端单测：`cid:` 引用与未命中外链两种用例 |
| C3 | 在线查看 | 前端 `DocumentAssetView` 对 `content_type=mhtml` 改为请求预览端点得 blob，渲染进 `sandbox` iframe（`sandbox` 禁脚本，`allow-same-origin` 不授予）；渲染失败退化为现有下载卡 | frontend `DocumentAssetView.tsx`、`api/documents.ts` | 前端单测：mhtml 走预览分支、失败态展示下载卡 |
| C4 | （安全口径） | 预览响应按 `Content-Disposition: inline` + `X-Content-Type-Options: nosniff` 返回；iframe 沙箱内脚本不执行（MHTML 来自外部网页存档，视为不可信内容） | documents plugin `routers/` | 后端单测断言响应头；前端单测断言 sandbox 属性 |
| C5 | （兼容口径） | ADR 0049 `convert` 模式与 0061 `archive` 默认链路行为均不变，预览为只读附加能力，不改导入产物 | `services/importers/` 既有链路 | 既有 mhtml 导入单测回归通过 |
| C6 | （文档口径） | 帮助教程「MHTML 导入」文案补充在线预览说明；CHANGELOG 记录新增能力 | `frontend/src/pages/help/content/tutorials.tsx`、`CHANGELOG` | `make check-docs` |
| C7 | （保真度：CSS 内联） | 预览解析同时收集 `text/css` part（键：Content-Location 精确 / URL 解码 / 唯一 basename / cid），根 HTML 中命中索引的 `<link rel="stylesheet">` 原位替换为内联 `<style>`（按原文出现顺序）；未命中 link 保留原样 | `services/importers/mhtml.py` | 判定层单测：link 命中内联、未命中保留、多张样式表按序 |
| C8 | （保真度：CSS 资源） | 内联 CSS 与根 HTML 既有内联 `<style>` 块中的 `url(...)` 引用按「相对 CSS part 自身 Content-Location 解析 → 三级匹配链」改写为 `data:` URI；图片按魔数嗅探 MIME，字体等非图片 part 使用 part 自带 Content-Type；未命中保留原样 | `services/importers/mhtml.py` | 判定层单测：背景图内联、@font-face 字体内联、未命中保留 |
| C9 | （保真度：srcset） | `<img srcset>` 属性值中的候选 URL 命中素材索引时逐项内联为 `data:` URI，描述符保留 | `services/importers/mhtml.py` | 判定层单测：srcset 命中改写、描述符不变 |
| C10 | （回归口径） | convert / archive 导入链路行为不变：CSS、字体 part 在导入转换中仍按 D6 丢弃，仅预览链路深度内联 | `services/importers/mhtml.py`、既有转换单测 | 既有 mhtml 转换单测回归通过 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | MHTML 原件 iframe 直塞（不可用根因） | `frontend/src/pages/documents/DocumentAssetView.tsx:132` | 浏览器不渲染 `multipart/related`，C3 改造点 |
| 2 | MHTML 解析能力（复用） | `src/cndb/plugins/documents/services/importers/mhtml.py:73`（`parse_mhtml`） | C1 复用，不重写 |
| 3 | 资源匹配索引（复用） | `src/cndb/plugins/documents/services/importers/mhtml.py:112`（`_build_index`） | C2 复用 |
| 4 | 原件取回端点 | documents plugin `routers/`（asset 下载接口，`documentsApi.assetBlob` 对应） | C1 新增 preview 端点与其并列 |
| 5 | 前端 API 层 | `frontend/src/api/documents.ts`（`assetBlob`） | C3 新增 `assetPreviewBlob` |
| 6 | 0061 archive 存档链路 | `services/importers/reader.py`、`importer.py` | C5 不变 |
| 7 | 教程文案 | `frontend/src/pages/help/content/tutorials.tsx` | C6 |

> 编号与 ADR「Context」表对齐：ADR 逐条给「确认 / 排除 / 新增」并补齐 `file:line`。本阶段只粗查，精查归 ADR。

## 未决问题

- [x] 方案分叉：**A. 后端预览端点**（复用 Python `email` 解析链路，健壮处理 base64 / quoted-printable / 字符集；前端只管渲染）——需求方已确认
- [x] CSS 处理：保留根 HTML 内联 `<style>`（样式还原度高，仅沙箱 iframe 渲染、脚本禁用）；独立 CSS part 仍按导入链路 D6 丢弃——需求方已确认
- [x] 方案分级：S1（跨前后端，新增一个只读端点，无数据模型 / 权限口径变化）；若实现中口径外溢再升级 S2 补 ADR——需求方已确认

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [ ] 未决问题全部有结论，需求方确认

# 需求卡片：PPTX 在线预览性能优化（逐页渲染 / 原件缓存 / 悬停预取）

- 编号：0128
- 来源 / 提出人：用户（会话 2026-11-09）
- 日期：2026-11-09
- 关联 ADR：无（S1，方案并入本卡片；PPTX 原件族口径见 ADR 0025，前端性能门禁见 ADR 0116）
- 状态：已确认（2026-11-09，用户批准）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> PPTX预览时非常缓慢，请针对性能优化给出建议，能否后台空闲时间转化格式便于预览。

补充确认（2026-11-09 用户选择）：

> 先做前端快速优化；可以接受逐页翻页，而不是连续滚动。

## 方案（口径）

**范围**：仅前端 PPTX 阅读器与文档列表预取，涉及 `frontend/src/pages/documents/PptxPreview.tsx`、`DocumentAssetView.tsx`、`DocumentsPage.tsx` 与相关单测 / 性能验证。**零后端接口、零数据模型、零迁移、零部署变更、零新增依赖**；`PptxSlideshow` 全屏放映行为保持不变。

**逐页渲染（主改动）**：`PptxPreview` 由 `mode: 'list'` 改为 `mode: 'slide'`，只渲染当前页，提供上一页 / 下一页 / 页码；首屏只等待第 1 页，不再等整份 PPT 全部渲染完成。DOM 中同一时刻只保留一个 `.pptx-preview-slide-wrapper`。保留现有错误提示与顶栏下载入口。

**尺寸口径**：按容器宽度计算，高度取「容器高度」与「宽度 × 0.75」的较大值，兼容 16:9 与 4:3，避免因幻灯片高于容器被裁切；不做「先 16:9 再按实际比例重建」的二次解析，避免首开耗时翻倍。

**缓存**：`pptx-preview` 动态 import 改为模块级 Promise（与放映页同口径），同一会话只解析一次；原件 blob 查询单独设置较长 `staleTime` / `gcTime`，文档页重新挂载时优先命中内存缓存；文档更新后仍由既有 `['documents', workspaceId]` 失效链刷新。

**悬停预取**：文档列表的 `.pptx` 行 hover 后防抖预取 `import('pptx-preview')` 与原件 blob；预取失败静默，不改变页面错误态；`saveData` 或慢网不预取，扫过列表不产生请求风暴。

**后台格式转换（本次不做）**：用户已确认先做前端优化。后端异步转 PDF / 图片衍生件涉及镜像、安全与后台任务，若前端优化后大页数文件仍不可接受，另立 S2 需求卡片 + ADR 评估，不在本卡片范围。

**性能验收**：用同一份 20 页 / 50 页 / 200 页 PPTX 夹具记录首张幻灯片可见时间、long task 与内存峰值；验收以「首张可见时间较现状下降 ≥50%，且 200 页不再等待全量渲染」为准，不设无依据的绝对毫秒数。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「PPTX预览时非常缓慢」 | `PptxPreview` 改 `mode: 'slide'`，只渲染当前页；提供上一页 / 下一页 / 页码；DOM 中最多 1 个 `.pptx-preview-slide-wrapper` | `frontend/src/pages/documents/PptxPreview.tsx` | 单测断言 `init` 参数为 `mode: 'slide'`；断言 `renderSingleSlide` 调用；手测 DOM 仅一页 |
| C2 | 「PPTX预览时非常缓慢」 | 首屏只等第 1 页；加载态在首页渲染完成后结束，不再等整份文件；解析失败仍显示「无法在线渲染」+ 下载兜底 | `PptxPreview.tsx` | 单测：`preview` unresolved 时显示 Spin，resolve 后显示内容；失败态沿用现有用例 |
| C3 | 「针对性能优化」 | `pptx-preview` 动态 import 走模块级 Promise，阅读器与放映页共享同一次加载；同一会话重复打开不重复解析模块 | `PptxPreview.tsx`、`PptxSlideshow.tsx`（仅抽取加载器，行为不变） | 单测断言两次挂载只调用一次动态 import；放映页既有用例全绿 |
| C4 | 「针对性能优化」 | 原件查询单独设置 `staleTime` / `gcTime`（建议 10 分钟 / 30 分钟）；文档页重挂载优先命中缓存，不重复下载大文件 | `frontend/src/pages/documents/DocumentAssetView.tsx` | 单测：首次挂载请求 1 次，卸载后重挂载在 `staleTime` 内不重复请求 |
| C5 | 「针对性能优化」 | 文档列表 `.pptx` 行 hover 防抖 150–300ms 后预取渲染库 chunk 与原件；`saveData` / 慢网跳过；失败静默 | `frontend/src/pages/documents/DocumentsPage.tsx` | 单测：防抖窗口内只预取 1 次；非 PPTX 行不预取；失败不抛错 |
| C6 | 「后台空闲时间转化格式」 | 本次不做后端转换；不新增接口、后台任务、镜像依赖与缓存目录；后续如需要另立 S2 ADR | 全仓 | 变更文件清单核对；`make check-fast` |
| C7 | 「可以接受逐页翻页」 | 预览交互统一为逐页翻页，不再保留 list 全量渲染；不新增缩略图栏等扩展功能 | `PptxPreview.tsx`、`frontend/src/index.css`（仅必要样式） | 手测前进 / 后退 / 首页末页禁用 / 页码正确 |
| C8 | （测试） | 更新 `PptxPreview.test.tsx`；补缓存与 hover 预取单测；`DocumentAssetView.test.tsx` 既有 PPTX 分支不回归 | `frontend/src/pages/documents/*.test.tsx` | `pnpm test` 对应用例全绿；`make flow` |
| C9 | （文档） | CHANGELOG 记录性能优化条目；帮助教程现有 PPTX 文案不涉及连续滚动，无需改动 | `CHANGELOG.md` | `make check-docs` |
| C10 | （边界） | 不改变 `PptxSlideshow` 全屏放映、标记笔、页码记忆；不改变错误提示、下载卡与权限口径；不新增 `pptx-preview` 版本变更 | `PptxPreview.tsx`、`PptxSlideshow.tsx`、`DocumentAssetView.tsx` | 既有 `PptxSlideshow.test.tsx`、`DocumentAssetView.test.tsx` 全绿 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | PPTX 预览初始化使用 list 全量渲染 | `frontend/src/pages/documents/PptxPreview.tsx:30-35` | 改为 slide 单页渲染（C1） |
| 2 | 预览加载态等整份渲染完成 | `frontend/src/pages/documents/PptxPreview.tsx:28-47` | 首屏只等第一页（C2） |
| 3 | 放映页已有 slide 模式与模块级 import 缓存 | `frontend/src/pages/documents/PptxSlideshow.tsx:20-22`、`:139-143` | 复用加载器，放映行为不变（C3/C10） |
| 4 | 原件 blob 查询无单独缓存配置 | `frontend/src/pages/documents/DocumentAssetView.tsx:70-74` | 加 `staleTime` / `gcTime`（C4） |
| 5 | 全局查询默认 30 秒 | `frontend/src/main.tsx:67-73` | 只对原件查询覆盖，不改全局（C4） |
| 6 | 文档列表行点击入口 | `frontend/src/pages/documents/DocumentsPage.tsx:717-726` | hover 预取挂载点（C5） |
| 7 | 列表渲染组件 | `frontend/src/pages/documents/DocumentsPage.tsx:1208-1224` | 文件夹与文档共用行，需按 `content_type` 过滤（C5） |
| 8 | 渲染库体积门禁 | `frontend/scripts/bundle-budget.json:136-142` | 仍为按需 chunk，本期不新增体积（C6） |
| 9 | 既有预览单测 | `frontend/src/pages/documents/PptxPreview.test.tsx:25-36` | 断言需从 list 改 slide（C8） |
| 10 | 依赖版本 | `frontend/package.json:63-66` | 不升级 `pptx-preview@1.0.7`（C10） |
| 11 | 帮助教程 PPTX 文案 | `frontend/src/pages/help/content/tutorials.tsx:649-654` | 未描述连续滚动，无需改（C9） |

## 未决问题（已确认）

- [x] ① 先做前端还是直接做后台转换：**结论**先做前端快速优化，后端异步转换本次不做（2026-11-09 用户选择）。
- [x] ② 是否接受逐页翻页：**结论**接受逐页翻页，不再连续滚动（2026-11-09 用户选择）。
- [x] ③ 是否保留 list 模式入口：**结论**不保留，统一逐页；后续如需要连续浏览，随 S2 衍生件方案一起评估（2026-11-09 由 ② 推得）。
- [x] ④ 原件缓存时长：**结论**`staleTime` 10 分钟、`gcTime` 30 分钟，文档更新沿用既有失效链（2026-11-09 方案内定，可评审调整）。
- [x] ⑤ 大页数 PPTX 验收方式：**结论**用 20 / 50 / 200 页样本手测并记录首张可见时间与 long task；仓库暂无 PPTX 二进制夹具，本期不新增静态二进制资产（2026-11-09 方案内定）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

## 落地记录

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0（C1-C5） | 已落地 | `frontend/src/pages/documents/{PptxPreview.tsx,PptxSlideshow.tsx,DocumentAssetView.tsx,DocumentsPage.tsx,pptxLoader.ts,pptxPrefetch.ts}` | `PptxPreview.test.tsx` 5 例（slide 模式 / 翻页边界 / 失败兜底 / 卸载销毁 / 加载器复用）；`DocumentAssetView.test.tsx` 新增缓存复用 1 例；`pptxPrefetch.test.ts` 4 例（非 PPTX / 失败静默 / saveData / 防抖） | 未提交 |
| P1（C8-C9） | 已落地 | `CHANGELOG.md`、本卡片 | `pnpm test` 260 文件 / 3212 例通过；`pnpm build`、`pnpm bundle:budget`、`make check-fast`、`make flow` 通过 | 未提交 |

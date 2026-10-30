# 需求卡片：文档数据表引用占位符可读化（表名/视图名展示）

- 编号：0071
- 来源 / 提出人：用户（会话反馈：文档中 `{{table:7|view=68}}` 占位符，用户无法对应上到底是哪个表）
- 日期：2026-10-30
- 关联 ADR：无（S1，不强制；若实现中出现设计分叉升级 S2 再补）

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐句）

> 文档中引用的数据表对应视图，代码信息{{table:7|view=68}}，用户无法对应上到底是哪个表。请给出解决方案。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 用户无法对应上到底是哪个表 | 编辑器 live 模式将 `{{table:…}}` 占位符装饰为可读徽章，展示「表名 · 视图名 · 每页 N」（按参数实际内容拼装：无 view 不显示视图段，limit 缺省或与默认值相同不显示每页段）；光标进入徽章还原为源码占位符便于编辑 | frontend `MarkdownLiveEditor.tsx` | 单测：占位段落装饰为徽章 Widget、光标进入还原源码 |
| C2 | 用户无法对应上到底是哪个表 | 徽章展示名以 API 实时数据为准：表名取编辑页既有表列表查询；视图名按需 `viewApi.get` 并进程内缓存；查不到（已删除/无权限/接口失败）回退 `#<ID>` 显示并以警示色标识 | frontend `MarkdownLiveEditor.tsx`、`DocumentEditorPage.tsx` | 单测：名称命中展示表名/视图名；失败回退 `#ID` 警示色 |
| C3 | 引用对应视图（view=68） | 预览态 TableEmbed 头部说明行把 `视图 #68` 实化为视图名；`viewApi.get` 失败回退 `视图 #<ID>`；无 view 参数行为不变 | frontend `TableEmbed.tsx` | 单测：带 view 显示视图名，失败回退 ID，无 view 不请求视图接口 |
| C4 | 代码信息{{table:7\|view=68}} | 占位符语法不变（不新增 `name=` 等展示参数）；解析器对未知键忽略的既有行为不改；占位符失效提示（TableEmbed 错误 Alert）保持既有文案与行为 | frontend `tableRef.ts`、`TableEmbed.tsx` | 既有 `tableRef.test.ts` 全绿；新增解析行为为零 |
| C5 | —（配套体验） | 插入数据表引用成功后 message 提示含表名与视图名（如「已插入：股票日线 · 全市场视图 引用」），无视图时只显示表名 | frontend `DocumentEditorPage.tsx` | 单测：插入回调触发后 message 文案含名称 |

## 现状影响面（候选，待核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | live 编辑器装饰机制（图片 widget / 表格整块替换） | `frontend/src/components/Document/MarkdownLiveEditor.tsx` | 徽章装饰复用同一套 Decoration/WidgetType 机制；注意块级替换限制（表格用 gapcursor 桥接），占位符是行内/单段文本，预计行内替换装饰即可 |
| 2 | TableEmbed 头部说明行 | `frontend/src/components/Document/TableEmbed.tsx:117-130` | 现显示 `表名 · 视图 #ID · 共 N 行` |
| 3 | 插入数据表引用 | `frontend/src/pages/documents/DocumentEditorPage.tsx:799-815` | `insertTableRef` 拼 ID 占位符，无名称提示 |
| 4 | 占位符解析 | `frontend/src/components/Document/tableRef.ts:41-81` | 未知键忽略；不改语法 |
| 5 | 源码模式（textarea） | `MarkdownLiveEditor.tsx` 源码分支 | 源码模式保持裸占位符不动（C1 只约束 live 模式） |

## 未决问题

- [x] 是否在占位符内持久化可读名（`name=` 参数）？——不做：表/视图改名后失同步成误导，展示名一律 API 实时取（用户已确认按推荐方案执行）。
- [x] 徽章是否可点击跳转？——本需求不做跳转，仅展示；光标点击即进入源码编辑。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认（用户 2026-10-30 确认按推荐组合执行）

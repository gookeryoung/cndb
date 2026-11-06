# 需求卡片：流水线检查 DSL 编辑器功能增强（行号 / 高亮 / 自动缩进 / 自动完成）

- 编号：0111
- 来源 / 提出人：用户（会话 2026-11-06）
- 日期：2026-11-06
- 关联 ADR：无（S1，方案并入本卡片；底座为 ADR 0076 流水线 DSL）

> 本卡片是**需求原文与约束编号的唯一副本**：需求变更后先改这里，再改代码。

## 需求原句（逐字）

> 针对流水线编辑功能增强制定方案。包括但不限于：行号显示，关键字高亮，自动缩进，自动完成（关键字、规则引用）等。

## 方案（口径）

**选型**：编辑器由 antd `Input.TextArea` 换成 CodeMirror 6 专用封装 `frontend/src/pages/pipelines/PipelineDslEditor.tsx`，口径对齐设计模块既有 `design/DslEditor.tsx`（lineNumbers / oneDark / 受控 value 同步 / updateListener），不引入自研编辑器框架。新增依赖 `@codemirror/autocomplete`（与需求 0110 设计 DSL 补全共享，先落地者先加）。

**单一语法口径**：高亮与补全共用 `frontend/src/pages/pipelines/pipelineDsl.ts` 导出的关键字常量；常量与后端 `src/cndb/plugins/pipeline/services/dsl/parse.py` 的 `_TOP_KEYS / _ON_KEYS / _JOB_KEYS / _STEP_KEYS` 及 `SEVERITIES` 逐项对齐（`name/on/vars/jobs`、`manual/events/schedule`、`needs/if/steps`、`uses/with/severity/continue-on-error`、`error/warn/info`）。

**高亮**：自写轻量 StreamLanguage（先例 `design/designLang.ts`）：DSL 关键字 → keyword，severity 值 → atom，`uses` 值 / 表名 → 字符串色，注释与表达式 `${{ ... }}` 单独着色；不用官方 `@codemirror/lang-yaml`（它无法区分 DSL 关键字与普通键，见未决问题②）。

**自动缩进**：`indentUnit.of('  ')`（YAML 2 空格）+ `indentWithTab`；回车继承当前行缩进（CodeMirror 默认），列表项行（`- ` 开头）回车延续前缀。缩进层级与 `checkCatalog.ts` 的 `buildStepSnippet`（6/8/10 空格）同口径。

**自动完成**（`frontend/src/pages/pipelines/pipelineCompletion.ts`，`CompletionSource`）：

- **关键字**（上下文分流）：顶层 → `name/on/vars/jobs`；`on:` 内 → `manual/events/schedule`；job 内 → `needs/if/steps`；step 内 → `uses/with/severity/continue-on-error`；`severity:` 值位 → `error/warn/info`。
- **规则引用**：`uses:` 值位 → 检查动作目录（`checks`，detail 用中文 `title` + 类别）；`with:` 键位 → 对应 `uses` 的 `inputs`（detail = 类型 + 描述 + 默认值）。目录数据由 `PipelinesPage` 经 props 注入（`checks` query 已存在，无新端点），completion 模块不 import api 层。
- **本地引用**：`needs:` 值位 → 当前文档其他 job id；表达式位（`if` / `vars` / `with` 值）→ `vars` 定义的变量名。轻量扫描提取（YAML 行级正则，不做完整前端解析器），误差不阻断输入，语法正确性由既有 400ms 防抖 `/validate` 兜底。
- **片段**：step 骨架复用 `checkCatalog.buildStepSnippet(check)`；完整 workflow 骨架复用 `defaultWorkflowContent(domain)` 常量展开；用 `snippet()` 槽位语法，`Tab` 跳转。

**交互**：标识符字符输入自动触发 + `Ctrl+Space` 手动唤起；候选 `detail` 中文一句话；检查目录「插入」按钮改为**插入光标处**（2026-11-06 用户拍板，经编辑器实例暴露的插入接口）；校验回显维持现有 Alert（`/validate` 无行号，本期不做行级诊断装饰，仅在方案中预留）。

**分期**：P0 换编辑器（行号 + 高亮 + 自动缩进 + 主题统一）+ 关键字 / severity 补全；P1 规则引用 + 本地引用 + 片段补全；P2 上下文细化打磨与 e2e 补齐。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 「行号显示」 | 编辑器挂 `lineNumbers()`，等宽字体与设计模块 `cn-dsl-editor` 同款口径 | `frontend/src/pages/pipelines/PipelineDslEditor.tsx` | e2e：编辑器容器渲染行号槽位 |
| C2 | 「关键字高亮」 | `pipelineDsl.ts` 关键字表与 `parse.py` 四组键集合 + `SEVERITIES` 逐项一致（单一来源导出）；DSL 关键字 keyword 色、severity 值 atom 色 | `frontend/src/pages/pipelines/pipelineDsl.ts`、`parse.py`（只读基准） | 前端单测：常量集合与后端逐项一致（硬编码期望清单）+ 着色分类 |
| C3 | 「自动缩进」 | `indentUnit '  '` + `indentWithTab`；回车继承缩进；`- ` 列表行回车延续前缀；层级与 `buildStepSnippet` 缩进口径一致 | `PipelineDslEditor.tsx` | 前端单测：回车 / Tab 后的缩进结果 |
| C4 | 「自动完成（关键字）」 | 关键字补全按上下文分流（顶层 / on / job / step / severity 值位），候选 detail 中文一句话；误差不阻断输入（后端 `/validate` 兜底） | `frontend/src/pages/pipelines/pipelineCompletion.ts` | 前端单测：同一文档不同光标位候选集合分流正确 |
| C5 | 「自动完成（规则引用）」 | `uses:` 值位补全检查动作目录（detail = 中文 title + 类别）；`with:` 键位补全该动作 `inputs`（detail = 类型 + 描述 + 默认值）；目录数据经 props 注入，无新端点；目录为空时该位静默无候选 | `pipelineCompletion.ts`、`PipelinesPage.tsx`（注入）、`frontend/src/api/pipelines.ts`（只读类型） | 前端单测：mock 目录后 uses / with 位候选正确、空目录降级 |
| C6 | 「自动完成」（本地引用，属「等」） | `needs:` 值位补全当前文档其他 job id；表达式位（`if` / `vars` / `with` 值）补全 `vars` 变量名；轻量行级扫描，不做完整前端解析器 | `pipelineCompletion.ts` | 前端单测：示例 DSL（含注释 / 深层缩进干扰）提取结果正确 |
| C7 | 「等」（片段） | step 骨架片段复用 `buildStepSnippet`、workflow 骨架复用 `defaultWorkflowContent`；`snippet()` 槽位 + `Tab` 跳转；目录「插入」按钮改为插入光标处，与补全片段共用同一生成函数 | `pipelineCompletion.ts`、`checkCatalog.ts`、`PipelinesPage.tsx` | 前端单测：片段展开文本与槽位；e2e 补全菜单选择插入 |
| C8 | （交互） | 标识符输入自动触发 + `Ctrl+Space` 手动唤起；校验回显维持既有 Alert（400ms 防抖不回归） | `PipelineDslEditor.tsx`、`PipelinesPage.tsx` | e2e：输入触发补全菜单；校验链路不回归 |
| C9 | （依赖） | 新增依赖 `@codemirror/autocomplete`（CodeMirror 官方包 6.x；与 0110 共享，先落地者先加并锁版本） | `frontend/package.json` | `make check-fast`（lock 更新 + 前端构建门禁） |
| C10 | （测试与门禁） | 测试分层：`pipelineDsl.test.ts` / `pipelineCompletion.test.ts` / `PipelinesPage.test.tsx` 更新 / e2e 新增 1 条（输入 → 补全 → 插入 → 保存校验不回归） | `frontend/src/pages/pipelines/`、`frontend/tests/e2e/critical/` | `make flow` 全绿 |
| C11 | （文档口径） | CHANGELOG 记增强条目；帮助文档快速上手补一句编辑器补全用法（可选） | `CHANGELOG.md`、`frontend/src/pages/help/content/` | `make check-docs` |
| C12 | 「敏感内容检查等内置流水线动作，也应实现自动完成提示功能」（2026-11-06 追加） | `with:` 参数值级提示：`document/sensitive` 的 `logic` 值位提示 `any` / `all` 与 `rules` 中已定义的规则名（顶层 `keywords` / `patterns` 提示隐式规则 `default`）；`rules` 列表项键位提示 `name` / `keywords` / `patterns`；其他动作不触发值级提示 | `frontend/src/pages/pipelines/pipelineCompletion.ts` | 前端单测：logic 值候选（含布尔表达式续写 / 隐式 default）、rules 项键候选、非敏感动作无候选 |

约束编号在实现中原样引用；不重编号、不合并。

## 现状影响面（候选）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 编辑器本体（TextArea 替换点） | `frontend/src/pages/pipelines/PipelinesPage.tsx:548-555` | C1/C3/C8 换成 `PipelineDslEditor`，受控 `content` / 防抖校验链路保留 |
| 2 | 检查目录「插入」按钮（append 到末尾） | `frontend/src/pages/pipelines/PipelinesPage.tsx:313-315、587` | C7 与补全共用片段生成；插入位置口径见未决问题③ |
| 3 | DSL 关键字口径（对齐基准） | `src/cndb/plugins/pipeline/services/dsl/parse.py:28-31`、`models.py SEVERITIES` | C2 只读引用不改 |
| 4 | 检查动作目录数据（补全数据源） | `frontend/src/pages/pipelines/PipelinesPage.tsx:156-160`（`checks` query）、`frontend/src/api/pipelines.ts:111-118`（`PipelineCheckSpec`） | C5 经 props 注入，无新端点 |
| 5 | 片段 / 模板生成（复用） | `frontend/src/pages/pipelines/checkCatalog.ts:91-131`（`buildStepSnippet` / `defaultWorkflowContent`） | C7 单一来源 |
| 6 | CodeMirror 封装先例（口径对齐） | `frontend/src/pages/design/DslEditor.tsx:61-133` | 结构复刻：受控同步 / updateListener / oneDark |
| 7 | 依赖清单 | `frontend/package.json:36-41` | C9：已有 6 个 codemirror 包，缺 `@codemirror/autocomplete`（与 0110 共享） |
| 8 | 既有流水线 e2e（回归面） | `frontend/tests/e2e/critical/pipelines.spec.ts` | C10 新增用例不破坏既有新建 / 编辑 / 保存流程 |
| 9 | 0110 设计 DSL 补全（依赖共享方） | `docs/requirements/0110-design-dsl-editor-completion.md` | 两卡片同用 `@codemirror/autocomplete`，先落地者先加依赖 |

## 未决问题（已确认）

- [x] ① 方案分级：**结论** S1（纯前端交互增强，方案并入本卡片，不写 ADR，2026-11-06 用户拍板）。
- [x] ② 高亮选型：**结论** 自写轻量 StreamLanguage（官方 `@codemirror/lang-yaml` 无法区分 DSL 关键字与普通键且多一个包体，2026-11-06 用户拍板）。
- [x] ③ 检查目录「插入」按钮行为：**结论** 改为插入光标处（2026-11-06 用户拍板）。
- [x] ④ 行级错误定位（编辑器内错误行装饰，需后端 `/validate` 返回行号，属跨模块改造）：**结论** 本期不纳入，仅在方案中预留（2026-11-06 用户拍板）。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论（2026-11-06 用户拍板）

## 落地记录

| 期 | 状态 | 代码落点 | 测试 | 提交 |
|---|---|---|---|---|
| P0 | 已落地 | `frontend/src/pages/pipelines/{pipelineDsl.ts,PipelineDslEditor.tsx,PipelinesPage.tsx}`、`frontend/src/index.css` | `pipelineDsl.test.ts`、`PipelineDslEditor.test.tsx`、`PipelinesPage.test.tsx` | `ba817ab2` |
| P1 | 已落地 | `frontend/src/pages/pipelines/pipelineCompletion.ts` | `pipelineCompletion.test.ts` | `ba817ab2` |
| P2 | 已落地 | `frontend/src/pages/pipelines/{pipelineCompletion.ts,PipelineDslEditor.tsx}` | `pipelineCompletion.test.ts`、`frontend/tests/e2e/critical/pipelines.spec.ts` | `ba817ab2` |
| 追加（C12） | 已落地 | `frontend/src/pages/pipelines/pipelineCompletion.ts` | `pipelineCompletion.test.ts`（新增 5 例） | 待提交 |

- 最近一次全绿：`make flow`（`check-fast` + `test`）@ 2026-11-06（e2e 在 CI 4 分片执行）

# 0069 — 未配置大模型时隐藏 AI 元素

## 需求原文

> 所有页面涉及到 AI 元素的，用户未配置 AI 大模型时，应当隐藏相关提示。

## 约束清单

- C1 可用性判定：以 `GET /v1/llm/config` 返回的 `configured === true` 作为「已配置」唯一口径；判定结果全局共享（react-query 同 queryKey 缓存，配置保存/清除后失效重取）。
- C2 隐藏而非禁用：未配置时 AI 元素**不渲染**（不出现禁用态按钮或「请先配置」提示文案）。
- C3 需隐藏的元素清单（以 `configured=false` 为条件）：
  - 文档编辑页：顶栏 `AiDocEntry`（AI 摘要 / AI 标签建议）；
  - 文档编辑页：`MarkdownToolbar` 的 AI 润色 / 精简 / 扩写入口（`MARKDOWN_AI_ITEMS`）；
  - 文档编辑页：更多菜单中 `ai-summarize` / `ai-suggest-tags` 菜单项；
  - 分析页：`AnalyticsAiPanel` 整块与 `AnalyticsResultView` 的 AI 按钮；
  - 表格：列头 AI 填充按钮（`header-ai-fill-*`，`buildColumns.tsx`）；
  - 导入对话框：AI 建议列映射面板（`ai-mapping-panel`，`ImportPanel.tsx`）。
- C4 保留项（不属于隐藏范围）：个人设置 → 大模型 Tab（`LlmConfigPanel`）与顶栏/用户菜单「大模型设置」入口——它们是配置入口，未配置时正是需要它们的时机。
- C5 数据源新建/编辑任务的 `llm_prompt` 提供方选项：未配置时同样隐藏（选择后必然不可用），已配置时保持原行为。
- C6 AI 配置保存成功或清除 Key 后，各页面 AI 元素随缓存失效即时出现/消失（无需整页刷新）。

## 口径

| 约束 | 落点 |
|---|---|
| C1 | 新增共享 hook（如 `frontend/src/api/useLlmConfigured.ts`），内部 `useQuery(['llm','config'], llmApi.get)`，导出 `configured` 布尔值；各 AI 入口组件/页面消费 |
| C3 | 各入口处 `if (!configured) return null` / 条件不加入菜单 items |
| C5 | `DatasourcePage` 提供方选项列表按 `configured` 过滤 `llm_prompt` |
| C6 | 保存/清除 mutation `onSuccess` 中 `queryClient.invalidateQueries(['llm','config'])`（`LlmConfigPanel` 内已有 query，需补失效） |

## 测试

- hook 单测：configured true/false 两态。
- 各入口组件未配置态不渲染的定向单测（文档顶栏 AI、工具栏 AI、分析 AI 面板、列头 AI 填充、导入 AI 映射、数据源 llm_prompt 选项）。
- `LlmConfigPanel` 保存后缓存失效的回归。

## 备注

- 后端无改动，纯前端。
- `MARKDOWN_AI_ITEMS` 为导出常量，工具栏渲染处按 configured 过滤，常量本身保留（编辑器快捷键路径同样需按 configured 屏蔽）。

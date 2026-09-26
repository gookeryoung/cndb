# 报表模板编辑器页签布局设计

## 概述

模板编辑/新建弹窗（`frontend/src/pages/reports/ReportsPage.tsx` 的 TemplateEditor Modal）采用 antd `Tabs` 分三页签，替代原单页纵向长表单。

## 页签定义

| 页签 key | 标题 | 内容 | forceRender |
|---|---|---|---|
| `basic` | 基本信息 | 名称/输出格式/主题/关联表/额外引用表/跨工作区引入/描述 | 是 |
| `editor` | 模板编辑 | Segmented（编辑模板/实时预览/语法帮助）+ 编辑器主体（高 `min(56vh, 640px)`） | 否（懒挂载） |
| `params` | 模板参数 | Form.List 参数定义区 | 是 |

- 默认页签：新建态 `basic`，编辑态 `editor`。
- 所有 Form.Item 共享既有 form 实例，Tabs 不销毁隐藏面板（antd 默认 keep-mounted）。
- `template_content` 隐藏 Form.Item 挂在 Tabs 外（Form 内），值仍由 CodeMirror 受控。

## 关键机制

### 编辑器懒挂载

`editorVisited` state：CodeMirror 避免在隐藏容器中初始化，「模板编辑」页签首次激活才挂载内容，之后保持挂载（页签往返不丢内容）。打开弹窗时编辑态直接置 `editorVisited=true`。

### 校验跳转与错误标记

- `FIELD_TAB_MAP`（常量）：字段名 → 页签映射（`name/output_format/theme/table_id/extra_table_ids/description → basic`；`template_content → editor`；`parameters → params`）。**新增表单字段必须同步维护此表。**
- 保存按钮 `handleSave`：`form.validateFields()` 失败时按 `errorFields[].name[0]` 收集出错页签 `erroredTabs`，页签标题叠加 `<Badge dot>` 红点，并跳转到第一个出错页签（basic → editor → params 顺序）；成功时清空 `erroredTabs` 后提交。

## 约束

- 数据流零改动：templateValue 受控、extraTableIds/crossTableInfo state、handleFormFinish 提交逻辑均保持原样。
- 页签文案「模板编辑」与 Segmented 选项「编辑模板」为不同字符串，测试定位时不得混用；页签点击用 `.ant-tabs-tab` 容器定位（「模板参数」与 pane 内 Form.Item 标签同名）。

## 验收

- [x] 三页签布局，各页签内容与原实现等价
- [x] 新建态默认基本信息、编辑态默认模板编辑
- [x] 校验失败自动跳转出错页签并显示红点标记
- [x] 页签往返切换后编辑器内容/参数行不丢失
- [x] 回归用例覆盖（ReportsPage.test.tsx「编辑器页签布局」组）28/28 通过
- [x] make check 全绿

# 计划：统一字段类型标签（中文类别标签 + 统一配色）

## 摘要

项目中「字段类型」的显示标签与颜色目前由 4 处独立维护，互不一致：表设置字段管理器用无色纯中文标签、导入数据预览用中英混排标签（`文本 text`）、报表字段面板用另一套中文标签（`布尔`/`时间`）、API 导入直接显示原始英文（`text`）。本计划新建单一真相源模块 `fieldTypeMeta.ts`，统一为「中文标签 + 类别 + antd 预设色」，并替换全部 4 处消费点，保证全项目任意出现字段类型标签的位置所见一致。

## 现状分析（Phase 1 探索结论）

| # | 文件 | 标签现状 | 颜色现状 | 问题 |
|---|------|---------|---------|------|
| 1 | [FieldManager.tsx](f:/Dev/cndb/frontend/src/pages/modals/FieldManager.tsx) L22-39 | 本地 `FIELD_TYPES` 纯中文（单行文本/是/否…）+ category | 字段行 Tag **无颜色**（L302）；引入对话框 L460 显示原始英文 `sf.field_type`；映射对比 L515/536 原始英文 | 无色、多处英文裸露 |
| 2 | [FileImportPreview.tsx](f:/Dev/cndb/frontend/src/pages/modals/FileImportPreview.tsx) L48-61, L200-205 | 本地 `PREVIEW_FIELD_TYPES` 中英混排（`文本 text`） | 本地 `TYPE_COLOR`（text=`default` 无色） | 列头 Tag L502 显示原始英文；左卡片 L386 `select` 英文；图例 L689 用混排标签 |
| 3 | [FieldPanel.tsx](f:/Dev/cndb/frontend/src/components/report-editor/FieldPanel.tsx) L31-58 | 本地 `labelMap`（文本/长文本/布尔/时间…） | 本地 `FIELD_TYPE_COLOR`（16 类全有色） | 标签与 FieldManager 冲突（`布尔` vs `是/否`、`时间` vs `日期时间`） |
| 4 | [ApiImportDialog.tsx](f:/Dev/cndb/frontend/src/pages/modals/ApiImportDialog.tsx) L27-45, L194 | 显示原始英文 `t` | 本地 `FIELD_TYPE_COLOR`（date=cyan，与 #3 的 orange 冲突） | 英文标签、色值冲突 |

- `FieldType` 联合类型见 [types.ts](f:/Dev/cndb/frontend/src/api/types.ts) L209-216：16 个主类型 + 历史别名（`long_text`/`decimal`/`multi_select`/`json`）+ 系统类型（`formula`/`auto_id`/`created_time`/`updated_time`/`created_by`/`updated_by`）。
- `ReportsPage.tsx` L19-24 的 `PARAM_TYPES` 是报表参数类型（string/number/date/boolean），非字段类型，**不在本次范围**。
- [TableSettingsModal.test.tsx](f:/Dev/cndb/frontend/src/pages/modals/TableSettingsModal.test.tsx) 仅构造 fixture，未断言类型标签文本，改动安全。

## 统一标准（决策）

**中文标签**：以表设置 FieldManager 现有标签为基准（最完整、用户视角最自然）。
**颜色**：以 FieldPanel 现有映射为基准（16 类全有色、区分度好、同为 antd 预设色名）。

| type | label | category | color | | type | label | category | color |
|------|-------|----------|-------|---|------|------|----------|-------|
| text | 单行文本 | 基础 | blue | | select | 单选 | 选择 | gold |
| longtext | 多行文本 | 基础 | cyan | | multiselect | 多选 | 选择 | gold |
| boolean | 是/否 | 基础 | purple | | email | 邮箱 | 高级 | geekblue |
| number | 整数 | 数字 | green | | url | 链接 | 高级 | geekblue |
| float | 小数 | 数字 | green | | phone | 电话 | 高级 | geekblue |
| percentage | 百分比 | 数字 | lime | | link | 关联 | 关联 | magenta |
| date | 日期 | 日期 | orange | | attachment | 附件 | 高级 | volcano |
| datetime | 日期时间 | 日期 | orange | | timestamp | 时间戳 | 日期 | orange |

历史别名兜底：`long_text`→多行文本、`decimal`→小数、`multi_select`→多选、`json`→JSON（default）、`formula`→公式（default）、`auto_id`→自动编号（default）、`created_time`→创建时间、`updated_time`→更新时间、`created_by`→创建人、`updated_by`→更新人（均 default 色）。未知类型：`getFieldTypeLabel` 返回原始值、`getFieldTypeColor` 返回 `default`（与各处现有 `?? 'default'` / `?? type` 兜底语义一致）。

## 变更内容

### 1. 新建 `frontend/src/utils/fieldTypeMeta.ts`（单一真相源）

```ts
export interface FieldTypeMeta { label: string; category: string; color: string }
export const FIELD_TYPE_META: Record<string, FieldTypeMeta>  // 上表 16 主类型 + 别名/系统类型
export function getFieldTypeLabel(type: string): string      // 未知类型返回原始 type
export function getFieldTypeColor(type: string): string      // 未知类型返回 'default'
export const FIELD_TYPE_OPTIONS                              // FieldManager 下拉：16 主类型 [{value,label:'单行文本（基础）' 形式由消费方拼}]，含 category
export const PREVIEW_FIELD_TYPE_VALUES                       // 导入预览可切换子集：原 12 项（text/number/float/boolean/date/datetime/select/multiselect/email/url/phone/percentage），沿用原过滤语义（排除 link/attachment/formula 等）
```

配套测试 `frontend/src/utils/fieldTypeMeta.test.ts`：
- 16 主类型标签/类别/颜色符合上表；
- 历史别名映射正确；未知类型返回原始值 / `default` 色；
- `PREVIEW_FIELD_TYPE_VALUES` 恰为原 12 项且不含 link/attachment。

### 2. `FieldManager.tsx`（表设置 → 字段）

- 删除本地 `FIELD_TYPES`（L22-39），下拉 options 改由 `FIELD_TYPE_OPTIONS` 生成，保持 `${label}（${category}）` 格式不变（L348）。
- 字段行 Tag（L302）：`<Tag color={getFieldTypeColor(r.field_type)}>{getFieldTypeLabel(r.field_type)}</Tag>`（L293 的 `typeMeta` 查找同步替换）。
- 引入字段 Checkbox Tag（L460）：原始英文 → 中文标签 + 统一色。
- 映射对比（L515 `${f.name}（${f.field_type}）`、L536）：类型文案 → `getFieldTypeLabel`。

### 3. `FileImportPreview.tsx`（导入数据预览）

- 删除本地 `PREVIEW_FIELD_TYPES`（L48-61）与 `TYPE_COLOR`（L200-205），改用共享模块。
- 类型下拉（L404）：options 由 `PREVIEW_FIELD_TYPE_VALUES` + 共享 META 生成，标签变为纯中文（如 `单行文本`），value 不变（提交 payload 不受影响）。
- 右侧列头 Tag（L502）：`{col.field_type}` → `{getFieldTypeLabel(col.field_type)}`，色用 `getFieldTypeColor`。
- 左侧卡片 select 提示 Tag（L386）：`select` → `单选`。
- 图例「数据类型颜色」（L689-693）：改用共享 META 生成中文标签 + 统一色（自动与下拉/列头一致）。
- L692 `PREVIEW_FIELD_TYPES.map` 改为按 `PREVIEW_FIELD_TYPE_VALUES` 遍历。

### 4. `FieldPanel.tsx`（报表编辑器字段面板）

- 删除本地 `FIELD_TYPE_COLOR`（L31-48）与 `labelMap`（L52-57），`FieldTag` 改用 `getFieldTypeLabel` / `getFieldTypeColor`（L50-59）。

### 5. `ApiImportDialog.tsx`（API 导入）

- 删除本地 `FIELD_TYPE_COLOR`（L27-45），L194 列头 Tag 改为 `<Tag color={getFieldTypeColor(t)}>{getFieldTypeLabel(t)}</Tag>`。

## 假设与决策记录

- 标签基准选 FieldManager、颜色基准选 FieldPanel：均为探索发现的最完整现套，改动最小；具体色值属实现细节，按迭代规则自主决策（待用户复核）。
- 类型 `value`（提交后端的英文值）一律不变，仅改显示层；不影响后端与既有 payload。
- `ReportsPage.PARAM_TYPES`（报表参数类型）语义不同，不改。
- `GridCell.tsx` L341 `title="多行文本"` 是 textarea 提示非类型标签，不改。

## 验证步骤

1. `cd frontend && pnpm typecheck && pnpm lint`（即 `pnpm check`）。
2. `cd frontend && pnpm test`——新增 `fieldTypeMeta.test.ts` 全绿；既有 `TableSettingsModal.test.tsx` / `tagColors.test.ts` 等不回归。
3. 人工核对一致性：表设置字段行 Tag、字段下拉、导入预览下拉/列头/图例、报表字段面板、API 导入列头，同一类型显示同一中文标签与同一颜色。
4. 收尾按项目门禁跑根目录 `make check`（Python 三项，前端改动不触及但提交前必须全绿）后再提交。

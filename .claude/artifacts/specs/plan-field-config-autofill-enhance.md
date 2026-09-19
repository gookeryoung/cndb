# 计划：表设置【字段】功能完善与增强

## Summary

针对【表设置 → 字段】完成三项增强：

1. **自动填充默认「不填充」+ 编辑态激活**：修复编辑对话框中 date/datetime 字段 `config.auto_fill` 键缺失时 Radio 无选中态的问题（存量字段、从其他表引入的字段 config 无该键）。
2. **字段行备注文字**：字段列表每行以备注风格文字显示「默认值」与「自动填充」设置。
3. **新增行自动填入**：网格新增行时，按规则预填 auto_fill 日期字段与 default_value 字段（前端草稿预填 + 后端 create 路径 default_value 兜底生效）。

## Current State Analysis

### 前端

- `frontend/src/pages/modals/FieldManager.tsx`
  - [openDialog](file:///f:/Dev/cndb/frontend/src/pages/modals/FieldManager.tsx#L201-L227) 编辑分支 `config: target.config ?? {}` 原样写入；`auto_fill` 键缺失时（历史字段/引入字段）`['config','auto_fill']` Radio.Group 值为 undefined → 无激活按钮。新建分支已通过 `defaultConfigForType` 给 date/datetime 默认 `auto_fill: ''`（对应「不自动」按钮）。
  - 字段行 [fm-row](file:///f:/Dev/cndb/frontend/src/pages/modals/FieldManager.tsx#L274-L303) 仅显示图标/名称/类型 Tag/必填/隐藏/操作，无备注区。
- `frontend/src/index.css` 有 `.fm-row` 系列样式（L806-L858），`.fm-row-name` 无 flex:1，`.fm-row-actions` 用 `margin-left:auto` 靠右。
- `frontend/src/pages/grid/GridPage.tsx`
  - [draftFor](file:///f:/Dev/cndb/frontend/src/pages/grid/GridPage.tsx#L479-L487)：新行（record=null）全部字段初始化为空值；[saveInline](file:///f:/Dev/cndb/frontend/src/pages/grid/GridPage.tsx#L548-L582) 仅提交非空字段。
  - date/datetime 草稿格式为字符串（`'YYYY-MM-DD'` / `'YYYY-MM-DD HH:mm:ss'`），DatePicker 用 `dayjs(String(draft))` 消费，finalize 对字符串直接透传（[GridCell.tsx L643-649](file:///f:/Dev/cndb/frontend/src/pages/grid/components/GridCell.tsx#L643-L649)）。
- `frontend/src/api/types.ts` `Field.default_value?: unknown`、`Field.config?: Record<string, unknown>` 已有类型。

### 后端

- `src/cndb/plugins/tables/field_types/types.py`
  - `DateFieldConfig.auto_fill`（`''` / `on_create` / `on_update`），`should_auto_fill`，Date/DateTime 的 `default_value(config)` 返回 today/now（`# pragma: no cover - auto_fill 待补测试`）。
- `src/cndb/plugins/tables/records.py`
  - [_normalize_values](file:///f:/Dev/cndb/src/cndb/plugins/tables/records.py#L85-L108)：auto_fill 已实现（on_update 覆盖、on_create 仅未传时补值）。
  - **`DataField.default_value` 在行创建路径完全未应用**（仅导入管道 `field_mapping.apply_gap_filling` 的 "default" 策略使用）→ 前端配置了默认值的新增行不会填入。
- 导入管道安全性：导入行经 `RowValidator` gap filling 后所有目标字段键均存在（"empty" 策略补 None），故 `_normalize_values` 中「键不存在才填默认值」不会改变导入行为。

## Proposed Changes

### 1. 前端 FieldManager.tsx（需求 1 + 2）

**1a. 编辑态 config 归一化（需求 1）**

`openDialog` 编辑分支，将：

```ts
config: target.config ?? {},
```

改为「类型默认值打底、已存值覆盖」：

```ts
config: { ...defaultConfigForType(target.field_type), ...(target.config ?? {}) },
```

- 缺失键（如 `auto_fill`）补默认 `''` → Radio「不自动」激活；已有键不被覆盖（options/颜色等安全）。
- 新建分支已有默认填充逻辑，不改。
- 注：`defaultConfigForType` 定义在文件底部，函数声明提升可用。

**1b. 字段行备注（需求 2）**

新增模块级 helper：

```ts
/** 字段行的备注文字：默认值 + 自动填充规则（备注风格，空设置不显示） */
function fieldNoteText(f: Field): string {
  const parts: string[] = []
  if (f.default_value !== null && f.default_value !== undefined && f.default_value !== '') {
    parts.push(`默认值：${String(f.default_value)}`)
  }
  const autoFill = (f.config?.auto_fill as string) ?? ''
  if ((f.field_type === 'date' || f.field_type === 'datetime') && autoFill) {
    parts.push(autoFill === 'on_create' ? '创建时自动填充' : '更新时自动填充')
  }
  return parts.join(' · ')
}
```

`fm-row` 中 name 之后插入（有内容才渲染）：

```tsx
{fieldNoteText(r) && <span className="fm-row-note" title={fieldNoteText(r)}>{fieldNoteText(r)}</span>}
```

`.fm-row-note` 用 `flex: 1` 占据中间剩余空间，tags/actions 保持靠右。

### 2. 前端 index.css（需求 2）

`.fm-row-actions` 前新增：

```css
/* 字段行备注文字（默认值 / 自动填充规则） */
.fm-row-note {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--cn-text-muted);
}
```

（若 `--cn-text-muted` 不存在则用 `var(--cn-text-secondary)`，实施时以 index.css 既有变量为准。）

### 3. 前端 GridPage.tsx（需求 3）

- 引入 `dayjs`（当前未引入，需新增 `import dayjs from 'dayjs'`）。
- 新增 helper：

```ts
/** 新增行草稿预填值：default_value 优先，其次 date/datetime 的 auto_fill（创建时/更新时规则），否则空值 */
function defaultValueForNewRow(f: Field): unknown {
  if (f.default_value !== null && f.default_value !== undefined && f.default_value !== '') {
    return normalizeCellValueForEdit(f.default_value, f)
  }
  const autoFill = (f.config?.auto_fill as string) ?? ''
  if (f.field_type === 'date' && (autoFill === 'on_create' || autoFill === 'on_update')) {
    return dayjs().format('YYYY-MM-DD')
  }
  if (f.field_type === 'datetime' && (autoFill === 'on_create' || autoFill === 'on_update')) {
    return dayjs().format('YYYY-MM-DD HH:mm:ss')
  }
  return normalizeCellValueForEdit(null, f)
}
```

- `draftFor` 中新行分支改为：

```ts
d[f.name] = record ? normalizeCellValueForEdit(record[f.name], f) : defaultValueForNewRow(f)
```

- 说明：`on_update` 规则后端每次更新都会覆盖，预填仅是可见性提示，不影响最终值；整行编辑（startEditRow）走 record 分支，不受影响。
- 预填值非空 → saveInline 会随 values 提交 → 用户所见即所得。

### 4. 后端 records.py（需求 3 兜底）

`_normalize_values` 在 auto_fill 块之后新增 default_value 填充（仅创建路径）：

```python
# ── DataField.default_value 默认值填充（仅创建、用户未传该字段时）──
if not for_update:
    for f in table.fields:
        if f.trashed or is_link_field(f):
            continue
        if f.name in values:
            continue  # 用户显式传过（含 None 清空意图）则不覆盖
        dv = f.default_value
        if dv is None or dv == "":
            continue
        ft = default_registry.get(f.field_type)
        if ft is None:
            continue
        try:
            result[f.db_column_name] = ft.validate_value(dv, f.config or {})
        except Exception as exc:
            logger.debug("字段 %s 默认值 %r 校验失败，跳过: %s", f.name, dv, exc)
```

- 放在必填校验之前 → 带默认值的必填字段不再误报「必填字段不能为空」。
- 导入管道不受影响（gap filling 已补齐所有键）。
- auto_fill 与 default_value 同时配置的 date 字段：用户未传时 default_value 优先生效（更明确），auto_fill 仅在无 default_value 时补当前时间。

### 5. 测试

**后端**（`tests/test_cov_records_edge.py` 或新建 `tests/test_records_default_value.py`，跟随现有风格）：

- create_row：text 字段 default_value 自动填入；number 字段字符串默认值被 coerce；date 字段 default_value 优先生效、无 default_value 时 auto_fill=on_create 填 today；非法默认值（number + "abc"）跳过不阻塞建行。
- update_row：不填默认值（for_update=True）。
- 用户显式传空值/传值时不被默认值覆盖（键存在即跳过）。
- 顺带移除 auto_fill 相关 `# pragma: no cover` 标记并补测试（types.py 中 Date/DateTime default_value、DateFieldConfig.should_auto_fill）。

**前端**（vitest，与现有 colocated 测试同风格）：

- FieldManager：新建/编辑对话框 — date 字段编辑时（config 无 auto_fill 键）「不自动」Radio 处于激活态；配置了 auto_fill 的字段编辑时对应按钮激活。
- FieldManager：字段行显示「默认值：xxx」与「创建时自动填充」备注文字；未配置则不渲染。
- GridPage 新增行：default_value 字段与 auto_fill date 字段草稿预填（扩展现有 `GridPage.newRow.test.tsx` 或新建文件）。

## Assumptions & Decisions

- **需求 1 根因判定**：新建字段默认已是「不填充」（`defaultConfigForType` 返回 `auto_fill: ''`），真正缺口是编辑存量/引入字段时 `auto_fill` 键缺失导致 Radio 无激活态 → 用「默认值打底合并」修复，同时保证未来新增 config 键也有兜底。
- **default_value 后端兜底**：纳入范围。理由：前端预填后若用户清空该单元格，保存时键不会提交，无后端兜底则默认值丢失；且 API/表单等其他创建路径也能受益。导入管道已验证不受影响。
- **时区**：前端预填本地时间字符串直接入库；后端 auto_fill 兜底路径存 UTC naive（现状行为，不在本次修改范围）。
- **on_update 预填**：仅作可见性提示（后端每次更新都会覆盖），不做特殊处理。
- 不改 `.trae/` 规则文件、不引入新依赖。

## Verification

1. 后端：`uv run pytest tests/test_records_default_value.py tests/test_cov_records_edge.py -x -q`（新测试 + 既有回归）。
2. 前端：`cd frontend && pnpm test`（vitest run）。
3. 门禁：`make check`（lint + typecheck + cov 全绿）。
4. 手动冒烟（可选）：新建 date 字段（自动填充=创建时）→ 网格新增行 → 日期单元格已预填今天；新建 text 字段（默认值=待办）→ 新增行预填「待办」；表设置 → 字段 Tab 中对应行显示备注文字。
5. 提交遵循 `feat: ...` 中文规范，推送用 `make push`。

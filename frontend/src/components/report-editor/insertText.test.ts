/**
 * buildFieldInsertText 单元测试 —— 插入语法单一来源的行为锚点.
 *
 * 主表/无分组：`{{ name }}`；额外表：`{{ records_by_table['表名'][0].name }}`。
 */

import { describe, expect, it } from 'vitest'
import { buildFieldInsertText } from './ReportTemplateEditor'

describe('buildFieldInsertText', () => {
  it('无分组时插入主表简化语法', () => {
    expect(buildFieldInsertText({ name: '姓名' })).toBe('{{ 姓名 }}')
  })

  it('主表分组（isPrimary）同样使用简化语法', () => {
    expect(
      buildFieldInsertText({ name: '姓名' }, { tableName: '员工表', isPrimary: true }),
    ).toBe('{{ 姓名 }}')
  })

  it('额外表分组使用 records_by_table 首行语法', () => {
    expect(
      buildFieldInsertText({ name: '项目名' }, { tableName: '项目表', isPrimary: false }),
    ).toBe("{{ records_by_table['项目表'][0].项目名 }}")
  })

  it('表名/字段名原样嵌入（不做转义，与模板字符串字面量语义一致）', () => {
    expect(
      buildFieldInsertText({ name: '薪资' }, { tableName: '2026 预算', isPrimary: false }),
    ).toBe("{{ records_by_table['2026 预算'][0].薪资 }}")
  })
})

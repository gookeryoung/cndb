/** 测试共享 fixture 工厂 —— 构造 API 类型对象的最小合法实例.
 *
 * 用途：单元测试与组件测试统一从这里拿 Field 等类型的数据构造器，
 * 避免各测试文件重复写全量字面量对象。
 */
import type { Field } from '@/api'

/** 构造一个最小合法的 Field 对象，仅覆盖必要字段，其余按测试需要覆盖 */
export function makeField(overrides: Partial<Field> & Pick<Field, 'id' | 'name' | 'field_type'>): Field {
  return { ...overrides }
}

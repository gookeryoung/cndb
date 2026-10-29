/** 公共搜索框 —— 全站统一的列表过滤 / 检索输入（需求 0068）.
 *
 * 口径（需求 0068 C1/C2）：
 * - 形态：`Input` + `SearchOutlined` prefix + `allowClear`，不使用 `Input.Search` 的搜索按钮；
 * - 尺寸：默认 `small`，可通过 `size` 覆盖；宽度由调用方经 `style` 控制；
 * - 文案：由调用方传入 placeholder，规则见需求卡片 C3
 *   （本地列表过滤「过滤 <对象>…」，跨数据检索「搜索 <范围>…」，省略号统一全角）。
 * 顶栏 GlobalSearch 为 GitHub 风格 borderless 形态，不在统一范围内（C5）。
 */
import { Input } from 'antd'
import type { InputProps } from 'antd'
import { SearchOutlined } from '@ant-design/icons'

type SearchInputProps = Omit<InputProps, 'prefix' | 'allowClear'>

export default function SearchInput({ size = 'small', ...rest }: SearchInputProps) {
  return <Input size={size} prefix={<SearchOutlined />} allowClear {...rest} />
}

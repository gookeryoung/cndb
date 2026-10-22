/** AI 建议 chips —— 标签 / 要点等短文本列表，可切换为多选（ADR 0020 C11）.
 *
 * 只负责展示与选择交互：是否把选中结果写回文档由调用方决定
 * （P1 标签建议只展示，不自动改文档元数据）。
 */

import { Empty, Tag } from 'antd'

import { SPACE, TEXT } from '@/theme/tokens'

export interface AiSuggestionListProps {
  /** 建议项（标签 / 要点文本） */
  items: string[]
  /** 受控选中项；传入时进入多选模式 */
  selected?: string[]
  /** 多选变更回调（配合 `selected` 使用） */
  onChange?: (next: string[]) => void
  /** 空态文案 */
  emptyText?: string
  /** 测试定位 id（子项 id 为 `${testId}-item-${文案}`） */
  testId?: string
}

export default function AiSuggestionList({
  items,
  selected,
  onChange,
  emptyText = '暂无建议',
  testId = 'ai-suggestion-list',
}: AiSuggestionListProps) {
  if (items.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
  }

  const selectable = selected !== undefined && typeof onChange === 'function'

  const toggle = (item: string) => {
    if (!selected || !onChange) return
    const next = selected.includes(item)
      ? selected.filter(value => value !== item)
      : [...selected, item]
    onChange(next)
  }

  return (
    <div
      data-testid={testId}
      style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: SPACE.md }}
    >
      {items.map(item =>
        selectable ? (
          <Tag.CheckableTag
            key={item}
            checked={selected!.includes(item)}
            onChange={() => toggle(item)}
            data-testid={`${testId}-item-${item}`}
            style={{ fontSize: TEXT.xs }}
          >
            {item}
          </Tag.CheckableTag>
        ) : (
          <Tag
            key={item}
            color="blue"
            data-testid={`${testId}-item-${item}`}
            style={{ marginInlineEnd: 0, fontSize: TEXT.xs }}
          >
            {item}
          </Tag>
        ),
      )}
    </div>
  )
}

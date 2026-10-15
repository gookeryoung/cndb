/** 文档查找 / 替换工具条 —— 纯展示组件.
 *
 * 逻辑（匹配计算、选中定位、写回正文）留在编辑器；这里只负责输入与触发，
 * 便于桌面顶栏与窄屏「更多」共用同一套界面。
 */

import { Button, Input, Space, Tooltip, Typography } from 'antd'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CloseOutlined,
  FontSizeOutlined,
  SwapOutlined,
} from '@ant-design/icons'

import type { MatchRange } from './documentSearch'

interface FindReplaceBarProps {
  /** 当前查询串 */
  query: string
  /** 替换文本 */
  replacement: string
  /** 全部匹配 */
  matches: MatchRange[]
  /** 当前选中匹配下标（-1 表示未定位） */
  currentIndex: number
  /** 是否区分大小写 */
  caseSensitive: boolean
  onQueryChange: (value: string) => void
  onReplacementChange: (value: string) => void
  onPrev: () => void
  onNext: () => void
  onReplace: () => void
  onReplaceAll: () => void
  onToggleCase: () => void
  onClose: () => void
}

export default function FindReplaceBar({
  query,
  replacement,
  matches,
  currentIndex,
  caseSensitive,
  onQueryChange,
  onReplacementChange,
  onPrev,
  onNext,
  onReplace,
  onReplaceAll,
  onToggleCase,
  onClose,
}: FindReplaceBarProps) {
  const total = matches.length
  const ordinal = total === 0 ? 0 : currentIndex >= 0 ? currentIndex + 1 : 0
  const countText = !query ? '' : total === 0 ? '无结果' : `${ordinal || 1}/${total}`

  return (
    <div className="cn-find-bar" data-testid="doc-find-bar">
      <Space size={4} wrap>
        <Input
          size="small"
          allowClear
          autoFocus
          placeholder="查找"
          value={query}
          style={{ width: 150 }}
          data-testid="doc-find-input"
          onChange={e => onQueryChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault()
              // Shift+Enter 向前找，Enter 向后找（与编辑器快捷键一致）
              if (e.shiftKey) onPrev()
              else onNext()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              onClose()
            }
          }}
        />
        <Typography.Text
          type={total === 0 && query ? 'danger' : 'secondary'}
          style={{ fontSize: 12, minWidth: 46, display: 'inline-block' }}
          data-testid="doc-find-count"
        >
          {countText}
        </Typography.Text>
        <Tooltip title="上一个（Shift+Enter）">
          <Button
            size="small"
            type="text"
            icon={<ArrowUpOutlined />}
            disabled={total === 0}
            aria-label="上一个匹配"
            data-testid="doc-find-prev"
            onMouseDown={e => e.preventDefault()}
            onClick={onPrev}
          />
        </Tooltip>
        <Tooltip title="下一个（Enter）">
          <Button
            size="small"
            type="text"
            icon={<ArrowDownOutlined />}
            disabled={total === 0}
            aria-label="下一个匹配"
            data-testid="doc-find-next"
            onMouseDown={e => e.preventDefault()}
            onClick={onNext}
          />
        </Tooltip>
        <Tooltip title={caseSensitive ? '区分大小写（已开启）' : '区分大小写（已关闭）'}>
          <Button
            size="small"
            type={caseSensitive ? 'primary' : 'text'}
            ghost={caseSensitive}
            icon={<FontSizeOutlined />}
            aria-label="区分大小写"
            aria-pressed={caseSensitive}
            data-testid="doc-find-case"
            onMouseDown={e => e.preventDefault()}
            onClick={onToggleCase}
          />
        </Tooltip>

        <Input
          size="small"
          allowClear
          placeholder="替换为"
          value={replacement}
          style={{ width: 140 }}
          data-testid="doc-find-replacement"
          onChange={e => onReplacementChange(e.target.value)}
        />
        <Button
          size="small"
          icon={<SwapOutlined />}
          disabled={total === 0}
          data-testid="doc-find-replace"
          onMouseDown={e => e.preventDefault()}
          onClick={onReplace}
        >
          替换
        </Button>
        <Button
          size="small"
          disabled={total === 0}
          data-testid="doc-find-replace-all"
          onMouseDown={e => e.preventDefault()}
          onClick={onReplaceAll}
        >
          全部替换
        </Button>
        <Tooltip title="关闭（Esc）">
          <Button
            size="small"
            type="text"
            icon={<CloseOutlined />}
            aria-label="关闭查找"
            data-testid="doc-find-close"
            onClick={onClose}
          />
        </Tooltip>
      </Space>
    </div>
  )
}

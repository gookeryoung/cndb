/** Markdown 快捷工具栏 —— 加粗 / 斜体 / 行内代码 / 标题 / 列表 / 引用 / 代码块 / 链接.
 *
 * 通过 `onAction(纯函数)` 把语法操作交回编辑器：编辑器负责读取 textarea 选区、写回内容并恢复光标。
 * 按钮 `onMouseDown` 阻止默认行为，保证点击工具栏时 textarea 的选区不丢失。
 */

import type { ReactNode } from 'react'
import { Button, Tooltip } from 'antd'
import {
  BoldOutlined,
  BlockOutlined,
  CodeOutlined,
  CompressOutlined,
  ExpandAltOutlined,
  FontSizeOutlined,
  HighlightOutlined,
  ItalicOutlined,
  LinkOutlined,
  MessageOutlined,
  OrderedListOutlined,
  TableOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'

import type { DocumentAiInstruction } from '@/api/documents'

import {
  insertLink,
  setHeadingLevel,
  toggleLinePrefix,
  toggleOrderedList,
  wrapCodeBlock,
  wrapSelection,
  type MarkdownEditResult,
} from './markdownEdit'

import TooltipDropdown from '@/components/TooltipDropdown'

/** 一次 Markdown 操作：输入文本与选区，输出新文本与新选区 */
export type MarkdownAction = (value: string, start: number, end: number) => MarkdownEditResult

interface MarkdownToolbarProps {
  onAction: (action: MarkdownAction) => void
  /** 插入 Markdown 表格骨架（列数 / 行数） */
  onInsertTable?: (cols: number, rows: number) => void
  disabled?: boolean
  /** AI 选区改写入口；不传时完全不渲染 AI 按钮（既有页面 / 测试无需感知） */
  onAiAction?: (instruction: DocumentAiInstruction) => void
  /** AI 请求中：只禁用 AI 按钮，不影响普通 Markdown 操作 */
  aiDisabled?: boolean
}

interface ToolbarItem {
  key: string
  icon: ReactNode
  title: string
  /** 普通按钮的语法操作；下拉类条目（标题 / 表格）由专门菜单驱动，无需此项 */
  action?: MarkdownAction
}

/** 标题层级下拉：level=0 表示取消标题（正文） */
export const MARKDOWN_HEADING_LEVELS: { key: string; label: string; level: number }[] = [
  { key: 'h1', label: '一级标题', level: 1 },
  { key: 'h2', label: '二级标题', level: 2 },
  { key: 'h3', label: '三级标题', level: 3 },
  { key: 'h4', label: '四级标题', level: 4 },
  { key: 'body', label: '正文', level: 0 },
]

/** Markdown 表格骨架预设（列数 × 行数） */
export const MARKDOWN_TABLE_PRESETS: { key: string; label: string; cols: number; rows: number }[] = [
  { key: '2x2', label: '2 列 × 2 行', cols: 2, rows: 2 },
  { key: '3x3', label: '3 列 × 3 行', cols: 3, rows: 3 },
  { key: '4x4', label: '4 列 × 4 行', cols: 4, rows: 4 },
]

/** AI 选区改写入口（润色 / 精简 / 扩写）：仅当页面传入 onAiAction 时渲染 */
export const MARKDOWN_AI_ITEMS: {
  key: DocumentAiInstruction
  icon: ReactNode
  title: string
  label: string
}[] = [
  { key: 'polish', icon: <HighlightOutlined />, title: 'AI 润色选中文本', label: '润色' },
  { key: 'shorten', icon: <CompressOutlined />, title: 'AI 精简选中文本', label: '精简' },
  { key: 'expand', icon: <ExpandAltOutlined />, title: 'AI 扩写选中文本', label: '扩写' },
]

/** 工具栏按钮定义（顺序即渲染顺序；快捷键在编辑器侧统一处理） */
export const MARKDOWN_TOOLBAR_ITEMS: ToolbarItem[] = [
  { key: 'bold', icon: <BoldOutlined />, title: '加粗（Ctrl+B）', action: (v, s, e) => wrapSelection(v, s, e, '**') },
  { key: 'italic', icon: <ItalicOutlined />, title: '斜体（Ctrl+I）', action: (v, s, e) => wrapSelection(v, s, e, '*') },
  { key: 'code', icon: <CodeOutlined />, title: '行内代码', action: (v, s, e) => wrapSelection(v, s, e, '`') },
  { key: 'heading', icon: <FontSizeOutlined />, title: '标题层级（H1–H4 / 正文）' },
  { key: 'ul', icon: <UnorderedListOutlined />, title: '无序列表', action: (v, s, e) => toggleLinePrefix(v, s, e, '- ') },
  { key: 'ol', icon: <OrderedListOutlined />, title: '有序列表', action: (v, s, e) => toggleOrderedList(v, s, e) },
  { key: 'quote', icon: <MessageOutlined />, title: '引用', action: (v, s, e) => toggleLinePrefix(v, s, e, '> ') },
  { key: 'codeblock', icon: <BlockOutlined />, title: '代码块', action: (v, s, e) => wrapCodeBlock(v, s, e) },
  { key: 'table', icon: <TableOutlined />, title: '插入 Markdown 表格' },
  { key: 'link', icon: <LinkOutlined />, title: '链接（Ctrl+K）', action: (v, s, e) => insertLink(v, s, e) },
]

export default function MarkdownToolbar({
  onAction,
  onInsertTable,
  disabled,
  onAiAction,
  aiDisabled,
}: MarkdownToolbarProps) {
  const triggerProps = {
    type: 'text' as const,
    size: 'small' as const,
    disabled,
    // 阻止默认行为：点击工具栏时 textarea 不失焦、选区不丢失
    onMouseDown: (e: React.MouseEvent) => e.preventDefault(),
  }

  return (
    <div className="cn-md-toolbar" role="toolbar" aria-label="Markdown 快捷工具" data-testid="md-toolbar">
      {MARKDOWN_TOOLBAR_ITEMS.map(item => {
        if (item.key === 'heading') {
          return (
            <TooltipDropdown
              key={item.key}
              title={item.title}
              menu={{
                items: MARKDOWN_HEADING_LEVELS.map(lv => ({
                  key: lv.key,
                  label: lv.label,
                  onClick: () => onAction((v, s, e) => setHeadingLevel(v, s, e, lv.level)),
                })),
              }}
            >
              <Button
                {...triggerProps}
                icon={item.icon}
                aria-label={item.title}
                data-testid={`md-toolbar-${item.key}`}
              />
            </TooltipDropdown>
          )
        }
        if (item.key === 'table') {
          return (
            <TooltipDropdown
              key={item.key}
              title={item.title}
              menu={{
                items: MARKDOWN_TABLE_PRESETS.map(p => ({
                  key: p.key,
                  label: p.label,
                  onClick: () => onInsertTable?.(p.cols, p.rows),
                })),
              }}
            >
              <Button
                {...triggerProps}
                icon={item.icon}
                aria-label={item.title}
                data-testid={`md-toolbar-${item.key}`}
              />
            </TooltipDropdown>
          )
        }
        return (
          <Tooltip key={item.key} title={item.title}>
            <Button
              {...triggerProps}
              icon={item.icon}
              aria-label={item.title}
              data-testid={`md-toolbar-${item.key}`}
              onClick={() => item.action && onAction(item.action)}
            />
          </Tooltip>
        )
      })}

      {/* AI 选区改写：只有页面传入 onAiAction 时才出现，默认完全不渲染 */}
      {onAiAction && (
        <>
          <span
            aria-hidden
            style={{
              display: 'inline-block',
              width: 1,
              height: 16,
              margin: '0 4px',
              background: 'var(--cn-border, #e8e8e8)',
            }}
          />
          {MARKDOWN_AI_ITEMS.map(item => (
            <Tooltip key={item.key} title={item.title}>
              <Button
                {...triggerProps}
                disabled={disabled || aiDisabled}
                icon={item.icon}
                aria-label={item.title}
                data-testid={`md-toolbar-ai-${item.key}`}
                onClick={() => onAiAction(item.key)}
              >
                {item.label}
              </Button>
            </Tooltip>
          ))}
        </>
      )}
    </div>
  )
}

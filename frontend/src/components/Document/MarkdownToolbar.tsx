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
  FontSizeOutlined,
  ItalicOutlined,
  LinkOutlined,
  MessageOutlined,
  OrderedListOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'

import {
  insertLink,
  toggleHeading,
  toggleLinePrefix,
  toggleOrderedList,
  wrapCodeBlock,
  wrapSelection,
  type MarkdownEditResult,
} from './markdownEdit'

/** 一次 Markdown 操作：输入文本与选区，输出新文本与新选区 */
export type MarkdownAction = (value: string, start: number, end: number) => MarkdownEditResult

interface MarkdownToolbarProps {
  onAction: (action: MarkdownAction) => void
  disabled?: boolean
}

interface ToolbarItem {
  key: string
  icon: ReactNode
  title: string
  action: MarkdownAction
}

/** 工具栏按钮定义（顺序即渲染顺序；快捷键在编辑器侧统一处理） */
export const MARKDOWN_TOOLBAR_ITEMS: ToolbarItem[] = [
  { key: 'bold', icon: <BoldOutlined />, title: '加粗（Ctrl+B）', action: (v, s, e) => wrapSelection(v, s, e, '**') },
  { key: 'italic', icon: <ItalicOutlined />, title: '斜体（Ctrl+I）', action: (v, s, e) => wrapSelection(v, s, e, '*') },
  { key: 'code', icon: <CodeOutlined />, title: '行内代码', action: (v, s, e) => wrapSelection(v, s, e, '`') },
  { key: 'heading', icon: <FontSizeOutlined />, title: '二级标题', action: (v, s, e) => toggleHeading(v, s, e, 2) },
  { key: 'ul', icon: <UnorderedListOutlined />, title: '无序列表', action: (v, s, e) => toggleLinePrefix(v, s, e, '- ') },
  { key: 'ol', icon: <OrderedListOutlined />, title: '有序列表', action: (v, s, e) => toggleOrderedList(v, s, e) },
  { key: 'quote', icon: <MessageOutlined />, title: '引用', action: (v, s, e) => toggleLinePrefix(v, s, e, '> ') },
  { key: 'codeblock', icon: <BlockOutlined />, title: '代码块', action: (v, s, e) => wrapCodeBlock(v, s, e) },
  { key: 'link', icon: <LinkOutlined />, title: '链接（Ctrl+K）', action: (v, s, e) => insertLink(v, s, e) },
]

export default function MarkdownToolbar({ onAction, disabled }: MarkdownToolbarProps) {
  return (
    <div className="cn-md-toolbar" role="toolbar" aria-label="Markdown 快捷工具" data-testid="md-toolbar">
      {MARKDOWN_TOOLBAR_ITEMS.map(item => (
        <Tooltip key={item.key} title={item.title}>
          <Button
            type="text"
            size="small"
            icon={item.icon}
            disabled={disabled}
            aria-label={item.title}
            data-testid={`md-toolbar-${item.key}`}
            // 阻止默认行为：点击工具栏时 textarea 不失焦、选区不丢失
            onMouseDown={e => e.preventDefault()}
            onClick={() => onAction(item.action)}
          />
        </Tooltip>
      ))}
    </div>
  )
}

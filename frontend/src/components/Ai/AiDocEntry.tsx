/** 文档页 AI 入口 —— 整篇摘要 / 标签建议的下拉入口（ADR 0020 P1）.
 *
 * 单独成组件是为了让页面用 `lazy(() => import(...))` 挂载：AI 面代码只在点击后
 * 才进入加载队列，不增加主入口体积。选区改写入口在 MarkdownToolbar（需要选区语义）。
 */

import { Dropdown } from 'antd'
import { ReadOutlined, RobotOutlined, TagsOutlined } from '@ant-design/icons'

import AiActionButton from './AiActionButton'

export interface AiDocEntryProps {
  /** 整篇摘要（后端读取最新版本正文） */
  onSummarize: () => void
  /** 标签建议（只展示建议，不自动改文档元数据） */
  onSuggestTags: () => void
  /** 请求中 / 文档不可用时禁用入口 */
  disabled?: boolean
}

export default function AiDocEntry({ onSummarize, onSuggestTags, disabled }: AiDocEntryProps) {
  return (
    <Dropdown
      trigger={['click']}
      disabled={disabled}
      menu={{
        items: [
          { key: 'summarize', icon: <ReadOutlined />, label: 'AI 摘要' },
          { key: 'suggest_tags', icon: <TagsOutlined />, label: 'AI 标签建议' },
        ],
        onClick: ({ key }) => {
          if (key === 'summarize') onSummarize()
          else onSuggestTags()
        },
      }}
    >
      {/* Dropdown 需要可挂事件的宿主元素：用 span 包裹，避免 Tooltip 影响 ref 转发 */}
      <span style={{ display: 'inline-block' }}>
        <AiActionButton
          icon={<RobotOutlined />}
          label="AI"
          tooltip="用大模型阅读整篇文档：生成摘要 / 标签建议"
          ariaLabel="AI 摘要与标签建议"
          testId="doc-ai-entry"
          disabled={disabled}
        />
      </span>
    </Dropdown>
  )
}

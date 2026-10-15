/** 实时协作 UI 组件：连接状态指示 + 文档在线成员.
 */

import { Badge, Space, Tag, Tooltip, Typography } from 'antd'
import { TeamOutlined, WifiOutlined } from '@ant-design/icons'
import type { PresenceMember, RealtimeStatus } from './realtimeClient'

const { Text } = Typography

const STATUS_TEXT: Record<RealtimeStatus, string> = {
  idle: '未连接',
  connecting: '连接中…',
  open: '实时已连接',
  reconnecting: '重连中…',
  closed: '已断开',
}

const STATUS_COLOR: Record<RealtimeStatus, string> = {
  idle: 'default',
  connecting: 'processing',
  open: 'success',
  reconnecting: 'warning',
  closed: 'default',
}

/** 顶栏连接状态（挂在 MainLayout 头部） */
export function RealtimeStatusTag({ status }: { status: RealtimeStatus }) {
  return (
    <Tooltip title={STATUS_TEXT[status]}>
      <Tag
        data-testid="realtime-status"
        color={STATUS_COLOR[status]}
        icon={<WifiOutlined />}
        style={{ marginInlineEnd: 0 }}
      >
        {status === 'open' ? '实时' : STATUS_TEXT[status]}
      </Tag>
    </Tooltip>
  )
}

/** 文档页在线成员（编辑者在前，编辑中的人高亮） */
export function DocumentViewers({
  members,
  currentUserId,
}: {
  members: PresenceMember[]
  /** 当前用户 id（后端为 number，前端 store 类型是 ID：number | string，故放宽） */
  currentUserId?: number | string
}) {
  if (members.length === 0) return null
  return (
    <Space size={4} data-testid="doc-viewers" wrap>
      <TeamOutlined style={{ color: '#8c8c8c' }} />
      {members.map((member) => {
        const isSelf = currentUserId !== undefined && String(member.user_id) === String(currentUserId)
        const editing = member.mode === 'editing'
        return (
          <Tooltip key={member.user_id} title={editing ? `${member.username} 正在编辑` : `${member.username} 正在查看`}>
            <Tag
              color={editing ? 'orange' : 'blue'}
              data-testid={`doc-viewer-${member.user_id}`}
              style={{ marginInlineEnd: 0 }}
            >
              {member.username}
              {isSelf ? '（我）' : ''}
              {editing ? ' · 编辑中' : ''}
            </Tag>
          </Tooltip>
        )
      })}
      {members.length > 1 && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {members.length} 人在线
        </Text>
      )}
    </Space>
  )
}

/** 纯文本形式的状态（用于测试与无条件渲染场景） */
export function realtimeStatusText(status: RealtimeStatus): string {
  return STATUS_TEXT[status]
}

export { Badge }

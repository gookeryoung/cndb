/** 实时协作 UI 组件：协作编辑状态标识 + 文档在线成员.
 */

import { Badge, Space, Tag, Tooltip, Typography } from 'antd'
import { DisconnectOutlined, SyncOutlined, TeamOutlined } from '@ant-design/icons'
import type { PresenceMember, RealtimeStatus } from './realtimeClient'

const { Text } = Typography

/** 协作状态文案（面向「协作编辑」语义，不再暴露"连接"这类底层实现词） */
const STATUS_TEXT: Record<RealtimeStatus, string> = {
  idle: '协作待接入',
  connecting: '协作接入中',
  open: '协作在线',
  reconnecting: '协作重连中',
  closed: '协作已断开',
}

const STATUS_COLOR: Record<RealtimeStatus, string> = {
  idle: 'default',
  connecting: 'processing',
  open: 'success',
  reconnecting: 'warning',
  closed: 'default',
}

const STATUS_HINT: Record<RealtimeStatus, string> = {
  idle: '尚未开始实时协作',
  connecting: '正在接入协作通道，稍候即可看到同文档的在线成员',
  open: '实时协作已在线：可看到同一文档的其他查看/编辑者，编辑锁与段落锁即时生效',
  reconnecting: '协作通道暂时中断，正在自动重连；此期间的改动仍会本地保留',
  closed: '协作通道已断开，暂时看不到其他协作者；可刷新页面恢复',
}

function StatusIcon({ status }: { status: RealtimeStatus }) {
  if (status === 'connecting' || status === 'reconnecting') return <SyncOutlined spin />
  if (status === 'closed') return <DisconnectOutlined />
  return <TeamOutlined />
}

/** 协作编辑状态标识（文档页顶栏；`idle` 不渲染以免空状态噪声） */
export function CollaborationStatusTag({ status }: { status: RealtimeStatus }) {
  if (status === 'idle') return null
  return (
    <Tooltip title={STATUS_HINT[status]}>
      <Tag
        data-testid="collab-status"
        data-status={status}
        color={STATUS_COLOR[status]}
        icon={<StatusIcon status={status} />}
        style={{ marginInlineEnd: 0 }}
      >
        {STATUS_TEXT[status]}
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

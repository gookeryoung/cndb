/**
 * 顶栏通知铃铛 —— 「谁把我加进了文档协作者」.
 *
 * 背景：文档级授权此前是"静默"的，被授权者只能自己翻目录树才发现。
 * 这里以未读角标 + 下拉列表呈现，点击条目标记已读并跳转到该文档。
 */
import { useMemo } from 'react'
import { App as AntApp, Badge, Button, Dropdown, Empty, List, Tooltip, Typography } from 'antd'
import { BellOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { notificationsApi, type NotificationItem } from '@/api/notifications'

const TYPE_LABEL: Record<string, (n: NotificationItem) => string> = {
    'document.collaborator_added': n =>
        `${n.actor_name || '有人'} 邀请你协作《${n.document_title || '未命名文档'}》${
            n.role === 'editor' ? '（可编辑）' : '（只读）'
        }`,
}

function describe(n: NotificationItem): string {
    const fn = TYPE_LABEL[n.type]
    return fn ? fn(n) : n.type
}

export default function NotificationBell() {
    const { message } = AntApp.useApp()
    const qc = useQueryClient()
    const navigate = useNavigate()

    const query = useQuery({
        queryKey: ['notifications'],
        queryFn: () => notificationsApi.list({ limit: 20 }),
        // 协作通知不要求实时：60s 轮询足够，避免每个页面都开长连接
        refetchInterval: 60_000,
        staleTime: 10_000,
    })

    const unread = query.data?.unread_count ?? 0

    const markRead = useMutation({
        mutationFn: (id: number) => notificationsApi.markRead(id),
        onSuccess: () => void qc.invalidateQueries({ queryKey: ['notifications'] }),
        onError: () => message.error('标记已读失败'),
    })

    const markAll = useMutation({
        mutationFn: () => notificationsApi.readAll(),
        onSuccess: () => void qc.invalidateQueries({ queryKey: ['notifications'] }),
        onError: () => message.error('操作失败'),
    })

    const panel = useMemo(
        () => {
            const items = query.data?.items ?? []
            return (
            <div
                data-testid="notif-panel"
                style={{
                    width: 340,
                    maxHeight: 420,
                    overflow: 'auto',
                    background: 'var(--cn-bg-container, #fff)',
                    borderRadius: 8,
                    boxShadow: '0 6px 16px rgba(0,0,0,.12)',
                    padding: 8,
                }}
            >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 4px 6px' }}>
                    <Typography.Text strong>通知</Typography.Text>
                    {unread > 0 && (
                        <Button
                            type="link"
                            size="small"
                            data-testid="notif-read-all"
                            loading={markAll.isPending}
                            onClick={() => markAll.mutate()}
                        >
                            全部已读
                        </Button>
                    )}
                </div>
                {items.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
                ) : (
                    <List
                        size="small"
                        dataSource={items}
                        renderItem={n => (
                            <List.Item
                                data-testid={`notif-item-${n.id}`}
                                style={{ cursor: n.document_id ? 'pointer' : 'default', opacity: n.read ? 0.6 : 1 }}
                                onClick={() => {
                                    if (!n.read) markRead.mutate(n.id)
                                    if (n.workspace_id && n.document_id) {
                                        navigate(`/w/${n.workspace_id}/documents/${n.document_id}`)
                                    }
                                }}
                            >
                                <Typography.Text style={{ fontSize: 13 }}>{describe(n)}</Typography.Text>
                            </List.Item>
                        )}
                    />
                )}
            </div>
            )
        },
        [query.data, unread, markAll, markRead, navigate],
    )

    return (
        <Dropdown popupRender={() => panel} trigger={['click']} placement="bottomRight">
            <Tooltip title="通知">
                <Button
                    type="text"
                    size="small"
                    data-testid="notif-bell"
                    aria-label={unread > 0 ? `通知（${unread} 条未读）` : '通知'}
                >
                    <Badge count={unread} size="small">
                        <BellOutlined />
                    </Badge>
                </Button>
            </Tooltip>
        </Dropdown>
    )
}

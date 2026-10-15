/** 文档协作者管理弹窗 —— 把草稿授权给指定同事（viewer 只读 / editor 可直编未发布内容）。 */
import { useState } from 'react'
import { App as AntApp, Button, Empty, List, Modal, Select, Space, Tag, Typography } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi, type DocumentPermissionRole } from '@/api/documents'
import { workspaceApi } from '@/api/workspaces'

interface Props {
    open: boolean
    onClose: () => void
    workspaceId: number
    documentId: number
    /** 是否可管理（创建者/工作区所有者）；false 时只读展示 */
    canManage: boolean
    /** 创建者 id：无需也无法对其授权 */
    createdById?: number | null
    currentUserId?: number | null
}

const ROLE_LABEL: Record<DocumentPermissionRole, string> = {
    viewer: '只读',
    editor: '可编辑',
}

export default function DocumentCollaboratorsModal({
    open,
    onClose,
    workspaceId,
    documentId,
    canManage,
    createdById,
    currentUserId,
}: Props) {
    const { message } = AntApp.useApp()
    const qc = useQueryClient()
    const [targetUser, setTargetUser] = useState<number | undefined>(undefined)
    const [role, setRole] = useState<DocumentPermissionRole>('viewer')

    const permQuery = useQuery({
        queryKey: ['document-permissions', workspaceId, documentId],
        queryFn: () => documentsApi.listPermissions(workspaceId, documentId),
        enabled: open,
    })

    const membersQuery = useQuery({
        queryKey: ['workspace-members', workspaceId],
        queryFn: () => workspaceApi.members(workspaceId),
        enabled: open && canManage,
    })

    const invalidate = () => {
        void qc.invalidateQueries({ queryKey: ['document-permissions', workspaceId, documentId] })
        // 授权会改变目录树/列表里"我能看到哪些文档"，一并使树失效
        void qc.invalidateQueries({ queryKey: ['document-tree', workspaceId] })
    }

    const grantMut = useMutation({
        mutationFn: (payload: { user_id: number; role: DocumentPermissionRole }) =>
            documentsApi.grantPermission(workspaceId, documentId, payload),
        onSuccess: (_data, payload) => {
            message.success(`已授权（${ROLE_LABEL[payload.role]}）：对方现在可以看到这份文档`)
            setTargetUser(undefined)
            invalidate()
        },
        onError: (err: unknown) => message.error(err instanceof Error ? err.message : '授权失败'),
    })

    const revokeMut = useMutation({
        mutationFn: (userId: number) => documentsApi.revokePermission(workspaceId, documentId, userId),
        onSuccess: () => {
            message.success('已撤销授权：对方将不再看到这份文档')
            invalidate()
        },
        onError: (err: unknown) => message.error(err instanceof Error ? err.message : '撤销失败'),
    })

    const existing = permQuery.data ?? []
    const existingIds = new Set(existing.map(i => i.user_id))
    const memberOptions = (membersQuery.data ?? [])
        .filter(
            m =>
                !existingIds.has(Number(m.user_id)) &&
                Number(m.user_id) !== createdById &&
                Number(m.user_id) !== currentUserId,
        )
        .map(m => ({
            value: Number(m.user_id),
            label: m.user?.nickname || m.user?.username || `用户 ${m.user_id}`,
        }))

    return (
        <Modal
            open={open}
            onCancel={onClose}
            title="协作者"
            footer={null}
            width={520}
            data-testid="doc-collaborators-modal"
        >
            <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                草稿（未发布）默认仅创建者与工作区所有可见。在这里可以把它开放给指定同事：
                「只读」可查看，「可编辑」可直接编辑未发布内容（已发布文档仍按工作区审核策略）。
            </Typography.Paragraph>

            {canManage && (
                <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
                    <Select
                        style={{ flex: 1 }}
                        placeholder="选择工作区成员"
                        value={targetUser}
                        onChange={setTargetUser}
                        options={memberOptions}
                        showSearch
                        optionFilterProp="label"
                        data-testid="doc-collaborator-select"
                    />
                    <Select<DocumentPermissionRole>
                        value={role}
                        onChange={setRole}
                        style={{ width: 110 }}
                        options={[
                            { value: 'viewer', label: ROLE_LABEL.viewer },
                            { value: 'editor', label: ROLE_LABEL.editor },
                        ]}
                    />
                    <Button
                        type="primary"
                        disabled={targetUser === undefined}
                        loading={grantMut.isPending}
                        onClick={() => targetUser !== undefined && grantMut.mutate({ user_id: targetUser, role })}
                    >
                        添加
                    </Button>
                </Space.Compact>
            )}

            <List
                size="small"
                loading={permQuery.isLoading}
                locale={{ emptyText: <Empty description="暂无协作者（仅创建者与工作区所有者可见）" /> }}
                dataSource={existing}
                renderItem={item => (
                    <List.Item
                        data-testid={`doc-collaborator-${item.user_id}`}
                        actions={
                            canManage
                                ? [
                                      <Button
                                          key="revoke"
                                          type="link"
                                          danger
                                          size="small"
                                          loading={revokeMut.isPending}
                                          data-testid={`doc-collaborator-revoke-${item.user_id}`}
                                          onClick={() => revokeMut.mutate(item.user_id)}
                                      >
                                          移除
                                      </Button>,
                                  ]
                                : undefined
                        }
                    >
                        <Space>
                            <span>{item.nickname || item.username || `用户 ${item.user_id}`}</span>
                            <Tag color={item.role === 'editor' ? 'blue' : 'default'}>{ROLE_LABEL[item.role]}</Tag>
                        </Space>
                    </List.Item>
                )}
            />
        </Modal>
    )
}

/** 视图权限 Drawer —— 三档可见性 + 共享名单（ADR 0003 P3）.
 *
 * 交互约定：**即时生效**（无「保存」按钮）——
 * 切档走 `POST /views/{id}/visibility`，加人/改权走 `PUT /views/{id}/members/{uid}`，
 * 收权走 `DELETE`。后端还有「开档 + 名单一次提交」的原子形态（`members` 字段），
 * 供批量客户端使用；逐条即时生效对单人多选场景请求量相同，但状态更简单、反馈更快。
 *
 * 权限门控（全部以**后端下发的能力位**为准，前端不做二次推断）：
 * - 能打开本 Drawer ⇔ `view.can_manage`（后端 VIEW_MANAGE）
 * - 「表内所有人可见」档 ⇔ 表 `EDIT_VIEWS`（决策 D4），由父级 `canPublishToTable` 传入
 * - `editor` 授权 ⇔ 对方有该表 `EDIT_VIEWS`，由 `shareable-members` 的 `can_edit_views` 标注
 */

import { useCallback, useEffect, useState } from 'react'
import { App as AntApp, Button, Drawer, Empty, Radio, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { DeleteOutlined, InfoCircleOutlined, LockOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import { viewApi, type ShareableMember, type View, type ViewMember, type ViewMemberRole, type ViewVisibility } from '@/api'

const { Text, Paragraph } = Typography

interface ViewPermissionDrawerProps {
  open: boolean
  onClose: () => void
  wid: string
  tid: string
  /** 当前视图（null = 未选中，Drawer 内部空态） */
  view: View | null
  /** 当前用户是否有该表 EDIT_VIEWS —— 决定「表内所有人可见」档是否可选（D4） */
  canPublishToTable: boolean
  /** 档位/名单变更成功后回传最新视图，供父级刷新列表 */
  onUpdated?: (view: View) => void
}

/** 档位选项（含门控说明，供单选行右侧灰字提示） */
const TIER_OPTIONS: ReadonlyArray<{
  value: ViewVisibility
  label: string
  icon: React.ReactNode
  hint: string
  /** 需要表 EDIT_VIEWS 才能切到该档 */
  needsEditViews?: boolean
}> = [
  {
    value: 'private',
    label: '仅本人可见',
    icon: <LockOutlined />,
    hint: '默认档位。其他成员（含表管理员）看不到这个视图',
  },
  {
    value: 'shared',
    label: '指定成员可见',
    icon: <UserOutlined />,
    hint: '仅下方名单内的成员可见；可再区分「只读」与「可编辑」',
  },
  {
    value: 'table',
    label: '表内所有人可见',
    icon: <TeamOutlined />,
    hint: '所有能看到这张表的成员都能看到（改配置仍需视图编辑权限）',
    needsEditViews: true,
  },
]

const ROLE_OPTIONS: { value: ViewMemberRole; label: string }[] = [
  { value: 'viewer', label: '只读' },
  { value: 'editor', label: '可编辑' },
]

export default function ViewPermissionDrawer({
  open, onClose, wid, tid, view, canPublishToTable, onUpdated,
}: ViewPermissionDrawerProps) {
  const { message } = AntApp.useApp()
  const [visibility, setVisibility] = useState<ViewVisibility>('private')
  const [members, setMembers] = useState<ViewMember[]>([])
  const [shareable, setShareable] = useState<ShareableMember[]>([])
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState(false)

  const viewId = view?.id != null ? String(view.id) : null

  /** 拉取名单与可授权对象（两者并行；名单在非 shared 档也可能有历史留存） */
  const load = useCallback(async (opts: { silent?: boolean } = {}) => {
    if (!viewId) return
    if (!opts.silent) setLoading(true)
    try {
      const [roster, candidates] = await Promise.all([
        viewApi.listMembers(wid, tid, viewId),
        viewApi.shareableMembers(wid, tid, viewId),
      ])
      setMembers(roster)
      setShareable(candidates)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载共享名单失败')
    } finally {
      if (!opts.silent) setLoading(false)
    }
  }, [wid, tid, viewId, message])

  // 打开时同步档位 + 拉取名单；关闭时清空，避免下次打开闪现上一个视图的数据
  useEffect(() => {
    if (!open) return
    if (!view) return
    setVisibility(view.visibility ?? 'private')
    void load()
  }, [open, view, load])

  useEffect(() => {
    if (open) return
    setMembers([])
    setShareable([])
  }, [open])

  /** 切档：只改档位，不动名单（后端 members 缺省 = 保留既有名单） */
  const handleVisibility = useCallback(async (next: ViewVisibility) => {
    if (!viewId || next === visibility) return
    const option = TIER_OPTIONS.find(o => o.value === next)
    if (option?.needsEditViews && !canPublishToTable) {
      message.warning('开放给表内所有人需要该数据表的「视图编辑」权限，请联系表管理员')
      return
    }
    setSwitching(true)
    try {
      const updated = await viewApi.setVisibility(wid, tid, viewId, { visibility: next })
      setVisibility(updated.visibility ?? next)
      onUpdated?.(updated)
      message.success(option ? `已设为「${option.label}」` : '可见性已更新')
      await load({ silent: true })
    } catch (err) {
      message.error(err instanceof Error ? err.message : '切换可见性失败')
    } finally {
      setSwitching(false)
    }
  }, [viewId, visibility, canPublishToTable, wid, tid, message, onUpdated, load])

  const handleAddMember = useCallback(async (userId: number) => {
    if (!viewId) return
    try {
      await viewApi.setMember(wid, tid, viewId, userId, 'viewer')
      await load({ silent: true })
      const updated = await viewApi.get(wid, tid, viewId)
      onUpdated?.(updated)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '添加成员失败')
    }
  }, [viewId, wid, tid, message, load, onUpdated])

  const handleRoleChange = useCallback(async (userId: number, role: ViewMemberRole) => {
    if (!viewId) return
    try {
      await viewApi.setMember(wid, tid, viewId, userId, role)
      await load({ silent: true })
    } catch (err) {
      message.error(err instanceof Error ? err.message : '修改权限失败')
    }
  }, [viewId, wid, tid, message, load])

  const handleRemoveMember = useCallback(async (userId: number) => {
    if (!viewId) return
    try {
      await viewApi.removeMember(wid, tid, viewId, userId)
      await load({ silent: true })
      const updated = await viewApi.get(wid, tid, viewId)
      onUpdated?.(updated)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '移除成员失败')
    }
  }, [viewId, wid, tid, message, load, onUpdated])

  const memberIds = new Set(members.map(m => m.user_id))
  const addableOptions = shareable
    .filter(c => !memberIds.has(c.user_id))
    .map(c => ({
      value: c.user_id,
      label: c.can_edit_views ? `${c.nickname || c.username}（可编辑）` : (c.nickname || c.username),
    }))

  const isShared = visibility === 'shared'
  const preservedRoster = !isShared && members.length > 0

  return (
    <Drawer
      title={view ? `视图权限 · ${view.name}` : '视图权限'}
      size={480}
      open={open}
      onClose={onClose}
      destroyOnHidden
      data-testid="view-permission-drawer"
    >
      {!view ? (
        <Empty description="未选中视图" />
      ) : (
        <Spin spinning={loading}>
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            视图权限只在数据表权限范围内放宽，不会让看不到这张表的人看到视图。
          </Paragraph>

          <Radio.Group
            value={visibility}
            onChange={e => void handleVisibility(e.target.value as ViewVisibility)}
            disabled={switching}
            style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
          >
            {TIER_OPTIONS.map(option => {
              const blocked = option.needsEditViews && !canPublishToTable
              return (
                <Radio key={option.value} value={option.value} disabled={blocked} data-testid={`view-tier-${option.value}`}>
                  <Space size={6} align="center">
                    {option.icon}
                    <Text strong>{option.label}</Text>
                    {option.value === 'shared' && members.length > 0 && <Tag color="cyan">{members.length} 人</Tag>}
                    {blocked && (
                      <Tooltip title="需要该数据表的「视图编辑」权限">
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          <InfoCircleOutlined /> 无权限
                        </Text>
                      </Tooltip>
                    )}
                  </Space>
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>{option.hint}</Text>
                  </div>
                </Radio>
              )
            })}
          </Radio.Group>

          {/* 名单区 —— 仅 shared 档可编辑（其余档名单保留但失效，后端会拒写） */}
          <div style={{ marginTop: 20 }} data-testid="view-member-section">
            {isShared ? (
              <>
                <Select
                  mode="multiple"
                  allowClear
                  value={[]}
                  placeholder="添加成员（本工作区且对该表可见）"
                  style={{ width: '100%' }}
                  options={addableOptions}
                  onChange={ids => {
                    const picked = (ids as number[]).filter(id => !memberIds.has(id))
                    picked.forEach(id => void handleAddMember(id))
                  }}
                  data-testid="view-member-add"
                  notFoundContent={<Text type="secondary">没有可添加的成员</Text>}
                />

                <div style={{ marginTop: 12 }}>
                  {members.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未共享给任何成员" />
                  ) : (
                    members.map(m => (
                      <div
                        key={m.user_id}
                        data-testid={`view-member-row-${m.user_id}`}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          padding: '6px 0', borderBottom: '1px solid var(--cn-border)',
                        }}
                      >
                        <Text style={{ flex: 1, minWidth: 0 }} ellipsis>
                          {m.nickname || m.username}
                          {!m.available && (
                            <Tooltip title="对方已离开工作区或失去该表权限，该授权当前不生效">
                              <Tag color="default" style={{ marginLeft: 6 }}>已失效</Tag>
                            </Tooltip>
                          )}
                        </Text>
                        <Select
                          size="small"
                          value={m.role}
                          style={{ width: 96 }}
                          options={ROLE_OPTIONS}
                          onChange={role => void handleRoleChange(m.user_id, role as ViewMemberRole)}
                          data-testid={`view-member-role-${m.user_id}`}
                        />
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label={`移除 ${m.username}`}
                          onClick={() => void handleRemoveMember(m.user_id)}
                        />
                      </div>
                    ))
                  )}
                </div>
              </>
            ) : preservedRoster ? (
              <Text type="secondary" style={{ fontSize: 12 }} data-testid="view-member-preserved">
                已保留 {members.length} 人的共享名单，切回「指定成员可见」后自动恢复生效。
              </Text>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>切换到「指定成员可见」后即可选择共享对象。</Text>
            )}
          </div>
        </Spin>
      )}
    </Drawer>
  )
}

/** Grid 顶部工具栏 — 标题/统计徽标/主操作区（从 GridPage 抽出）.
 *
 * 注：返回导航由 MainLayout 融合导航行的面包屑（数据表 tab / 表名）承担，
 * 工具栏不再重复渲染返回按钮。 */

import { Button, Space, Typography, Tooltip, Dropdown } from 'antd'
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, EditOutlined,
  MoreOutlined, CopyOutlined, ImportOutlined,
  SwapOutlined, MenuOutlined, ColumnWidthOutlined, ClearOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { tableApi } from '@/api'
import { App as AntApp } from 'antd'
import { useResponsive } from '@/hooks/useResponsive'

const { Text } = Typography

interface GridToolbarProps {
  wid: string
  tid: string
  tableKey: string
  tableName?: string
  recordCount?: number | null
  mode: string
  /** 新增行按钮是否禁用（编辑中或无编辑权限） */
  addRowDisabled: boolean
  onAddRow: () => void
  /** 当前用户对该表的权限徽标文案（如「可编辑」「只读」）；缺省不显示 */
  permissionLabel?: string
  /** 编辑选中的行（仅恰好选中一行时可用）；缺省不显示按钮 */
  onEditRow?: () => void
  /** 编辑行按钮是否禁用（未选中或多选） */
  editRowDisabled?: boolean
  canEditSchema: boolean
  /** 是否可执行数据治理（MANAGE_DATA） */
  canManageData: boolean
  onOpenTableSettings: () => void
  onOpenImportExport: () => void
  onOpenGovernance: () => void
  activeViewName?: string
  activeViewId?: number | string | null
  onCopyTable: (opts: { mode: 'structure' | 'all' | 'view'; viewId?: number | string }) => void
  onMove: () => void
  /** 重置列布局（列宽覆盖 + 列序）；缺省表示当前模式不可用（菜单项置灰） */
  onResetColumnLayout?: () => void
}

export default function GridToolbar({
  wid, tid, tableKey, tableName, recordCount, mode, addRowDisabled, onAddRow,
  permissionLabel, onEditRow, editRowDisabled,
  canEditSchema, canManageData, onOpenTableSettings, onOpenImportExport, onOpenGovernance,
  activeViewName, activeViewId, onCopyTable, onMove, onResetColumnLayout,
}: GridToolbarProps) {
  const { message, modal } = AntApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // 移动端按钮收纳为 icon-only，功能入口不变（Tooltip 仍提供说明）
  const { isMobile } = useResponsive()

  return (
    <div className="cn-grid-toolbar" style={{ padding: '8px 16px', borderBottom: '1px solid var(--cn-border)', display: 'flex', gap: 8, alignItems: 'center' }}>
      <Text strong ellipsis style={{ fontSize: 16, maxWidth: isMobile ? '36vw' : undefined }}>{tableName || '...'}</Text>
      {/* 统计小徽标（来自后端增强字段） */}
      {recordCount != null && recordCount > 0 && (
        <span className="cn-record-pill">{recordCount} 条记录</span>
      )}
      {/* 当前用户对该表的权限徽标 —— 明确告知只读/可编辑，避免误操作 */}
      {permissionLabel && (
        <Tooltip title={`当前用户对该表的权限：${permissionLabel}`}>
          <span
            className="cn-record-pill"
            data-testid="table-permission-pill"
            style={permissionLabel === '只读' ? { color: 'var(--cn-text-tertiary, #8c8c8c)' } : undefined}
          >
            {permissionLabel}
          </span>
        </Tooltip>
      )}
      <div style={{ flex: 1 }} />
      {/* 右侧主操作区 */}
      <Space size={6}>
        {mode === 'grid' && (
          <Tooltip title={addRowDisabled ? '请先完成当前编辑' : '新增一行：在表格末尾添加空记录，逐格填写后回车保存'}>
            <Button
              type="primary"
              size="middle"
              icon={<PlusOutlined />}
              data-testid="add-row-btn"
              onClick={onAddRow}
              disabled={addRowDisabled}
            >
              新增行
            </Button>
          </Tooltip>
        )}
        {mode === 'grid' && onEditRow && (
          <Tooltip title={editRowDisabled ? '编辑行：请先在表格中选中一行' : '编辑行：打开选中行的详情抽屉'}>
            <Button
              size="middle"
              icon={<EditOutlined />}
              data-testid="edit-row-btn"
              onClick={onEditRow}
              disabled={editRowDisabled}
            >
              编辑行
            </Button>
          </Tooltip>
        )}
        <Tooltip title="表设置：管理字段结构、视图列表与权限授权">
          <Button
            data-testid="table-settings-btn"
            icon={<MenuOutlined />}
            onClick={onOpenTableSettings}
          >
            {!isMobile && '表设置'}
          </Button>
        </Tooltip>
        <Tooltip title="导入 / 导出：批量新增或更新数据、导出 CSV / Excel / JSON">
          <Button icon={<ImportOutlined />} data-testid="import-export-btn" onClick={onOpenImportExport}>{!isMobile && '更新/导出'}</Button>
        </Tooltip>
        <Tooltip title="数据治理：重复检测、合并与清洗">
          <Button
            icon={<ClearOutlined />}
            data-testid="governance-btn"
            disabled={!canManageData}
            onClick={onOpenGovernance}
          >
            {!isMobile && '数据治理'}
          </Button>
        </Tooltip>
        <Dropdown menu={{
          items: [
            { key: 'refresh', icon: <ReloadOutlined />, label: '刷新', onClick: () => queryClient.invalidateQueries({ queryKey: ['table-records', tableKey] }) },
            { key: 'reset-layout', icon: <ColumnWidthOutlined />, label: '重置列宽与列序', disabled: !onResetColumnLayout, onClick: onResetColumnLayout },
            { type: 'divider' },
            {
              key: 'copy', icon: <CopyOutlined />, label: '复制表',
              children: [
                { key: 'copy-structure', label: '仅复制表结构', onClick: () => onCopyTable({ mode: 'structure' }) },
                { key: 'copy-all', label: '复制表结构 + 全部数据', onClick: () => onCopyTable({ mode: 'all' }) },
                {
                  key: 'copy-view',
                  label: `复制当前视图数据${activeViewName ? `（${activeViewName}）` : ''}`,
                  disabled: !activeViewId,
                  onClick: () => activeViewId && onCopyTable({ mode: 'view', viewId: activeViewId }),
                },
              ],
            },
            { key: 'move', icon: <SwapOutlined />, label: '移动到其他工作区', onClick: onMove },
            { type: 'divider' },
            {
              key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除表',
              disabled: !canEditSchema,
              onClick: () => modal.confirm({
                title: `删除表 "${tableName}" ？`,
                content: '表内所有记录和字段将被永久移除。此操作不可恢复。',
                okText: '删除',
                okType: 'danger',
                cancelText: '取消',
                onOk: () => tableApi.remove(wid, tid).then(() => {
                  message.success('表已删除')
                  queryClient.invalidateQueries({ queryKey: ['workspaces', wid, 'tables'] })
                  navigate(`/w/${wid}`)
                }),
              }),
            },
          ]
        }}><Tooltip title="更多操作：刷新、复制表、移动工作区、删除表"><Button icon={<MoreOutlined />} data-testid="grid-more-menu" /></Tooltip></Dropdown>
      </Space>
    </div>
  )
}

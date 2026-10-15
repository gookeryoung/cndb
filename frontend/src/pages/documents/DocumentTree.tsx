/** 文档结构树 — 思源笔记式左栏导航：组树 + 右键就地管理（新建/重命名/移动/删除）.

数据源为后端扁平 tree 列表，前端按 parent_id 组装层级；
选中态由路由驱动（/w/:wid/documents/:docId），编辑文档时自动展开其祖先链。
*/

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { App as AntApp, Button, Dropdown, Empty, Input, Modal, Tree, TreeSelect } from 'antd'
import type { DataNode } from 'antd/es/tree'
import {
  ApartmentOutlined,
  CalendarOutlined,
  DeleteOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FolderAddOutlined,
  FolderOutlined,
  MoreOutlined,
  PushpinFilled,
  PushpinOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '@/api/documents'
import type { DocumentItem } from '@/api/documents'

/** 树节点：文档/文件夹 + 子节点 */
export interface DocTreeNode extends DocumentItem {
  children: DocTreeNode[]
}

/** 扁平文档列表组装为层级树（孤儿节点挂到根，避免数据异常时整树丢失） */
export function buildDocTree(items: DocumentItem[]): DocTreeNode[] {
  const byId = new Map<number, DocTreeNode>()
  for (const it of items) byId.set(it.id, { ...it, children: [] })
  const roots: DocTreeNode[] = []
  for (const node of byId.values()) {
    const parent = node.parent_id != null ? byId.get(node.parent_id) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  return roots
}

/** 从扁平列表解析节点祖先链（含自身） */
export function ancestorChain(items: DocumentItem[], id: number): DocumentItem[] {
  const byId = new Map(items.map(d => [d.id, d]))
  const chain: DocumentItem[] = []
  let cur = byId.get(id)
  while (cur) {
    chain.unshift(cur)
    cur = cur.parent_id != null ? byId.get(cur.parent_id) : undefined
  }
  return chain
}

/** 收集节点自身及全部子孙 id（移动/拖拽时用于环检测与目标排除） */
export function descendantIds(node: DocTreeNode): number[] {
  const ids: number[] = [node.id]
  for (const child of node.children) ids.push(...descendantIds(child))
  return ids
}

/** 按 id 递归查找树节点（用于系列详情定位当前文件夹等） */
export function findNodeById(nodes: DocTreeNode[], id: number): DocTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const hit = findNodeById(n.children, id)
    if (hit) return hit
  }
  return null
}

/** 拖拽落点相对语义：-1 放目标之前 / 1 放目标之后 / 0 成为目标的最后子节点 */
export type DropRel = -1 | 0 | 1

/** 拖拽产生的元数据更新操作（PATCH 逐项提交） */
export interface DropOp {
  id: number
  parent_id?: number
  sort_order?: number
}

/**
 * 规划拖拽移动：返回需逐项 PATCH 的操作序列；返回 null 表示被拦截。
 *
 * 拦截条件：目标为拖拽节点自身或其子孙（防环）、或目标非文件夹却要求成为其子节点。
 * 排序语义：重排后的同级列表按索引赋 sort_order，仅对发生变化的项生成操作。
 */
export function planDropMove(
  roots: DocTreeNode[],
  dragId: number,
  targetId: number,
  rel: DropRel,
): DropOp[] | null {
  const dragNode = findByKey(roots, dragId)
  const targetNode = findByKey(roots, targetId)
  if (!dragNode || !targetNode) return null
  if (dragId === targetId) return null
  // 环检测：目标在自身子树内（含自身）即拦截（rel=0 时新父为目标，rel=±1 时新父为目标的父——均为子树内）
  if (new Set(descendantIds(dragNode)).has(targetId)) return null
  // 成为子节点要求目标是文件夹
  if (rel === 0 && !targetNode.is_folder) return null

  const newParentId = rel === 0 ? targetId : (targetNode.parent_id ?? null)
  const parentChildren =
    newParentId == null ? roots : (findByKey(roots, newParentId)?.children ?? [])
  const siblings = parentChildren.filter(n => n.id !== dragId)

  const ordered = [...siblings]
  if (rel === 0) {
    ordered.push(dragNode)
  } else {
    const targetIdx = siblings.findIndex(n => n.id === targetId)
    if (targetIdx < 0) ordered.push(dragNode)
    else ordered.splice(rel === -1 ? targetIdx : targetIdx + 1, 0, dragNode)
  }

  const ops: DropOp[] = []
  if ((dragNode.parent_id ?? null) !== newParentId) {
    ops.push({ id: dragId, parent_id: newParentId ?? 0 }) // 0 = 根目录约定
  }
  ordered.forEach((n, idx) => {
    if (n.sort_order !== idx) ops.push({ id: n.id, sort_order: idx })
  })
  return ops
}

const STATUS_DOT_COLOR: Record<string, string> = {
  draft: 'var(--cn-text-muted, #999)',
  published: 'var(--cn-success, #52c41a)',
  archived: 'var(--cn-warning, #faad14)',
}

/** 右键菜单触达的节点上下文 */
interface MenuState {
  open: boolean
  x: number
  y: number
  node: DocTreeNode | null
}

/** 就地操作弹窗状态 */
type DialogState =
  | { kind: 'create'; type: 'doc' | 'folder'; parent: DocTreeNode | null }
  | { kind: 'rename'; node: DocTreeNode }
  | { kind: 'move'; node: DocTreeNode }
  | null

export default function DocumentTree({ onNavigate }: { onNavigate?: () => void }) {
  const { wid, docId } = useParams<{ wid: string; docId?: string }>()
  const navigate = useNavigate()
  const { modal, message } = AntApp.useApp()
  const qc = useQueryClient()
  const workspaceId = Number(wid)
  const selectedId = docId != null ? Number(docId) : null

  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([])
  const [keyword, setKeyword] = useState('')
  const [menu, setMenu] = useState<MenuState>({ open: false, x: 0, y: 0, node: null })
  const [dialog, setDialog] = useState<DialogState>(null)
  const [inputValue, setInputValue] = useState('')
  const [moveTarget, setMoveTarget] = useState<number | null>(null)

  const treeQuery = useQuery({
    queryKey: ['documents', workspaceId, 'tree'],
    queryFn: () => documentsApi.tree(workspaceId),
    enabled: Number.isFinite(workspaceId),
  })

  const items = useMemo(() => treeQuery.data ?? [], [treeQuery.data])
  const treeData = useMemo(() => buildDocTree(items), [items])

  const invalidate = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['documents', workspaceId] })
  }, [qc, workspaceId])

  // 选中文档变化时展开其祖先链（仅追加，不折叠用户已展开的节点）
  useEffect(() => {
    if (selectedId == null || items.length === 0) return
    const chain = ancestorChain(items, selectedId)
    if (chain.length <= 1) return
    setExpandedKeys(prev => {
      const set = new Set(prev)
      for (const n of chain.slice(0, -1)) set.add(n.id)
      return [...set]
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, items.length, treeQuery.dataUpdatedAt])

  const createMut = useMutation({
    mutationFn: (vars: { title: string; isFolder: boolean; parentId: number | null }) =>
      documentsApi.create(workspaceId, {
        title: vars.title,
        content: vars.isFolder ? '' : '',
        is_folder: vars.isFolder,
        parent_id: vars.parentId,
      }),
    onSuccess: doc => {
      message.success(doc.is_folder ? '文件夹已创建' : '文档已创建')
      setDialog(null)
      setInputValue('')
      invalidate()
      // 新建后：展开父级并选中新节点（文件夹仅展开，文档直接进入编辑）
      setExpandedKeys(prev => {
        const set = new Set(prev)
        if (doc.parent_id != null) set.add(doc.parent_id)
        return [...set]
      })
      if (!doc.is_folder) {
        navigate(`/w/${workspaceId}/documents/${doc.id}`)
        onNavigate?.()
      }
    },
    onError: () => message.error('创建失败'),
  })

  const renameMut = useMutation({
    mutationFn: (vars: { id: number; title: string }) =>
      documentsApi.updateMeta(workspaceId, vars.id, { title: vars.title }),
    onSuccess: () => {
      message.success('已重命名')
      setDialog(null)
      invalidate()
    },
    onError: () => message.error('重命名失败'),
  })

  const moveMut = useMutation({
    mutationFn: (vars: { id: number; parentId: number | null }) =>
      documentsApi.updateMeta(workspaceId, vars.id, {
        parent_id: vars.parentId ?? 0,
      }),
    onSuccess: () => {
      message.success('已移动')
      setDialog(null)
      setMoveTarget(null)
      invalidate()
    },
    onError: () => message.error('移动失败'),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => documentsApi.remove(workspaceId, id),
    onSuccess: () => {
      message.success('已删除')
      setMenu({ open: false, x: 0, y: 0, node: null })
      invalidate()
    },
    onError: () => message.error('删除失败'),
  })

  // 每日笔记（幂等）：后端当日复用同一篇，返回后进入编辑
  /** 置顶 / 取消置顶（个人偏好）：成功后整树刷新，置顶项由后端排到最前 */
  const pinMut = useMutation({
    mutationFn: (id: number) => documentsApi.pinDocument(workspaceId, id),
    onSuccess: () => {
      message.success('已置顶')
      invalidate()
    },
    onError: () => message.error('置顶失败'),
  })

  const unpinMut = useMutation({
    mutationFn: (id: number) => documentsApi.unpinDocument(workspaceId, id),
    onSuccess: () => {
      message.success('已取消置顶')
      invalidate()
    },
    onError: () => message.error('取消置顶失败'),
  })


  const dailyNoteMut = useMutation({
    mutationFn: () => documentsApi.dailyNote(workspaceId),
    onSuccess: doc => {
      invalidate()
      navigate(`/w/${workspaceId}/documents/${doc.id}`)
      onNavigate?.()
    },
    onError: () => message.error('打开今日笔记失败'),
  })

  // 拖拽整理：逐项 PATCH（移动 parent_id + 同级排序 sort_order），完成后整树刷新
  const dropMut = useMutation({
    mutationFn: async (ops: DropOp[]) => {
      for (const op of ops) {
        await documentsApi.updateMeta(workspaceId, op.id, {
          parent_id: op.parent_id,
          sort_order: op.sort_order,
        })
      }
    },
    onSuccess: () => {
      message.success('已移动')
      invalidate()
    },
    onError: () => message.error('移动失败'),
  })

  /** 打开节点操作菜单（右键与「更多」按钮共用；位置取自触发元素） */
  const openNodeMenu = useCallback((node: DocTreeNode, x: number, y: number) => {
    setMenu({ open: true, x, y, node })
  }, [])

  /** 节点「更多」按钮：桌面悬停显现、触摸端常显；右键菜单在触摸设备不可达，必须有可点入口 */
  const moreButton = useCallback((node: DocTreeNode) => (
    <Button
      type="text"
      size="small"
      className="cn-doc-tree-more"
      icon={<MoreOutlined />}
      aria-label={`更多操作：${node.title}`}
      data-testid={`doc-tree-more-${node.id}`}
      onClick={(e) => {
        e.stopPropagation()
        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
        openNodeMenu(node, rect.left, rect.bottom)
      }}
    />
  ), [openNodeMenu])

  /** 树节点渲染：图标 + 标题 + 状态色点 + 置顶标记 + 「更多」按钮（触摸端可达） */
  const titleRender = useCallback((node: DocTreeNode) => {
    const pinMark = node.pinned ? (
      <PushpinFilled
        aria-label="已置顶"
        data-testid={`doc-tree-pinned-${node.id}`}
        style={{ marginLeft: 6, fontSize: 11, color: 'var(--cn-brand-color)' }}
      />
    ) : null
    if (node.is_folder) {
      return (
        <span data-testid={`doc-tree-folder-${node.id}`}>
          <FolderOutlined style={{ marginRight: 6, color: 'var(--cn-warning, #faad14)' }} />
          {node.title}
          {pinMark}
          {moreButton(node)}
        </span>
      )
    }
    return (
      <span data-testid={`doc-tree-doc-${node.id}`}>
        <FileTextOutlined style={{ marginRight: 6, color: 'var(--cn-primary, #1890ff)' }} />
        {node.title}
        {pinMark}
        {moreButton(node)}
        <span
          aria-label="doc-status-dot"
          style={{
            display: 'inline-block',
            width: 6,
            height: 6,
            borderRadius: 3,
            marginLeft: 6,
            background: STATUS_DOT_COLOR[node.status] ?? STATUS_DOT_COLOR.draft,
          }}
        />
      </span>
    )
  }, [moreButton])

  const treeNodes: DataNode[] = useMemo(() => {
    const toData = (node: DocTreeNode): DataNode => ({
      key: node.id,
      title: titleRender(node),
      children: node.children.length > 0 ? node.children.map(toData) : undefined,
      isLeaf: !node.is_folder,
    })
    const kw = keyword.trim().toLowerCase()
    if (!kw) return treeData.map(toData)
    // 关键词过滤：自身或任一子孙命中则保留该分支
    const filter = (node: DocTreeNode): DocTreeNode | null => {
      const children = node.children.map(filter).filter((c): c is DocTreeNode => c !== null)
      const hit = node.title.toLowerCase().includes(kw)
      if (!hit && children.length === 0) return null
      return { ...node, children }
    }
    return treeData.map(filter).filter((n): n is DocTreeNode => n !== null).map(toData)
  }, [treeData, keyword, titleRender])

  /** 移动目标下拉数据：全部文件夹，排除自身及其子孙 */
  const moveTreeData = useMemo(() => {
    if (!dialog || dialog.kind !== 'move') return []
    const excluded = new Set(descendantIds(dialog.node))
    const toOption = (node: DocTreeNode): DataNode & { value: number } => ({
      key: node.id,
      value: node.id,
      title: node.title,
      disabled: excluded.has(node.id),
      children: node.children.filter(c => c.is_folder).map(toOption),
    })
    return [
      { value: 0, title: '（根目录）', children: treeData.filter(n => n.is_folder).map(toOption) },
    ]
  }, [dialog, treeData])

  const confirmDelete = (node: DocTreeNode) => {
    modal.confirm({
      title: node.is_folder ? `删除文件夹「${node.title}」？` : `删除文档「${node.title}」？`,
      content: node.is_folder ? '文件夹内的全部文档与子文件夹将一并删除。' : '文档将移入回收（软删除）。',
      okType: 'danger',
      okText: '删除',
      onOk: () => deleteMut.mutate(node.id),
    })
    setMenu({ open: false, x: 0, y: 0, node: null })
  }

  const menuItems = [
    {
      key: 'create-doc',
      label: '新建子文档',
      icon: <FileAddOutlined />,
      onClick: () => {
        setDialog({ kind: 'create', type: 'doc', parent: menu.node })
        setInputValue('')
        setMenu({ open: false, x: 0, y: 0, node: null })
      },
    },
    {
      key: 'create-folder',
      label: '新建子文件夹',
      icon: <FolderAddOutlined />,
      onClick: () => {
        setDialog({ kind: 'create', type: 'folder', parent: menu.node })
        setInputValue('')
        setMenu({ open: false, x: 0, y: 0, node: null })
      },
    },
    { type: 'divider' as const },
    {
      key: menu.node?.pinned ? 'unpin' : 'pin',
      label: menu.node?.pinned ? '取消置顶' : '置顶',
      icon: menu.node?.pinned ? <PushpinFilled /> : <PushpinOutlined rotate={90} />,
      onClick: () => {
        if (menu.node) {
          const mutation = menu.node.pinned ? unpinMut : pinMut
          mutation.mutate(menu.node.id)
        }
        setMenu({ open: false, x: 0, y: 0, node: null })
      },
    },
    {
      key: 'rename',
      label: '重命名',
      icon: <PushpinOutlined rotate={90} />,
      onClick: () => {
        if (menu.node) {
          setDialog({ kind: 'rename', node: menu.node })
          setInputValue(menu.node.title)
        }
        setMenu({ open: false, x: 0, y: 0, node: null })
      },
    },
    {
      key: 'move',
      label: '移动到…',
      icon: <ApartmentOutlined />,
      onClick: () => {
        if (menu.node) {
          setDialog({ kind: 'move', node: menu.node })
          setMoveTarget(menu.node.parent_id)
        }
        setMenu({ open: false, x: 0, y: 0, node: null })
      },
    },
    { type: 'divider' as const },
    {
      key: 'delete',
      label: '删除',
      icon: <DeleteOutlined />,
      danger: true,
      onClick: () => {
        if (menu.node) confirmDelete(menu.node)
      },
    },
  ]

  if (!Number.isFinite(workspaceId)) return null

  return (
    <div data-testid="document-tree" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 工具栏：新建 + 每日笔记 + 过滤 */}
      <div style={{ padding: '8px 8px 4px', display: 'flex', gap: 4 }}>
        <Button
          size="small"
          type="primary"
          icon={<FileAddOutlined />}
          data-testid="doc-tree-new-doc"
          onClick={() => {
            setDialog({ kind: 'create', type: 'doc', parent: null })
            setInputValue('')
          }}
        >
          文档
        </Button>
        <Button
          size="small"
          icon={<FolderAddOutlined />}
          data-testid="doc-tree-new-folder"
          onClick={() => {
            setDialog({ kind: 'create', type: 'folder', parent: null })
            setInputValue('')
          }}
        >
          文件夹
        </Button>
        <Button
          size="small"
          icon={<CalendarOutlined />}
          data-testid="doc-tree-daily-note"
          loading={dailyNoteMut.isPending}
          onClick={() => dailyNoteMut.mutate()}
        >
          今日笔记
        </Button>
        <Button
          size="small"
          type="text"
          icon={<ReloadOutlined />}
          aria-label="刷新文档树"
          onClick={() => void treeQuery.refetch()}
        />
      </div>
      <div style={{ padding: '0 8px 8px' }}>
        <Input.Search
          size="small"
          allowClear
          placeholder="过滤文档树…"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          data-testid="doc-tree-filter"
        />
      </div>

      {/* 树主体 */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '0 4px' }}>
        {treeQuery.isLoading ? (
          <div style={{ padding: 16, color: 'var(--cn-text-muted)', fontSize: 13 }}>加载中…</div>
        ) : items.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无文档"
            style={{ marginTop: 32 }}
          />
        ) : (
          <Tree
            blockNode
            showIcon
            expandAction="click"
            draggable
            onDrop={info => {
              const dragId = Number(info.dragNode.key)
              const targetId = Number(info.node.key)
              // antd dropPosition 为展开列表绝对索引，换算为相对目标的 -1/0/1
              const posParts = String(info.node.pos).split('-')
              const rel = (info.dropPosition - Number(posParts[posParts.length - 1])) as DropRel
              const ops = planDropMove(treeData, dragId, targetId, rel)
              if (!ops || ops.length === 0) {
                if (!ops) message.warning('不能移动到自身或其子孙节点内')
                return
              }
              dropMut.mutate(ops)
            }}
            treeData={treeNodes}
            expandedKeys={expandedKeys}
            selectedKeys={selectedId != null ? [selectedId] : []}
            onExpand={keys => setExpandedKeys(keys)}
            onSelect={(_keys, info) => {
              const node = info.node as unknown as { key: React.Key; isLeaf?: boolean }
              // 文件夹由树自身展开/收起；文档导航到编辑页
              if (!node.isLeaf) return
              navigate(`/w/${workspaceId}/documents/${node.key}`)
              onNavigate?.()
            }}
            onRightClick={info => {
              const raw = info.node as unknown as { key: React.Key }
              const node = findNodeById(treeData, Number(raw.key))
              setMenu({ open: true, x: info.event.clientX, y: info.event.clientY, node })
            }}
          />
        )}
      </div>

      {/* 右键菜单：固定定位到点击位置 */}
      {menu.open && (
        <Dropdown
          open
          trigger={[]}
          onOpenChange={o => {
            if (!o) setMenu({ open: false, x: 0, y: 0, node: null })
          }}
          menu={{ items: menuItems }}
        >
          <div style={{ position: 'fixed', left: menu.x, top: menu.y, width: 0, height: 0 }} />
        </Dropdown>
      )}

      {/* 新建 / 重命名弹窗 */}
      <Modal
        title={
          dialog?.kind === 'create'
            ? dialog.type === 'folder'
              ? `在「${dialog.parent?.title ?? '根目录'}」下新建文件夹`
              : `在「${dialog.parent?.title ?? '根目录'}」下新建文档`
            : '重命名'
        }
        open={dialog?.kind === 'create' || dialog?.kind === 'rename'}
        onCancel={() => {
          setDialog(null)
          setInputValue('')
        }}
        onOk={() => {
          const title = inputValue.trim()
          if (!title || !dialog) return
          if (dialog.kind === 'create') {
            createMut.mutate({ title, isFolder: dialog.type === 'folder', parentId: dialog.parent?.id ?? null })
          } else {
            renameMut.mutate({ id: dialog.node.id, title })
          }
        }}
        okButtonProps={{ disabled: !inputValue.trim(), loading: createMut.isPending || renameMut.isPending }}
        okText={dialog?.kind === 'rename' ? '保存' : '创建'}
        cancelText="取消"
        destroyOnHidden
      >
        <Input
          placeholder="标题"
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onPressEnter={() => {
            const title = inputValue.trim()
            if (!title || !dialog) return
            if (dialog.kind === 'create') createMut.mutate({ title, isFolder: dialog.type === 'folder', parentId: dialog.parent?.id ?? null })
            else renameMut.mutate({ id: dialog.node.id, title })
          }}
          autoFocus
          data-testid="doc-tree-dialog-input"
        />
      </Modal>

      {/* 移动弹窗：TreeSelect 选目标文件夹（排除自身及子孙） */}
      <Modal
        title={`移动「${dialog?.kind === 'move' ? dialog.node.title : ''}」到…`}
        open={dialog?.kind === 'move'}
        onCancel={() => setDialog(null)}
        onOk={() => {
          if (dialog?.kind === 'move') {
            moveMut.mutate({ id: dialog.node.id, parentId: moveTarget })
          }
        }}
        confirmLoading={moveMut.isPending}
        okText="移动"
        cancelText="取消"
        destroyOnHidden
      >
        <TreeSelect
          style={{ width: '100%' }}
          treeDefaultExpandAll
          value={moveTarget ?? 0}
          onChange={(v: number) => setMoveTarget(v)}
          treeData={moveTreeData}
          data-testid="doc-tree-move-target"
        />
      </Modal>
    </div>
  )
}

/** 按 key 递归查找树节点（planDropMove 内部使用） */
function findByKey(nodes: DocTreeNode[], key: number): DocTreeNode | null {
  return findNodeById(nodes, key)
}

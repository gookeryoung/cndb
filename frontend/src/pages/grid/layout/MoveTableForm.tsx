/** 移动表到其他工作区 — 内嵌在 Modal 内 */

import { Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/api'
import type { ID } from '@/api'

interface MoveTableFormProps {
  currentWid: number | string
  /** 受控：当前选中的目标工作区 id */
  value?: ID | null
  /** 受控：选中目标工作区时回调 */
  onChange?: (value: ID) => void
}

/** 内嵌在"移动表" Modal 内的目标工作区选择 */
export default function MoveTableForm({ currentWid, value, onChange }: MoveTableFormProps) {
  const { data: workspaces = [], isLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })
  // 排除当前工作区：移动到自身没有意义，也不应误清表级成员授权
  const options = workspaces.filter(w => String(w.id) !== String(currentWid))
  return (
    <div style={{ marginTop: 12 }}>
      {isLoading ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>加载中...</div>
      ) : options.length === 0 ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>没有其他工作区可移动</div>
      ) : (
        <Select<ID>
          style={{ width: '100%' }}
          placeholder="选择目标工作区"
          value={value ?? undefined}
          onChange={onChange}
          options={options.map(w => ({ value: w.id, label: w.name }))}
          data-testid="move-ws-select"
        />
      )}
    </div>
  )
}

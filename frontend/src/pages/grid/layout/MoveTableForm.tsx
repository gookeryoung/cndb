/** 移动表到其他工作区 — 内嵌在 Modal 内 */

import { Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/api'

interface MoveTableFormProps {
  currentWid: number | string
}

/** 内嵌在"移动表" Modal 内的目标工作区选择 */
export default function MoveTableForm({ currentWid }: MoveTableFormProps) {
  const { data: workspaces = [], isLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })
  const options = workspaces.filter(w => String(w.id) !== String(currentWid))
  return (
    <div style={{ marginTop: 12 }}>
      {isLoading ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>加载中...</div>
      ) : options.length === 0 ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>没有其他工作区可移动</div>
      ) : (
        <Select
          style={{ width: '100%' }}
          placeholder="选择目标工作区"
          options={options.map(w => ({ value: w.id, label: w.name }))}
          data-move-ws
        />
      )}
    </div>
  )
}

/** 顶部项目切换器（ADR 0122）：单项目自动选中并隐藏，多项目写 URL ?project=. */

import { useEffect, useMemo } from 'react'
import { Select, Tooltip } from 'antd'
import { AppstoreOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { workspaceProjectsApi } from '@/api/workspaceProjects'

interface Props {
  wid: string
}

export default function ProjectSwitcher({ wid }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const projectId = searchParams.get('project')

  const { data } = useQuery({
    queryKey: ['workspace-projects', wid],
    queryFn: () => workspaceProjectsApi.list(wid),
    enabled: !!wid,
    staleTime: 30_000,
  })

  const items = useMemo(
    () => (data?.project_mode === 'project' ? data.items : []),
    [data],
  )

  // 单项目工作台：自动带出 project 参数，页面无需用户选择
  useEffect(() => {
    if (items.length !== 1 || projectId) return
    const next = new URLSearchParams(searchParams)
    next.set('project', String(items[0].project_row_id))
    setSearchParams(next, { replace: true })
  }, [items, projectId, searchParams, setSearchParams])

  if (data?.project_mode !== 'project' || items.length <= 1) return null

  return (
    <Tooltip title="切换项目">
      <Select
        data-testid="project-switcher"
        size="small"
        suffixIcon={<AppstoreOutlined />}
        value={projectId ?? undefined}
        placeholder="选择项目"
        style={{ minWidth: 160, maxWidth: 240 }}
        popupMatchSelectWidth={false}
        options={items.map(item => ({
          value: String(item.project_row_id),
          label: `${item.title}${item.stage_name ? ` · ${item.stage_name}` : ''}`,
        }))}
        onChange={(value) => {
          const next = new URLSearchParams(searchParams)
          next.set('project', value)
          setSearchParams(next)
        }}
      />
    </Tooltip>
  )
}

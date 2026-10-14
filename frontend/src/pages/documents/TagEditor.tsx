/** 标签选择器 + 新建 —— 从 DocumentEditorPage 抽出（自持新建 mutation） */

import { useState } from 'react'
import { Button, Divider, Input, Tag, Typography, message } from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { documentsApi } from '@/api/documents'
import type { TagItem } from '@/api/documents'

const { Text } = Typography

/** 标签选择器 + 新建 */
export default function TagEditor({
  workspaceId,
  allTags,
  selectedIds,
  onChange,
}: {
  workspaceId: number
  allTags: TagItem[]
  selectedIds: number[]
  onChange: (ids: number[]) => void
}) {
  const qc = useQueryClient()
  const [newName, setNewName] = useState('')

  const createMut = useMutation({
    mutationFn: () => documentsApi.createTag(workspaceId, { name: newName.trim() }),
    onSuccess: tag => {
      setNewName('')
      void qc.invalidateQueries({ queryKey: ['documents', workspaceId, 'tags'] })
      onChange([...selectedIds, tag.id])
    },
    onError: () => message.error('创建标签失败（可能重名）'),
  })

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <Input
          placeholder="新标签名称"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onPressEnter={() => newName.trim() && createMut.mutate()}
        />
        <Button type="primary" disabled={!newName.trim()} loading={createMut.isPending} onClick={() => createMut.mutate()}>
          添加
        </Button>
      </div>
      <Divider style={{ margin: '8px 0' }} />
      {allTags.length === 0 ? (
        <Text type="secondary">暂无标签，先创建一个</Text>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {allTags.map(tag => {
            const checked = selectedIds.includes(tag.id)
            return (
              <Tag.CheckableTag
                key={tag.id}
                checked={checked}
                onChange={checkedNow => {
                  onChange(
                    checkedNow ? [...selectedIds, tag.id] : selectedIds.filter(x => x !== tag.id),
                  )
                }}
                style={{ fontSize: 13, padding: '4px 12px', borderColor: tag.color }}
              >
                {tag.name} ({tag.doc_count})
              </Tag.CheckableTag>
            )
          })}
        </div>
      )}
      {selectedIds.length > 0 && (
        <>
          <Divider style={{ margin: '16px 0 8px' }} />
          <Button
            type="primary"
            icon={<CheckOutlined />}
            onClick={() => {
              onChange(selectedIds)
              message.success('标签已保存')
            }}
          >
            完成
          </Button>
        </>
      )}
    </div>
  )
}

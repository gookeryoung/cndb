/** 全文搜索抽屉 —— 自持关键词状态与 FTS5 查询，点击命中进入文档编辑页. */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Drawer, Empty, Input, List, Space, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { documentsApi } from '@/api/documents'
import type { SearchHitItem } from '@/api/documents'
import { useResponsive } from '@/hooks/useResponsive'
import { parseHitHighlight } from '@/components/Document/outline'
import { formatTime, STATUS_LABELS } from './documentDisplay'

const { Text } = Typography

interface SearchDrawerProps {
  open: boolean
  onClose: () => void
  /** 工作区 ID（数字形式，与页面内 workspaceId 同源） */
  wid: number
}

export default function SearchDrawer({ open, onClose, wid }: SearchDrawerProps) {
  const navigate = useNavigate()
  const { isMobile } = useResponsive()
  const [keyword, setKeyword] = useState('')

  // 全文搜索（FTS5）：抽屉打开且有关键词时触发
  const searchQuery = useQuery({
    queryKey: ['documents', wid, 'search', keyword],
    queryFn: () => documentsApi.search(wid, keyword, { limit: 30 }),
    enabled: Number.isFinite(wid) && open && keyword.trim().length > 0,
    placeholderData: prev => prev,
  })

  return (
    <Drawer title="全文搜索" width={isMobile ? '100%' : 520} open={open} onClose={onClose}>
          <Input.Search
            allowClear
            autoFocus
            enterButton
            placeholder="标题 / 正文 / 摘要关键词…"
            data-testid="doc-search-input"
            onSearch={q => setKeyword(q)}
            style={{ marginBottom: 16 }}
          />
          {keyword.trim() === '' ? (
            <Text type="secondary">输入关键词回车搜索（正文全文检索）</Text>
          ) : searchQuery.isLoading ? (
            <div>搜索中…</div>
          ) : (searchQuery.data?.items ?? []).length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无命中结果" />
          ) : (
            <List
              dataSource={searchQuery.data?.items ?? []}
              renderItem={(hit: SearchHitItem) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  data-testid={`doc-search-hit-${hit.id}`}
                  onClick={() => {
                    onClose()
                    navigate(`/w/${wid}/documents/${hit.id}`)
                  }}
                >
                  <List.Item.Meta
                    title={<HitText hit={hit.title_hit} strong />}
                    description={
                      <Space direction="vertical" size={2}>
                        <HitText hit={hit.summary_hit} />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {STATUS_LABELS[hit.status] ?? hit.status} · 更新 {formatTime(hit.updated_at)}
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          )}
    </Drawer>
  )
}

function HitText({ hit, strong }: { hit: string; strong?: boolean }) {
  return (
    <>
      {parseHitHighlight(hit).map((p, i) =>
        p.marked ? (
          <Text key={i} mark strong={strong}>
            {p.text}
          </Text>
        ) : (
          <Text key={i} type="secondary" strong={strong}>
            {p.text}
          </Text>
        ),
      )}
    </>
  )
}

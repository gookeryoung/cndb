/** 反链抽屉：引用了 [[本文档标题]] 的文档列表，点击跳转（从 DocumentEditorPage 抽出）. */

import { Drawer, Typography } from 'antd'

import type { BacklinkItem } from '@/api/documents'

const { Text } = Typography

export default function BacklinksDrawer({
  open,
  onClose,
  items,
  loading,
  docTitle,
  onOpenDoc,
}: {
  open: boolean
  onClose: () => void
  items: BacklinkItem[]
  loading: boolean
  /** 当前文档标题 —— 仅用于空态提示文案 */
  docTitle: string
  onOpenDoc: (docId: number) => void
}) {
  return (
    <Drawer title="反向链接" size={420} open={open} onClose={onClose}>
      {loading ? (
        <Text type="secondary">加载中…</Text>
      ) : items.length === 0 ? (
        <Text type="secondary">暂无反向链接（其他文档正文中出现 [[{docTitle}]] 即会出现在这里）</Text>
      ) : (
        items.map((b: BacklinkItem) => (
          <div
            key={b.id}
            data-testid={`doc-backlink-${b.id}`}
            style={{
              padding: '8px 12px',
              marginBottom: 8,
              border: '1px solid var(--cn-border, #e8e8e8)',
              borderRadius: 8,
              cursor: 'pointer',
            }}
            onClick={() => onOpenDoc(b.id)}
          >
            <Text strong>{b.title}</Text>
            {b.summary && (
              <div>
                <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                  {b.summary}
                </Text>
              </div>
            )}
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {new Date(b.updated_at).toLocaleString('zh-CN', { hour12: false })}
              </Text>
            </div>
          </div>
        ))
      )}
    </Drawer>
  )
}

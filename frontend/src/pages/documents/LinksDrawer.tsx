/** 出链抽屉：正文 [[标题]] 命中与断链修复（从 DocumentEditorPage 抽出）.
 *
 * 页面侧把 query 结果解包为 props（links / brokenCount / targets），抽屉不依赖
 * React Query，便于独立测试。
 */

import { Alert, Button, Drawer, Select, Space, Tag, Typography } from 'antd'
import { CheckOutlined } from '@ant-design/icons'

import type { DocumentItem, OutgoingLinkItem } from '@/api/documents'

const { Text } = Typography

export default function LinksDrawer({
  open,
  onClose,
  loading,
  links,
  brokenCount,
  targets,
  repairTargets,
  onTargetChange,
  onRepair,
  repairing,
  onOpenDoc,
}: {
  open: boolean
  onClose: () => void
  loading: boolean
  links: OutgoingLinkItem[]
  brokenCount: number
  targets: DocumentItem[]
  /** 断链标题 → 已选目标文档 id */
  repairTargets: Record<string, number>
  onTargetChange: (title: string, targetId: number) => void
  onRepair: () => void
  repairing: boolean
  onOpenDoc: (docId: number) => void
}) {
  return (
    <Drawer title="文档链接" width={460} open={open} onClose={onClose} data-testid="doc-links-drawer">
      {loading ? (
        <Text type="secondary">加载中…</Text>
      ) : links.length === 0 ? (
        <Text type="secondary">正文中没有 [[标题]] 形式的链接</Text>
      ) : (
        <>
          {brokenCount > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={`${brokenCount} 条断链`}
              description="选择目标文档后点击「修复断链」，正文将改写为新标题并生成新版本。"
            />
          )}
          {links.map((item: OutgoingLinkItem) => (
            <div
              key={item.title}
              data-testid={`doc-link-${item.title}`}
              style={{
                padding: '8px 12px',
                marginBottom: 8,
                border: '1px solid var(--cn-border, #e8e8e8)',
                borderRadius: 8,
              }}
            >
              <Space size={6} wrap>
                <Text strong>{`[[${item.title}]]`}</Text>
                {item.exists ? <Tag color="green">已解析</Tag> : <Tag color="red">断链</Tag>}
              </Space>
              {item.exists && item.document_id != null ? (
                <div style={{ marginTop: 6 }}>
                  <Button
                    size="small"
                    type="link"
                    data-testid={`doc-link-open-${item.title}`}
                    onClick={() => onOpenDoc(item.document_id as number)}
                  >
                    打开目标文档
                  </Button>
                </div>
              ) : (
                <div style={{ marginTop: 6 }}>
                  <Select
                    size="small"
                    style={{ width: 240 }}
                    placeholder="选择要指向的文档"
                    value={repairTargets[item.title]}
                    onChange={(value: number) => onTargetChange(item.title, value)}
                    options={targets.map(d => ({
                      value: d.id,
                      label: d.is_folder ? `📁 ${d.title}` : d.title,
                    }))}
                    showSearch
                    optionFilterProp="label"
                    data-testid={`doc-link-target-${item.title}`}
                  />
                </div>
              )}
            </div>
          ))}
          <Space style={{ marginTop: 8 }}>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              data-testid="doc-link-repair"
              loading={repairing}
              disabled={Object.keys(repairTargets).length === 0}
              onClick={onRepair}
            >
              修复断链
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              已选 {Object.keys(repairTargets).length} 条
            </Text>
          </Space>
        </>
      )}
    </Drawer>
  )
}

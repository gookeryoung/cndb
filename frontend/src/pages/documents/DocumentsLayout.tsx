/** 文档模块布局 — 桌面端「左树 + 右内容」双栏，移动端树收入抽屉（思源笔记式）.

路由结构：/w/:wid/documents（总览列表）与 /w/:wid/documents/:docId（编辑器）
共用本布局，右栏经 <Outlet /> 渲染，跨页切换时树保持挂载不重拉。
*/

import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Button, Drawer, Tooltip } from 'antd'
import { ApartmentOutlined } from '@ant-design/icons'
import { useResponsive } from '@/hooks/useResponsive'
import DocumentTree from './DocumentTree'

export default function DocumentsLayout() {
  const { isMobile } = useResponsive()
  const [treeOpen, setTreeOpen] = useState(false)

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0 }} data-testid="documents-layout">
      {/* 桌面端常驻左栏 */}
      {!isMobile && (
        <aside
          data-testid="doc-tree-aside"
          style={{
            width: 260,
            flexShrink: 0,
            borderRight: '1px solid var(--cn-border)',
            background: 'var(--cn-bg-container)',
            overflow: 'auto',
          }}
        >
          <DocumentTree />
        </aside>
      )}

      {/* 右栏内容 */}
      <div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
        <Outlet />
      </div>

      {/* 移动端：浮动按钮 + 抽屉树 */}
      {isMobile && (
        <>
          <Tooltip title="文档树">
            <Button
              type="primary"
              shape="circle"
              icon={<ApartmentOutlined />}
              data-testid="doc-tree-fab"
              aria-label="打开文档树"
              onClick={() => setTreeOpen(true)}
              style={{ position: 'fixed', left: 16, bottom: 24, zIndex: 100 }}
            />
          </Tooltip>
          <Drawer
            title="文档树"
            placement="left"
            open={treeOpen}
            onClose={() => setTreeOpen(false)}
            width={280}
            styles={{ body: { padding: 0 } }}
          >
            <DocumentTree onNavigate={() => setTreeOpen(false)} />
          </Drawer>
        </>
      )}
    </div>
  )
}

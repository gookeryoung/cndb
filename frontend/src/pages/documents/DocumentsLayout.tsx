/** 文档模块布局 — 内容区直出（需求 0065：文档树由 MainLayout 侧边栏承担，不再渲染页面内左树）.

路由结构：/w/:wid/documents（总览列表）、/w/:wid/documents/change-requests（修改申请）、
/w/:wid/documents/issues（问题清单）与 /w/:wid/documents/:docId（编辑器）共用本布局，
右栏经 <Outlet /> 渲染，跨页切换时保持路由嵌套结构。
*/

import { Outlet } from 'react-router-dom'

export default function DocumentsLayout() {
  return (
    <div style={{ height: '100%', minHeight: 0 }} data-testid="documents-layout">
      <Outlet />
    </div>
  )
}

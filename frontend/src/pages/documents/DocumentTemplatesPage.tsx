/** 文档导出模板页（ADR 0152）.
 *
 * 模板是**工作区级**共享资源，与文档导出强相关，因此入口放在文档区二级页签
 * （「质量检查」右侧），而不是个人设置。
 *
 * 页面只提供容器；页头（图标 / 标题 / 「新建模板」入口）与双栏面板（左模板清单 /
 * 右排版配置 + 可收起预览）都在 `TemplatePanel` 内，与「质量检查」页同一套原语。
 */

import TemplatePanel from '@/pages/settings/TemplatePanel'

export default function DocumentTemplatesPage() {
  return (
    <div className="cn-page cn-doc-tpl-page" data-testid="document-templates-page">
      <TemplatePanel />
    </div>
  )
}

/** 文档导出模板页（ADR 0152）.
 *
 * 模板是**工作区级**共享资源，与文档导出强相关，因此入口放在文档区二级页签
 * （「质量检查」右侧），而不是个人设置 —— 个人设置里管工作区资源在语义上是错的。
 *
 * 页面本体复用 `settings/TemplatePanel`（同一套列表 / 配置 / 预览），
 * 这里只提供页面级容器与标题，避免两份实现漂移。
 */

import { Typography } from 'antd'

import TemplatePanel from '@/pages/settings/TemplatePanel'

const { Title, Text } = Typography

export default function DocumentTemplatesPage() {
  return (
    <div className="cn-page" data-testid="document-templates-page">
      <div>
        <Title level={4} style={{ margin: 0 }}>
          文档模板
        </Title>
        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
          工作区共享的导出排版模板：一份配置同时作用于 Word 与 PDF（字体、标题、段落、表格、题注）。
          内置模板只读，可另存为自定义；未指定模板时按「工作区默认 → 标准」导出。
        </Text>
      </div>
      <TemplatePanel />
    </div>
  )
}

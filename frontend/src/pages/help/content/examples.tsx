/** 帮助文档 · 典型示例内容（ADR 0029）.
 *
 * 三个主题只负责把场景 key 交给 `ExamplesSection`：清单、表格、亮点、步骤
 * 与 CSV 下载均由后端 `/api/v1/help/examples` 提供。
 */

import ExamplesSection from './ExamplesSection'
import type { HelpTopic } from '../helpNav'

export const exampleTopics: HelpTopic[] = [
    { key: 'sales', label: '某企业销售管理', content: <ExamplesSection scenarioKey="sales" /> },
    { key: 'research', label: '科研项目管理', content: <ExamplesSection scenarioKey="research" /> },
    { key: 'datasource', label: '数据源示例', content: <ExamplesSection scenarioKey="datasource" /> },
]

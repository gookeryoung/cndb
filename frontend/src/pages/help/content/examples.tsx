/** 帮助文档 · 典型示例内容（ADR 0029 / ADR 0036）.
 *
 * 三个主题的结构一致（场景说明 / 数据表与下载 / 数据预览 / 练习与步骤），
 * 内容只负责把场景 key 交给 `ExamplesSection`：清单、表格、亮点、步骤与 CSV 下载
 * 均由后端 `/api/v1/help/examples` 提供，前端不维护第二份清单。
 */

import type { HelpTopic } from '../helpNav'
import { ExamplePractice, ExamplePreviews, ExampleSummary, ExampleTables } from './ExamplesSection'
import { P } from './primitives'

function scenarioTopic(key: string, label: string, intro: string): HelpTopic {
    return {
        key,
        label,
        intro: <P>{intro}</P>,
        subsections: [
            { key: 'scenario', label: '场景说明', body: <ExampleSummary scenarioKey={key} /> },
            { key: 'tables', label: '数据表与下载', body: <ExampleTables scenarioKey={key} /> },
            { key: 'preview', label: '数据预览', body: <ExamplePreviews scenarioKey={key} /> },
            { key: 'practice', label: '怎么练与导入步骤', body: <ExamplePractice scenarioKey={key} /> },
        ],
    }
}

const sales = scenarioTopic(
    'sales',
    '某企业销售管理',
    '一套销售运营场景：订单级销售明细、客户流失、营销活动与团队待办，适合练视图组合与图表分析。',
)

const research = scenarioTopic(
    'research',
    '科研项目管理',
    '一套科研管理场景：课题主数据、任务分解、经费台账与资源排期，适合练层级结构、关联字段与时间视图。',
)

const datasource = scenarioTopic(
    'datasource',
    '数据源示例',
    '一套数据接入场景：行情、政策台账、国际情报与天气观测，适合练数据源同步、去重键与画廊阅读。',
)

export const exampleTopics: HelpTopic[] = [sales, research, datasource]

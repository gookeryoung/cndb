/** 帮助文档 · 典型示例内容（ADR 0029 / ADR 0036）.
 *
 * 两个主题的结构一致（场景说明 / 数据表与下载 / 数据预览 / 练习与步骤），
 * 内容只负责把场景 key 交给 `ExamplesSection`：清单、表格、亮点、步骤与 CSV 下载
 * 均由后端 `/api/v1/help/examples` 提供，前端不维护第二份清单。
 */

import type { HelpTopic } from '../helpNav'
import {
    ExampleCreateWorkspace,
    ExampleDesigns,
    ExamplePractice,
    ExamplePreviews,
    ExampleSummary,
    ExampleTables,
} from './ExamplesSection'
import { P } from './primitives'

function scenarioTopic(key: string, label: string, intro: string): HelpTopic {
    return {
        key,
        label,
        intro: <P>{intro}</P>,
        subsections: [
            { key: 'scenario', label: '场景说明', body: <ExampleSummary scenarioKey={key} /> },
            { key: 'create', label: '创建示例工作区', body: <ExampleCreateWorkspace scenarioKey={key} /> },
            { key: 'tables', label: '数据表与下载', body: <ExampleTables scenarioKey={key} /> },
            { key: 'preview', label: '数据预览', body: <ExamplePreviews scenarioKey={key} /> },
            { key: 'practice', label: '怎么练与导入步骤', body: <ExamplePractice scenarioKey={key} /> },
        ],
    }
}

/** 设计示例场景：无数据表，故不渲染「创建示例工作区 / 数据表 / 数据预览」三节。 */
function designTopic(key: string, label: string, intro: string): HelpTopic {
    return {
        key,
        label,
        intro: <P>{intro}</P>,
        subsections: [
            { key: 'scenario', label: '场景说明', body: <ExampleSummary scenarioKey={key} /> },
            { key: 'designs', label: '设计文件与下载', body: <ExampleDesigns scenarioKey={key} /> },
            { key: 'practice', label: '怎么练与用法', body: <ExamplePractice scenarioKey={key} /> },
        ],
    }
}

const sales = scenarioTopic(
    'sales',
    '某企业销售管理',
    '本页你能学到什么：用一套销售数据练视图组合与图表分析，并跟着步骤导入练习。适合谁：想找现成数据上手的新成员。',
)

const research = scenarioTopic(
    'research',
    '科研项目管理',
    '本页你能学到什么：用科研项目数据练层级结构、关联字段与时间视图，并跟着步骤导入练习。适合谁：要搭项目管理场景的成员。',
)

const mechanical = designTopic(
    'mechanical',
    '机械设计示例',
    '本页你能学到什么：从最小零件到千图元装配，逐份看懂结构设计 DSL（参数、布尔、阵列、分文件引用、约束求解）。适合谁：要上手设计模块、或想找现成模板改造的成员。',
)

export const exampleTopics: HelpTopic[] = [sales, research, mechanical]

/** 供 helpNav 的 HELP_SECTION_LOADERS 按部分懒加载（0090 C1）。 */
export default exampleTopics

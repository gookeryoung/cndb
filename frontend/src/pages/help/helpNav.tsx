/** 帮助文档导航（ADR 0029 / ADR 0035）：路由、侧栏、页内目录与内容共用的唯一真相源。
 *
 * 四层模型：
 * - L1 部分（`HelpSection`）：固定 5 个，顺序不变，对应侧栏分组；
 * - L2 主题（`HelpTopic`）：一个独立页面 + 独立路由 `/help/<section>/<topic>`；
 * - L3 小节（`HelpSubsection`）：页面内 `<h2>`，带锚点，进入页内目录；
 * - L4 条目（`HelpItem`）：小节内 `<h3>`，带锚点，只在所属小节展开，不入侧栏。
 *
 * 层级归属规则（ADR 0035 §2）：
 * - L2 按「对象 / 任务族」切；L3 按「阶段 / 属性维度」切；L4 是单一实例
 *   （一个视图类型、一个字段类型、一个设置项、一条排障症状、一个 FAQ 问题）。
 * - 每个 L2 至少 2 个 L3；每个 L3 要么有自己的正文，要么有 ≥2 个 L4；不允许空层。
 * - 同一事实只在一个 L4 写全，其它位置用交叉引用链接指过去（见 `helpLink`）。
 */

import {
    BookOutlined,
    CompassOutlined,
    QuestionCircleOutlined,
    SettingOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'
import { configurationTopics } from './content/configuration'
import { exampleTopics } from './content/examples'
import { quickStartTopics } from './content/quickStart'
import { troubleshootingTopics } from './content/troubleshooting'
import { tutorialTopics } from './content/tutorials'

/** L4 条目：小节内的单一实例，渲染为 `<h3>` + 锚点。 */
export interface HelpItem {
    key: string
    label: string
    body: ReactNode
}

/** L3 小节：渲染为 `<h2>` + 锚点；`body` 与 `items` 至少有一个非空。 */
export interface HelpSubsection {
    key: string
    label: string
    /** 小节导语（可选），一句话说清这一节覆盖什么。 */
    summary?: string
    body?: ReactNode
    items?: HelpItem[]
}

/** L2 主题：一个页面。 */
export interface HelpTopic {
    key: string
    label: string
    /** 页首导语，固定展示在标题下方。 */
    intro: ReactNode
    subsections: HelpSubsection[]
}

/** L1 部分：侧栏分组。 */
export interface HelpSection {
    key: string
    label: string
    icon: ReactNode
    topics: HelpTopic[]
}

export const HELP_DOCS_TITLE = '帮助文档'

export const HELP_SECTIONS: HelpSection[] = [
    { key: 'quick-start', label: '快速入门', icon: <ThunderboltOutlined />, topics: quickStartTopics },
    { key: 'tutorials', label: '教程&最佳实践', icon: <BookOutlined />, topics: tutorialTopics },
    { key: 'examples', label: '典型示例', icon: <CompassOutlined />, topics: exampleTopics },
    { key: 'configuration', label: '系统配置', icon: <SettingOutlined />, topics: configurationTopics },
    { key: 'troubleshooting', label: '问题排查', icon: <QuestionCircleOutlined />, topics: troubleshootingTopics },
]

/** `/help/<section>/<topic>`；section/topic key 只含小写字母、数字与连字符，无需编码。 */
export function topicPath(sectionKey: string, topicKey: string): string {
    return `/help/${sectionKey}/${topicKey}`
}

/** L3 锚点 id：全局唯一，前缀避免与页面其它 id 冲突。 */
export function subsectionAnchor(subsectionKey: string): string {
    return `help-${subsectionKey}`
}

/** L4 锚点 id：`<小节>--<条目>`，保证同一页面内条目不会撞 id。 */
export function itemAnchor(subsectionKey: string, itemKey: string): string {
    return `help-${subsectionKey}--${itemKey}`
}

/** 主题页 + 锚点的完整地址，用于页面内交叉引用（`helpLink('tutorials','roles','model')`）。 */
export function helpLink(sectionKey: string, topicKey: string, anchor?: string): string {
    const base = topicPath(sectionKey, topicKey)
    return anchor ? `${base}#${anchor}` : base
}

/** 主题内全部可定位锚点：页内目录与「层级完整性」检查共用同一口径。 */
export function topicAnchors(topic: HelpTopic): { subsection: string; items: string[] }[] {
    return topic.subsections.map((subsection) => ({
        subsection: subsectionAnchor(subsection.key),
        items: (subsection.items ?? []).map((item) => itemAnchor(subsection.key, item.key)),
    }))
}

/** 解析路由参数：未知或缺失时回落到第一个部分的首个主题。 */
export function findTopic(sectionKey?: string, topicKey?: string): { section: HelpSection; topic: HelpTopic } {
    const section = HELP_SECTIONS.find((item) => item.key === sectionKey) ?? HELP_SECTIONS[0]
    const topic = section.topics.find((item) => item.key === topicKey) ?? section.topics[0]
    return { section, topic }
}

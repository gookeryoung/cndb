/** 帮助文档导航（ADR 0029）：路由、侧栏与内容共用的唯一真相源。
 *
 * 一级 5 个部分顺序固定；每个部分至少 1 个主题；主题 key 在所属部分内唯一。
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

export interface HelpTopic {
    key: string
    label: string
    content: ReactNode
}

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

/** 解析路由参数：未知或缺失时回落到第一个部分的首个主题。 */
export function findTopic(sectionKey?: string, topicKey?: string): { section: HelpSection; topic: HelpTopic } {
    const section = HELP_SECTIONS.find((item) => item.key === sectionKey) ?? HELP_SECTIONS[0]
    const topic = section.topics.find((item) => item.key === topicKey) ?? section.topics[0]
    return { section, topic }
}

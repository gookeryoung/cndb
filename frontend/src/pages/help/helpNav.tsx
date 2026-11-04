/** 帮助文档导航（ADR 0029 / ADR 0036 / 需求卡片 0090）：元数据唯一真相源 + 按 section 懒加载正文。
 *
 * 四层模型：
 * - L1 部分（`HelpSectionMeta`）：固定 5 个，顺序不变，对应侧栏分组；
 * - L2 主题（`HelpTopicMeta`）：一个独立页面 + 独立路由 `/help/<section>/<topic>`；
 * - L3 小节（`HelpSubsection`）：页面内 `<h2>`，带锚点，进入页内目录；
 * - L4 条目（`HelpItem`）：小节内 `<h3>`，带锚点，只在所属小节展开，不入侧栏。
 *
 * 层级归属规则（ADR 0036 §2）：
 * - L2 按「对象 / 任务族」切；L3 按「阶段 / 属性维度」切；L4 是单一实例
 *   （一个视图类型、一个字段类型、一个设置项、一条排障症状、一个 FAQ 问题）。
 * - 每个 L2 至少 2 个 L3；每个 L3 要么有自己的正文，要么有 ≥2 个 L4；不允许空层。
 * - 同一事实只在一个 L4 写全，其它位置用交叉引用链接指过去（见 `helpLink`）。
 *
 * 体积口径（0090 C1）：本模块只含元数据（key / label / icon），**不静态 import 任何
 * content 模块**——正文经 `HELP_SECTION_LOADERS` 按 L1 部分动态拆 chunk，新增帮助文案
 * 只落进对应 section chunk，不再推动 `HelpDocsPage` 壳 chunk 膨胀。
 */

import {
    BookOutlined,
    CompassOutlined,
    QuestionCircleOutlined,
    SettingOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

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

/** L2 主题正文：一个页面的完整内容（由 content 模块懒加载提供）。 */
export interface HelpTopic {
    key: string
    label: string
    /** 页首导语，固定展示在标题下方。 */
    intro: ReactNode
    subsections: HelpSubsection[]
}

/** L2 主题元数据：侧栏与路由只需要 key / label，不含正文。 */
export interface HelpTopicMeta {
    key: string
    label: string
}

export type HelpSectionKey = 'quick-start' | 'tutorials' | 'examples' | 'configuration' | 'troubleshooting'

/** L1 部分：侧栏分组（纯元数据）。 */
export interface HelpSectionMeta {
    key: HelpSectionKey
    label: string
    icon: ReactNode
    topics: HelpTopicMeta[]
}

export const HELP_DOCS_TITLE = '帮助文档'

export const HELP_SECTIONS: HelpSectionMeta[] = [
    {
        key: 'quick-start',
        label: '快速入门',
        icon: <ThunderboltOutlined />,
        topics: [
            { key: 'overview', label: '认识晶格协同' },
            { key: 'philosophy', label: '设计理念' },
            { key: 'workflow', label: '十分钟上手' },
            { key: 'ui-tour', label: '界面导航' },
        ],
    },
    {
        key: 'tutorials',
        label: '教程&最佳实践',
        icon: <BookOutlined />,
        topics: [
            { key: 'view-types', label: '视图类型' },
            { key: 'field-types', label: '字段类型' },
            { key: 'import-export', label: '数据导入导出' },
            { key: 'roles', label: '权限与角色' },
            { key: 'documents', label: '文档：编辑、导入与分享' },
            { key: 'analytics', label: '数据分析与图表' },
            { key: 'search', label: '搜索与收藏' },
            { key: 'view-config', label: '视图配置实践' },
            { key: 'quality-checks', label: '质量检查与流水线' },
            { key: 'design-dsl', label: '结构设计（DSL）' },
        ],
    },
    {
        key: 'examples',
        label: '典型示例',
        icon: <CompassOutlined />,
        topics: [
            { key: 'sales', label: '某企业销售管理' },
            { key: 'research', label: '科研项目管理' },
            { key: 'datasource', label: '数据源示例' },
        ],
    },
    {
        key: 'configuration',
        label: '系统配置',
        icon: <SettingOutlined />,
        topics: [
            { key: 'workspace', label: '工作区设置' },
            { key: 'personal', label: '个人设置与大模型' },
            { key: 'datasource', label: '数据同步' },
            { key: 'admin', label: '管理台' },
            { key: 'storage', label: '存储、备份与部署' },
        ],
    },
    {
        key: 'troubleshooting',
        label: '问题排查',
        icon: <QuestionCircleOutlined />,
        topics: [
            { key: 'faq', label: '常见问题' },
            { key: 'guide', label: '使用与故障排查' },
            { key: 'feedback', label: '诊断与反馈' },
        ],
    },
]

/** 按 L1 部分懒加载正文：每个 content 模块 default-export 该部分的主题数组（0090 C1）。 */
export const HELP_SECTION_LOADERS: Record<HelpSectionKey, () => Promise<{ default: HelpTopic[] }>> = {
    'quick-start': () => import('./content/quickStart'),
    tutorials: () => import('./content/tutorials'),
    examples: () => import('./content/examples'),
    configuration: () => import('./content/configuration'),
    troubleshooting: () => import('./content/troubleshooting'),
}

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

/** 解析路由参数到元数据：未知或缺失时回落到第一个部分的首个主题（不触发正文加载）。 */
export function findTopicMeta(
    sectionKey?: string,
    topicKey?: string,
): { section: HelpSectionMeta; topic: HelpTopicMeta } {
    const section = HELP_SECTIONS.find((item) => item.key === sectionKey) ?? HELP_SECTIONS[0]!
    const topic = section.topics.find((item) => item.key === topicKey) ?? section.topics[0]!
    return { section, topic }
}

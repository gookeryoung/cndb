/** 帮助文档导航（ADR 0029 / ADR 0036）单测 —— 四层层级、归属唯一性、锚点与 URL 解析。 */

import { describe, expect, it } from 'vitest'
import {
    HELP_DOCS_TITLE,
    HELP_SECTIONS,
    findTopic,
    helpLink,
    itemAnchor,
    subsectionAnchor,
    topicAnchors,
    topicPath,
} from './helpNav'

/** 全站所有主题：层级检查逐个跑一遍，新增主题无需改测试。 */
const ALL_TOPICS = HELP_SECTIONS.flatMap((section) => section.topics.map((topic) => ({ section, topic })))

describe('helpNav 一级 / 二级结构', () => {
    it('一级固定 5 个部分且顺序符合需求', () => {
        expect(HELP_DOCS_TITLE).toBe('帮助文档')
        expect(HELP_SECTIONS.map((s) => s.label)).toEqual([
            '快速入门',
            '教程&最佳实践',
            '典型示例',
            '系统配置',
            '问题排查',
        ])
    })

    it('每个部分至少 1 个主题，且 section / topic key 唯一', () => {
        const sectionKeys = new Set<string>()
        for (const section of HELP_SECTIONS) {
            expect(section.topics.length).toBeGreaterThan(0)
            expect(sectionKeys.has(section.key)).toBe(false)
            sectionKeys.add(section.key)

            const topicKeys = new Set<string>()
            for (const topic of section.topics) {
                expect(topic.label.length).toBeGreaterThan(0)
                expect(topic.intro).toBeTruthy()
                expect(topicKeys.has(topic.key)).toBe(false)
                topicKeys.add(topic.key)
            }
        }
    })
})

describe('helpNav 三级 / 四级层级规则（ADR 0036 §2）', () => {
    it('每个主题至少 2 个 L3 小节', () => {
        for (const { section, topic } of ALL_TOPICS) {
            expect(topic.subsections.length, `${section.key}/${topic.key}`).toBeGreaterThanOrEqual(2)
        }
    })

    it('L3 key 在主题内唯一，且必须有正文或至少 2 个 L4 条目（不留空层）', () => {
        for (const { topic } of ALL_TOPICS) {
            const keys = new Set<string>()
            for (const subsection of topic.subsections) {
                expect(subsection.label.length, `${topic.key}/${subsection.key}`).toBeGreaterThan(0)
                expect(keys.has(subsection.key), `重复小节 key: ${topic.key}/${subsection.key}`).toBe(false)
                keys.add(subsection.key)

                const itemCount = subsection.items?.length ?? 0
                const hasBody = Boolean(subsection.body)
                // 单个条目不足以构成一级：要么有自己的正文，要么 ≥2 条，避免「标题 + 一句话」的空壳小节
                expect(hasBody || itemCount >= 2, `空白小节: ${topic.key}/${subsection.key}`).toBe(true)
            }
        }
    })

    it('L4 key 在小节内唯一，且 label 不与同级重复', () => {
        for (const { topic } of ALL_TOPICS) {
            for (const subsection of topic.subsections) {
                const keys = new Set<string>()
                const labels = new Set<string>()
                for (const item of subsection.items ?? []) {
                    expect(keys.has(item.key), `重复条目 key: ${topic.key}/${subsection.key}/${item.key}`).toBe(false)
                    keys.add(item.key)
                    expect(labels.has(item.label), `重复条目名: ${topic.key}/${item.label}`).toBe(false)
                    labels.add(item.label)
                    expect(item.body).toBeTruthy()
                }
            }
        }
    })

    it('锚点在主题内全局唯一：同页不同小节、条目都不会撞 id', () => {
        for (const { topic } of ALL_TOPICS) {
            const anchors: string[] = []
            for (const group of topicAnchors(topic)) {
                anchors.push(group.subsection, ...group.items)
            }
            expect(new Set(anchors).size, `锚点冲突: ${topic.key}`).toBe(anchors.length)
        }
    })

    it('生成的锚点可直接作为 DOM id 使用', () => {
        expect(subsectionAnchor('quick-start')).toBe('help-quick-start')
        expect(itemAnchor('concepts', 'workspace')).toBe('help-concepts--workspace')
        expect(subsectionAnchor('quick-start')).toMatch(/^[a-z0-9-]+$/)
        expect(itemAnchor('concepts', 'workspace')).toMatch(/^[a-z0-9-]+$/)
    })
})

describe('topicPath / helpLink 生成地址', () => {
    it('topicPath 生成 /help/<section>/<topic>', () => {
        expect(topicPath('tutorials', 'roles')).toBe('/help/tutorials/roles')
    })

    it('helpLink 追加锚点', () => {
        expect(helpLink('tutorials', 'roles', 'model')).toBe('/help/tutorials/roles#model')
        expect(helpLink('tutorials', 'roles')).toBe('/help/tutorials/roles')
    })
})

describe('findTopic 解析与回落', () => {
    it('命中已知 section / topic', () => {
        const { section, topic } = findTopic('tutorials', 'roles')
        expect(section.key).toBe('tutorials')
        expect(topic.key).toBe('roles')
    })

    it('缺失或未知参数回落到首个部分的首个主题', () => {
        expect(findTopic().topic.key).toBe(HELP_SECTIONS[0]!.topics[0]!.key)
        expect(findTopic('nope', 'nope').section.key).toBe(HELP_SECTIONS[0]!.key)
        expect(findTopic('tutorials', 'nope').topic.key).toBe(HELP_SECTIONS[1]!.topics[0]!.key)
    })
})

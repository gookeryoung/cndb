/** 帮助文档导航（ADR 0029）单测 —— 一级顺序、主题完整性、URL 解析与回落。 */

import { describe, expect, it } from 'vitest'
import { HELP_DOCS_TITLE, HELP_SECTIONS, findTopic, topicPath } from './helpNav'

describe('helpNav 导航结构', () => {
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
                expect(topic.content).toBeTruthy()
                expect(topicKeys.has(topic.key)).toBe(false)
                topicKeys.add(topic.key)
            }
        }
    })

    it('topicPath 生成 /help/<section>/<topic>', () => {
        expect(topicPath('tutorials', 'roles')).toBe('/help/tutorials/roles')
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

/** 帮助文档正文渲染器（ADR 0036）.
 *
 * 内容文件只交数据结构，层级与锚点由这里统一生成：
 * L3 小节 → `<section id="help-<sub>"><h2>`；L4 条目 → `<div id="help-<sub>--<item>"><h3>`。
 * 因此「页内目录里有的标题」与「正文里渲染的标题」必然一致，不会出现导航与内容漂移。
 */

import { itemAnchor, subsectionAnchor, type HelpTopic } from '../helpNav'

export default function HelpDoc({ topic }: { topic: HelpTopic }) {
    return (
        <>
            <div className="cn-help-docs-lead" data-testid="help-topic-intro">
                {topic.intro}
            </div>

            {topic.subsections.map((subsection) => (
                <section
                    key={subsection.key}
                    id={subsectionAnchor(subsection.key)}
                    className="cn-help-docs-section"
                    data-testid={`help-subsection-${subsection.key}`}
                >
                    <h2 className="cn-help-docs-h2">{subsection.label}</h2>
                    {subsection.summary && <p className="cn-help-docs-summary">{subsection.summary}</p>}
                    {subsection.body}

                    {(subsection.items ?? []).map((item) => (
                        <div
                            key={item.key}
                            id={itemAnchor(subsection.key, item.key)}
                            className="cn-help-docs-item"
                            data-testid={`help-item-${subsection.key}-${item.key}`}
                        >
                            <h3 className="cn-help-docs-h3">{item.label}</h3>
                            {item.body}
                        </div>
                    ))}
                </section>
            ))}
        </>
    )
}

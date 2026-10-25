/** 帮助文档 · 典型示例内容（ADR 0029 P0）.
 *
 * P0 先提供三套示例场景的图文说明（数据规模与字段要点）；
 * P1 接入后端示例清单后，在本节补充 CSV 下载与导入步骤。
 */

import { Tag, Typography } from 'antd'
import type { HelpTopic } from '../helpNav'

const { Text } = Typography

function ScenarioIntro({ children }: { children: React.ReactNode }) {
    return <Text type="secondary">{children}</Text>
}

function SalesContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <ScenarioIntro>
                从订单明细、客户流失到营销活动与日常待办的完整销售运营示例，适合练习「多表协作 + 多视图 + 数据分析」。
            </ScenarioIntro>
            <div>
                <Text strong>包含的数据表</Text>
                <br />
                <Text type="secondary">
                    电商销售（订单号、商品类别、单价、数量、支付方式、评分、销售额、日期）、客户流失、营销活动、日常待办、出差统计、产品开发、产品批次，以及部门 / 员工业务表。
                </Text>
            </div>
            <div>
                <Text strong>可以怎么练</Text>
                <br />
                <Text type="secondary">
                    用图表视图看月度销售额与渠道构成；用看板跟踪客户流失回访状态；用数据分析模板做商品类别占比与客单价；用文档记录季度复盘。
                </Text>
            </div>
            <div>
                <Text strong>涉及能力</Text>
                <div style={{ marginTop: 4 }}>
                    <Tag>CSV 导入</Tag>
                    <Tag>图表视图</Tag>
                    <Tag>看板视图</Tag>
                    <Tag>数据分析</Tag>
                    <Tag>文档协作</Tag>
                </div>
            </div>
        </div>
    )
}

function ResearchContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <ScenarioIntro>
                科研项目管理示例：围绕课题立项、任务分解、经费、资源排期与技术体系组织数据，适合练习层级与关联字段。
            </ScenarioIntro>
            <div>
                <Text strong>包含的数据表</Text>
                <br />
                <Text type="secondary">
                    科研项目（课题编号、项目名称、项目类别、承担单位、立项年份、计划周期、项目状态、经费总额、成果形式、结题日期等）、科研任务分解、科研待办事项、科研经费、科研资源排期、课题负责人、技术体系。
                </Text>
            </div>
            <div>
                <Text strong>可以怎么练</Text>
                <br />
                <Text type="secondary">
                    用工作分解视图按「课题 → 任务 → 子任务」组织层级；用甘特图看资源排期；用树形「技术脉络」查看技术体系；用文档维护管理制度与周报模板。
                </Text>
            </div>
            <div>
                <Text strong>涉及能力</Text>
                <div style={{ marginTop: 4 }}>
                    <Tag>关联字段</Tag>
                    <Tag>工作分解视图</Tag>
                    <Tag>甘特图</Tag>
                    <Tag>树形视图</Tag>
                    <Tag>文档目录</Tag>
                </div>
            </div>
        </div>
    )
}

function DatasourceContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <ScenarioIntro>
                数据源同步示例：把外部数据按计划写入数据表，覆盖资讯、美食与天气三类内容，适合练习数据接入与画廊阅读。
            </ScenarioIntro>
            <div>
                <Text strong>包含的数据表</Text>
                <br />
                <Text type="secondary">
                    国际形势发展动态（日期、地区、来源、摘要、标题、主题、趋势判断、链接）、美食推荐做法、天气每日。
                </Text>
            </div>
            <div>
                <Text strong>可以怎么练</Text>
                <br />
                <Text type="secondary">
                    用画廊视图阅读资讯与菜谱；配置「数据源同步」任务按 cron 周期抓取；用去重键避免重复入库；在分析页做天气趋势与地区分布统计。
                </Text>
            </div>
            <div>
                <Text strong>涉及能力</Text>
                <div style={{ marginTop: 4 }}>
                    <Tag>数据源同步</Tag>
                    <Tag>llm_prompt</Tag>
                    <Tag>画廊视图</Tag>
                    <Tag>周期性调度</Tag>
                </div>
            </div>
        </div>
    )
}

export const exampleTopics: HelpTopic[] = [
    { key: 'sales', label: '某企业销售管理', content: <SalesContent /> },
    { key: 'research', label: '科研项目管理', content: <ResearchContent /> },
    { key: 'datasource', label: '数据源示例', content: <DatasourceContent /> },
]

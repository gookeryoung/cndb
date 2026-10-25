/** 帮助文档 · 快速入门内容（ADR 0029 P0）.
 *
 * 两个主题：认识 cndb（核心概念）/ 十分钟上手（五步流程）。
 * 面向初次使用的用户：短句、动词开头，说清「做什么 + 得到什么」。
 */

import { Typography } from 'antd'
import type { HelpTopic } from '../helpNav'

const { Text } = Typography

function OverviewContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Text type="secondary">
                cndb 是自托管的数据与文档协作工具：把表格数据、文档和基于它们的视图放在同一个工作区里管理。
            </Text>
            <div>
                <Text strong>工作区</Text>
                <br />
                <Text type="secondary">独立的数据空间，用来存放一组相关的数据表、文档与成员权限。创建工作区是开始使用的第一步。</Text>
            </div>
            <div>
                <Text strong>数据表与字段</Text>
                <br />
                <Text type="secondary">数据表是行列结构；每个字段有类型（文本、数字、日期、单选等）。类型决定录入控件、校验与可用的视图能力。</Text>
            </div>
            <div>
                <Text strong>视图</Text>
                <br />
                <Text type="secondary">同一份数据可以用表格、看板、日历、画廊、甘特图、矩阵、图表等方式查看。筛选与排序保存在每个视图里，互不影响。</Text>
            </div>
            <div>
                <Text strong>文档</Text>
                <br />
                <Text type="secondary">工作区内的知识载体，支持 Markdown 编辑、文件导入与游客级只读分享。</Text>
            </div>
            <div>
                <Text strong>怎么用这份帮助</Text>
                <br />
                <Text type="secondary">
                    左侧按「快速入门 / 教程&最佳实践 / 典型示例 / 系统配置 / 问题排查」组织；每个主题都有独立地址，可直接分享或收藏。
                </Text>
            </div>
        </div>
    )
}

function WorkflowContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>1. 创建工作区</Text>
                <br />
                <Text type="secondary">在「工作区」页面点击「新建工作区」，填写名称即可。工作区是数据表与文档的容器。</Text>
            </div>
            <div>
                <Text strong>2. 创建数据表或导入数据</Text>
                <br />
                <Text type="secondary">
                    进入工作区后，在「数据表」页面点击「新建表」手动定义字段，或点击「导入数据表」上传 CSV / Excel / JSON 文件，系统会自动推断字段类型。
                </Text>
            </div>
            <div>
                <Text strong>3. 录入与管理数据</Text>
                <br />
                <Text type="secondary">
                    打开一张表，点击右上角「新增一行」逐行录入；点击单元格直接编辑，回车保存。也可以用「导入 / 导出」批量更新数据。
                </Text>
            </div>
            <div>
                <Text strong>4. 按需切换视图</Text>
                <br />
                <Text type="secondary">
                    点击视图栏左侧的 + 新建视图，每个视图可单独配置筛选和排序。视图类型与适用场景见「教程&最佳实践 → 视图类型」。
                </Text>
            </div>
            <div>
                <Text strong>5. 设置权限并协作</Text>
                <br />
                <Text type="secondary">
                    在「工作区设置」的成员管理中邀请成员并分配角色；在每张表的「表设置」中可对单张表做更细粒度的授权。
                </Text>
            </div>
        </div>
    )
}

export const quickStartTopics: HelpTopic[] = [
    { key: 'overview', label: '认识 cndb', content: <OverviewContent /> },
    { key: 'workflow', label: '十分钟上手', content: <WorkflowContent /> },
]

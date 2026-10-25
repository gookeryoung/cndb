/** 帮助文档 · 教程&最佳实践内容（ADR 0029 P0）.
 *
 * 迁入原「视图类型 / 数据导入导出 / 权限与角色 / 字段类型」四个主题，补充视图配置实践。
 * 字段类型与角色等事实与代码保持一致（16 主类型、owner/editor/viewer 三角色）。
 */

import { Table, Typography } from 'antd'
import type { HelpTopic } from '../helpNav'

const { Text } = Typography

function ViewTypesContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>表格视图（Grid）</Text>
                <br />
                <Text type="secondary">默认视图，类 Excel 的行列结构，适合数据录入、编辑与批量管理。</Text>
            </div>
            <div>
                <Text strong>看板视图（Kanban）</Text>
                <br />
                <Text type="secondary">
                    按某个单选/多选字段分组，卡片式拖拽流转，适合任务管理、销售漏斗等状态跟踪场景。创建看板视图时需选择「分组字段」。
                </Text>
            </div>
            <div>
                <Text strong>卡片画廊视图（Gallery）</Text>
                <br />
                <Text type="secondary">
                    卡片墙阅读态：标题 + 摘要 + 彩色标签 + 日期徽章，适合资讯、菜谱等内容型数据浏览与分享。可配置标题/摘要/标签/元信息/日期字段与卡片尺寸；只读，点击卡片打开行详情。
                </Text>
            </div>
            <div>
                <Text strong>日历视图（Calendar）</Text>
                <br />
                <Text type="secondary">按日期字段把每行数据显示在月历上，适合排期、日程类数据。创建时需选择「开始时间字段」。</Text>
            </div>
            <div>
                <Text strong>甘特图视图（Gantt）</Text>
                <br />
                <Text type="secondary">时间轴上展示任务的起止时间与进度，适合项目排期。需表中含日期类型字段。</Text>
            </div>
            <div>
                <Text strong>工作分解视图</Text>
                <br />
                <Text type="secondary">树状层级组织任务（1 / 1.1 / 1.1.1 编号），需配置「父任务关联字段」指定层级关系。</Text>
            </div>
            <div>
                <Text type="secondary">提示：筛选规则与排序规则保存在每个视图里，切换视图互不影响；在「表设置 → 视图」中可重命名、编辑或删除视图。</Text>
            </div>
        </div>
    )
}

function ImportExportContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>支持的文件格式</Text>
                <br />
                <Text type="secondary">CSV（推荐 UTF-8 编码）、Excel（.xlsx）、JSON。导入时系统会自动推断每列的字段类型，也可以在预览页面手动修改。</Text>
            </div>
            <div>
                <Text strong>导入流程</Text>
                <br />
                <Text type="secondary">「导入数据」→ 上传文件 → 预览列类型与数据质量 → 确认导入。导入完成后可在报告页查看错误行明细。</Text>
            </div>
            <div>
                <Text strong>更新已有数据</Text>
                <br />
                <Text type="secondary">
                    导入时选择「更新已有数据」模式，并指定一个或多个「参考列」字段（如工号、邮箱）。系统按参考列查找已有行：找到则更新，找不到则新增。参考列推荐选择唯一性高的字段（带 ★ 推荐标记）。
                </Text>
            </div>
            <div>
                <Text strong>导出数据</Text>
                <br />
                <Text type="secondary">
                    在表格页点击「导入 / 导出」按钮，可将当前表导出为 XLSX / CSV / PDF / JSON 文件；视图配置也可以导出为 JSON 备份，并可在其他表中导入复用。
                </Text>
            </div>
            <div>
                <Text strong>字段类型推断规则摘要</Text>
                <br />
                <Text type="secondary">
                    识别「2024-01-01」等格式为日期；「是/否、true/false」为布尔；带 % 的数值为百分比；少量重复值（≤30 个选项）自动提升为单选/多选。推断结果可在预览页逐列调整。
                </Text>
            </div>
        </div>
    )
}

const roleColumns = [
    { title: '角色', dataIndex: 'role', key: 'role', width: 90 },
    { title: '工作区级权限', dataIndex: 'ws', key: 'ws' },
    { title: '表级权限', dataIndex: 'tbl', key: 'tbl' },
]

const roleData = [
    { key: 'owner', role: '所有者', ws: '全部权限，可删除工作区、转让所有权、管理成员', tbl: '全部权限' },
    { key: 'editor', role: '编辑者', ws: '编辑数据、创建视图', tbl: '可录入与编辑数据' },
    { key: 'viewer', role: '查看者', ws: '只读查看（编辑自动生成修改申请）', tbl: '只读查看' },
]

function RolesContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>角色从高到低：所有者 &gt; 编辑者 &gt; 查看者</Text>
                <br />
                <Text type="secondary">
                    成员角色在工作区设置的「成员管理」中分配；单张表可在「表设置 → 权限」中对成员/角色做显式授权，未显式授权时遵循工作区角色。
                </Text>
            </div>
            <Table size="small" columns={roleColumns} dataSource={roleData} pagination={false} />
            <div>
                <Text strong>工作区可见性</Text>
                <br />
                <Text type="secondary">公开（public）：登录用户均可查看；仅成员（member-only）：仅工作区成员可见；私有（private）：仅拥有者与管理员可见。</Text>
            </div>
        </div>
    )
}

function FieldTypesContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Text type="secondary">共 16 种字段类型，按类别分组：</Text>
            <div>
                <Text strong>基础：</Text>
                <Text type="secondary">单行文本、多行文本、是/否（勾选框）。</Text>
            </div>
            <div>
                <Text strong>数字：</Text>
                <Text type="secondary">整数、小数、百分比（可输入「85%」或 0.85）。</Text>
            </div>
            <div>
                <Text strong>日期：</Text>
                <Text type="secondary">日期（仅年月日）、日期时间、时间戳。</Text>
            </div>
            <div>
                <Text strong>选择：</Text>
                <Text type="secondary">单选（下拉选一个，自动配色）、多选（可选多个，支持逗号/顿号分隔）。</Text>
            </div>
            <div>
                <Text strong>高级：</Text>
                <Text type="secondary">邮箱（自动校验格式）、链接、电话、附件（上传文件）。</Text>
            </div>
            <div>
                <Text strong>关联：</Text>
                <Text type="secondary">关联其他表的一行或多行数据（如下拉选择员工表中的员工），支持搜索选择与空值清空。</Text>
            </div>
            <Text type="secondary">提示：唯一值约束可防止重复值；默认值会在新增行时自动填入；修改默认值会触发表重建，数据量大时稍慢。</Text>
        </div>
    )
}

function ViewConfigContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>按用途选视图</Text>
                <br />
                <Text type="secondary">
                    录入与批量编辑用表格；状态流转用看板；内容阅读用画廊；排期用日历 / 甘特图；层级任务用工作分解；趋势与构成用图表或数据分析。
                </Text>
            </div>
            <div>
                <Text strong>筛选与排序放在视图里</Text>
                <br />
                <Text type="secondary">
                    同一张表可以建多个视图，各自保存筛选与排序；不要为了不同筛选复制数据表。视图配置在「表设置 → 视图」中维护。
                </Text>
            </div>
            <div>
                <Text strong>命名与职责</Text>
                <br />
                <Text type="secondary">
                    视图名写清用途（如「本周待办」「客户流失回访」），让成员从视图栏就能理解该看什么；共享视图前确认可见性设置。
                </Text>
            </div>
            <div>
                <Text strong>只读视图优先</Text>
                <br />
                <Text type="secondary">面向汇报与浏览的场景优先用画廊 / 图表等只读视图，减少误编辑；需要录入时再切回表格。</Text>
            </div>
        </div>
    )
}

export const tutorialTopics: HelpTopic[] = [
    { key: 'view-types', label: '视图类型', content: <ViewTypesContent /> },
    { key: 'import-export', label: '数据导入导出', content: <ImportExportContent /> },
    { key: 'roles', label: '权限与角色', content: <RolesContent /> },
    { key: 'field-types', label: '字段类型', content: <FieldTypesContent /> },
    { key: 'view-config', label: '视图配置实践', content: <ViewConfigContent /> },
]

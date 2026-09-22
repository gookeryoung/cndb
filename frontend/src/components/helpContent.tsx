/** 帮助中心内容数据 — 纯静态 JSX，随代码版本维护.
 *
 * 六大主题：快速上手 / 视图类型 / 数据导入导出 / 权限与角色 / 字段类型参考 / 常见问题。
 * 内容面向初级用户编写：短句、动词开头、说清「做什么 + 产生什么结果」。
 * 字段类型与角色等事实与代码保持一致（fieldTypeMeta 16 主类型、owner/admin/editor/viewer 四角色）。
 */

import React from 'react'
import { Steps, Table, Typography } from 'antd'

const { Text } = Typography

/** 单个帮助主题定义 */
export interface HelpTopic {
    key: string
    label: string
    /** 主题内容 */
    content: React.ReactNode
}

/* ── 快速上手 ─────────────────────────────────────────────── */

const quickStartContent = (
    <Steps
        direction="vertical"
        current={-1}
        items={[
            {
                title: '创建工作区',
                description: '工作区是一个独立的空间，用来存放一组相关的数据表。在「工作区」页面点击「新建工作区」，填写名称即可。',
            },
            {
                title: '创建数据表或导入数据',
                description: '进入工作区后，在「数据表」页面点击「新建表」手动定义字段，或点击「导入数据表」上传 CSV / Excel / JSON 文件，系统会自动推断字段类型。',
            },
            {
                title: '录入与管理数据',
                description: '打开一张表，点击右上角「新增一行」逐行录入；点击单元格直接编辑，回车保存。也可以用「导入 / 导出」批量更新数据。',
            },
            {
                title: '按需切换视图',
                description: '同一份数据可以用表格、看板、日历、画廊、甘特图、WBS 六种视图查看。点击视图栏左侧的 + 新建视图，每个视图可单独配置筛选和排序。',
            },
            {
                title: '设置权限并协作',
                description: '在「工作区设置」的成员管理中邀请成员并分配角色；在每张表的「表设置」中可对单张表做更细粒度的授权。',
            },
        ]}
    />
)

/* ── 视图类型说明 ─────────────────────────────────────────── */

const viewModeContent = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
            <Text strong>表格视图（Grid）</Text>
            <br />
            <Text type="secondary">默认视图，类 Excel 的行列结构，适合数据录入、编辑与批量管理。</Text>
        </div>
        <div>
            <Text strong>看板视图（Kanban）</Text>
            <br />
            <Text type="secondary">按某个单选/多选字段分组，卡片式拖拽流转，适合任务管理、销售漏斗等状态跟踪场景。创建看板视图时需选择「分组字段」。</Text>
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
            <Text strong>WBS 视图（Work Breakdown Structure）</Text>
            <br />
            <Text type="secondary">树状层级分解任务（1 / 1.1 / 1.1.1 编号），需配置「父任务关联字段」指定层级关系。</Text>
        </div>
        <div>
            <Text type="secondary">提示：筛选规则与排序规则保存在每个视图里，切换视图互不影响；在「表设置 → 视图」中可重命名、编辑或删除视图。</Text>
        </div>
    </div>
)

/* ── 数据导入导出 ─────────────────────────────────────────── */

const importExportContent = (
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
            <Text strong>更新已有数据（upsert）</Text>
            <br />
            <Text type="secondary">导入时选择「更新已有数据」模式，并指定一个或多个「匹配键」字段（如工号、邮箱）。系统按匹配键查找已有行：找到则更新，找不到则新增。匹配键推荐选择唯一性高的字段（带 ★ 推荐标记）。</Text>
        </div>
        <div>
            <Text strong>导出数据</Text>
            <br />
            <Text type="secondary">在表格页点击「导入 / 导出」按钮，可将当前表导出为 CSV / Excel / JSON 文件；视图配置也可以导出为 JSON 备份，并可在其他表中导入复用。</Text>
        </div>
        <div>
            <Text strong>字段类型推断规则摘要</Text>
            <br />
            <Text type="secondary">识别「2024-01-01」等格式为日期；「是/否、true/false」为布尔；带 % 的数值为百分比；少量重复值（≤30 个选项）自动提升为单选/多选。推断结果可在预览页逐列调整。</Text>
        </div>
    </div>
)

/* ── 权限与角色 ───────────────────────────────────────────── */

const roleColumns = [
    { title: '角色', dataIndex: 'role', key: 'role', width: 90 },
    { title: '工作区级权限', dataIndex: 'ws', key: 'ws' },
    { title: '表级权限', dataIndex: 'tbl', key: 'tbl' },
]

const roleData = [
    { key: 'owner', role: 'owner', ws: '全部权限，可删除工作区、转让所有权', tbl: '全部权限' },
    { key: 'admin', role: 'admin', ws: '管理成员（添加/移除）、编辑设置', tbl: '可编辑表结构与数据' },
    { key: 'editor', role: 'editor', ws: '编辑数据、创建视图', tbl: '可录入与编辑数据' },
    { key: 'viewer', role: 'viewer', ws: '只读查看', tbl: '只读查看' },
]

const roleContent = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
            <Text strong>角色从高到低：owner &gt; admin &gt; editor &gt; viewer</Text>
            <br />
            <Text type="secondary">成员角色在工作区设置的「成员管理」中分配；单张表可在「表设置 → 权限」中对成员/角色做显式授权，未显式授权时遵循工作区角色。</Text>
        </div>
        <Table
            size="small"
            columns={roleColumns}
            dataSource={roleData}
            pagination={false}
        />
        <div>
            <Text strong>工作区可见性</Text>
            <br />
            <Text type="secondary">
                公开（public）：登录用户均可查看；仅成员（member-only）：仅工作区成员可见；私有（private）：仅拥有者与管理员可见。
            </Text>
        </div>
    </div>
)

/* ── 字段类型参考 ─────────────────────────────────────────── */

const fieldTypeContent = (
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
        <Text type="secondary">提示：唯一约束（is_unique）可防止重复值；默认值会在新增行时自动填入；修改默认值会触发表重建，数据量大时稍慢。</Text>
    </div>
)

/* ── 常见问题 ─────────────────────────────────────────────── */

const faqContent = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
            <Text strong>筛选和排序会保存吗？</Text>
            <br />
            <Text type="secondary">会。筛选/排序规则保存在当前视图中，每个视图独立；通过「表设置 → 视图」可编辑视图的规则。</Text>
        </div>
        <div>
            <Text strong>删除的行还能找回吗？</Text>
            <br />
            <Text type="secondary">删除行是软删除：数据仍保留在数据库中，只是默认不再显示。如需恢复请联系工作区管理员通过接口恢复，删除前请谨慎确认。</Text>
        </div>
        <div>
            <Text strong>如何让别人填写数据？</Text>
            <br />
            <Text type="secondary">公开表单功能可将表暴露为匿名可填写的表单页面（/public/form/链接）；公开分享则提供只读的数据查看页（/public/share/链接）。链接无效或过期时页面会给出提示。</Text>
        </div>
        <div>
            <Text strong>为什么有些按钮是灰色的？</Text>
            <br />
            <Text type="secondary">顶部「报表」「工作区设置」按钮需要先在左上角选择工作区；部分操作需要更高角色权限（如删除工作区仅 owner 可用）。将鼠标悬停在按钮上可查看说明。</Text>
        </div>
        <div>
            <Text strong>数据存在哪里？</Text>
            <br />
            <Text type="secondary">cndb 是自托管应用，数据存储在服务器本地的 SQLite 数据库中；打包安装版存放在系统用户数据目录（如 Windows 的 %APPDATA%\cndb）。</Text>
        </div>
    </div>
)

/* ── 主题清单 ─────────────────────────────────────────────── */

export const HELP_TOPICS: HelpTopic[] = [
    { key: 'quick-start', label: '快速上手', content: quickStartContent },
    { key: 'view-modes', label: '视图类型说明', content: viewModeContent },
    { key: 'import-export', label: '数据导入导出', content: importExportContent },
    { key: 'roles', label: '权限与角色', content: roleContent },
    { key: 'field-types', label: '字段类型参考', content: fieldTypeContent },
    { key: 'faq', label: '常见问题', content: faqContent },
]

/** 帮助中心标题（测试与抽屉共用） */
export const HELP_CENTER_TITLE = '帮助中心'

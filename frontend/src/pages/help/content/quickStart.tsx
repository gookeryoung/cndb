/** 帮助文档 · 快速入门（ADR 0035）.
 *
 * 三个主题：认识 cndb（概念）/ 十分钟上手（流程）/ 界面导航（入口速查）。
 * 面向初次使用者：短句、动词开头，说清「做什么 + 得到什么」。
 */

import HelpFigure from '../HelpFigure'
import type { HelpTopic } from '../helpNav'
import { Bullets, HelpLink, Note, P, Strong } from './primitives'

const overview: HelpTopic = {
    key: 'overview',
    label: '认识 cndb',
    intro: <P>cndb 是自托管的数据与文档协作工具：把表格数据、文档和基于它们的视图放在同一个工作区里管理。</P>,
    subsections: [
        {
            key: 'concepts',
            label: '核心概念',
            summary: '先把五个概念分清，后面所有操作都是这五个概念的组合。',
            items: [
                {
                    key: 'workspace',
                    label: '工作区',
                    body: (
                        <P>
                            独立的数据空间，用来存放一组相关的数据表、文档与成员权限。创建工作区是开始使用的第一步；
                            工作区之间数据、成员与配额互不影响。
                        </P>
                    ),
                },
                {
                    key: 'table',
                    label: '数据表与字段',
                    body: (
                        <P>
                            数据表是行列结构；每个字段有类型（文本、数字、日期、单选等）。类型决定录入控件、校验与可用的视图能力，
                            选型建议见 <HelpLink section="tutorials" topic="field-types" anchor="choose">字段类型 · 选型建议</HelpLink>。
                        </P>
                    ),
                },
                {
                    key: 'view',
                    label: '视图',
                    body: (
                        <P>
                            同一份数据可以用表格、看板、日历、画廊、甘特图、工作分解、K 线、图表等方式查看。筛选与排序保存在每个视图里，
                            互不影响；视图类型与适用场景见 <HelpLink section="tutorials" topic="view-types">视图类型</HelpLink>。
                        </P>
                    ),
                },
                {
                    key: 'document',
                    label: '文档',
                    body: (
                        <P>
                            工作区内的知识载体，支持 Markdown 编辑、版本历史、库导入与游客级只读分享，
                            见 <HelpLink section="tutorials" topic="documents">文档：编辑、导入与分享</HelpLink>。
                        </P>
                    ),
                },
                {
                    key: 'member',
                    label: '成员与角色',
                    body: (
                        <P>
                            成员在「工作区设置」里邀请，角色分所有者 / 编辑者 / 查看者三档，决定能读什么、能写什么、写入是否转审批，
                            见 <HelpLink section="tutorials" topic="roles" anchor="model">权限与角色 · 角色模型</HelpLink>。
                        </P>
                    ),
                },
            ],
            body: <HelpFigure id="workspace-structure" />,
        },
        {
            key: 'help-map',
            label: '这份帮助怎么用',
            summary: '按「要找什么」选部分，每个主题都有独立地址，可直接分享或收藏。',
            body: (
                <Bullets
                    items={[
                        <>
                            <Strong>快速入门</Strong>：第一次使用，先看概念与五步流程。
                        </>,
                        <>
                            <Strong>教程&amp;最佳实践</Strong>：具体功能怎么配、怎么用才不出错。
                        </>,
                        <>
                            <Strong>典型示例</Strong>：三套可下载的业务场景数据，照着练一遍。
                        </>,
                        <>
                            <Strong>系统配置</Strong>：工作区、个人、数据源、管理台与部署。
                        </>,
                        <>
                            <Strong>问题排查</Strong>：症状 → 原因 → 处理，另有常见问题与反馈入口。
                        </>,
                    ]}
                />
            ),
        },
    ],
}

const workflow: HelpTopic = {
    key: 'workflow',
    label: '十分钟上手',
    intro: <P>从零到「有数据、有视图、有协作者」的最小路径，五步走完即可正常使用。</P>,
    subsections: [
        {
            key: 'steps',
            label: '五步流程',
            summary: '每一步都能在帮助里找到对应的详细主题。',
            body: <HelpFigure id="quick-start-flow" caption="五步上手：每一步在下面都有对应说明。" />,
            items: [
                {
                    key: 'create-workspace',
                    label: '1. 创建工作区',
                    body: <P>在「工作区」页面点击「新建工作区」，填写名称即可。工作区是数据表与文档的容器。</P>,
                },
                {
                    key: 'create-table',
                    label: '2. 创建数据表或导入数据',
                    body: (
                        <P>
                            进入工作区后，在「数据表」页面点击「新建表」手动定义字段，或点击「导入数据表」上传 CSV / Excel / JSON
                            文件，系统会自动推断字段类型；见 <HelpLink section="tutorials" topic="import-export" anchor="flow">数据导入导出 · 导入流程</HelpLink>。
                        </P>
                    ),
                },
                {
                    key: 'input-data',
                    label: '3. 录入与管理数据',
                    body: (
                        <P>
                            打开一张表，点击右上角「新增一行」逐行录入；点击单元格直接编辑，回车保存。
                            也可以用「导入 / 导出」批量更新数据。
                        </P>
                    ),
                },
                {
                    key: 'create-view',
                    label: '4. 按需切换视图',
                    body: (
                        <P>
                            点击视图栏左侧的 + 新建视图，每个视图可单独配置筛选和排序。
                            选型见 <HelpLink section="tutorials" topic="view-config" anchor="choose">视图配置实践 · 按用途选视图</HelpLink>。
                        </P>
                    ),
                },
                {
                    key: 'permission',
                    label: '5. 设置权限并协作',
                    body: (
                        <P>
                            在「工作区设置」的成员管理中邀请成员并分配角色；在每张表的「表设置」中可对单张表做更细粒度的授权。
                            只读成员想改数据时，编辑会转成修改申请，由所有者 / 编辑者审批。
                        </P>
                    ),
                },
            ],
        },
        {
            key: 'after',
            label: '完成后你能做什么',
            summary: '五步之后的常见下一步，按需继续。',
            body: (
                <Bullets
                    items={[
                        <>
                            把重复性的数据接入交给周期任务：
                            <HelpLink section="configuration" topic="datasource" anchor="schedule">数据源同步 · 调度与运行记录</HelpLink>。
                        </>,
                        <>
                            用公式、分组汇总与图表做分析：
                            <HelpLink section="tutorials" topic="analytics" anchor="entry">数据分析与图表 · 入口与数据范围</HelpLink>。
                        </>,
                        <>
                            把结论沉淀成文档并对外只读分享：
                            <HelpLink section="tutorials" topic="documents" anchor="share">文档 · 分享与游客访问</HelpLink>。
                        </>,
                        <>
                            照着示例数据练一遍：
                            <HelpLink section="examples" topic="sales">典型示例 · 某企业销售管理</HelpLink>。
                        </>,
                    ]}
                />
            ),
        },
    ],
}

const uiTour: HelpTopic = {
    key: 'ui-tour',
    label: '界面导航',
    intro: <P>记住三块区域即可：顶栏（全局）、工作区页签（当前工作区）、视图栏（当前表或文档）。</P>,
    subsections: [
        {
            key: 'layout',
            label: '整体布局',
            summary: '从上到下、从左到右，各区域只负责一类事情。',
            items: [
                {
                    key: 'topbar',
                    label: '顶栏',
                    body: (
                        <P>
                            左侧是工作区切换与侧栏开关；中间是全局搜索（范围可切「全部 / 数据表 / 文档」）；右侧是新建、帮助文档与用户菜单
                            （个人设置、大模型设置、关于系统、退出登录）。窄屏下帮助入口收进用户菜单。
                        </P>
                    ),
                },
                {
                    key: 'tabs',
                    label: '工作区页签',
                    body: (
                        <P>
                            数据表 / 文档 / 数据分析 / 数据源同步 / 修改申请 / 问题清单 / 工作区设置。
                            页签数量由工作区类型决定（仅数据、仅文档或两者兼有）。
                        </P>
                    ),
                },
                {
                    key: 'sidebar',
                    label: '侧栏与视图栏',
                    body: (
                        <P>
                            进入某张表后，左侧是表清单，进入文档后是文档结构树；表页顶部的视图栏切换视图并承载筛选、排序与视图设置。
                        </P>
                    ),
                },
                {
                    key: 'content',
                    label: '内容区工具条',
                    body: (
                        <P>
                            当前表或文档的主操作都收在内容区右上角（新增行、导入 / 导出、分享、设置）。
                            灰色按钮通常是没有权限或没选工作区，见 <HelpLink section="troubleshooting" topic="guide" anchor="permission">故障排查 · 权限与可见性</HelpLink>。
                        </P>
                    ),
                },
            ],
        },
        {
            key: 'entries',
            label: '常用入口速查',
            summary: '六个高频动作各自的位置，找不到入口时先看这里。',
            items: [
                { key: 'new-table', label: '新建数据表 / 导入数据', body: <P>「数据表」页签右上角：「新建表」「导入数据表」。</P> },
                {
                    key: 'new-view',
                    label: '新建视图',
                    body: <P>表页视图栏左侧的 + 号；创建后立刻进入该视图的配置项。</P>,
                },
                { key: 'search', label: '搜索', body: <P>顶栏中间搜索框，也可在任意页面用键盘唤起；范围与结果见 <HelpLink section="tutorials" topic="search" anchor="global">搜索与收藏 · 全局搜索范围</HelpLink>。</P> },
                { key: 'invite', label: '邀请成员', body: <P>「工作区设置 → 成员管理 → 邀请成员」，选择角色后发送。</P> },
                { key: 'help', label: '帮助文档', body: <P>桌面顶栏问号图标；窄屏在用户菜单里。本页即帮助文档，可从任意主题复制地址分享。</P> },
                { key: 'personal', label: '个人设置', body: <P>右上角头像 →「个人设置」；大模型连接、调用记录与偏好都在这里。</P> },
            ],
        },
        {
            key: 'interaction',
            label: '交互习惯',
            summary: '几个一致的操作约定，学会后到处通用。',
            body: (
                <Bullets
                    items={[
                        '点单元格即进入编辑，回车保存、Esc 取消；行详情更适合一次看完整行。',
                        '列表与卡片左侧的拖拽手柄用于排序，需要编辑者及以上角色。',
                        '所有筛选、排序、视图配置都按「视图」保存，不改变原始数据。',
                        '窄屏（< 768px）下侧栏收进抽屉，页签横向滚动，表格支持横向滚动查看全部列。',
                    ]}
                />
            ),
        },
        {
            key: 'first-run',
            label: '第一次进入时',
            summary: '如果看到的是空工作区或引导浮层。',
            body: (
                <Note>
                    新账号默认没有工作区，需要先创建或等待被邀请。新手引导可以随时从帮助文档页右上角「重新播放新手引导」再看一次。
                </Note>
            ),
        },
    ],
}

export const quickStartTopics: HelpTopic[] = [overview, workflow, uiTour]

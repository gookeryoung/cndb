/** 帮助文档 · 快速入门（ADR 0036）.
 *
 * 四个主题：认识晶格协同（概念）/ 设计理念（为什么这样做）/ 十分钟上手（流程）/ 界面导航（入口速查）。
 * 面向初次使用者：短句、动词开头，说清「做什么 + 得到什么」。
 */

import HelpFigure from '../HelpFigure'
import type { HelpTopic } from '../helpNav'
import { Bullets, HelpLink, Note, P, Strong } from './primitives'

const overview: HelpTopic = {
    key: 'overview',
    label: '认识晶格协同',
    intro: <P>本页你能学到什么：工作区、数据表、视图、文档与成员这几个核心概念怎么串起来。适合谁：第一次打开晶格协同、还没建过工作区的新成员。</P>,
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
                            <Strong>快速入门</Strong>：第一次使用，先看概念与理念，再照五步流程走一遍。
                        </>,
                        <>
                            <Strong>教程&amp;最佳实践</Strong>：具体功能怎么配、怎么用才不出错。
                        </>,
                        <>
                            <Strong>典型示例</Strong>：两套可下载的业务场景数据，照着练一遍。
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

const philosophy: HelpTopic = {
    key: 'philosophy',
    label: '设计理念',
    intro: (
        <P>
            本页你能学到什么：几条设计原则，以及它们如何解释产品里的常见行为。
            适合谁：想理解「为什么这样设计」的成员。
        </P>
    ),
    subsections: [
        {
            key: 'principles',
            label: '五条原则',
            summary: '每条原则对应一类你在产品里能直接感知的行为。',
            items: [
                {
                    key: 'data-first',
                    label: '数据为中心',
                    body: (
                        <P>
                            数据表是整个系统的地基：字段有类型、行列有结构，文档、视图、图表都围绕表展开。
                            数据如晶格般规整排列、彼此关联——link 字段建立表与表的引用，文档与图表再把这些数据讲成结论。
                        </P>
                    ),
                },
                {
                    key: 'views-not-data',
                    label: '一份数据，多种呈现',
                    body: (
                        <P>
                            筛选、排序、字段显隐与视图配置都保存在「视图」上，任何视图操作都不修改原始数据。
                            同一张表可以有表格、看板、日历、甘特图、K 线、图表等多种读法，彼此互不影响；要改数据，回到单元格与行详情。
                        </P>
                    ),
                },
                {
                    key: 'doc-data-bridge',
                    label: '数据与文档互通',
                    body: (
                        <P>
                            文档不是孤立的文本：正文里可以用 <Strong>{'{{table:表名}}'}</Strong> 引用实时数据表、
                            用 <Strong>{'{{chart:编号}}'}</Strong> 内嵌图表、用 <Strong>[[标题]]</Strong> 双向链接其他文档。
                            数据更新后文档里的呈现随之更新，结论与数据始终同源。
                        </P>
                    ),
                },
                {
                    key: 'declarative',
                    label: '声明式配置，不写代码',
                    body: (
                        <P>
                            复杂能力以「填配置」的方式开放：字段类型决定录入与校验行为；数据同步只需声明请求、解析、
                            幂等键与调度四要素，即可把外部数据周期性接入同一张表；分析由公式、图表与分组汇总组合而成，无需开发。
                        </P>
                    ),
                },
                {
                    key: 'graduated-collaboration',
                    label: '分级协作，写入有轨',
                    body: (
                        <P>
                            成员分所有者 / 编辑者 / 查看者三级；写入遵循「双轨制」——有编辑权的人直编直存，
                            查看者的修改自动转为修改申请，由所有者 / 编辑者审批后生效。问题清单则承接反馈与提问，
                            让协作有迹可循。
                        </P>
                    ),
                },
            ],
        },
        {
            key: 'in-product',
            label: '理念如何落到产品',
            summary: '把原则对应到具体功能，遇到需求时按图索骥。',
            body: (
                <Bullets
                    items={[
                        <>
                            想换一种看数据的方式 → 建视图，而不是改数据：
                            <HelpLink section="tutorials" topic="view-types">视图类型</HelpLink>。
                        </>,
                        <>
                            想把外部数据接进来 → 配置数据同步任务，而不是手工搬运：
                            <HelpLink section="configuration" topic="datasource">数据同步</HelpLink>。
                        </>,
                        <>
                            想沉淀分析结论 → 数据分析出图表，文档引用实时数据表：
                            <HelpLink section="tutorials" topic="analytics" anchor="entry">数据分析与图表</HelpLink>、
                            <HelpLink section="tutorials" topic="documents">文档</HelpLink>。
                        </>,
                        <>
                            想控制谁能改什么 → 三级角色叠加表级授权，越权写入自动转修改申请：
                            <HelpLink section="tutorials" topic="roles" anchor="model">权限与角色</HelpLink>。
                        </>,
                    ]}
                />
            ),
        },
        {
            key: 'boundaries',
            label: '边界与取舍',
            summary: '理念也决定了产品「不做什么」，避免错误预期。',
            body: (
                <Note>
                    cndb 是自托管系统：数据与部署都由你自己掌握，备份恢复、离线部署是一等公民；
                    但也因此，浏览器基线只承诺 Chrome / Edge 81+，不承诺 Firefox / Safari。
                    领域专属的数据接入不做进通用适配器，而是沉淀为领域模板与推荐提示词——通用框架稳定，领域能力外挂。
                </Note>
            ),
        },
    ],
}

const workflow: HelpTopic = {
    key: 'workflow',
    label: '十分钟上手',
    intro: (
        <>
            <P>本页你能学到什么：五步从零建起一个可用的工作区。适合谁：第一次使用的成员。</P>
            <P>从零到「有数据、有视图、有协作者」的最小路径，五步走完即可正常使用。</P>
            <P>
                拿到的是模板工作区？按这条路径走：先看
                <HelpLink section="tutorials" topic="templates">工作区模板</HelpLink>
                ，再按
                <HelpLink section="tutorials" topic="data-flow">数据流程</HelpLink>
                填报，最后用
                <HelpLink section="tutorials" topic="view-types">视图类型</HelpLink>
                挑一个合适视图查看结果。
            </P>
        </>
    ),
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
                            <HelpLink section="configuration" topic="datasource" anchor="schedule">数据同步 · 调度与运行记录</HelpLink>。
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
    intro: <P>本页你能学到什么：顶栏、工作区页签与视图栏分别管什么。适合谁：刚登录、找不到入口的新成员。</P>,
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
                            按左、右两区划分：左侧是品牌、工作区切换与一级模块导航（数据表 / 文档 / 设计 / 项目 / 工作区设置；
                            「项目」仅在启用项目级管理的工作区出现）；
                            右侧依次是搜索框（工作区内可切「全部 / 数据表 / 文档」范围，主页等无工作区上下文时为跨工作区搜索）、
                            大模型设置、帮助文档与用户菜单（个人设置、关于系统、退出登录；系统管理员另有管理台入口）。
                            搜索框固定在右侧操作按钮左侧，主页与工作区两种视图位置一致。
                            工作区切换保持当前一级模块：例如在「文档」里切到另一个工作区，仍进入该工作区的文档模块
                            （目标工作区未勾选该模块时，回到它勾选的第一个一级模块，顺序同导航：数据表 → 文档 → 设计）。
                            项目模式工作区另有项目切换器：选中项目后，数据流程、生命周期与文档树都只显示该项目的数据，
                            地址栏带 <code>?project=</code>，分享链接会停在同一项目。
                            窄屏下一级模块收进页签行、帮助入口收进用户菜单。
                        </P>
                    ),
                },
                {
                    key: 'tabs',
                    label: '工作区二级页签',
                    body: (
                        <P>
                            内容区上方只承载二级模块：数据列表 / 数据分析 / 数据同步 / 质量检查 / 修改申请 / 问题清单；一级模块（数据表 / 文档 /
                            设计 / 工作区设置）位于顶栏导航。页签由工作区勾选的功能模块决定：数据分析与数据同步随数据表一并开放，
                            且仅在数据表模块下显示（切到文档 / 设计 / 工作区设置时隐藏），质量检查在文档 / 设计模块下隐藏——
                            文档段入口由文档区子页「质量检查」承载，设计段不承载质量检查入口；数据表与设置段仍显示。
                            修改申请与问题清单参考文档模块放在数据表模块层级（跨全部可读表聚合）；选中单表时不再渲染表名与表级子页入口，数据表设置路由仍可直接访问。
                            进入文档模块后，页签行右侧提供文档区子页：「文档结构」回到文档总览列表，
                            「质量检查」进入文档质量检查页（只呈现文档检查动作与规则），修改申请与问题清单作用于全部文档。
                            进入设计模块后是单一工作台：侧栏在产品列表与结构树之间就地切换，
                            选择产品后侧栏切为该产品的装配结构树（按 系统（system）→ 组件 → 分组 → 零件 展开），
                            内容区只承载 DSL 编辑器与 3D 视图；点击树节点可定位到结构 DSL 源行。
                            进入设计模块会自动打开最近更新的产品，点侧栏「产品列表」可切回列表。
                        </P>
                    ),
                },
                {
                    key: 'sidebar',
                    label: '侧栏与视图栏',
                    body: (
                        <P>
                            进入某张表后，左侧是表清单，进入文档后是文档结构树，进入设计模块后是「产品列表 ↔ 装配结构树」两态侧栏
                            （选中产品后侧栏就地切入结构树，内容区留给 DSL 编辑器与 3D 视图）；
                            进入工作区设置时侧栏沿用来源模块（从文档 / 设计进入就保持对应侧栏），
                            刷新或直接打开设置页才回落到表清单；表页顶部的视图栏切换视图并承载筛选、排序与视图设置。
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
                { key: 'search', label: '搜索', body: <P>顶栏右侧搜索框（操作按钮左侧），也可在任意页面用键盘唤起；范围与结果见 <HelpLink section="tutorials" topic="search" anchor="global">搜索与收藏 · 全局搜索范围</HelpLink>。</P> },
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

export const quickStartTopics: HelpTopic[] = [overview, philosophy, workflow, uiTour]

/** 供 helpNav 的 HELP_SECTION_LOADERS 按部分懒加载（0090 C1）。 */
export default quickStartTopics

/** 帮助文档 · 系统配置（ADR 0036）.
 *
 * 五个主题按「配置对象的归属」切：工作区、个人、数据源任务、管理台（跨工作区）、
 * 存储与部署（实例级）。同一开关只在一个主题里写全，其余位置用链接指过去。
 */

import HelpFigure from '../HelpFigure'
import type { HelpTopic } from '../helpNav'
import { Bullets, HelpLink, Note, P } from './primitives'

const workspace: HelpTopic = {
    key: 'workspace',
    label: '工作区设置',
    intro: <P>工作区设置决定「谁能进、能改什么、数据怎么管」，分基本设置、成员管理、统计信息三块。</P>,
    subsections: [
        {
            key: 'basic',
            label: '基本信息与类型',
            body: (
                <P>
                    在「工作区设置 → 基本设置」修改名称与描述。工作区类型决定开放的功能：数据 + 文档（默认）、
                    仅数据表与数据分析、仅文档；修改后顶部页签与侧栏随之调整，已有数据不会被删除。
                </P>
            ),
        },
        {
            key: 'visibility',
            label: '公开性',
            body: (
                <P>
                    公开：登录用户均可查看；成员可见：仅工作区成员可访问；私有：仅所有者与管理员可见。
                    修改后立即生效。三档的完整口径见
                    <HelpLink section="tutorials" topic="roles" anchor="visibility"> 权限与角色 · 工作区可见性 </HelpLink>。
                </P>
            ),
        },
        {
            key: 'member',
            label: '成员与角色',
            body: (
                <P>
                    「成员管理」按所有者 / 编辑者 / 查看者三区展示成员，可邀请、改角色、移除；仅所有者可管理成员。
                    单张表还可以在「表设置 → 权限」中做更细的显式授权。
                </P>
            ),
        },
        {
            key: 'allow-edit',
            label: '编辑权限开关',
            body: (
                <>
                    <P>
                        关闭「编辑权限」后，编辑者的保存会转为修改申请，由所有者 / 编辑者审批后生效；
                        适合需要留痕或集中审核的阶段。所有者自身仍可直接修改。
                    </P>
                    <Note>关闭期间新建的数据与文档仍会保存，只是写入路径变成申请；恢复开关后未审批的申请不会自动生效。</Note>
                </>
            ),
        },
        {
            key: 'stats',
            label: '统计与配额',
            body: (
                <P>
                    「统计信息」展示表数、文档数、成员数与存储用量；存储上限由管理员在
                    <HelpLink section="configuration" topic="admin" anchor="storage"> 管理台 · 空间分配 </HelpLink>
                    中设置，用超后上传会被拒绝。
                </P>
            ),
        },
        {
            key: 'danger',
            label: '危险操作',
            body: (
                <Note kind="warn">
                    删除工作区会永久删除其中的数据表、数据行、视图、文档与成员关系，无法恢复。删除前先用
                    <HelpLink section="configuration" topic="admin" anchor="backup"> 管理台 · 系统备份 </HelpLink>
                    做一次整库备份。所有权可转让给其他成员，转让后自己降为编辑者。
                </Note>
            ),
        },
    ],
}

const personal: HelpTopic = {
    key: 'personal',
    label: '个人设置与大模型',
    intro: <P>个人设置只影响自己：账号资料、界面主题、表格交互偏好与大模型连接，都不改变工作区里其他人的视图。</P>,
    subsections: [
        {
            key: 'account',
            label: '账号资料',
            body: <P>点击右上角头像 →「个人设置 → 资料」，可修改昵称与邮箱；用户名只读。密码修改在资料页下方，需要先验证当前密码。</P>,
        },
        {
            key: 'theme',
            label: '主题与显示',
            body: (
                <P>
                    「主题」页签切换配色与字号；选择按账号保存，登录后在任意设备一致。
                    默认字号与字重口径是全站统一的，界面里的表格密度可在「表格」页签单独调整。
                </P>
            ),
        },
        {
            key: 'llm',
            label: '大模型连接',
            body: (
                <P>
                    「大模型」页签配置 base_url、模型与 API Key；配置为个人级、任务之间共用，
                    密钥加密保存且不回显。未配置时，依赖大模型的任务在运行时会提示先完成配置。
                    连接可先「测试连通」，再用于同步任务、数据填充与分析。
                </P>
            ),
        },
        {
            key: 'usage',
            label: '调用记录',
            body: <P>同一页签可查看本人的调用记录（动作、模型、耗时、token 用量与状态）；记录不保存提示词与输出全文。</P>,
        },
        {
            key: 'preference',
            label: '收藏与排序偏好',
            body: (
                <P>
                    首页「我的视图」收藏与工作区排序都按用户保存，换设备后仍然是同一顺序；
                    怎么加收藏见 <HelpLink section="tutorials" topic="search" anchor="favorite"> 搜索与收藏 · 我的视图收藏 </HelpLink>。
                </P>
            ),
        },
    ],
}

const datasource: HelpTopic = {
    key: 'datasource',
    label: '数据源同步',
    intro: <P>数据源同步把外部数据按计划写进数据表：任务是声明式的（Provider + 请求 + 字段映射 + 调度），运行时按幂等键去重。</P>,
    subsections: [
        {
            key: 'entry',
            label: '入口与任务列表',
            body: (
                <P>
                    工作区页签「数据源同步」：管理同步任务、查看运行记录、配置凭证会话。
                    任务列表显示最近一次运行状态与下次触发时间，点任务查看配置与历史。
                </P>
            ),
        },
        {
            key: 'provider',
            label: 'Provider 与字段映射',
            items: [
                {
                    key: 'http-json',
                    label: 'http_json（声明式 HTTP）',
                    body: (
                        <P>
                            最多用的一类：声明 URL、请求头、参数与响应取值路径，再把源字段映射到目标表字段（可缩放、可丢弃）。
                            支持分页、并发、全局限速与行级常量填充，领域无关 —— 新接口通常只需改配置，不需要新 Provider。
                        </P>
                    ),
                },
                {
                    key: 'llm-prompt',
                    label: 'llm_prompt（大模型提示词）',
                    body: (
                        <P>
                            用自然语言提示词让模型产出结构化数据（如情报摘要、政策台账），配合推荐提示词开箱可用。
                            需要个人大模型连接；输出必须能解析成约定的 JSON 结构，解析失败会在运行记录中报出。
                        </P>
                    ),
                },
            ],
        },
        {
            key: 'credential',
            label: '凭证会话',
            body: (
                <P>
                    请求头与密钥集中存放在「凭证会话」中，任务以会话引用；密钥加密入库、只写不回显，
                    删除会话会解绑任务。这样多个任务共用一套凭证，换密钥只改一处。
                </P>
            ),
        },
        {
            key: 'schedule',
            label: '调度与运行记录',
            body: (
                <>
                    <P>
                        任务按 cron 周期由后台调度触发，也可手动「立即运行」。运行时按幂等键更新已有行，避免重复入库；
                        首次接入建议先「预览」确认字段映射，再启用周期调度。
                    </P>
                    <HelpFigure id="datasource-sync" />
                </>
            ),
        },
        {
            key: 'incremental',
            label: '大规模同步与增量',
            body: (
                <P>
                    全市场级别的任务（如数千只股票的日线）通过三项声明接入：标的动态来源（从清单表按前缀取值，新标的自动纳入）、
                    按标的回补水位的增量游标（每轮只补缺口，补满自动跳过）、并发与全局限速（防止打爆对方接口）。
                    历史回补是长任务，建议用命令行 `cndb sync tick` 驱动，中断后重跑会从水位断点继续，不会重复已补数据。
                </P>
            ),
        },
        {
            key: 'maintenance',
            label: '大表与库体积维护',
            body: (
                <P>
                    千万行级目标表会在首次同步时按幂等键自动建复合索引，写入与去重性能不受影响。
                    库体积随数据自然增长（十年日线约数百 MB）：SQLite 默认 WAL 模式下删除行不即时回收空间，可在低峰期执行 VACUUM 压实；
                    每轮数据源同步结束（成功 / 部分失败 / 失败）会自动执行一次 WAL checkpoint，WAL 文件随之回落；
                    异常增长时检查是否有长事务未提交；
                    系统备份按整库打包，建议错开大表回补与备份的时间窗。
                </P>
            ),
        },
    ],
}

const admin: HelpTopic = {
    key: 'admin',
    label: '管理台',
    intro: <P>管理台是跨工作区的实例级配置：账号、事件、空间、备份、恢复与运行信息，仅管理员可见。</P>,
    subsections: [
        {
            key: 'users',
            label: '用户管理',
            body: (
                <P>
                    查看账号资料、角色与启停状态；停用后立即无法登录，已登录会话在下一次请求时失效。
                    所有变更写入操作日志，可在事件流里追溯。
                </P>
            ),
        },
        {
            key: 'storage',
            label: '空间分配',
            body: (
                <P>
                    按工作区设置存储上限（默认 100MB）并查看已用空间与使用率。统计来自后台定期同步的快照，
                    进入页面即展示已有结果，不阻塞等待实时统计；上传预判与工作区详情读同一份快照。
                </P>
            ),
        },
        {
            key: 'events',
            label: '事件流',
            body: (
                <P>
                    跨插件统一的事件视图，可按动作与关键词检索，用于追溯「谁在什么时候改了什么」。
                    排查页面异常时，可先按时间与动作定位一次请求。
                </P>
            ),
        },
        {
            key: 'backup',
            label: '系统备份',
            body: (
                <P>
                    把整库打包为 .tar.gz（含 manifest 元信息与附件目录）。备份模式可选自动 / 完整（打包数据库文件，最快）/
                    兼容（逐表导出，适用面更广）。备份包可下载归档，建议升级前与大批量导入前各做一次。
                </P>
            ),
        },
        {
            key: 'restore',
            label: '系统恢复',
            body: (
                <Note kind="warn">
                    恢复会校验备份包后覆盖式还原，操作不可撤销，且会覆盖当前全部数据。恢复前先做一次当前状态的备份；
                    备份包版本与当前应用不兼容时会被拒绝，不会半途写入。
                </Note>
            ),
        },
        {
            key: 'info',
            label: '系统信息',
            body: <P>展示应用名称与版本、数据库类型与路径、数据 / 附件目录、认证开关与时区，反馈问题时请一并提供这些信息。</P>,
        },
    ],
}

const storage: HelpTopic = {
    key: 'storage',
    label: '存储、备份与部署',
    intro: <P>实例级配置：数据落在哪、占多少空间、怎么备份恢复、离线环境怎么装与升级。</P>,
    subsections: [
        {
            key: 'where',
            label: '数据落点',
            body: (
                <P>
                    cndb 是自托管应用，数据存储在服务器本地的 SQLite 数据库中；打包安装版存放在系统用户数据目录
                    （如 Windows 的 %APPDATA%\cndb）。附件与帮助图示快照写在数据目录下的子目录，可随实例迁移。
                </P>
            ),
        },
        {
            key: 'space',
            label: '空间与配额',
            body: (
                <P>
                    配额按工作区计算，含数据行、文档正文、附件与上传的资产；管理员在
                    <HelpLink section="configuration" topic="admin" anchor="storage"> 管理台 · 空间分配 </HelpLink>
                    中调整上限。接近上限时上传会被拒绝，删除回收站内容后才释放。
                </P>
            ),
        },
        {
            key: 'backup',
            label: '备份与恢复',
            body: (
                <P>
                    备份 / 恢复入口都在管理台，口径见
                    <HelpLink section="configuration" topic="admin" anchor="backup"> 管理台 · 系统备份 </HelpLink>
                    与 <HelpLink section="configuration" topic="admin" anchor="restore"> 系统恢复 </HelpLink>。
                    迁移实例时：备份 → 部署新实例 → 恢复，比直接拷贝数据库文件更安全（含附件与 schema 版本校验）。
                </P>
            ),
        },
        {
            key: 'offline',
            label: '离线部署与升级',
            body: (
                <Bullets
                    items={[
                        '离线环境通过导出镜像与部署脚本安装，不依赖外网拉包。',
                        '升级前先做一次系统备份，避免迁移失败无法回退。',
                        '升级会执行数据库迁移；迁移失败时保留原库，按部署文档回滚镜像即可。',
                    ]}
                />
            ),
        },
        {
            key: 'env',
            label: '关键环境变量',
            body: (
                <Bullets
                    items={[
                        '认证开关：关闭时为开放访问，仅适合内网试用环境。',
                        '数据库与数据目录、附件目录：迁移实例时需一并迁移。',
                        '帮助图示刷新：可开关后台定期重建并调整周期。',
                        '后台统计刷新：控制空间分配快照的同步周期。',
                    ]}
                />
            ),
        },
    ],
}

export const configurationTopics: HelpTopic[] = [workspace, personal, datasource, admin, storage]

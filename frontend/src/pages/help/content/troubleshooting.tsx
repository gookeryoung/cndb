/** 帮助文档 · 问题排查（ADR 0035）.
 *
 * 三个主题：常见问题（按主题分组的短问答）/ 使用与故障排查（症状 → 原因 → 处理）/
 * 诊断与反馈（提交问题前要准备什么）。新增排障条目按「一个症状一个 L4」落位。
 */

import type { HelpTopic } from '../helpNav'
import { Bullets, HelpLink, Note, P, Steps } from './primitives'

const faq: HelpTopic = {
    key: 'faq',
    label: '常见问题',
    intro: <P>高频短问答，按主题分组；每条只回答一个问题，需要完整步骤时点进对应主题。</P>,
    subsections: [
        {
            key: 'data',
            label: '数据与视图',
            items: [
                {
                    key: 'filter-saved',
                    label: '筛选和排序会保存吗？',
                    body: <P>会。筛选 / 排序规则保存在当前视图中，每个视图独立；通过「表设置 → 视图」可编辑视图的规则。</P>,
                },
                {
                    key: 'reorder',
                    label: '数据表的显示顺序怎么调整？',
                    body: (
                        <P>
                            在「数据表」页面按住每行 / 每张卡片左侧的拖拽手柄上下拖动，松手即保存（需要编辑者及以上角色）；
                            窄屏卡片长按手柄拖动。筛选状态下只能拖动当前可见的表，被筛掉的表保持原位置。
                        </P>
                    ),
                },
                {
                    key: 'restore-row',
                    label: '删除的行还能找回吗？',
                    body: (
                        <P>
                            删除行不会立即从数据库物理移除：数据仍然保留，只是默认不再显示。
                            如需恢复请联系工作区管理员通过接口恢复，删除前请谨慎确认。
                        </P>
                    ),
                },
                {
                    key: 'two-views',
                    label: '同一张表能同时有两个筛选吗？',
                    body: <P>能。新建多个视图，各自保存自己的筛选与排序，视图栏一点即切换，不需要复制数据表。</P>,
                },
            ],
        },
        {
            key: 'collab',
            label: '权限与协作',
            items: [
                {
                    key: 'share-data',
                    label: '如何让别人查看数据？',
                    body: (
                        <P>
                            把对方加入工作区并授予数据表的查看权限即可（工作区 → 成员 → 邀请）。
                            对方登录后只能看到自己被授权范围内的数据；如需收集他人反馈，可让其登录后在问题清单中提交。
                        </P>
                    ),
                },
                {
                    key: 'gray-button',
                    label: '为什么有些按钮是灰色的？',
                    body: (
                        <P>
                            内容区顶部的「数据表」「文档」「工作区设置」分页导航需要先在左上角选择工作区；
                            部分操作需要更高权限（如删除工作区仅所有者可用）。将鼠标悬停在按钮上可查看说明。
                        </P>
                    ),
                },
                {
                    key: 'viewer-edit',
                    label: '查看者能直接改数据吗？',
                    body: (
                        <P>
                            不能。查看者的保存会转成修改申请，由所有者 / 编辑者审批后生效；
                            工作区关闭「编辑权限」时，编辑者的修改也走同一路径。
                        </P>
                    ),
                },
            ],
        },
        {
            key: 'document',
            label: '文档与分享',
            items: [
                {
                    key: 'draft-invisible',
                    label: '为什么别人看不到我的文档？',
                    body: <P>草稿只有创建者本人与工作区所有者可见；需要成员都看到时把状态改为「已发布」。</P>,
                },
                {
                    key: 'share-link',
                    label: '分享链接能收回吗？',
                    body: <P>能。文档分享弹窗里撤销后链接立刻失效；撤销只影响该链接，不改文档可见性。</P>,
                },
                {
                    key: 'anchor-dead',
                    label: '文档里的目录跳转没反应？',
                    body: <P>锚点按标题文本匹配，标题改过之后旧链接会失效；重新从目录点一次即可拿到新锚点。</P>,
                },
            ],
        },
        {
            key: 'instance',
            label: '实例与备份',
            items: [
                {
                    key: 'where-data',
                    label: '数据存在哪里？',
                    body: (
                        <P>
                            cndb 是自托管应用，数据存储在服务器本地的 SQLite 数据库中；
                            打包安装版存放在系统用户数据目录（如 Windows 的 %APPDATA%\cndb）。
                        </P>
                    ),
                },
                {
                    key: 'quota',
                    label: '上传提示空间不足怎么办？',
                    body: (
                        <P>
                            工作区配额用尽：先清空回收站与无用附件，或联系管理员在「管理台 → 空间分配」提高上限。
                            配额包含数据行、文档与附件。
                        </P>
                    ),
                },
            ],
        },
    ],
}

const guide: HelpTopic = {
    key: 'guide',
    label: '使用与故障排查',
    intro: <P>按症状定位：每一条给出「先查什么 → 常见原因 → 怎么处理」，仍无法解决时按诊断与反馈收集信息。</P>,
    subsections: [
        {
            key: 'login',
            label: '登录与账号',
            items: [
                {
                    key: 'expired',
                    label: '提示登录已过期',
                    body: <P>重新登录即可；若频繁出现，检查浏览器是否禁用本地存储或系统时间是否准确。</P>,
                },
                {
                    key: 'disabled',
                    label: '账号被停用',
                    body: <P>停用后无法登录，需要管理员在「管理台 → 用户管理」重新启用；停用不会删除该账号创建的数据。</P>,
                },
            ],
        },
        {
            key: 'permission',
            label: '权限与可见性',
            items: [
                {
                    key: 'missing-table',
                    label: '看不到某张表 / 按钮无权限',
                    body: (
                        <P>
                            确认当前工作区是否选对；查看自己在工作区的角色，以及该表「表设置 → 权限」是否做了显式限制。
                            查看者编辑会转为修改申请，需要所有者 / 编辑者审批后生效。
                        </P>
                    ),
                },
                {
                    key: 'missing-view',
                    label: '别人看不到我建的视图',
                    body: (
                        <P>
                            新建视图默认「仅自己可见」，在视图权限里改成「继承表权限」或「指定成员可见」后其他人才看得到。
                            口径见 <HelpLink section="tutorials" topic="roles" anchor="view"> 权限与角色 · 视图可见性 </HelpLink>。
                        </P>
                    ),
                },
                {
                    key: 'row-hidden',
                    label: '行数比同事少',
                    body: <P>行级权限按主体合成读范围：同一张表不同角色看到的行数可以不同；导出与统计沿用同一范围。</P>,
                },
            ],
        },
        {
            key: 'import',
            label: '导入与导出',
            items: [
                {
                    key: 'import-error',
                    label: '导入文件失败或出现大量错误行',
                    body: (
                        <P>
                            先确认文件编码为 UTF-8（CSV），并检查首行表头是否被说明行占据；导入预览页会自动识别表头行，
                            低置信度时会提示人工确认。错误行明细可在导入报告页查看。
                        </P>
                    ),
                },
                {
                    key: 'date-as-text',
                    label: '导入后日期变成文本',
                    body: <P>预览页里该列被推断成文本：手动改成日期类型再导入，或用统一格式（如 2024-01-01）重导。</P>,
                },
                {
                    key: 'export-missing-row',
                    label: '导出的行比页面少',
                    body: <P>导出遵循当前视图筛选与行级权限，且不含已删除行；需要全量时切到「全部」视图再导出。</P>,
                },
            ],
        },
        {
            key: 'document',
            label: '文档',
            items: [
                {
                    key: 'save-blocked',
                    label: '保存文档却生成了修改申请',
                    body: <P>当前角色无直接写权限，或工作区关闭了「编辑权限」；由所有者 / 编辑者审批后内容才会并入正文。</P>,
                },
                {
                    key: 'import-lost-image',
                    label: '导入文档库后图片丢失',
                    body: <P>相对链接的图片需要一并导入为资产：导入时勾选包含附件，并保持原目录结构。</P>,
                },
            ],
        },
        {
            key: 'sync',
            label: '数据源同步',
            items: [
                {
                    key: 'no-data',
                    label: '同步没有产出数据',
                    body: (
                        <P>
                            依次检查：任务是否启用、cron 是否正确、凭证会话中的密钥是否有效、目标表字段映射是否与响应一致。
                            大模型类任务还需确认个人「大模型」配置已完成。
                        </P>
                    ),
                },
                {
                    key: 'throttled',
                    label: '运行记录报「目标站可能正在限流」',
                    body: <P>对方按出口 IP 限流：降低并发、提高请求间隔，或错开任务时间；连续重试会延长封禁窗口。</P>,
                },
                {
                    key: 'backfill-stuck',
                    label: '历史回补看着不动',
                    body: <P>回补按标的水位逐轮前推，每轮只补一个区间；在任务详情看水位日期是否在变小，未变则看是否被限流中断。</P>,
                },
            ],
        },
        {
            key: 'llm',
            label: '大模型调用',
            items: [
                {
                    key: 'not-configured',
                    label: '提示先完成大模型配置',
                    body: <P>大模型连接是个人级的：在「个人设置 → 大模型」填 base_url、模型与 API Key，先测试连通再运行任务。</P>,
                },
                {
                    key: 'truncated',
                    label: '模型输出被截断 / JSON 不合法',
                    body: <P>提高 max_tokens 或精简提示词的输出要求；截断与普通语法错误在运行记录里给出的提示不同，按提示调参。</P>,
                },
            ],
        },
        {
            key: 'backup',
            label: '备份与恢复',
            items: [
                {
                    key: 'restore-refused',
                    label: '恢复被拒绝',
                    body: <P>备份包版本与当前应用不兼容，或包校验失败；用同版本实例恢复，或先升级应用再恢复。</P>,
                },
                {
                    key: 'backup-slow',
                    label: '备份很慢 / 体积很大',
                    body: <P>备份按整库打包，附件与大表都会计入体积；错开大表回补与备份时间窗，必要时清理回收站与无用附件。</P>,
                },
            ],
        },
        {
            key: 'ui',
            label: '页面与兼容性',
            items: [
                {
                    key: 'broken-page',
                    label: '页面异常或数据可疑',
                    body: (
                        <P>
                            先刷新页面；仍异常时在工作区的问题清单中提交（标题 + 描述 + 类别），
                            或在管理台事件流中按时间与动作追溯一次请求。
                        </P>
                    ),
                },
                {
                    key: 'old-browser',
                    label: '老内核浏览器显示错乱',
                    body: <P>生产构建按 Chrome 81 兼容基线产出；若仍错乱，记录浏览器版本与页面地址一并反馈。</P>,
                },
            ],
        },
    ],
}

const feedback: HelpTopic = {
    key: 'feedback',
    label: '诊断与反馈',
    intro: <P>提交问题前花一分钟收集信息，能显著缩短定位时间；本页说明需要准备什么、去哪里提交。</P>,
    subsections: [
        {
            key: 'collect',
            label: '先收集信息',
            body: (
                <Steps
                    items={[
                        '复现路径：从哪个页面、点了什么、期望结果与实际结果。',
                        '环境：浏览器与版本、是否移动端、账号角色。',
                        '时间点：大致发生时刻（便于在事件流里定位）。',
                        '版本：管理台「系统信息」里的应用版本与数据结构版本。',
                    ]}
                />
            ),
        },
        {
            key: 'trace',
            label: '事件流追溯',
            body: (
                <P>
                    管理员可在「管理台 → 事件流」按时间与动作检索一次请求，确认是权限、数据还是接口问题；
                    追溯结论可以直接贴进问题描述，避免来回确认。
                </P>
            ),
        },
        {
            key: 'issue',
            label: '问题清单提交',
            body: (
                <P>
                    工作区页签「问题清单」提交（标题 + 描述 + 类别），可分派给成员并跟踪状态；
                    与具体数据行相关时，附上表名与行标识。
                </P>
            ),
        },
        {
            key: 'scope',
            label: '哪些内容不要贴',
            body: (
                <Note kind="warn">
                    不要粘贴 API Key、访问令牌或整库备份；密钥类信息一旦出现在问题描述里，请立即在个人设置中重置。
                </Note>
            ),
        },
        {
            key: 'self-check',
            label: '提交前的自检',
            body: (
                <Bullets
                    items={[
                        '刷新后仍能复现？',
                        '换一个账号 / 角色是否同样出现（区分权限问题与缺陷）？',
                        '是否刚升级或刚导入大量数据（先看对应排查条目）？',
                    ]}
                />
            ),
        },
    ],
}

export const troubleshootingTopics: HelpTopic[] = [faq, guide, feedback]

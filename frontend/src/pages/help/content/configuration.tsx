/** 帮助文档 · 系统配置内容（ADR 0029 P0）.
 *
 * 覆盖工作区设置、个人设置与大模型、数据源同步、存储与备份四类配置。
 */

import { Typography } from 'antd'
import type { HelpTopic } from '../helpNav'

const { Text } = Typography

function WorkspaceSettingsContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>工作区名称与类型</Text>
                <br />
                <Text type="secondary">
                    在「工作区设置 → 基本设置」修改名称与描述。工作区类型决定开放的功能：数据 + 文档（默认）、仅数据表与数据分析、仅文档；修改后顶部页签与侧栏随之调整。
                </Text>
            </div>
            <div>
                <Text strong>公开性</Text>
                <br />
                <Text type="secondary">
                    公开：登录用户均可查看；成员可见：仅工作区成员可访问；私有：仅所有者与管理员可见。修改后立即生效。
                </Text>
            </div>
            <div>
                <Text strong>成员与角色</Text>
                <br />
                <Text type="secondary">
                    在「成员管理」邀请成员并分配所有者 / 编辑者 / 查看者。单张表还可以在「表设置 → 权限」中做更细的显式授权。
                </Text>
            </div>
            <div>
                <Text strong>允许编辑</Text>
                <br />
                <Text type="secondary">
                    关闭「允许编辑」后，编辑者的保存也会转为修改申请，由所有者 / 编辑者审批后生效；适合需要留痕或集中审核的阶段。
                </Text>
            </div>
        </div>
    )
}

function PersonalSettingsContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>个人设置</Text>
                <br />
                <Text type="secondary">点击右上角头像 →「个人设置」，可修改昵称、邮箱与密码等账号资料。</Text>
            </div>
            <div>
                <Text strong>大模型连接</Text>
                <br />
                <Text type="secondary">
                    个人设置 →「大模型」页签配置 base_url、模型与 API Key；配置为个人级、任务之间共用，密钥加密保存且不回显。未配置时，依赖大模型的任务在运行时会提示先完成配置。
                </Text>
            </div>
            <div>
                <Text strong>调用记录</Text>
                <br />
                <Text type="secondary">
                    同一页签可查看本人的调用记录（动作、模型、耗时、token 用量与状态）；记录不保存提示词与输出全文。
                </Text>
            </div>
        </div>
    )
}

function DatasourceSettingsContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>入口</Text>
                <br />
                <Text type="secondary">工作区页签「数据源同步」：管理同步任务、查看运行记录、配置凭证会话。</Text>
            </div>
            <div>
                <Text strong>任务配置</Text>
                <br />
                <Text type="secondary">
                    选择 Provider（http_json 声明式 HTTP + JSON，或 llm_prompt 大模型提示词）、目标表、幂等键与 cron 调度；运行时按幂等键更新已有行，避免重复入库。
                </Text>
            </div>
            <div>
                <Text strong>凭证会话</Text>
                <br />
                <Text type="secondary">
                    请求头与密钥集中存放在「凭证会话」中，任务以会话引用；密钥加密入库、只写不回显，删除会话会解绑任务。
                </Text>
            </div>
            <div>
                <Text strong>运行与排期</Text>
                <br />
                <Text type="secondary">
                    生产环境由后台调度触发；可在任务详情查看最近运行状态与错误摘要。首次接入建议先「预览」确认字段映射，再启用周期调度。
                </Text>
            </div>
        </div>
    )
}

function StorageBackupContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>数据存在哪里</Text>
                <br />
                <Text type="secondary">
                    cndb 是自托管应用，数据存储在服务器本地的 SQLite 数据库中；打包安装版存放在系统用户数据目录（如 Windows 的 %APPDATA%\cndb）。
                </Text>
            </div>
            <div>
                <Text strong>空间分配</Text>
                <br />
                <Text type="secondary">管理员可在「管理台 → 空间分配」按工作区设置存储上限并查看使用率；工作区详情与上传预判读取后台统计快照。</Text>
            </div>
            <div>
                <Text strong>系统备份与恢复</Text>
                <br />
                <Text type="secondary">
                    管理员在「管理台 → 系统备份」把整库打包为 .tar.gz（含 manifest 与附件目录）；「系统恢复」会校验备份包后覆盖式还原，操作不可撤销。
                </Text>
            </div>
            <div>
                <Text strong>离线部署</Text>
                <br />
                <Text type="secondary">离线环境通过导出镜像与部署脚本安装；升级前先做一次系统备份，避免迁移失败无法回退。</Text>
            </div>
        </div>
    )
}

export const configurationTopics: HelpTopic[] = [
    { key: 'workspace', label: '工作区设置', content: <WorkspaceSettingsContent /> },
    { key: 'personal', label: '个人设置与大模型', content: <PersonalSettingsContent /> },
    { key: 'datasource', label: '数据源同步', content: <DatasourceSettingsContent /> },
    { key: 'storage', label: '存储、备份与部署', content: <StorageBackupContent /> },
]

/** 帮助文档 · 问题排查内容（ADR 0029 P0）.
 *
 * 「常见问题」承接原 FAQ；「使用与故障排查」覆盖导入、权限、登录与数据源同步。
 */

import { Typography } from 'antd'
import type { HelpTopic } from '../helpNav'

const { Text } = Typography

function FaqContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
                <Text strong>筛选和排序会保存吗？</Text>
                <br />
                <Text type="secondary">会。筛选/排序规则保存在当前视图中，每个视图独立；通过「表设置 → 视图」可编辑视图的规则。</Text>
            </div>
            <div>
                <Text strong>数据表的显示顺序怎么调整？</Text>
                <br />
                <Text type="secondary">
                    在「数据表」页面按住每行/每张卡片左侧的拖拽手柄上下拖动，松手即保存（需要编辑者及以上角色）；窄屏卡片长按手柄拖动。筛选状态下只能拖动当前可见的表，被筛掉的表保持原位置。
                </Text>
            </div>
            <div>
                <Text strong>删除的行还能找回吗？</Text>
                <br />
                <Text type="secondary">
                    删除行不会立即从数据库物理移除：数据仍然保留，只是默认不再显示。如需恢复请联系工作区管理员通过接口恢复，删除前请谨慎确认。
                </Text>
            </div>
            <div>
                <Text strong>如何让别人查看数据？</Text>
                <br />
                <Text type="secondary">
                    把对方加入工作区并授予数据表的查看权限即可（工作区 → 成员 → 邀请）。对方登录后只能看到自己被授权范围内的数据；如需收集他人反馈，可让其登录后在问题清单中提交。
                </Text>
            </div>
            <div>
                <Text strong>为什么有些按钮是灰色的？</Text>
                <br />
                <Text type="secondary">
                    内容区顶部的「数据表」「文档」「工作区设置」分页导航需要先在左上角选择工作区；部分操作需要更高权限（如删除工作区仅所有者可用）。将鼠标悬停在按钮上可查看说明。
                </Text>
            </div>
            <div>
                <Text strong>数据存在哪里？</Text>
                <br />
                <Text type="secondary">
                    cndb 是自托管应用，数据存储在服务器本地的 SQLite 数据库中；打包安装版存放在系统用户数据目录（如 Windows 的 %APPDATA%\cndb）。
                </Text>
            </div>
        </div>
    )
}

function TroubleshootContent() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
                <Text strong>导入文件失败或出现大量错误行</Text>
                <br />
                <Text type="secondary">
                    先确认文件编码为 UTF-8（CSV），并检查首行表头是否被说明行占据；导入预览页会自动识别表头行，低置信度时会提示人工确认。错误行明细可在导入报告页查看。
                </Text>
            </div>
            <div>
                <Text strong>看不到某张表 / 按钮无权限</Text>
                <br />
                <Text type="secondary">
                    确认当前工作区是否选对；查看自己在工作区的角色，以及该表「表设置 → 权限」是否做了显式限制。查看者编辑会转为修改申请，需要所有者 / 编辑者审批后生效。
                </Text>
            </div>
            <div>
                <Text strong>提示登录已过期</Text>
                <br />
                <Text type="secondary">重新登录即可；若频繁出现，检查浏览器是否禁用本地存储或系统时间是否准确。</Text>
            </div>
            <div>
                <Text strong>数据源同步没有产出数据</Text>
                <br />
                <Text type="secondary">
                    依次检查：任务是否启用、cron 是否正确、凭证会话中的密钥是否有效、目标表字段映射是否与响应一致。大模型类任务还需确认个人「大模型」配置已完成。
                </Text>
            </div>
            <div>
                <Text strong>页面异常或数据可疑</Text>
                <br />
                <Text type="secondary">
                    先刷新页面；仍异常时在工作区的问题清单中提交（标题 + 描述 + 类别），或在管理台事件流中按时间与动作追溯一次请求。
                </Text>
            </div>
        </div>
    )
}

export const troubleshootingTopics: HelpTopic[] = [
    { key: 'faq', label: '常见问题', content: <FaqContent /> },
    { key: 'guide', label: '使用与故障排查', content: <TroubleshootContent /> },
]

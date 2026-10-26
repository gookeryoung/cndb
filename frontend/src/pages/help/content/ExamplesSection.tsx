/** 帮助文档 · 典型示例（ADR 0029 P1 / ADR 0036）.
 *
 * 场景内容完全由后端 `/api/v1/help/examples` 清单驱动：表格、亮点、步骤与
 * CSV 下载都来自接口，前端不维护第二份示例清单。
 *
 * 四个 L3 小节各自只渲染自己那一块，标题与锚点由 `HelpDoc` 统一生成 ——
 * 因此「页内目录里的标题」与正文标题必然一致。
 */

import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { Alert, App, Button, Skeleton, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { helpApi, type HelpExampleTable } from '@/api/help'
import HelpFigure from '../HelpFigure'

const { Paragraph, Text } = Typography

/** 触发浏览器下载 Blob（auth 头无法随 <a href> 携带，故先取 blob 再下载） */
function triggerDownload(filename: string, blob: Blob) {
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    // 延迟释放，避免部分浏览器下载中断
    setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 清单查询：四个小节共用同一 queryKey，TanStack Query 只发一次请求。 */
function useExample(scenarioKey: string) {
    const query = useQuery({
        queryKey: ['help', 'examples'],
        queryFn: helpApi.listExamples,
        staleTime: 5 * 60 * 1000,
    })
    const example = query.data?.items.find((item) => item.key === scenarioKey)
    return { query, example }
}

function ExampleError({ onRetry, message }: { onRetry: () => void; message: string }) {
    return (
        <Alert
            type="error"
            showIcon
            message="示例清单加载失败"
            description={message}
            action={
                <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>
                    重试
                </Button>
            }
            data-testid="help-examples-error"
        />
    )
}

/** L3-1 场景说明：一句话说清这套示例练什么。 */
export function ExampleSummary({ scenarioKey }: { scenarioKey: string }) {
    const { query, example } = useExample(scenarioKey)

    if (query.isPending) {
        return <Skeleton active title={false} paragraph={{ rows: 2 }} data-testid="help-examples-loading" />
    }
    if (query.isError) {
        return <ExampleError message={query.error.message} onRetry={() => void query.refetch()} />
    }
    if (!example) {
        return <Alert type="warning" showIcon message="示例清单中未找到该场景" data-testid="help-examples-missing" />
    }
    return (
        <div data-testid="help-examples-section">
            <Paragraph type="secondary" style={{ margin: 0 }}>
                {example.summary}
            </Paragraph>
        </div>
    )
}

/** L3-2 数据表清单与 CSV 下载。 */
export function ExampleTables({ scenarioKey }: { scenarioKey: string }) {
    const { message } = App.useApp()
    const [downloading, setDownloading] = useState<string | null>(null)
    const { example } = useExample(scenarioKey)

    if (!example) return null

    const handleDownload = async (table: HelpExampleTable) => {
        setDownloading(table.file)
        try {
            const blob = await helpApi.downloadExampleFile(scenarioKey, table.file)
            triggerDownload(table.file, blob)
        } catch (err) {
            message.error(err instanceof Error ? err.message : '下载失败，请稍后重试')
        } finally {
            setDownloading(null)
        }
    }

    const columns: ColumnsType<HelpExampleTable> = [
        {
            title: '数据表',
            dataIndex: 'title',
            key: 'title',
            render: (_: unknown, table) => (
                <div>
                    <Text strong>{table.title}</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                        {table.file}
                    </Text>
                </div>
            ),
        },
        {
            title: '说明',
            dataIndex: 'description',
            key: 'description',
            render: (description: string) => <Text type="secondary">{description}</Text>,
        },
        {
            title: '约行数',
            dataIndex: 'rows',
            key: 'rows',
            width: 88,
            render: (rows: number) => <Text type="secondary">{rows}</Text>,
        },
        {
            title: '操作',
            key: 'action',
            width: 120,
            render: (_: unknown, table) => (
                <Button
                    size="small"
                    icon={<DownloadOutlined />}
                    loading={downloading === table.file}
                    onClick={() => void handleDownload(table)}
                    data-testid={`help-example-download-${table.file}`}
                >
                    下载 CSV
                </Button>
            ),
        },
    ]

    return (
        <Table<HelpExampleTable>
            rowKey="file"
            size="small"
            pagination={false}
            columns={columns}
            dataSource={example.tables}
            scroll={{ x: 640 }}
        />
    )
}

/** L3-3 数据预览：每张示例表一张图，取自真实 CSV。 */
export function ExamplePreviews({ scenarioKey }: { scenarioKey: string }) {
    const { example } = useExample(scenarioKey)

    if (!example) return null

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
                预览取自示例 CSV 的真实表头与首批行，文件更新后图示自动重建。
            </Paragraph>
            {example.tables.map((table, index) => (
                <HelpFigure
                    key={table.file}
                    id={`example-${scenarioKey}-table-${index + 1}`}
                    caption={`${table.title} · ${table.description}`}
                />
            ))}
        </div>
    )
}

/** L3-4 可以怎么练 + 导入步骤。 */
export function ExamplePractice({ scenarioKey }: { scenarioKey: string }) {
    const { example } = useExample(scenarioKey)

    if (!example) return null

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                {example.highlights.map((item) => (
                    <li key={item}>
                        <Text type="secondary">{item}</Text>
                    </li>
                ))}
            </ul>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {example.steps.map((step, index) => (
                    <Tag key={step}>{`${index + 1}. ${step}`}</Tag>
                ))}
            </div>
        </div>
    )
}

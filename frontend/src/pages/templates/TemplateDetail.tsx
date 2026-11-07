/** 模板只读结构化详情：模板中心右栏与编辑器「结构预览」共用（ADR 0121）.
 */

import { useMemo } from 'react'
import { Collapse, Empty, List, Space, Table, Tabs, Tag, Timeline, Typography } from 'antd'
import {
  ApartmentOutlined, CheckCircleOutlined, ClockCircleOutlined, FileTextOutlined, TableOutlined,
} from '@ant-design/icons'
import type { TemplateSpecForm, WorkspaceTemplate } from '@/api'

const { Text, Paragraph } = Typography

function FormDetail({ form }: { form: TemplateSpecForm }) {
  return (
    <div>
      <Paragraph type="secondary" style={{ marginBottom: 8 }}>{form.description || '—'}</Paragraph>
      <Table
        size="small"
        rowKey="name"
        pagination={false}
        dataSource={form.fields}
        columns={[
          { title: '字段', dataIndex: 'name' },
          { title: '类型', dataIndex: 'type', width: 120 },
          {
            title: '必填',
            dataIndex: 'required',
            width: 70,
            render: (v: boolean) => (v ? <Tag color="red">必填</Tag> : <Text type="secondary">否</Text>),
          },
        ]}
      />
    </div>
  )
}

export default function TemplateDetail({ template }: { template: WorkspaceTemplate }) {
  const spec = template.spec
  const stageNames = useMemo(() => {
    const forms = new Map(spec.forms.map(f => [f.key, f.name]))
    const docs = new Map(spec.documents.map(d => [d.key, d.title]))
    return { forms, docs }
  }, [spec])

  const stageItems = spec.stages.map(stage => ({
    color: stage.order === 1 ? 'blue' : 'gray',
    dot: stage.order === 1 ? <CheckCircleOutlined /> : <ClockCircleOutlined />,
    children: (
      <div data-testid={`template-stage-${stage.key}`}>
        <Space>
          <Text strong>阶段 {stage.order} · {stage.name}</Text>
          <Tag>{stage.forms.length} 表单</Tag>
          <Tag>{stage.documents.length} 文档规则</Tag>
        </Space>
        <div style={{ color: 'var(--cn-text-secondary)', fontSize: 'var(--cn-text-sm)', marginTop: 2 }}>{stage.description || '—'}</div>
        <div style={{ marginTop: 4, fontSize: 'var(--cn-text-sm)' }}>
          表单：{stage.forms.map(k => stageNames.forms.get(k) ?? k).join('、') || '—'}
        </div>
        <div style={{ fontSize: 'var(--cn-text-sm)' }}>
          文档：{stage.documents.map(k => stageNames.docs.get(k) ?? k).join('、') || '—'}
        </div>
      </div>
    ),
  }))

  return (
    <Tabs
      size="small"
      items={[
        {
          key: 'stages',
          label: <span><ApartmentOutlined /> 流程阶段</span>,
          children: spec.stages.length ? <Timeline className="cn-tpl-detail-timeline" items={stageItems} /> : <Empty />,
        },
        {
          key: 'forms',
          label: <span><TableOutlined /> 表单（{spec.forms.length}）</span>,
          children: spec.forms.length ? (
            <Collapse
              size="small"
              items={spec.forms.map(form => ({
                key: form.key,
                label: <span>{form.name} <Text type="secondary">· {form.fields.length} 个字段</Text></span>,
                children: <FormDetail form={form} />,
              }))}
            />
          ) : <Empty />,
        },
        {
          key: 'flows',
          label: <span><ApartmentOutlined /> 端到端流程（{spec.flows?.length ?? 0}）</span>,
          children: (spec.flows?.length ?? 0) ? (
            <Collapse
              size="small"
              items={(spec.flows ?? []).map(flow => ({
                key: flow.key,
                label: <span>{flow.name} <Text type="secondary">· {flow.steps.length} 步</Text></span>,
                children: (
                  <div>
                    <Paragraph type="secondary" style={{ marginBottom: 8 }}>{flow.description || '—'}</Paragraph>
                    <Timeline
                      className="cn-tpl-detail-timeline"
                      items={flow.steps.map((step, index) => ({
                        color: step.form ? 'blue' : 'gray',
                        children: (
                          <div>
                            <Text strong>步骤 {index + 1} · {step.name}</Text>
                            <div style={{ fontSize: 'var(--cn-text-xs)', color: 'var(--cn-text-secondary)' }}>
                              {step.form ? `表单：${spec.forms.find(f => f.key === step.form)?.name ?? step.form}` : '审批 / 确认节点'}
                              {step.documents?.length ? ` · 文档：${step.documents.join('、')}` : ''}
                            </div>
                            {step.description && <div style={{ fontSize: 'var(--cn-text-xs)' }}>{step.description}</div>}
                          </div>
                        ),
                      }))}
                    />
                  </div>
                ),
              }))}
            />
          ) : <Empty description="未配置端到端流程（旧模板由阶段自动派生）" />,
        },
        {
          key: 'documents',
          label: <span><FileTextOutlined /> 文档规则（{spec.documents.length}）</span>,
          children: spec.documents.length ? (
            <List
              size="small"
              dataSource={spec.documents}
              renderItem={doc => (
                <List.Item>
                  <List.Item.Meta
                    title={<Space>{doc.title}{doc.required !== false ? <Tag color="red">必需</Tag> : <Tag>可选</Tag>}</Space>}
                    description={doc.naming || '未设置命名规则'}
                  />
                </List.Item>
              )}
            />
          ) : <Empty />,
        },
      ]}
    />
  )
}

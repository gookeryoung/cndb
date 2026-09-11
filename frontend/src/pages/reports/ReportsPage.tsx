import React from 'react'
import { Typography, Empty, Button, Modal, Form, Input, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

export default function ReportsPage() {
  const [createOpen, setCreateOpen] = React.useState(false)
  const [form] = Form.useForm()

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>报表</Title>
          <Text type="secondary">将多张表的数据汇总为报表（简化版占位）</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建报表</Button>
      </div>

      <Empty description="报表功能即将上线，敬请期待" style={{ padding: 64 }} />

      <Modal title="新建报表" open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={() => {
          message.info('报表创建（占位）'); setCreateOpen(false)
        }}>
          <Form.Item name="name" label="报表名称" rules={[{ required: true }]}><Input placeholder="例如：月度销售" /></Form.Item>
          <Form.Item name="desc" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
      
    </div>
  )
}

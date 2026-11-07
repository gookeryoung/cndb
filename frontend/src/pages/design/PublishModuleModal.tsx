/** 发布为复用模块弹窗（ADR 0118 P1 / §4）
 *
 * 仅 part 可发布；首次发布生成全局唯一 `module_key`，后续发布递增版本。
 * 发布是「编译 + 依赖闭包打包」的快照动作：正文仍保存在原设计，之后修改不影响已发布版本。
 */

import { App as AntApp, Form, Input, Modal, Radio, Typography } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { designsApi } from '@/api'

interface Props {
  open: boolean
  wid: string
  designId: number
  defaultName: string
  defaultDescription?: string
  onClose: () => void
  onPublished?: (result: { module_key: string; version_number: number }) => void
}

interface FormValues {
  name: string
  description?: string
  visibility: 'public' | 'workspace'
  comment?: string
}

export default function PublishModuleModal({
  open, wid, designId, defaultName, defaultDescription, onClose, onPublished,
}: Props) {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm<FormValues>()

  const publish = useMutation({
    mutationFn: (values: FormValues) => designsApi.publish(wid, designId, {
      name: values.name,
      description: values.description ?? '',
      visibility: values.visibility,
      comment: values.comment ?? '',
    }),
    onSuccess: (result) => {
      message.success(`已发布 ${result.module_key} v${result.version_number}`)
      onPublished?.(result)
      onClose()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '发布失败'),
  })

  return (
    <Modal
      title="发布为复用模块"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="发布"
      confirmLoading={publish.isPending}
      destroyOnHidden
      afterOpenChange={(visible) => {
        if (visible) {
          form.setFieldsValue({
            name: defaultName,
            description: defaultDescription ?? '',
            visibility: 'workspace',
            comment: '',
          })
        }
      }}
    >
      <Typography.Paragraph type="secondary">
        发布后生成不可变版本快照，其他设计用 <Typography.Text code>use &quot;lib:模块key@版本&quot;</Typography.Text> 引用；
        后续修改需重新发布。
      </Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: defaultName,
          description: defaultDescription ?? '',
          visibility: 'workspace',
          comment: '',
        }}
        onFinish={values => publish.mutate(values)}
      >
        <Form.Item
          name="name"
          label="模块名称"
          rules={[{ required: true, message: '请输入模块名称' }, { max: 200, message: '名称不超过 200 字' }]}
        >
          <Input data-testid="publish-name" />
        </Form.Item>
        <Form.Item name="description" label="描述（可选）">
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
        <Form.Item name="visibility" label="可见范围" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="workspace">仅本工作区</Radio>
            <Radio value="public">公开（允许跨工作区引用）</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item name="comment" label="版本说明（可选）">
          <Input maxLength={500} placeholder="如：调整法兰厚度" data-testid="publish-comment" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

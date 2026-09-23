/** 新建 / 编辑字段 Modal.
 *
 * 通用属性（必填 / 唯一 / 视图中隐藏）、默认值与类型专属配置统一由
 * FieldConfigPanel 承载（三个分区卡片），本文件只保留 Modal 外壳与
 * 字段名 / 类型选择行。
 */
import { Modal, Row, Col, Form, Input, Select } from 'antd'
import type { Field, FieldType, TableSummary } from '@/api'
import { FIELD_TYPE_OPTIONS } from '@/utils/fieldTypeMeta'
import HelpTip from '@/components/HelpTip'
import { defaultConfigForType } from './typeConfigPanel'
import FieldConfigPanel from './FieldConfigPanel'

interface FieldEditorProps {
  open: boolean
  /** null 表示新建，非 null 为正在编辑的字段 */
  editTarget: Field | null
  /** 当前选中的字段类型（决定 config 编辑区与默认值控件） */
  fieldType: FieldType | undefined
  form: ReturnType<typeof Form.useForm>[0]
  wid: string
  tid: string
  tables: TableSummary[]
  submitPending: boolean
  onSubmit: () => void
  onCancel: () => void
  /** 切换字段类型时回调（父层更新 fieldType 状态） */
  onFieldTypeChange: (type: FieldType) => void
}

/** 新建 / 编辑字段的内部 Modal（Modal 与嵌入模式共用） */
export default function FieldEditor({ open, editTarget, fieldType, form, wid, tid, tables, submitPending, onSubmit, onCancel, onFieldTypeChange }: FieldEditorProps) {
  return (
    <Modal
      title={editTarget ? '编辑字段' : '新建字段'}
      open={open}
      destroyOnHidden={false}
      onCancel={onCancel}
      onOk={onSubmit}
      confirmLoading={submitPending}
      width={640}
      okText={editTarget ? '保存' : '创建'}
      cancelText="取消"
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="name" label="字段名" rules={[{ required: true, message: '请输入字段名' }]}>
              <Input placeholder="例如：姓名" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="field_type"
              label={<>类型<HelpTip title="类型决定数据的存储格式与编辑控件，选择后可在下方配置专属选项" /></>}
              rules={[{ required: true, message: '请选择类型' }]}
            >
              <Select
                showSearch
                options={FIELD_TYPE_OPTIONS.map(t => ({ label: `${t.label}（${t.category}）`, value: t.value }))}
                filterOption={(input, option) => {
                  const label = (option?.label as string) ?? ''
                  return label.toLowerCase().includes(input.toLowerCase())
                }}
                onChange={(v) => {
                  onFieldTypeChange(v)
                  // 编辑时切换类型：重置 config 为新类型的默认值（避免旧类型 config 残留）
                  if (editTarget && v !== editTarget.field_type) {
                    const defaults = defaultConfigForType(v)
                    form.setFieldValue('config', defaults)
                  }
                }}
              />
            </Form.Item>
          </Col>
        </Row>

        {/* 统一字段配置面板：基础属性 / 默认值 / 类型专属配置 三个分区卡片 */}
        <FieldConfigPanel
          fieldType={fieldType}
          form={form}
          wid={wid}
          tid={tid}
          tables={tables}
          isEdit={!!editTarget}
          editTargetId={editTarget?.id ?? null}
        />
      </Form>
    </Modal>
  )
}

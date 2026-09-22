/** 视图创建/编辑/导入 Modal 组（从 GridPage 抽出）. */

import { Modal, Upload, App as AntApp } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import type { View, ViewCreate, Field } from '@/api'
import CreateEditViewForm from './view-config/CreateEditViewForm'

interface GridViewModalsProps {
  fields: Field[]
  activeView: View | null | undefined
  createOpen: boolean
  onCloseCreate: () => void
  editOpen: boolean
  onCloseEdit: () => void
  importOpen: boolean
  onCloseImport: () => void
  onCreate: (payload: { name: string; view_type: string; view_options?: Record<string, unknown> }) => void
  onEditSave: (vid: number | string, payload: { name: string; view_type: string; view_options?: Record<string, unknown> }) => void
  onImport: (views: ViewCreate[]) => void
  importPending: boolean
  importFile: File | null
  importFileContent: string
  onImportFileChange: (file: File | null, content: string) => void
}

export default function GridViewModals({
  fields, activeView,
  createOpen, onCloseCreate,
  editOpen, onCloseEdit,
  importOpen, onCloseImport,
  onCreate, onEditSave, onImport, importPending,
  importFile, importFileContent, onImportFileChange,
}: GridViewModalsProps) {
  const { message } = AntApp.useApp()

  return (
    <>
      {/* 创建新视图 Modal */}
      <Modal
        title="创建新视图"
        open={createOpen}
        onCancel={onCloseCreate}
        footer={null}
        width={720}
        className="cevf-modal"
        destroyOnHidden
      >
        <CreateEditViewForm
          fields={fields}
          submitLabel="创建"
          onSubmit={(name, vt, opts) => {
            const payload: { name: string; view_type: string; view_options?: Record<string, unknown> } = { name, view_type: vt }
            if (opts && Object.keys(opts).length) payload.view_options = opts
            onCreate(payload)
          }}
        />
      </Modal>

      {/* 编辑视图 Modal */}
      <Modal
        title="编辑视图"
        open={editOpen}
        onCancel={onCloseEdit}
        footer={null}
        width={720}
        className="cevf-modal"
        destroyOnHidden
      >
        {activeView && (
          <CreateEditViewForm
            fields={fields}
            initialName={activeView.name}
            initialType={activeView.view_type}
            initialOptions={activeView.view_options || undefined}
            submitLabel="保存"
            onSubmit={(name, vt, opts) => {
              const payload: { name: string; view_type: string; view_options?: Record<string, unknown> } = { name, view_type: vt }
              if (opts && Object.keys(opts).length) payload.view_options = opts
              onEditSave(activeView.id, payload)
            }}
          />
        )}
      </Modal>

      {/* 导入视图 Modal */}
      <Modal
        title="导入视图"
        open={importOpen}
        onCancel={onCloseImport}
        width={560}
        onOk={() => {
          if (!importFileContent) {
            message.warning('请先选择或拖入 JSON 文件')
            return
          }
          let parsed: ViewCreate[]
          try {
            parsed = JSON.parse(importFileContent)
            if (!Array.isArray(parsed)) throw new Error('JSON 根节点必须是数组')
          } catch (e) {
            message.error('JSON 解析失败: ' + (e instanceof Error ? e.message : String(e)))
            return
          }
          onImport(parsed)
        }}
        confirmLoading={importPending}
        okText="导入"
        cancelText="取消"
        okButtonProps={{ disabled: !importFileContent }}
      >
        <Upload.Dragger
          accept=".json,application/json"
          maxCount={1}
          fileList={importFile ? [{ uid: '-1', name: importFile.name, status: 'done' }] : []}
          beforeUpload={(file: File) => {
            const reader = new FileReader()
            reader.onload = () => {
              onImportFileChange(file, String(reader.result ?? ''))
            }
            reader.onerror = () => {
              message.error('读取文件失败')
              onImportFileChange(null, '')
            }
            reader.readAsText(file, 'utf-8')
            return false
          }}
          onRemove={() => { onImportFileChange(null, ''); return true }}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
          <p className="ant-upload-hint">支持 .json 格式，内容为视图配置数组</p>
        </Upload.Dragger>
        {importFile && (
          <div style={{ marginTop: 12, fontSize: 12, color: '#1677ff', textAlign: 'center' }}>
            已选择：{importFile.name}（{(importFile.size / 1024).toFixed(1)} KB）
          </div>
        )}
      </Modal>
    </>
  )
}

/** 关于系统 Modal — 所有登录用户可查看的系统基本信息（版本/鉴权开关/时区/服务器时间）.
 *
 * 数据来自 GET /api/v1/system/about（登录即可，不含数据库路径等管理敏感字段）；
 * 管理员完整系统信息见 /admin 管理台。
 */

import { Modal, Descriptions, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { systemApi } from '@/api'

interface Props {
  open: boolean
  onClose: () => void
}

/** 关于系统弹窗 — 打开时才拉取，关闭不卸载（缓存内重复开合不闪加载态）. */
export default function AboutModal({ open, onClose }: Props) {
  const { data: info, isLoading } = useQuery({
    queryKey: ['system-about'],
    queryFn: systemApi.about,
    enabled: open,
    staleTime: 60_000,
  })

  return (
    <Modal title="关于系统" open={open} onCancel={onClose} footer={null} width={480}>
      {isLoading || !info ? (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : (
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="应用名称">{info.app_name}</Descriptions.Item>
          <Descriptions.Item label="版本">{info.app_version}</Descriptions.Item>
          <Descriptions.Item label="鉴权">{info.auth_enabled ? '已启用' : '未启用'}</Descriptions.Item>
          <Descriptions.Item label="时区">{info.timezone}</Descriptions.Item>
          <Descriptions.Item label="服务器时间">{new Date(info.server_time).toLocaleString()}</Descriptions.Item>
        </Descriptions>
      )}
    </Modal>
  )
}

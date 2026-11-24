/** 行操作失败的可重试错误条（路线图 0141 P0-3）.
 *
 * 现状：行写入失败只有一次性 `message.error`，网络抖一下就得让用户自己重做一遍
 * （且不知道重做了什么）。这里把「最近一次失败的行操作」保留下来，给一个显式的
 * 重试入口；成功后自动收起。
 */

import { Alert, Button, Space } from 'antd'
import { ReloadOutlined, CloseOutlined } from '@ant-design/icons'

export interface RetryableError {
  /** 面向用户的简短说明（来自后端 detail 或兜底文案） */
  message: string
  /** 重试动作（幂等重放同一次提交） */
  retry: () => void
}

interface Props {
  error: RetryableError | null
  onDismiss: () => void
  /** 重试后由页面重新发起请求，条本身保持可见直到成功或被关闭 */
  retrying?: boolean
}

export default function GridErrorBar({ error, onDismiss, retrying = false }: Props) {
  if (!error) return null
  return (
    <Alert
      type="error"
      showIcon
      data-testid="grid-error-bar"
      style={{ margin: '4px 12px' }}
      title={
        <Space size={8} wrap>
          <span data-testid="grid-error-bar-message">{error.message}</span>
          <Button
            size="small"
            type="link"
            icon={<ReloadOutlined />}
            loading={retrying}
            data-testid="grid-error-bar-retry"
            onClick={error.retry}
          >
            重试
          </Button>
          <Button
            size="small"
            type="link"
            icon={<CloseOutlined />}
            data-testid="grid-error-bar-dismiss"
            onClick={onDismiss}
          >
            忽略
          </Button>
        </Space>
      }
    />
  )
}

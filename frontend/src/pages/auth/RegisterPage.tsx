import { Card, Form, Input, Button, Typography, App as AntApp } from 'antd'
import { UserOutlined, MailOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import axios from 'axios'
import { useAuthStore } from '@/store'

const { Title, Text } = Typography

/** 公开注册页面 —— 已收窄为仅注册普通用户.
 *
 * 三员账号（system_admin / security_admin / audit_admin）必须由超级管理员
 * 通过 `cndb users create --role <role>` 或 admin-register API 创建，
 * 不在公开注册入口暴露角色选择。
 *
 * 错误提示分类：
 * - 400 去重冲突（用户名/邮箱已被使用）：内联展示到对应表单项；
 * - 网络异常（无响应）：提示检查网络；
 * - 其余（422 校验、500 等）：展示后端 detail 文案（拦截器已归一化进 err.message）。
 */

interface RegisterFormValues {
  username: string
  email?: string
  password: string
  nickname?: string
}

export default function RegisterPage() {
  const { message } = AntApp.useApp()
  const register = useAuthStore(s => s.register)
  const navigate = useNavigate()
  const [form] = Form.useForm<RegisterFormValues>()

  /** 注册失败分类提示：去重冲突内联到字段，其余走全局 message */
  const showRegisterError = (err: unknown) => {
    if (axios.isAxiosError<{ detail?: unknown }>(err)) {
      const detail = err.response?.data?.detail
      if (err.response?.status === 400 && typeof detail === 'string') {
        // 去重类错误内联到对应表单项，方便用户直接定位修改
        if (detail.includes('用户名')) {
          form.setFields([{ name: 'username', errors: [detail] }])
          return
        }
        if (detail.includes('邮箱')) {
          form.setFields([{ name: 'email', errors: [detail] }])
          return
        }
        message.error(detail)
        return
      }
      if (!err.response) {
        message.error('网络异常，请检查网络后重试')
        return
      }
    }
    message.error(err instanceof Error ? err.message : '注册失败，请检查输入')
  }

  const onFinish = async (values: RegisterFormValues) => {
    try {
      // 空邮箱/昵称归一化为 undefined，避免后端把空字符串当有效邮箱存储
      await register({
        ...values,
        email: values.email?.trim() || undefined,
        nickname: values.nickname?.trim() || undefined,
      })
      message.success('注册成功，欢迎加入')
      navigate('/w', { replace: true })
    } catch (err) {
      showRegisterError(err)
    }
  }

  return (
    <Card>
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ marginBottom: 4 }}>创建账号</Title>
        <Text type="secondary">加入 cndb，开始构建你的数据工作区</Text>
      </div>
      <Form<RegisterFormValues>
        form={form}
        layout="vertical"
        onFinish={onFinish}
      >
        <Form.Item
          name="username"
          label="用户名"
          rules={[{ required: true, message: '请输入用户名' }, { min: 2, message: '至少 2 个字符' }]}
        >
          <Input prefix={<UserOutlined />} placeholder="用户名" size="large" />
        </Form.Item>

        <Form.Item
          name="nickname"
          label="昵称"
        >
          <Input prefix={<UserOutlined />} placeholder="显示昵称（可选）" size="large" />
        </Form.Item>

        <Form.Item
          name="email"
          label="邮箱"
          rules={[{ type: 'email', message: '邮箱格式不正确' }]}
        >
          <Input prefix={<MailOutlined />} placeholder="your@email.com" size="large" />
        </Form.Item>

        <Form.Item
          name="password"
          label="密码"
          rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '至少 6 位' }]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
        </Form.Item>

        <Button type="primary" htmlType="submit" block size="large">注册</Button>
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Text type="secondary">已有账号？</Text>{' '}
          <Link to="/login">立即登录</Link>
        </div>
      </Form>
    </Card>
  )
}

import { Card, Form, Input, Button, Typography, message } from 'antd'
import { UserOutlined, MailOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'

const { Title, Text } = Typography

/** 公开注册页面 —— 已收窄为仅注册普通用户.
 *
 * 三员账号（system_admin / security_admin / audit_admin）必须由超级管理员
 * 通过 `cndb users create --role <role>` 或 admin-register API 创建，
 * 不在公开注册入口暴露角色选择。
 */

interface RegisterFormValues {
  username: string
  email?: string
  password: string
  nickname?: string
}

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const onFinish = async (values: RegisterFormValues) => {
    try {
      await register(values)
      message.success('注册成功，请登录')
      navigate('/login', { replace: true })
    } catch {
      message.error('注册失败，请检查输入')
    }
  }

  return (
    <Card>
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ marginBottom: 4 }}>创建账号</Title>
        <Text type="secondary">加入 cndb，开始构建你的数据工作区</Text>
      </div>
      <Form<RegisterFormValues>
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

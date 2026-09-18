import { Card, Form, Input, Button, Typography, message, Checkbox } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { useAuthStore } from '@/store'

const { Title, Text } = Typography

export default function LoginPage() {
  const login = useAuthStore(s => s.login)
  const navigate = useNavigate()
  const [sp] = useSearchParams()
  const returnTo = sp.get('return_to') || '/w'

  const onFinish = async (values: { login: string; password: string }) => {
    try {
      await login(values)
      message.success('登录成功')
      navigate(returnTo, { replace: true })
    } catch {
      message.error('用户名或密码错误')
    }
  }

  return (
    <Card>
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ marginBottom: 4 }}>cndb</Title>
        <Text type="secondary">登录以继续</Text>
      </div>
      <Form layout="vertical" onFinish={onFinish} initialValues={{ remember: true }}>
        <Form.Item name="login" label="用户名" rules={[{ required: true, message: '请输入用户名或邮箱' }]}>
          <Input prefix={<UserOutlined />} placeholder="用户名或邮箱" size="large" />
        </Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
        </Form.Item>
        <Form.Item name="remember" valuePropName="checked" style={{ marginBottom: 16 }}>
          <Checkbox>记住我</Checkbox>
        </Form.Item>
        <Button type="primary" htmlType="submit" block size="large">登录</Button>
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Text type="secondary">还没有账号？</Text>{' '}
          <Link to="/register">立即注册</Link>
        </div>
      </Form>
    </Card>
  )
}


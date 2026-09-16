import { Card, Form, Input, Button, Typography, message, Radio } from 'antd'
import { UserOutlined, MailOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import type { UserRole } from '@/api/types'

const { Title, Text } = Typography

/** 公开注册页面 —— 支持三员角色选择
 *
 * 安全说明：
 * - 公开注册端点后端会静默降级非 user 角色，所以前端提供完整角色选择
 *   是为了让用户了解系统角色设计，后端始终强制最终角色为 user
 * - 真正的三员账号需要由超级管理员通过 admin-register 创建
 */

interface RegisterFormValues {
  username: string
  email?: string
  password: string
  nickname?: string
  role: UserRole
}

const ROLE_OPTIONS: Array<{ value: UserRole; label: string; hint: string; color: string }> = [
  { value: 'system_admin', label: '系统管理员', hint: '系统配置、用户管理、工作区创建', color: '#1677ff' },
  { value: 'security_admin', label: '安全管理员', hint: '权限策略、数据安全、访问控制', color: '#eb2f96' },
  { value: 'audit_admin', label: '审计管理员', hint: '审计日志查看、合规检查', color: '#faad14' },
  { value: 'user', label: '普通用户', hint: '日常业务操作（公开注册默认此角色）', color: '#52c41a' },
]

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form] = Form.useForm<RegisterFormValues>()

  const onFinish = async (values: RegisterFormValues) => {
    try {
      await register(values)
      message.success('注册成功，欢迎加入')
      navigate('/w', { replace: true })
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
        form={form}
        layout="vertical"
        initialValues={{ role: 'user' as UserRole }}
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

        <Form.Item
          name="role"
          label="角色"
          tooltip="三员角色参考 GB/T 22239 等级保护模型。公开注册时三员角色将自动降级为普通用户，需管理员创建。"
        >
          <Radio.Group optionType="button" buttonStyle="solid" size="large">
            {ROLE_OPTIONS.map((opt) => (
              <Radio.Button key={opt.value} value={opt.value}>
                <span style={{ color: opt.color }}>●</span> {opt.label}
              </Radio.Button>
            ))}
          </Radio.Group>
        </Form.Item>
        <Text type="secondary" style={{ display: 'block', marginTop: -8, marginBottom: 16, fontSize: 12 }}>
          {(() => {
            const currentRole = form.getFieldValue('role') as UserRole
            const currentOption = ROLE_OPTIONS.find((o) => o.value === currentRole)
            return currentOption ? `说明：${currentOption.hint}` : ''
          })()}
        </Text>

        <Button type="primary" htmlType="submit" block size="large">注册</Button>
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Text type="secondary">已有账号？</Text>{' '}
          <Link to="/login">立即登录</Link>
        </div>
      </Form>
    </Card>
  )
}

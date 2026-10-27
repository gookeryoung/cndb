/** 用户设置面板 — 用户资料 + 主题（配色/字体）+ 表格（显示/操作）+ 大模型（个人连接配置）. */

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal, Button, Radio, Typography, Tabs, Select, Switch, Form, Input, App, Alert } from 'antd'
import { useTheme } from '@/theme/ThemeProvider'
import {
  THEME_META, THEME_MODES, FONT_SCALES, FONT_SCALE_META,
  DEFAULT_FONT_SETTINGS, DEFAULT_THEME_MODE,
  type ThemeMode,
} from '@/theme/theme'
import { useTableSettingsStore, useAuthStore, type SettingsTab } from '@/store'
import { authApi } from '@/api'
import { useResponsive } from '@/hooks/useResponsive'
import type { Density, NewRowPosition } from '@/theme/tableSettings'
import LlmConfigPanel from './LlmConfigPanel'
import { WEIGHT } from '@/theme/tokens'

interface Props {
  open: boolean
  onClose: () => void
  /** 打开时定位的页签（Modal destroyOnHidden，每次打开重新挂载生效） */
  initialTab?: SettingsTab
}

/** 每个主题对应的色板（展示用，不影响实际渲染） */
const themeSwatches: Record<ThemeMode, { primary: string; bg: string; text: string; border: string }> = {
  modern: { primary: '#3b82f6', bg: '#ffffff', text: '#1f2937', border: '#d1d5db' },
  'github-dark': { primary: '#58a6ff', bg: '#0d1117', text: '#e6edf3', border: '#30363d' },
  'github-light': { primary: '#0969da', bg: '#ffffff', text: '#1f2328', border: '#d0d7de' },
  minimal: { primary: '#525252', bg: '#fafafa', text: '#262626', border: '#d4d4d4' },
  ocean: { primary: '#0891b2', bg: '#ffffff', text: '#0f3a45', border: '#cfe2e8' },
  forest: { primary: '#16a34a', bg: '#ffffff', text: '#14301b', border: '#d3e4d5' },
  sepia: { primary: '#a16207', bg: '#fbf6ea', text: '#43341f', border: '#ddcfae' },
  sakura: { primary: '#db2777', bg: '#ffffff', text: '#3d2230', border: '#f2d9e5' },
  midnight: { primary: '#a78bfa', bg: '#1d1830', text: '#e9e4f5', border: '#383150' },
  oled: { primary: '#22d3ee', bg: '#0a0a0a', text: '#f5f5f5', border: '#262626' },
}

const { Text } = Typography

function ThemeCard({ mode, selected, onSelect }: {
  mode: ThemeMode
  selected: boolean
  onSelect: () => void
}) {
  const meta = THEME_META[mode]
  const s = themeSwatches[mode]
  return (
    <label
      data-theme-card={mode}
      onClick={onSelect}
      style={{
        cursor: 'pointer',
        border: selected
          ? `2px solid ${s.primary}`
          : '2px solid transparent',
        borderRadius: 10,
        padding: 12,
        background: s.bg,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        transition: 'border-color 120ms, box-shadow 120ms',
        boxShadow: selected ? `0 0 0 3px ${s.primary}22` : 'none',
        // 每张卡片根据自己展示的主题色板来决定文字色，不能 inherit 外层
        // 否则当外层是深色模式时，浅色主题卡片（白背景）会继承浅色文字，看不清
        color: s.text,
      }}
    >
      {/* 小预览条 */}
      <div style={{
        display: 'flex',
        gap: 4,
        alignItems: 'center',
        height: 24,
      }}>
        <div style={{ width: 24, height: 24, borderRadius: 6, background: s.primary }} />
        <div style={{ width: 40, height: 10, borderRadius: 4, background: s.bg, border: `1px solid ${s.border}` }} />
        <div style={{ width: 20, height: 10, borderRadius: 4, background: s.text, opacity: 0.8 }} />
        <div style={{ width: 12, height: 10, borderRadius: 4, background: s.border }} />
      </div>
      <div>
        <div style={{ fontWeight: selected ? WEIGHT.semibold : WEIGHT.medium, fontSize: 13 }}>{meta.label}</div>
        <div style={{
          fontSize: 11,
          color: meta.isDark ? '#8b949e' : '#8c8c8c',
          marginTop: 2,
          lineHeight: 1.4,
        }}>{meta.description}</div>
      </div>
    </label>
  )
}

/** 用户资料分页内容 — 用户名只读，昵称/邮箱自助更新 */
function ProfilePanel() {
  const { isMobile } = useResponsive()
  const { message } = App.useApp()
  const user = useAuthStore(s => s.user)
  const refresh = useAuthStore(s => s.refresh)
  const [form] = Form.useForm()

  // 每次打开/用户变化时用 store 中最新值重置表单
  useEffect(() => {
    if (user) {
      form.setFieldsValue({
        username: user.username,
        nickname: user.nickname ?? '',
        email: user.email ?? '',
      })
    }
  }, [user, form])

  const handleSave = async (values: { nickname: string; email: string }) => {
    try {
      await authApi.updateProfile({ nickname: values.nickname, email: values.email })
      await refresh()
      message.success('用户资料已保存')
    } catch (err: unknown) {
      // axios 错误响应里带后端 400 明细（如邮箱已被使用）
      const detail =
        typeof err === 'object' && err !== null && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined
      message.error(detail ?? '保存失败，请稍后重试')
    }
  }

  return (
    <div style={{ padding: '12px 0' }}>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSave}
      >
        {/* 用户名/昵称/邮箱同行紧凑排布；用户名只读。
            说明文字统一用 Text secondary 12px（与主题/表格页签提示一致），
            不用 Form.Item extra（其默认色为 colorTextDescription，比其他提示浅）。
            移动端改为纵向堆叠：三列并排在 390px 宽度下每格仅约 110px，昵称/邮箱会被截断 */}
        <div
          data-testid="profile-fields"
          style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 12 }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <Form.Item name="username" label="用户名" style={{ marginBottom: 0 }}>
              <Input disabled />
            </Form.Item>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
              注册后不可修改
            </Text>
          </div>
          <Form.Item
            name="nickname"
            label="昵称"
            rules={[{ max: 150, message: '昵称不能超过 150 个字符' }]}
            style={{ flex: 1, minWidth: 0, marginBottom: 12 }}
          >
            <Input placeholder="输入昵称" allowClear />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { type: 'email', message: '邮箱格式不正确' },
              { max: 255, message: '邮箱不能超过 255 个字符' },
            ]}
            style={{ flex: 1.3, minWidth: 0, marginBottom: 12 }}
          >
            <Input placeholder="输入邮箱" allowClear />
          </Form.Item>
        </div>
        <Button type="primary" htmlType="submit">保存</Button>
      </Form>
    </div>
  )
}

/** 安全分页内容 — 自助修改密码（成功后全部会话失效并强制重新登录） */
function SecurityPanel({ onClose }: { onClose: () => void }) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const logout = useAuthStore(s => s.logout)
  const [form] = Form.useForm<{ current_password: string; new_password: string; confirm_password: string }>()

  const handleSubmit = async (values: { current_password: string; new_password: string }) => {
    try {
      await authApi.changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      message.success('密码已修改，请用新密码重新登录')
      onClose()
      // 服务端已吊销全部会话，本地登出后回到登录页
      logout()
      navigate('/login', { replace: true })
    } catch (err: unknown) {
      const detail =
        typeof err === 'object' && err !== null && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined
      message.error(detail ?? '修改失败，请稍后重试')
    }
  }

  return (
    <div style={{ padding: '12px 0' }}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="修改成功后，包括当前设备在内的全部会话将失效，需要用新密码重新登录。"
      />
      <Form form={form} layout="vertical" onFinish={handleSubmit} style={{ maxWidth: 420 }}>
        <Form.Item
          name="current_password"
          label="当前密码"
          rules={[{ required: true, message: '请输入当前密码' }]}
        >
          <Input.Password placeholder="输入当前密码" autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 6, max: 128, message: '密码长度须为 6-128 位' },
            ({ getFieldValue }) => ({
              validator(_, value: string) {
                if (value && value === getFieldValue('current_password')) {
                  return Promise.reject(new Error('新密码不能与当前密码相同'))
                }
                return Promise.resolve()
              },
            }),
          ]}
        >
          <Input.Password placeholder="6-128 位" autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm_password"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator(_, value: string) {
                if (value && value !== getFieldValue('new_password')) {
                  return Promise.reject(new Error('两次输入的新密码不一致'))
                }
                return Promise.resolve()
              },
            }),
          ]}
        >
          <Input.Password placeholder="再次输入新密码" autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit">修改密码</Button>
      </Form>
    </div>
  )
}

/** 主题分页内容 — 配色 + 字体 */
function ThemePanel() {
  const { message } = App.useApp()
  const { mode, setMode, font, setFontScale, setFontBold } = useTheme()

  // 恢复默认：复用既有 setter 即时持久化（主题 modern / 字号标准 / 不加粗）
  const handleReset = () => {
    setMode(DEFAULT_THEME_MODE)
    setFontScale(DEFAULT_FONT_SETTINGS.scale)
    setFontBold(DEFAULT_FONT_SETTINGS.bold)
    message.info('已恢复主题设置为默认值')
  }

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ fontSize: 14 }}>配色</Text>
        <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
          设置会自动保存到浏览器
        </Text>
      </div>

      <Radio.Group
        value={mode}
        onChange={e => setMode(e.target.value)}
        buttonStyle="solid"
        style={{ marginBottom: 16, display: 'flex', flexWrap: 'wrap', gap: 8 }}
      >
        {THEME_MODES.map(m => (
          <Radio.Button key={m} value={m}>
            {THEME_META[m].label}
          </Radio.Button>
        ))}
      </Radio.Group>

      {/* 卡片式选择（视觉友好） */}
      <div
        data-testid="theme-grid"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
          gap: 10,
        }}
      >
        {THEME_MODES.map(m => (
          <ThemeCard
            key={m}
            mode={m}
            selected={mode === m}
            onSelect={() => setMode(m)}
          />
        ))}
      </div>

      <div style={{ marginTop: 20, marginBottom: 12 }}>
        <Text strong style={{ fontSize: 14 }}>字体</Text>
        <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
          即时生效，自动保存到浏览器
        </Text>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 13 }}>字号</Text>
          <Select
            data-testid="font-scale-select"
            value={font.scale}
            onChange={(v) => setFontScale(v)}
            style={{ width: 96 }}
            options={FONT_SCALES.map(s => ({ value: s, label: FONT_SCALE_META[s].label }))}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 13 }}>全局加粗</Text>
          <Switch
            data-testid="font-bold-switch"
            checked={font.bold}
            onChange={setFontBold}
          />
        </div>
      </div>

      <Button size="small" style={{ marginTop: 20 }} onClick={handleReset}>
        恢复默认
      </Button>
    </div>
  )
}

/** 表格分页内容 — 显示模式（全局偏好）+ 操作风格，全部即时生效并持久化到浏览器 */
function TablePanel() {
  const { message } = App.useApp()
  const density = useTableSettingsStore(s => s.density)
  const defaultPageSize = useTableSettingsStore(s => s.defaultPageSize)
  const newRowPosition = useTableSettingsStore(s => s.newRowPosition)
  const autoFillLocked = useTableSettingsStore(s => s.autoFillLocked)
  const updateSettings = useTableSettingsStore(s => s.updateSettings)
  const resetSettings = useTableSettingsStore(s => s.resetSettings)

  const positionOptions: Array<{ value: NewRowPosition; label: string; description: string }> = [
    { value: 'top', label: '表格顶部', description: '新增行作为第一条数据显示在表格开头' },
    { value: 'tail', label: '表格尾部', description: '新增行追加到整个表格末尾（跨分页）' },
    { value: 'page', label: '页面尾部', description: '新增行追加到当前可见页的末尾' },
  ]

  const densityOptions: Array<{ value: Density; label: string }> = [
    { value: 'compact', label: '紧凑' },
    { value: 'comfortable', label: '适中' },
    { value: 'spacious', label: '宽松' },
  ]

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ fontSize: 14 }}>显示模式</Text>
        <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
          全局生效，适用于所有数据表
        </Text>
      </div>

      {/* 间距 + 每页行数：窄屏放不下时换行，避免两个下拉被压缩 */}
      <div
        data-testid="table-display-row"
        style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8, flexWrap: 'wrap' }}
      >
        <Text style={{ fontSize: 13 }}>间距</Text>
        <Select
          data-testid="density-select"
          value={density}
          onChange={(v: Density) => updateSettings({ density: v })}
          style={{ width: 120 }}
          options={densityOptions}
        />
        <Text style={{ fontSize: 13 }}>每页行数</Text>
        <Select
          data-testid="page-size-select"
          value={defaultPageSize}
          onChange={(v: number) => updateSettings({ defaultPageSize: v })}
          style={{ width: 120 }}
          options={[25, 50, 100, 200].map(n => ({ value: n, label: `${n} 条` }))}
        />
      </div>
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4, marginBottom: 20 }}>
        间距同样影响看板、画廊、日历的卡片密度
      </Text>

      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ fontSize: 14 }}>操作风格</Text>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8 }}>
        <Text style={{ fontSize: 13 }}>新增行默认位置</Text>
        <Select
          value={newRowPosition}
          onChange={(v: NewRowPosition) => updateSettings({ newRowPosition: v })}
          style={{ width: 200 }}
          options={positionOptions.map(o => ({ value: o.value, label: o.label }))}
        />
      </div>
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4, marginBottom: 16 }}>
        {positionOptions.find(o => o.value === newRowPosition)?.description}
      </Text>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
        <Text style={{ fontSize: 13 }}>自动填充锁定</Text>
        <Switch
          checked={autoFillLocked}
          onChange={(checked) => updateSettings({ autoFillLocked: checked })}
          checkedChildren="开启"
          unCheckedChildren="关闭"
        />
      </div>
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
        开启后，新增行时由默认值或自动填充规则预填的字段将设为只读，避免误修改，提高录入速度
      </Text>

      <Button
        size="small"
        style={{ marginTop: 20 }}
        onClick={() => { resetSettings(); message.info('已恢复表格设置为默认值') }}
      >
        恢复默认
      </Button>
    </div>
  )
}

export default function SettingsModal({ open, onClose, initialTab }: Props) {
  return (
    <Modal
      title="个人设置"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={760}
      className="settings-modal"
      destroyOnHidden
    >
      <Tabs
        defaultActiveKey={initialTab ?? 'profile'}
        items={[
          { key: 'profile', label: '用户资料', children: <ProfilePanel /> },
          { key: 'security', label: '安全', children: <SecurityPanel onClose={onClose} /> },
          { key: 'theme', label: '主题', children: <ThemePanel /> },
          { key: 'table', label: '表格', children: <TablePanel /> },
          // 大模型入口已在顶栏常驻（桌面图标 / 移动端用户菜单），设置内排在「表格」右侧，避免与高频的资料 / 主题争前排
          { key: 'llm', label: '大模型', children: <LlmConfigPanel /> },
        ]}
      />
    </Modal>
  )
}

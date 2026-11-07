/** 用户设置面板 — 用户资料（含修改密码）+ 主题（配色/字体）+ 表格（显示/操作）+ 大模型（个人连接配置）. */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal, Button, Radio, Typography, Tabs, Select, Switch, Form, Input, App } from 'antd'
import {
  UserOutlined, BgColorsOutlined, TableOutlined, FileTextOutlined, RobotOutlined, CodeOutlined,
} from '@ant-design/icons'
import { useTheme } from '@/theme/ThemeProvider'
import {
  THEME_META, THEME_MODES, FONT_SCALES, FONT_SCALE_META,
  EDITOR_THEME_IDS, EDITOR_THEME_META, EDITOR_FONT_FAMILIES, EDITOR_FONT_META,
  EDITOR_FONT_SIZES, EDITOR_FONT_SIZE_LABEL, getEditorPalette,
  DEFAULT_EDITOR_SETTINGS,
  type ThemePreference,
  DEFAULT_FONT_SETTINGS, DEFAULT_THEME_MODE,
  type ThemeMode, type EditorThemeId, type EditorFontFamily, type EditorFontSize,
} from '@/theme/theme'
import { useTableSettingsStore, useDocSettingsStore, useAuthStore, type SettingsTab } from '@/store'
import { authApi } from '@/api'
import { useResponsive } from '@/hooks/useResponsive'
// 编辑器字体只在设置面板 / 编辑器 chunk 中加载（大体积等宽字体不进首屏入口）
import '@/theme/editorFontAssets'
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
  modern: { primary: '#3b82f6', bg: '#ffffff', text: '#1f2937', border: '#d1d9e0' },
  'github-dark': { primary: '#58a6ff', bg: '#0d1117', text: '#e6edf3', border: '#3d444d' },
  'github-light': { primary: '#0969da', bg: '#ffffff', text: '#1f2328', border: '#d1d9e0' },
  minimal: { primary: '#525252', bg: '#fafafa', text: '#262626', border: '#d4d4d4' },
  ocean: { primary: '#0891b2', bg: '#ffffff', text: '#0f3a45', border: '#cfe2e8' },
  forest: { primary: '#16a34a', bg: '#ffffff', text: '#14301b', border: '#d3e4d5' },
  sepia: { primary: '#a16207', bg: '#fbf6ea', text: '#43341f', border: '#ddcfae' },
  sakura: { primary: '#db2777', bg: '#ffffff', text: '#3d2230', border: '#f2d9e5' },
  midnight: { primary: '#a78bfa', bg: '#1d1830', text: '#e9e4f5', border: '#383150' },
  oled: { primary: '#22d3ee', bg: '#0a0a0a', text: '#f5f5f5', border: '#262626' },
}

const { Text } = Typography

/** 分区标题：GitHub 风格 —— 标题行下紧跟分隔线，而不是在内容块之间插分隔符.
 *
 * 标题与行内辅助说明同一行，底线明确每节的起点；`topGap` 供同页多节时拉开节奏。
 */
function SectionHeader({ title, description, topGap = 0 }: {
  title: string
  description: string
  topGap?: number
}) {
  return (
    <div
      className="settings-section-header"
      style={{
        marginTop: topGap,
        paddingBottom: 8,
        marginBottom: 16,
        borderBottom: '1px solid var(--cn-border)',
        display: 'flex',
        alignItems: 'baseline',
        gap: 8,
        flexWrap: 'wrap',
      }}
    >
      <Text strong style={{ fontSize: 'var(--cn-text-md)' }}>{title}</Text>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>{description}</Text>
    </div>
  )
}

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
        <div style={{ fontWeight: selected ? WEIGHT.semibold : WEIGHT.medium, fontSize: 'var(--cn-text-sm)' }}>{meta.label}</div>
        <div style={{
          fontSize: 'var(--cn-text-2xs)',
          color: meta.isDark ? '#8b949e' : '#8c8c8c',
          marginTop: 2,
          lineHeight: 1.4,
        }}>{meta.description}</div>
      </div>
    </label>
  )
}

/** 取后端错误响应里的 detail（如邮箱已被使用、当前密码错误） */
function apiDetail(err: unknown): string | undefined {
  return typeof err === 'object' && err !== null && 'response' in err
    ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
    : undefined
}

type ProfileValues = { username?: string; nickname?: string; email?: string }
type PasswordValues = { current_password?: string; new_password?: string; confirm_password?: string }

/** 用户资料分页内容 — 基本资料 + 账号安全，由底部「更新资料」统一提交.
 *
 * 两个表单不再各带按钮：密码三个字段全空时只更新昵称 / 邮箱；
 * 填了任一密码字段则随「更新资料」一并校验并修改密码（成功后全部会话失效，强制重新登录）。
 */
function ProfilePanel({ onClose }: { onClose: () => void }) {
  const { isMobile } = useResponsive()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const user = useAuthStore(s => s.user)
  const refresh = useAuthStore(s => s.refresh)
  const logout = useAuthStore(s => s.logout)
  const [profileForm] = Form.useForm<ProfileValues>()
  const [passwordForm] = Form.useForm<PasswordValues>()
  const [submitting, setSubmitting] = useState(false)

  // 每次打开/用户变化时用 store 中最新值重置表单
  useEffect(() => {
    if (user) {
      profileForm.setFieldsValue({
        username: user.username,
        nickname: user.nickname ?? '',
        email: user.email ?? '',
      })
    }
  }, [user, profileForm])

  const handleUpdate = async () => {
    let profile: ProfileValues
    try {
      profile = await profileForm.validateFields()
    } catch {
      return // 字段校验失败，错误提示已在表单内展示
    }

    // 密码字段全空视为「不改密码」，避免 required 规则拦住只更新资料的场景
    const rawPassword = passwordForm.getFieldsValue()
    const wantsPasswordChange = Object.values(rawPassword).some(
      v => typeof v === 'string' && v.trim() !== '',
    )
    let password: PasswordValues | null = null
    if (wantsPasswordChange) {
      try {
        password = await passwordForm.validateFields()
      } catch {
        return
      }
    }

    setSubmitting(true)
    try {
      await authApi.updateProfile({
        nickname: profile.nickname ?? '',
        email: profile.email ?? '',
      })
      await refresh()
    } catch (err: unknown) {
      message.error(apiDetail(err) ?? '保存失败，请稍后重试')
      setSubmitting(false)
      return
    }

    if (!password) {
      message.success('用户资料已更新')
      setSubmitting(false)
      return
    }

    try {
      await authApi.changePassword({
        current_password: password.current_password ?? '',
        new_password: password.new_password ?? '',
      })
    } catch (err: unknown) {
      message.error(apiDetail(err) ?? '修改失败，请稍后重试')
      setSubmitting(false)
      return
    }

    message.success('用户资料已更新，密码已修改，请用新密码重新登录')
    onClose()
    // 服务端已吊销全部会话，本地登出后回到登录页
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div style={{ padding: '12px 0' }}>
      <SectionHeader title="基本资料" description="昵称、邮箱自助更新，点击底部「更新资料」即时生效" />
      <Form form={profileForm} layout="vertical">
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
            <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: 4 }}>
              注册后不可修改
            </Text>
          </div>
          <Form.Item
            name="nickname"
            label="昵称"
            rules={[{ max: 150, message: '昵称不能超过 150 个字符' }]}
            style={{ flex: 1, minWidth: 0, marginBottom: isMobile ? 12 : 0 }}
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
            style={{ flex: 1.3, minWidth: 0, marginBottom: isMobile ? 0 : undefined }}
          >
            <Input placeholder="输入邮箱" allowClear />
          </Form.Item>
        </div>
      </Form>

      <SectionHeader
        title="账号安全"
        description="填写后随「更新资料」一并提交；修改成功后全部会话失效，需用新密码重新登录"
        topGap={20}
      />
      {/* 桌面端三个密码框并排一行（与上方基本资料单行结构呼应，降低纵向高度）；
          移动端纵向堆叠，避免窄屏输入框被压缩 */}
      <Form form={passwordForm} layout="vertical">
        <div
          data-testid="password-fields"
          style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 12 }}
        >
          <Form.Item
            name="current_password"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
            style={{ flex: 1, minWidth: 0, marginBottom: isMobile ? 0 : undefined }}
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
            style={{ flex: 1, minWidth: 0, marginBottom: isMobile ? 0 : undefined }}
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
            style={{ flex: 1, minWidth: 0, marginBottom: 0 }}
          >
            <Input.Password placeholder="再次输入新密码" autoComplete="new-password" />
          </Form.Item>
        </div>
      </Form>

      {/* 两个表单共用一个底部动作，不再各自散落「保存」「修改密码」按钮 */}
      <Button
        type="primary"
        loading={submitting}
        style={{ marginTop: 16 }}
        onClick={handleUpdate}
      >
        更新资料
      </Button>
    </div>
  )
}

/** 编辑器配色 / 字体实时预览（DSL 片段，不依赖 CodeMirror，避免设置页拉编辑器包） */
function EditorPreview({ theme, family }: {
  theme: EditorThemeId
  family: EditorFontFamily
}) {
  const { isDark } = useTheme()
  const p = getEditorPalette(theme, isDark)
  const keyword = (text: string) => <span style={{ color: p.keyword }}>{text}</span>
  const number = (text: string) => <span style={{ color: p.number }}>{text}</span>
  const comment = (text: string) => <span style={{ color: p.comment }}>{text}</span>
  return (
    <div
      data-testid="editor-theme-preview"
      style={{
        marginTop: 12,
        background: p.bg,
        border: `1px solid ${p.border}`,
        borderRadius: 8,
        padding: '10px 12px',
        fontFamily: EDITOR_FONT_META[family].css,
        fontSize: 'var(--cn-text-xs)',
        lineHeight: 1.7,
        color: p.text,
        overflow: 'hidden',
      }}
    >
      <div>
        <span style={{ color: p.muted, marginRight: 10 }}>1</span>
        {keyword('param')} width = {number('120')}
      </div>
      <div>
        <span style={{ color: p.muted, marginRight: 10 }}>2</span>
        {keyword('module')} base {'{'}
      </div>
      <div>
        <span style={{ color: p.muted, marginRight: 10 }}>3</span>
        {'  '}{keyword('box')}(size = [{number('width')}, {number('80')}, {number('40')}]) {comment('// 底座')}
      </div>
      <div>
        <span style={{ color: p.muted, marginRight: 10 }}>4</span>
        {'}'}
      </div>
    </div>
  )
}

/** 主题分页内容 — 全站配色 + 字体（编辑器外观已拆到独立页签） */
function ThemePanel() {
  const { message } = App.useApp()
  const { mode, pref, setMode, font, setFontScale, setFontBold } = useTheme()

  // 恢复默认：只重置全站配色与字体（偏好跟随系统 auto / 字号标准 / 不加粗），不动编辑器外观
  const handleReset = () => {
    setMode(DEFAULT_THEME_MODE)
    setFontScale(DEFAULT_FONT_SETTINGS.scale)
    setFontBold(DEFAULT_FONT_SETTINGS.bold)
    message.info('已恢复主题设置为默认值')
  }

  return (
    <div style={{ padding: '12px 0' }}>
      <SectionHeader title="配色" description="设置会自动保存到浏览器" />

      {/* 「跟随系统」虚拟档（0066 C7）：持久化 auto，生效主题按系统明暗实时解析 */}
      <Radio.Group
        value={pref}
        onChange={e => setMode(e.target.value as ThemePreference)}
        buttonStyle="solid"
        style={{ marginBottom: 16, display: 'flex', flexWrap: 'wrap', gap: 8 }}
      >
        <Radio.Button value="auto">跟随系统</Radio.Button>
        {THEME_MODES.map(m => (
          <Radio.Button key={m} value={m}>
            {THEME_META[m].label}
          </Radio.Button>
        ))}
      </Radio.Group>

      {/* 卡片式选择（视觉友好）；pref=auto 时无卡片选中，生效主题见上方回显 */}
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
            selected={mode === m && pref === m}
            onSelect={() => setMode(m)}
          />
        ))}
      </div>

      {/* auto 生效回显：当前解析到的实际主题（0066 C7） */}
      {pref === 'auto' && (
        <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)' }}>
          跟随系统中：当前按系统明暗使用「{THEME_META[mode].label}」
        </Text>
      )}

      <SectionHeader title="字体" description="即时生效，自动保存到浏览器" topGap={20} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>字号</Text>
          <Select
            data-testid="font-scale-select"
            value={font.scale}
            onChange={(v) => setFontScale(v)}
            style={{ width: 96 }}
            options={FONT_SCALES.map(s => ({ value: s, label: FONT_SCALE_META[s].label }))}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>全局加粗</Text>
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

/** 编辑器分页内容 — 结构 DSL 与流水线编辑器独立的配色 / 字体 / 字号，可单独恢复默认 */
function EditorPanel() {
  const { message } = App.useApp()
  const { editor, updateEditorSettings } = useTheme()

  const handleReset = () => {
    updateEditorSettings(DEFAULT_EDITOR_SETTINGS)
    message.info('已恢复编辑器设置为默认值')
  }

  return (
    <div style={{ padding: '12px 0' }}>
      <SectionHeader
        title="编辑器外观"
        description="结构 DSL 与流水线编辑器独立配色，避免与页面主题相互迁就"
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>配色</Text>
          <Select
            data-testid="editor-theme-select"
            value={editor.theme}
            onChange={(v: EditorThemeId) => updateEditorSettings({ theme: v })}
            style={{ width: 148 }}
            options={EDITOR_THEME_IDS.map(id => ({
              value: id,
              label: EDITOR_THEME_META[id].label,
            }))}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>字体</Text>
          <Select
            data-testid="editor-font-select"
            value={editor.font.family}
            onChange={(v: EditorFontFamily) => updateEditorSettings({ font: { family: v } })}
            style={{ width: 150 }}
            options={EDITOR_FONT_FAMILIES.map(id => ({
              value: id,
              label: EDITOR_FONT_META[id].label,
            }))}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 'var(--cn-text-sm)' }}>字号</Text>
          <Select
            data-testid="editor-font-size-select"
            value={editor.font.size}
            onChange={(v: EditorFontSize) => updateEditorSettings({ font: { size: v } })}
            style={{ width: 110 }}
            options={EDITOR_FONT_SIZES.map(size => ({
              value: size,
              label: EDITOR_FONT_SIZE_LABEL[size],
            }))}
          />
        </div>
      </div>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: 8 }}>
        {EDITOR_THEME_META[editor.theme].description}
      </Text>
      <EditorPreview theme={editor.theme} family={editor.font.family} />

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
      <SectionHeader title="显示模式" description="全局生效，适用于所有数据表" />

      {/* 间距 + 每页行数：窄屏放不下时换行，避免两个下拉被压缩 */}
      <div
        data-testid="table-display-row"
        style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8, flexWrap: 'wrap' }}
      >
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>间距</Text>
        <Select
          data-testid="density-select"
          value={density}
          onChange={(v: Density) => updateSettings({ density: v })}
          style={{ width: 120 }}
          options={densityOptions}
        />
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>每页行数</Text>
        <Select
          data-testid="page-size-select"
          value={defaultPageSize}
          onChange={(v: number) => updateSettings({ defaultPageSize: v })}
          style={{ width: 120 }}
          options={[25, 50, 100, 200].map(n => ({ value: n, label: `${n} 条` }))}
        />
      </div>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: 4, marginBottom: 20 }}>
        间距同样影响看板、画廊、日历的卡片密度
      </Text>

      <SectionHeader title="操作风格" description="新增行的落点与自动填充锁定" topGap={20} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8 }}>
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>新增行默认位置</Text>
        <Select
          value={newRowPosition}
          onChange={(v: NewRowPosition) => updateSettings({ newRowPosition: v })}
          style={{ width: 200 }}
          options={positionOptions.map(o => ({ value: o.value, label: o.label }))}
        />
      </div>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: 4, marginBottom: 16 }}>
        {positionOptions.find(o => o.value === newRowPosition)?.description}
      </Text>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 }}>
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>自动填充锁定</Text>
        <Switch
          checked={autoFillLocked}
          onChange={(checked) => updateSettings({ autoFillLocked: checked })}
          checkedChildren="开启"
          unCheckedChildren="关闭"
        />
      </div>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: 4 }}>
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

/** 文档分页内容 — 文档内表格/图片的对齐与默认宽度，全部即时生效并持久化到浏览器 */
function DocPanel() {
  const { message } = App.useApp()
  const tableAlign = useDocSettingsStore(s => s.tableAlign)
  const imageAlign = useDocSettingsStore(s => s.imageAlign)
  const tableDefaultWidth = useDocSettingsStore(s => s.tableDefaultWidth)
  const imageDefaultWidth = useDocSettingsStore(s => s.imageDefaultWidth)
  const updateSettings = useDocSettingsStore(s => s.updateSettings)
  const resetSettings = useDocSettingsStore(s => s.resetSettings)

  const alignOptions = [
    { value: 'left' as const, label: '靠左' },
    { value: 'center' as const, label: '居中' },
  ]

  return (
    <div style={{ padding: '12px 0' }}>
      <SectionHeader title="对齐方式" description="文档内表格与图片的水平对齐" />
      <div data-testid="doc-align-row" style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8, flexWrap: 'wrap' }}>
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>表格对齐</Text>
        <Select
          data-testid="doc-table-align-select"
          value={tableAlign}
          onChange={(v) => updateSettings({ tableAlign: v })}
          style={{ width: 96 }}
          options={alignOptions}
        />
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>图片对齐</Text>
        <Select
          data-testid="doc-image-align-select"
          value={imageAlign}
          onChange={(v) => updateSettings({ imageAlign: v })}
          style={{ width: 96 }}
          options={alignOptions}
        />
      </div>

      <SectionHeader title="默认宽度" description="插入时的缺省宽度，正文显式指定不受影响" topGap={20} />
      <div data-testid="doc-width-row" style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8, flexWrap: 'wrap' }}>
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>表格默认宽度</Text>
        <Select
          data-testid="doc-table-width-select"
          value={tableDefaultWidth}
          onChange={(v) => updateSettings({ tableDefaultWidth: v })}
          style={{ width: 96 }}
          options={[50, 75, 100].map(n => ({ value: n, label: `${n}%` }))}
        />
        <Text style={{ fontSize: 'var(--cn-text-sm)' }}>图片默认宽度</Text>
        <Select
          data-testid="doc-image-width-select"
          value={imageDefaultWidth}
          onChange={(v) => updateSettings({ imageDefaultWidth: v })}
          style={{ width: 96 }}
          options={[50, 75].map(n => ({ value: n, label: `${n}%` }))}
        />
      </div>
      <Text type="secondary" style={{ fontSize: 'var(--cn-text-xs)', display: 'block', marginTop: 4, marginBottom: 16 }}>
        仅影响缺省情况：正文中已显式指定宽度的表格引用不受影响
      </Text>

      <Button
        size="small"
        onClick={() => { resetSettings(); message.info('已恢复文档设置为默认值') }}
      >
        恢复默认
      </Button>
    </div>
  )
}

export default function SettingsModal({ open, onClose, initialTab }: Props) {
  const { isMobile } = useResponsive()

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
        // GitHub 风格：桌面端左侧竖向列表 + 右侧独立滚动内容区；
        // 移动端竖排导航会挤占本就有限的宽度，回落为顶部横排（可横向滚动）。
        tabPlacement={isMobile ? 'top' : 'start'}
        className={`settings-modal-tabs ${isMobile ? 'is-top' : 'is-side'}`}
        items={[
          // 修改密码表单并入用户资料页签下方，不再单设「安全」页签；两节各自标题带分隔线
          {
            key: 'profile',
            label: <span><UserOutlined aria-hidden />用户资料</span>,
            children: <ProfilePanel onClose={onClose} />,
          },
          { key: 'theme', label: <span><BgColorsOutlined aria-hidden />主题</span>, children: <ThemePanel /> },
          { key: 'table', label: <span><TableOutlined aria-hidden />表格</span>, children: <TablePanel /> },
          // 文档渲染配置：表格/图片对齐与默认宽度，排在「表格」之后
          { key: 'doc', label: <span><FileTextOutlined aria-hidden />文档</span>, children: <DocPanel /> },
          // 编辑器外观独立成页签，排在「文档」之后，避免与全站配色 / 字体相互牵连
          { key: 'editor', label: <span><CodeOutlined aria-hidden />编辑器</span>, children: <EditorPanel /> },
          // 大模型入口已在顶栏常驻（桌面图标 / 移动端用户菜单），设置内排在末位，避免与高频的资料 / 主题争前排
          { key: 'llm', label: <span><RobotOutlined aria-hidden />大模型</span>, children: <LlmConfigPanel /> },
        ]}
      />
    </Modal>
  )
}

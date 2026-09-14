/** 用户设置面板 — 主题切换. */

import { Modal, Button, Radio, Typography } from 'antd'
import { useTheme } from '@/theme/ThemeProvider'
import { THEME_META, THEME_MODES, type ThemeMode } from '@/theme/theme'

interface Props {
  open: boolean
  onClose: () => void
}

/** 每个主题对应的色板（展示用，不影响实际渲染） */
const themeSwatches: Record<ThemeMode, { primary: string; bg: string; text: string; border: string }> = {
  modern:      { primary: '#3b82f6', bg: '#ffffff', text: '#1f2937', border: '#d1d5db' },
  'github-dark': { primary: '#58a6ff', bg: '#0d1117', text: '#e6edf3', border: '#30363d' },
  'github-light': { primary: '#0969da', bg: '#ffffff', text: '#1f2328', border: '#d0d7de' },
  minimal:     { primary: '#525252', bg: '#fafafa', text: '#262626', border: '#d4d4d4' },
  ocean:       { primary: '#0891b2', bg: '#ffffff', text: '#0f3a45', border: '#cfe2e8' },
  forest:      { primary: '#16a34a', bg: '#ffffff', text: '#14301b', border: '#d3e4d5' },
  sepia:       { primary: '#a16207', bg: '#fbf6ea', text: '#43341f', border: '#ddcfae' },
  sakura:      { primary: '#db2777', bg: '#ffffff', text: '#3d2230', border: '#f2d9e5' },
  midnight:    { primary: '#a78bfa', bg: '#1d1830', text: '#e9e4f5', border: '#383150' },
  oled:        { primary: '#22d3ee', bg: '#0a0a0a', text: '#f5f5f5', border: '#262626' },
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
        <div style={{ fontWeight: selected ? 600 : 500, fontSize: 13 }}>{meta.label}</div>
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

export default function SettingsModal({ open, onClose }: Props) {
  const { mode, setMode } = useTheme()

  return (
    <Modal
      title="个人设置"
      open={open}
      onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>]}
      width={660}
      destroyOnHidden
    >
      <div style={{ padding: '12px 0' }}>
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ fontSize: 14 }}>主题</Text>
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
      </div>
    </Modal>
  )
}

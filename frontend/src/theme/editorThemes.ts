/** DSL / 流水线编辑器（CodeMirror 6）配色主题.
 *
 * 编辑器的配色与字号不再与全站主题绑定：
 *  - `auto` 跟随个人设置里的浅色 / 深色主题（GitHub 同族）；
 *  - 其余为固定主题，用户可在「个人设置 → 编辑器」单独选用。
 *
 * 色板口径参考各主题官方实现（GitHub Primer / One Dark / Solarized），
 * 只保留语法高亮需要的语义色，避免逐主题维护一套完整调色板。
 *
 * 本模块只放元信息与纯数据色板（无 @codemirror/* 运行时依赖），可被设置面板与
 * 主入口安全引用；需要 CodeMirror API 的外观组装在 `editorAppearance`。
 */

/** 可选编辑器主题 ID（auto = 跟随全站主题明暗） */
export const EDITOR_THEME_IDS = [
  'auto',
  'github-light',
  'github-dark',
  'one-dark',
  'solarized-light',
  'solarized-dark',
  'high-contrast',
] as const
export type EditorThemeId = (typeof EDITOR_THEME_IDS)[number]

/** 实际生效的配色 ID（不含 auto） */
export type ResolvedEditorThemeId = Exclude<EditorThemeId, 'auto'>

export interface EditorThemeMeta {
  id: EditorThemeId
  label: string
  description: string
  /** auto 无固定明暗，展示时按当前应用主题解析 */
  isDark: boolean
}

export const EDITOR_THEME_META: Record<EditorThemeId, EditorThemeMeta> = {
  auto: {
    id: 'auto',
    label: '跟随应用',
    description: '随个人设置里的浅色 / 深色主题自动切换',
    isDark: false,
  },
  'github-light': {
    id: 'github-light',
    label: 'GitHub 浅色',
    description: '白底低饱和，长时间阅读不刺眼',
    isDark: false,
  },
  'github-dark': {
    id: 'github-dark',
    label: 'GitHub 深色',
    description: '深灰蓝底，与 GitHub 代码视图一致',
    isDark: true,
  },
  'one-dark': {
    id: 'one-dark',
    label: 'One Dark',
    description: 'Atom 经典深色，色彩分层明显',
    isDark: true,
  },
  'solarized-light': {
    id: 'solarized-light',
    label: 'Solarized 浅色',
    description: '米色底低对比，护眼取向',
    isDark: false,
  },
  'solarized-dark': {
    id: 'solarized-dark',
    label: 'Solarized 深色',
    description: '深青底，暖色关键字对照',
    isDark: true,
  },
  'high-contrast': {
    id: 'high-contrast',
    label: '高对比',
    description: '纯黑底高亮文字，弱光与视力辅助场景',
    isDark: true,
  },
}

export interface EditorPalette {
  id: ResolvedEditorThemeId
  isDark: boolean
  /** 编辑区背景 */
  bg: string
  /** 行号槽 / 折叠槽背景 */
  gutterBg: string
  /** 当前行底色 */
  activeLine: string
  /** 选区底色（半透明，叠在编辑器底色上） */
  selection: string
  text: string
  muted: string
  cursor: string
  /** 行号槽右边界线 */
  border: string
  /** 补全 / 提示弹层选中项底色 */
  accent: string
  keyword: string
  string: string
  comment: string
  number: string
  function: string
  type: string
  operator: string
  tag: string
  property: string
  variable: string
  invalid: string
}

const PALETTES: Record<ResolvedEditorThemeId, EditorPalette> = {
  'github-light': {
    id: 'github-light',
    isDark: false,
    bg: '#ffffff',
    gutterBg: '#f6f8fa',
    activeLine: '#f6f8fa',
    selection: 'rgba(9, 105, 218, 0.18)',
    text: '#1f2328',
    muted: '#6e7781',
    cursor: '#0969da',
    border: '#d1d9e0',
    accent: 'rgba(9, 105, 218, 0.10)',
    keyword: '#cf222e',
    string: '#0a3069',
    comment: '#6e7781',
    number: '#0550ae',
    function: '#8250df',
    type: '#953800',
    operator: '#57606a',
    tag: '#116329',
    property: '#0550ae',
    variable: '#953800',
    invalid: '#cf222e',
  },
  'github-dark': {
    id: 'github-dark',
    isDark: true,
    bg: '#0d1117',
    gutterBg: '#0d1117',
    activeLine: '#161b22',
    selection: 'rgba(56, 139, 253, 0.30)',
    text: '#e6edf3',
    muted: '#8b949e',
    cursor: '#58a6ff',
    border: '#30363d',
    accent: 'rgba(56, 139, 253, 0.18)',
    keyword: '#ff7b72',
    string: '#a5d6ff',
    comment: '#8b949e',
    number: '#79c0ff',
    function: '#d2a8ff',
    type: '#ffa657',
    operator: '#c9d1d9',
    tag: '#7ee787',
    property: '#79c0ff',
    variable: '#ffa657',
    invalid: '#ff7b72',
  },
  'one-dark': {
    id: 'one-dark',
    isDark: true,
    bg: '#282c34',
    gutterBg: '#282c34',
    activeLine: '#2c313c',
    selection: 'rgba(82, 139, 255, 0.28)',
    text: '#abb2bf',
    muted: '#7f848e',
    cursor: '#528bff',
    border: '#3e4451',
    accent: 'rgba(82, 139, 255, 0.16)',
    keyword: '#c678dd',
    string: '#98c379',
    comment: '#7f848e',
    number: '#d19a66',
    function: '#61afef',
    type: '#e5c07b',
    operator: '#56b6c2',
    tag: '#e06c75',
    property: '#e06c75',
    variable: '#e06c75',
    invalid: '#e06c75',
  },
  'solarized-light': {
    id: 'solarized-light',
    isDark: false,
    bg: '#fdf6e3',
    gutterBg: '#eee8d5',
    activeLine: '#eee8d5',
    selection: 'rgba(38, 139, 210, 0.18)',
    text: '#586e75',
    muted: '#93a1a1',
    cursor: '#268bd2',
    border: '#eee8d5',
    accent: 'rgba(38, 139, 210, 0.10)',
    keyword: '#859900',
    string: '#2aa198',
    comment: '#93a1a1',
    number: '#d33682',
    function: '#268bd2',
    type: '#b58900',
    operator: '#6c71c4',
    tag: '#268bd2',
    property: '#268bd2',
    variable: '#cb4b16',
    invalid: '#dc322f',
  },
  'solarized-dark': {
    id: 'solarized-dark',
    isDark: true,
    bg: '#002b36',
    gutterBg: '#073642',
    activeLine: '#073642',
    selection: 'rgba(38, 139, 210, 0.26)',
    text: '#93a1a1',
    muted: '#657b83',
    cursor: '#268bd2',
    border: '#073642',
    accent: 'rgba(38, 139, 210, 0.16)',
    keyword: '#859900',
    string: '#2aa198',
    comment: '#657b83',
    number: '#d33682',
    function: '#268bd2',
    type: '#b58900',
    operator: '#6c71c4',
    tag: '#268bd2',
    property: '#268bd2',
    variable: '#cb4b16',
    invalid: '#dc322f',
  },
  'high-contrast': {
    id: 'high-contrast',
    isDark: true,
    bg: '#000000',
    gutterBg: '#0a0a0a',
    activeLine: '#141414',
    selection: 'rgba(96, 165, 250, 0.40)',
    text: '#ffffff',
    muted: '#b3b3b3',
    cursor: '#facc15',
    border: '#525252',
    accent: 'rgba(250, 204, 21, 0.18)',
    keyword: '#ff7b72',
    string: '#7ee787',
    comment: '#b3b3b3',
    number: '#79c0ff',
    function: '#d2a8ff',
    type: '#ffd866',
    operator: '#e6edf3',
    tag: '#7ee787',
    property: '#79c0ff',
    variable: '#ffa657',
    invalid: '#ff7b72',
  },
}

/** auto → 按应用主题明暗落到 GitHub 同族（与全站 auto 落点一致） */
export function resolveEditorTheme(id: EditorThemeId, appIsDark: boolean): ResolvedEditorThemeId {
  if (id !== 'auto') return id
  return appIsDark ? 'github-dark' : 'github-light'
}

/** 取实际生效的色板；未知 ID 回退跟随应用（容错持久化脏数据） */
export function getEditorPalette(id: EditorThemeId, appIsDark: boolean): EditorPalette {
  const resolved = resolveEditorTheme(
    EDITOR_THEME_IDS.includes(id) ? id : 'auto',
    appIsDark,
  )
  return PALETTES[resolved]
}

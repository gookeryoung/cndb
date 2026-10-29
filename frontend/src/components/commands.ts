/**
 * 命令面板命令注册表（需求 0067 C2/C3）——GlobalSearch 命令模式（输入 `>` 前缀）的数据源。
 *
 * 每条命令只声明 key / 标题 / 关键词别名 / 执行动作；面板渲染与键盘导航不内联命令实现。
 * 全部命令为前端动作（路由跳转 / store / localStorage），不新增后端调用（C7）。
 */

import type { ThemePreference } from '@/theme/theme'
import type { SettingsTab } from '@/store'

/** 命令执行上下文 —— GlobalSearch 在渲染时注入，命令本身不依赖组件实例 */
export interface CommandContext {
  navigate: (path: string) => void
  /** 当前工作区 id；无工作区上下文（如 /admin、/help）时为 undefined */
  workspaceId: number | undefined
  /** ui store：打开个人设置弹窗（可带页签） */
  openSettings: (tab?: SettingsTab) => void
  /** theme store：写入主题偏好（含 auto，0066） */
  setThemeMode: (m: ThemePreference) => void
}

export interface Command {
  key: string
  title: string
  /** 子串匹配别名（含拼音 / 英文），与 title 一起参与过滤 */
  keywords?: string
  /** 需要工作区上下文：无 wid 时从命令列表剔除 */
  needsWorkspace?: boolean
  run: (ctx: CommandContext) => void
}

/** 首批命令集（0067 C3）。needsWorkspace 的命令在 /admin、/help 等无 wid 页面自动隐藏。 */
export function buildCommands(ctx: CommandContext): Command[] {
  const wid = ctx.workspaceId
  return [
    {
      key: 'new-table',
      title: '新建数据表',
      keywords: 'new table 建表 create',
      needsWorkspace: true,
      run: () => ctx.navigate(`/w/${wid}/tables?create=1`),
    },
    {
      key: 'new-document',
      title: '新建文档',
      keywords: 'new document 建文档 create',
      needsWorkspace: true,
      run: () => ctx.navigate(`/w/${wid}/documents?create=1`),
    },
    {
      key: 'new-workspace',
      title: '新建工作区',
      keywords: 'new workspace create',
      run: () => ctx.navigate('/w?create=1'),
    },
    {
      key: 'theme-light',
      title: '切换主题：浅色',
      keywords: 'theme light 主题 浅色',
      run: c => c.setThemeMode('github-light'),
    },
    {
      key: 'theme-dark',
      title: '切换主题：深色',
      keywords: 'theme dark 主题 深色',
      run: c => c.setThemeMode('github-dark'),
    },
    {
      key: 'theme-system',
      title: '切换主题：跟随系统',
      keywords: 'theme system auto 主题 跟随系统',
      run: c => c.setThemeMode('auto'),
    },
    {
      key: 'open-settings',
      title: '打开个人设置',
      keywords: 'settings 设置 profile',
      run: c => c.openSettings(),
    },
    {
      key: 'open-llm-settings',
      title: '打开大模型设置',
      keywords: 'llm ai 大模型 设置',
      run: c => c.openSettings('llm'),
    },
    {
      key: 'open-help',
      title: '打开帮助文档',
      keywords: 'help 帮助 文档',
      run: c => c.navigate('/help'),
    },
    {
      key: 'open-workspaces',
      title: '打开工作区列表',
      keywords: 'workspaces 工作区 主页 home',
      run: c => c.navigate('/w'),
    },
  ]
}

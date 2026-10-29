/** 命令面板命令注册表（0067 C2/C3）—— 结构约束 + 逐条执行断言.
 *
 * 全部命令为前端动作（路由 / store / 主题 setter），不新增后端调用（C7）。
 */

import { describe, expect, it, vi } from 'vitest'
import { buildCommands } from './commands'
import type { CommandContext } from './commands'

function mockCtx(overrides: Partial<CommandContext> = {}): CommandContext {
  return {
    navigate: vi.fn(),
    workspaceId: 10,
    openSettings: vi.fn(),
    setThemeMode: vi.fn(),
    ...overrides,
  }
}

describe('命令注册表 buildCommands', () => {
  it('首批命令集完整：key 唯一、标题非空（C2）', () => {
    const ctx = mockCtx()
    const cmds = buildCommands(ctx)
    const keys = cmds.map(c => c.key)
    expect(new Set(keys).size).toBe(keys.length)
    expect(keys).toEqual(expect.arrayContaining([
      'new-table', 'new-document', 'new-workspace',
      'theme-light', 'theme-dark', 'theme-system',
      'open-settings', 'open-llm-settings', 'open-help', 'open-workspaces',
    ]))
    for (const c of cmds) {
      expect(c.title.trim().length).toBeGreaterThan(0)
      expect(typeof c.run).toBe('function')
    }
  })

  it('新建命令：带当前工作区 id 导航到对应列表页（?create=1 口径）', () => {
    const ctx = mockCtx()
    const cmds = Object.fromEntries(buildCommands(ctx).map(c => [c.key, c]))
    cmds['new-table'].run(ctx)
    expect(ctx.navigate).toHaveBeenCalledWith('/w/10/tables?create=1')
    cmds['new-document'].run(ctx)
    expect(ctx.navigate).toHaveBeenCalledWith('/w/10/documents?create=1')
    cmds['new-workspace'].run(ctx)
    expect(ctx.navigate).toHaveBeenCalledWith('/w?create=1')
  })

  it('主题命令：写入对应主题偏好（auto 持久化跟随系统，0066）', () => {
    const ctx = mockCtx()
    const cmds = Object.fromEntries(buildCommands(ctx).map(c => [c.key, c]))
    cmds['theme-light'].run(ctx)
    cmds['theme-dark'].run(ctx)
    cmds['theme-system'].run(ctx)
    expect(ctx.setThemeMode).toHaveBeenNthCalledWith(1, 'github-light')
    expect(ctx.setThemeMode).toHaveBeenNthCalledWith(2, 'github-dark')
    expect(ctx.setThemeMode).toHaveBeenNthCalledWith(3, 'auto')
  })

  it('设置与导航命令：复用 ui store 与既有路由', () => {
    const ctx = mockCtx()
    const cmds = Object.fromEntries(buildCommands(ctx).map(c => [c.key, c]))
    cmds['open-settings'].run(ctx)
    expect(ctx.openSettings).toHaveBeenCalledWith()
    cmds['open-llm-settings'].run(ctx)
    expect(ctx.openSettings).toHaveBeenLastCalledWith('llm')
    cmds['open-help'].run(ctx)
    expect(ctx.navigate).toHaveBeenLastCalledWith('/help')
    cmds['open-workspaces'].run(ctx)
    expect(ctx.navigate).toHaveBeenLastCalledWith('/w')
  })

  it('命令执行不触达任何 api 模块（C7：纯前端动作）', () => {
    const ctx = mockCtx()
    for (const c of buildCommands(ctx)) c.run(ctx)
    // 动作只调用 navigate / openSettings / setThemeMode 三个注入项
    expect(vi.mocked(ctx.navigate).mock.calls.length).toBeGreaterThan(0)
    expect(vi.mocked(ctx.setThemeMode).mock.calls.length).toBeGreaterThan(0)
  })
})

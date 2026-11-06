/** DSL / 流水线编辑器（CodeMirror 6）外观扩展.
 *
 * 色板与元信息在 `editorThemes`（无 CodeMirror 依赖，可被设置面板与首屏安全引用）；
 * 本模块只承载需要 CodeMirror 运行时 API 的主题 / 语法高亮组装，
 * 保持为独立模块，避免把 @codemirror/* 静态链进主入口 chunk。
 */

import type { Extension } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

import type { EditorFontSettings } from './editorSettings'
import { getEditorPalette, type EditorPalette, type EditorThemeId, type ResolvedEditorThemeId } from './editorThemes'

/* ─────────────── 语法高亮 ─────────────── */

const highlightCache = new Map<ResolvedEditorThemeId, HighlightStyle>()

function highlightStyle(palette: EditorPalette): HighlightStyle {
  const cached = highlightCache.get(palette.id)
  if (cached) return cached
  const style = HighlightStyle.define([
    { tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.modifier], color: palette.keyword },
    { tag: [t.string, t.special(t.string), t.regexp], color: palette.string },
    {
      tag: [t.comment, t.lineComment, t.blockComment, t.docComment],
      color: palette.comment,
      fontStyle: 'italic',
    },
    { tag: [t.number, t.bool, t.null, t.atom, t.unit], color: palette.number },
    { tag: [t.function(t.variableName), t.function(t.propertyName), t.macroName], color: palette.function },
    { tag: [t.typeName, t.className, t.namespace, t.tagName], color: palette.type },
    { tag: [t.operator, t.punctuation, t.bracket], color: palette.operator },
    { tag: [t.propertyName, t.attributeName, t.labelName], color: palette.property },
    { tag: [t.variableName, t.name], color: palette.variable },
    { tag: [t.heading, t.strong, t.emphasis, t.link], color: palette.tag },
    { tag: t.invalid, color: palette.invalid, textDecoration: 'underline wavy' },
  ])
  highlightCache.set(palette.id, style)
  return style
}

/* ─────────────── 编辑器主题 ─────────────── */

/** 字号 'auto' 跟随全站字号；显式档位用 px 覆盖 */
function fontSizeCss(font: EditorFontSettings): string {
  return font.size === 'auto' ? '1em' : `${font.size}px`
}

const themeCache = new Map<string, Extension>()

function buildTheme(palette: EditorPalette, font: EditorFontSettings): Extension {
  const family = font.family
  const size = fontSizeCss(font)
  const key = `${palette.id}|${family}|${size}`
  const cached = themeCache.get(key)
  if (cached) return cached

  const theme = EditorView.theme(
    {
      '&': {
        backgroundColor: palette.bg,
        color: palette.text,
        fontSize: size,
      },
      '.cm-scroller': {
        fontFamily: family,
        fontSize: size,
        lineHeight: '1.65',
      },
      '.cm-content': {
        caretColor: palette.cursor,
        padding: '10px 0',
      },
      '.cm-line': {
        padding: '0 12px',
      },
      '&.cm-focused': { outline: 'none' },
      '.cm-cursor, .cm-dropCursor': { borderLeftColor: palette.cursor },
      '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
        backgroundColor: palette.selection,
      },
      '.cm-activeLine': { backgroundColor: palette.activeLine },
      '.cm-selectionMatch': { backgroundColor: palette.accent },
      '.cm-gutters': {
        backgroundColor: palette.gutterBg,
        color: palette.muted,
        borderRight: `1px solid ${palette.border}`,
      },
      '.cm-activeLineGutter': {
        backgroundColor: palette.activeLine,
        color: palette.text,
      },
      '.cm-lineNumbers .cm-gutterElement': { padding: '0 10px 0 14px' },
      '.cm-foldGutter .cm-gutterElement': { color: palette.muted },
      '.cm-matchingBracket, .cm-nonmatchingBracket': {
        backgroundColor: palette.accent,
        outline: `1px solid ${palette.border}`,
      },
      '.cm-tooltip': {
        backgroundColor: palette.bg,
        border: `1px solid ${palette.border}`,
        color: palette.text,
      },
      '.cm-tooltip-autocomplete > ul > li[aria-selected]': {
        backgroundColor: palette.accent,
        color: palette.text,
      },
      '.cm-tooltip-autocomplete .cm-completionDetail': { color: palette.muted },
      '.cm-panels': {
        backgroundColor: palette.gutterBg,
        color: palette.text,
      },
      '.cm-searchMatch': {
        backgroundColor: palette.accent,
        outline: `1px solid ${palette.border}`,
      },
    },
    { dark: palette.isDark },
  )

  themeCache.set(key, theme)
  return theme
}

/** 组装编辑器外观扩展：主题（颜色 / 字体 / 字号）+ 语法高亮 */
export function editorAppearanceExtensions(
  id: EditorThemeId,
  appIsDark: boolean,
  font: EditorFontSettings,
): Extension[] {
  const palette = getEditorPalette(id, appIsDark)
  return [buildTheme(palette, font), syntaxHighlighting(highlightStyle(palette))]
}

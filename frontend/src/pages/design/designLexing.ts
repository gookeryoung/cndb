/** 结构 DSL 的轻量词法扫描（无依赖的纯函数）.
 *
 * 单独成模块（ADR 0116 / 需求 0160 体积收口）：`stripCommentsAndStrings` 同时被
 * 补全（`designCompletion`）与缩进（`designIndent`）使用；若留在 `designCompletion` 里，
 * 缩进路径会把整个补全候选表（关键字 / 片段 / 签名，约 15 KB 源码）静态拽进
 * 设计编辑器首屏 chunk。拆出后补全表可按需加载，缩进仍为零成本。
 */

/** 去掉注释与字符串内容（等长替换为空格，保留换行；轻量扫描与上下文判定共用） */
export function stripCommentsAndStrings(doc: string): string {
  const out: string[] = []
  let state: 'code' | 'line' | 'block' | 'string' = 'code'
  for (let i = 0; i < doc.length; i += 1) {
    const ch = doc[i]
    const next = doc[i + 1]
    if (state === 'code') {
      if (ch === '/' && next === '/') {
        state = 'line'
        out.push(' ', ' ')
        i += 1
      } else if (ch === '/' && next === '*') {
        state = 'block'
        out.push(' ', ' ')
        i += 1
      } else if (ch === '"') {
        state = 'string'
        out.push(' ')
      } else {
        out.push(ch)
      }
      continue
    }
    if (state === 'line') {
      if (ch === '\n') {
        state = 'code'
        out.push('\n')
      } else {
        out.push(' ')
      }
      continue
    }
    if (state === 'block') {
      if (ch === '*' && next === '/') {
        state = 'code'
        out.push(' ', ' ')
        i += 1
      } else {
        out.push(ch === '\n' ? '\n' : ' ')
      }
      continue
    }
    // string
    if (ch === '"') {
      state = 'code'
      out.push(' ')
    } else {
      out.push(ch === '\n' ? '\n' : ' ')
    }
  }
  return out.join('')
}

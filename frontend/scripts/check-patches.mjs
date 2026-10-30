#!/usr/bin/env node
/**
 * 校验 pnpm patch 的落地结果（patch 漏打 / 被改坏时立刻失败）。
 *
 * `@rc-component/util` 的补丁（ADR 0074 D5，迁移自旧 rc-util 补丁）：
 * antd 6 的 rc-table 依赖 `@rc-component/util` 的 `isEqual`，原实现用全局
 * refSet 做循环引用检测，存在 DAG（同一子对象多条路径可达）误报为循环的问题
 * ——rc-table 的 columns 结构合法包含 Function 自引用，会触发误报。
 * 补丁改用「祖先链」追踪，只记录当前递归路径上的祖先。
 *
 * 为什么不用单测守：vitest 里 antd 解析到依赖的 **CJS(lib)**，而 dev/build
 * 用的是 **ES(es)**，只测一份代码可能漏掉另一份（历史实测坏版本仍能通过）。
 *
 * `react-dom@19.3.1` 的补丁（ADR 0074 P2）：React 19 的 delayed-commit 会在
 * 提交后经 scheduler 排一个读取 `window.event` 的回调；vitest 逐文件拆除 jsdom
 * 环境后该回调才触发即抛 "ReferenceError: window is not defined"（覆盖率模式必现，
 * 计为 unhandled error 使门禁失败）。补丁给三处 `window.event` 读取加
 * `typeof window` 守卫——浏览器中 window 恒存在，行为零变化；上游若修复可撤补丁。
 *
 * 历史背景：antd 5 时代还有一枚 `rc-field-form` 摇树补丁；antd 6 依赖已迁移
 * 到 `@rc-component/*`，该补丁随之删除（ADR 0074 D5）。若 P0 后实测发现
 * `@rc-component/form` 存在同类 barrel 不可摇树问题，再按 pnpm patch 流程重建。
 *
 * 依赖解析注意：pnpm 严格 node_modules 下项目无法直接解析 @rc-component/util，
 * 必须从 antd 的包位置解析。
 */
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const frontendDir = path.resolve(import.meta.dirname, '..')
const require = createRequire(import.meta.url)

/** @type {Array<{name: string, check: () => string[]}>} */
const CHECKS = [
  {
    name: '@rc-component/util isEqual',
    check: () => {
      const errors = []
      const antdPkg = require.resolve('antd/package.json')
      const antdRequire = createRequire(antdPkg)
      const targets = ['es/isEqual.js', 'lib/isEqual.js']
      for (const target of targets) {
        let entry
        try {
          entry = antdRequire.resolve(`@rc-component/util/${target}`)
        } catch {
          return [`无法解析 @rc-component/util/${target}（依赖是否已安装？跑 pnpm install）`]
        }
        const source = fs.readFileSync(entry, 'utf8')
        // 补丁要点：去掉全局 refSet（DAG 误报），改用祖先链
        // 注意注释里仍会提到 refSet，只能认代码形态：ancestors.includes(...)
        if (!/ancestors\.includes\(/.test(source)) {
          errors.push(`${entry}\n    仍是旧的 refSet 实现（循环引用误报补丁没生效）`)
        }
        if (/refSet\.has\(/.test(source)) {
          errors.push(`${entry}\n    仍存在 refSet 循环引用检测（DAG 误报未移除）`)
        }
      }
      return errors
    },
  },
  {
    name: 'react-dom window.event 守卫',
    check: () => {
      const errors = []
      const rdPkg = require.resolve('react-dom/package.json')
      const rdDir = path.dirname(rdPkg)
      // 仅 development 构建含 delayed-commit 的 window.event 遥测读取
      // （production 已剥离该代码，无需守卫）
      const entry = path.join(rdDir, 'cjs/react-dom-client.development.js')
      if (!fs.existsSync(entry)) {
        return [`${entry} 不存在（react-dom 版本是否已变？补丁需重新评估）`]
      }
      const source = fs.readFileSync(entry, 'utf8')
      // 守卫要点：delayed-commit 的 window.event 读取必须容错 jsdom 环境拆除
      if (!/typeof window !== "undefined" \? window\.event/.test(source)) {
        errors.push(`${entry}\n    缺少 window.event 守卫（jsdom 拆除竞态补丁没生效）`)
      }
      return errors
    },
  },
]

let failed = false
for (const { name, check } of CHECKS) {
  const errors = check()
  if (errors.length === 0) {
    console.log(`[check-patches] ${name} ok`)
    continue
  }
  failed = true
  for (const error of errors) console.error(`[check-patches] ${name} FAILED: ${error}`)
}
if (failed) {
  console.error(`\n[check-patches] 修复：确认 frontend/pnpm-workspace.yaml 的 patchedDependencies 后重跑 pnpm install`)
  console.error(`[check-patches] 参考 ${path.join(frontendDir, 'patches')} 下的补丁文件说明`)
  process.exit(1)
}

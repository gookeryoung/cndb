#!/usr/bin/env node
/**
 * 校验 pnpm patch 的落地结果（patch 漏打 / 被改坏时立刻失败）。
 *
 * 为什么需要它：`rc-field-form` 的补丁只为摇树（`sideEffects: false` + 去掉 barrel
 * 顶层的静态属性挂载），但**默认导出的 `React.forwardRef` 包装不能动** ——
 * antd 的 Form 靠 ref 取表单实例，去掉后 dev 环境会报
 * 「Function components cannot be given refs」，交互时报
 * 「Cannot add property current, object is not extensible」，登录页直接不可用。
 *
 * 为什么不用单测守：vitest 里 antd 解析到 rc-field-form 的 **CJS(lib)**，而 dev/build
 * 用的是 **ES(es)**，单测永远看不到出问题的那份代码（实测坏版本仍能通过）。
 *
 * 依赖解析注意：pnpm 严格 node_modules 下项目无法直接解析 rc-field-form，
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
    name: 'rc-field-form',
    check: () => {
      const errors = []
      const antdPkg = require.resolve('antd/package.json')
      const antdRequire = createRequire(antdPkg)
      let entry
      try {
        entry = antdRequire.resolve('rc-field-form/es/index.js')
      } catch {
        return ['无法解析 rc-field-form/es/index.js（依赖是否已安装？跑 pnpm install）']
      }
      const source = fs.readFileSync(entry, 'utf8')
      if (!/React\.forwardRef\(\s*FieldForm\s*\)/.test(source)) {
        errors.push(
          `${entry}\n    默认导出缺少 React.forwardRef 包装（antd Form 的 ref 会失效，登录页不可用）`,
        )
      }
      // 只认「行首的赋值语句」；补丁注释里也提到 RefForm.FormProvider = …
      if (/^\s*RefForm\.\w+\s*=/m.test(source)) {
        errors.push(`${entry}\n    仍有静态属性挂载（barrel 不可摇树，主入口会重新涨回去）`)
      }
      const pkgPath = path.join(path.dirname(path.dirname(entry)), 'package.json')
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
      if (pkg.sideEffects !== false) {
        errors.push(`${pkgPath}\n    缺少 "sideEffects": false（摇树失效）`)
      }
      return errors
    },
  },
  {
    name: 'rc-util isEqual',
    check: () => {
      const errors = []
      const antdPkg = require.resolve('antd/package.json')
      const antdRequire = createRequire(antdPkg)
      let entry
      try {
        entry = antdRequire.resolve('rc-util/es/isEqual.js')
      } catch {
        return ['无法解析 rc-util/es/isEqual.js（依赖是否已安装？跑 pnpm install）']
      }
      const source = fs.readFileSync(entry, 'utf8')
      // 补丁要点：去掉全局 refSet（DAG 误报），改用祖先链
      // 注意注释里仍会提到 refSet，只能认代码形态：ancestors.includes(...)
      if (!/ancestors\.includes\(/.test(source)) {
        errors.push(`${entry}\n    仍是旧的 refSet 实现（循环引用误报补丁没生效）`)
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

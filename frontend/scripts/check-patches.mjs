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
 * 到 `@rc-component/*`，该补丁随之删除（ADR 0074 D5）。
 *
 * `@rc-component/form@1.8.6` 的补丁（ADR 0116 C5）：antd 6 的表单入口把成员挂到
 * `RefForm.Field = Field` 这类属性赋值上，ES barrel 因此不可摇树，入口静态带上约
 * 46 KB 原始体积。补丁移除属性赋值、保留 named export 与默认导出，并给 package.json
 * 补 `sideEffects: false`；行为不变，仅让未被引用的成员可被 tree-shaking 去掉。
 *
 * `pptx-preview@1.0.7` 的补丁（需求 0128 PPTX 在线预览 / 放映）：
 * 1) 库解析了 `<a:bodyPr wrap="none">`（不换行，文本框可溢出显示）却从未使用该属性，
 *    所有文本框都按固定宽度 `word-break: break-word` 折行——PPT 里靠 `wrap="none"`
 *    保持单行的标签（如「火工依赖度」）被折成两行并与下方文字重叠。补丁在文本渲染处按
 *    `props.wrap === 'none'` 追加 `white-space: nowrap`（宽度与居中不变，溢出可见）。
 * 2) 库把 `a:off` / `a:ext` 换算后的几何值 `Math.round` 成整数 pt，再整体按视口缩放：
 *    每个元素的左/上坐标与宽/高各被独立取整（误差 ≤0.5pt，缩放后约 1px），相邻元素
 *    因此出现「上下高度 / 左右宽度」的细微错位；段落顶边距 `floor(0.2em)` 又按字号
 *    产生不同下移。补丁去掉这两类整数取整，保留 EMU 换算后的精确小数。
 * 其余文本框与形状行为不变；上游修复后可撤补丁。
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
    name: '@rc-component/form 入口可摇树',
    check: () => {
      const antdPkg = require.resolve('antd/package.json')
      const antdRequire = createRequire(antdPkg)
      let entry
      try {
        entry = antdRequire.resolve('@rc-component/form/es/index.js')
      } catch {
        return ['无法解析 @rc-component/form/es/index.js（依赖是否已安装？跑 pnpm install）']
      }
      const source = fs.readFileSync(entry, 'utf8')
      const errors = []
      // 补丁要点：移除 `RefForm.Field = ...` 等属性赋值，保留 named export 与默认导出
      if (/RefForm\.(Field|List|FormProvider|useForm|useWatch)\s*=/.test(source)) {
        errors.push(`${entry}\n    入口仍把成员挂到 RefForm 上（barrel 不可摇树，入口体积会反弹）`)
      }
      const pkgPath = path.resolve(path.dirname(entry), '..', 'package.json')
      if (!fs.readFileSync(pkgPath, 'utf8').includes('"sideEffects": false')) {
        errors.push(`${pkgPath}\n    缺少 sideEffects: false（tree-shaking 不生效）`)
      }
      return errors
    },
  },
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
    name: 'pptx-preview bodyPr wrap=none',
    check: () => {
      let entry
      try {
        const pkg = require.resolve('pptx-preview/package.json')
        entry = path.resolve(path.dirname(pkg), 'dist/pptx-preview.es.js')
      } catch {
        return ['无法解析 pptx-preview/package.json（依赖是否已安装？跑 pnpm install）']
      }
      if (!fs.existsSync(entry)) {
        return [`${entry} 不存在（pptx-preview 版本是否已变？补丁需重新评估）`]
      }
      const source = fs.readFileSync(entry, 'utf8')
      const errors = []
      // 补丁要点 1：仅对 wrap="none" 的文本框关闭折行，其他文本框行为不变
      if (!/"none"===s\.wrap&&h\.style\.setProperty\("white-space","nowrap"\)/.test(source)) {
        errors.push(`${entry}\n    缺少 wrap=none 的 white-space 补丁（放映/预览文字会折行重叠）`)
      }
      // 补丁要点 2：形状几何不再取整，段落顶边距不再 floor
      if (/x:Math\.round\(h\(parseInt\(/.test(source)) {
        errors.push(`${entry}\n    形状坐标/尺寸仍被 Math.round 取整（元素会出现 ±1px 的细微错位）`)
      }
      if (!source.includes('.2*u()')) {
        errors.push(`${entry}\n    段落顶边距仍按字号向下取整（文字会整体偏下）`)
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

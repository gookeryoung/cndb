// ESLint 配置 —— 面向 React + TypeScript + Vite 项目.
// 使用 eslint.config.js 扁平配置（ESLint 9+ 格式）.
//
// 运行: pnpm lint (检查) | pnpm lint:fix (自动修复)

import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import testingLibrary from 'eslint-plugin-testing-library'

export default tseslint.config(
  // 忽略文件（优先级最高）
  { ignores: ['dist', 'node_modules', 'coverage', 'playwright-report', '.local-ms-playwright', '.playwright-browsers'] },

  // JavaScript 推荐规则
  js.configs.recommended,

  // TypeScript 推荐规则
  ...tseslint.configs.recommended,

  // React 规则
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { react },
    settings: { react: { version: 'detect' } },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs['jsx-runtime'].rules,
      // 组件 props 不需要显式声明
      'react/prop-types': 'off',
      // 允许使用 target="_blank"（内部统一由 antd/Popconfirm 封装）
      'react/no-unknown-property': 'off',
    },
  },

  // React Hooks 规则
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },

  // Vite React Refresh 规则
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-refresh': reactRefresh },
    rules: {
      ...reactRefresh.configs.vite.rules,
      // 关闭：允许 Provider 文件同时导出 Context 和工具函数
      'react-refresh/only-export-components': 'off',
    },
  },

  // 项目自定义规则（最后覆盖）
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        localStorage: 'readonly',
        console: 'readonly',
      },
    },
    rules: {
      // 允许 `any`（渐进迁移中）
      '@typescript-eslint/no-explicit-any': 'off',
      // 允许未使用的变量（以 _ 开头）
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // 允许空函数
      '@typescript-eslint/no-empty-function': 'off',
      // 允许非空断言 `!`
      '@typescript-eslint/no-non-null-assertion': 'off',
      // 允许 `Record<string, unknown>` 作为宽泛类型
      '@typescript-eslint/consistent-type-definitions': 'off',
      // 不强制 `import type`（项目中混用）
      '@typescript-eslint/consistent-type-imports': 'off',
      // 允许 require
      '@typescript-eslint/no-require-imports': 'off',
      // 允许 TS 注释
      '@typescript-eslint/ban-ts-comment': 'off',
    },
  },

  // ── 体积防线：表页闭包入口不得静态链入「点了才出现」的交互面板 ────────────
  // 这些 panel（Dialog/Modal/Drawer/Manager/Editor 结尾的组件）只在用户操作后出现，
  // 一旦被 GridPage.tsx 静态 import，就会被打进 GridPage chunk 随首屏一起下载，
  // 每次功能迭代线性膨胀 —— 2026-10-10 就是这样把 GridPage 顶到 43KB 超预算的。
  // 正确写法是 GridPage.tsx 里已有的 const X = lazy(() => import('...')) + Suspense。
  // 真正的硬性兜底仍是 bundle:budget（见 scripts/bundle-budget.mjs）：本规则拦的是最常犯的那一步，
  // 间接依赖（A 静态引 B，B 静态引面板）由预算门禁兜住。
  {
    files: ['src/pages/grid/GridPage.tsx', 'src/pages/grid/gridViewModals.tsx'],
    rules: {
      '@typescript-eslint/no-restricted-imports': ['error', {
        patterns: [{
          group: [
            '**/*Dialog', '**/*Dialog/index',
            '**/*Modal', '**/*Modal/index',
            '**/*Drawer', '**/*Drawer/index',
            '**/*Manager', '**/*Manager/index',
            '**/*Editor', '**/*Editor/index',
          ],
          message:
            '按需打开的交互面板不得被表页入口静态引入（会进 GridPage chunk 拖累首屏）。' +
            "请改为：const X = lazy(() => import('...'))，并在渲染处用 <Suspense> 包裹。" +
            '类型是编译期信息，`import type` 不受此限制。',
          // 只从面板模块取类型不应被拦（如 import type { FilterRule } from '.../ViewConfigDialog'）；
          // 该选项必须放在 pattern 对象内部，放在外层 options 会导致 ESLint schema 校验失败
          allowTypeImports: true,
        }],
      }],
    },
  },

  // Node.js 脚本（coverage 校验等构建期脚本）—— 提供 Node 全局
  {
    files: ['scripts/**/*.mjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        console: 'readonly',
      },
    },
  },

  // E2E 测试代码放宽规则（Playwright fixture 类型天然需要 any / 声明但不用的辅助变量）
  {
    files: ['tests/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },

  // Testing Library 组件测试规则 —— 防"同步 getBy 与异步渲染竞态"（AntD portal 类 UI 异步挂载，
  // 本地机器快掩盖、CI 稳定失败，见 GridCell.test.tsx 已保存断言案例）
  {
    files: ['src/**/*.{test,spec}.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    plugins: { 'testing-library': testingLibrary },
    rules: {
      // 异步查询（findBy*）必须 await，事件后的出现/消失断言禁止同步 getBy/queryBy 抢跑
      'testing-library/await-async-queries': 'error',
      'testing-library/await-async-utils': 'error',
      // 不允许 await 同步查询（掩盖真实异步时序）
      'testing-library/no-await-sync-queries': 'error',
      // waitFor 回调内禁止副作用（setState/firEvent 等），防止轮询放大竞态
      'testing-library/no-wait-for-side-effects': 'error',
      // 出现断言优先 findBy 而非 waitFor(getBy)
      'testing-library/prefer-find-by': 'error',
    },
  },
)

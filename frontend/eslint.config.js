// ESLint 配置 —— 面向 React + TypeScript + Vite 项目.
// 使用 eslint.config.js 扁平配置（ESLint 9+ 格式）.
//
// 运行: pnpm lint (检查) | pnpm lint:fix (自动修复)

import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default tseslint.config(
  // 忽略文件（优先级最高）
  { ignores: ['dist', 'node_modules', 'coverage', 'playwright-report'] },

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

  // E2E 测试代码放宽规则（Playwright fixture 类型天然需要 any）
  {
    files: ['tests/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
)

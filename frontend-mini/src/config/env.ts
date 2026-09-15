/** API 基础地址 —— 从环境变量或构建配置读取. */
// Taro 4 构建时会将 config/dev.js 和 config/prod.js 的 defineConstants 注入
// VITE_API_BASE_URL 由 config/index.js 中的 env.defineConstants 机制提供
declare const process: { env: Record<string, string> }

const baseUrl = process.env.VITE_API_BASE_URL || (
  process.env.NODE_ENV === 'production'
    ? 'https://api.yourdomain.com/api'
    : 'http://localhost:8000/api'
)

export const API_BASE_URL = baseUrl

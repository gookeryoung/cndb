import axios from 'axios'

// 创建 axios 实例，统一 baseURL 和默认配置
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 响应拦截器 - 统一错误处理
api.interceptors.response.use(
  (res) => res,
  (err) => {
    // 401 未授权：简单提示（本项目暂无鉴权，仅预留接口）
    if (err.response?.status === 401) {
      console.warn('401 未授权，请检查后端鉴权配置')
    }
    console.error('API Error:', err.response?.data || err.message)
    return Promise.reject(err)
  },
)

export default api

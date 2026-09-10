import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 代理所有 /api 请求到 FastAPI 后端
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 构建产物直接输出到后端 static 目录，由 FastAPI 统一 serve
    outDir: path.resolve(__dirname, '../src/pyweb_template/static'),
    emptyOutDir: true,
  },
})

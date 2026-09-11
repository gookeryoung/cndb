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
      '/api': {
        target: 'http://127.0.0.1:8772',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../src/cndb/static'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 对象式 manualChunks：顶层 node_modules 包名直接映射到 chunk。
        // 避免函数式写法因路径包含关系导致"跨包循环引用"警告。
        // 业务页面按路由 lazy import 自动拆分（见 App.tsx）。
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          tanstack: ['@tanstack/react-query'],
        },
      },
    },
  },
})
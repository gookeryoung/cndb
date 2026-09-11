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
        // 分包策略：稳定第三方库独立 chunk，利用浏览器缓存
        // 业务页面按路由 lazy import 自动分包（见 App.tsx）
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react-router-dom') || id.includes('react-dom') || id.includes('react/')) {
              return 'react'
            }
            if (id.includes('antd') || id.includes('@ant-design/icons')) {
              return 'antd'
            }
            if (id.includes('@tanstack')) {
              return 'tanstack'
            }
            if (id.includes('dayjs')) {
              return 'dayjs'
            }
            if (id.includes('axios')) {
              return 'axios'
            }
            // 其余 node_modules 打入 vendor
            return 'vendor'
          }
          // 业务代码不手动分包，按路由 lazy import 自动切分
        },
      },
    },
  },
})
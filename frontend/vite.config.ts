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
    // 现代浏览器目标：去掉 asyncIterator/Map/Set/Proxy 等老 polyfill
    target: 'es2022',
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 不使用 manualChunks —— antd 内部模块间有大量交叉引用，
        // 手动拆分无论怎么划分都会产生循环依赖，触发 ES module
        // 暂时性死区导致运行时 TypeError。交给 Rollup 自行分析依赖图。
      },
    },
  },
})
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// antd 重型 ESM 子模块 —— 只放 lazy 路由才需要的组件
// 原则：源码体积大 + 非首屏必需（LoginPage/MainLayout/WorkspaceList 不用）
// Form/Modal/Input 虽然体积不小但首屏需要，归 core
const ANTD_HEAVY_ES_MODULES = [
  '/es/table/',       // 163KB — 虚拟滚动 + 固定列 + 排序筛选（GridPage/ReportsPage）
  '/es/date-picker/', // 147KB — 日历面板 + dayjs（GridCell/RowDetailDrawer）
  '/es/select/',      //  68KB — 下拉选择 + 搜索（GridCell/RowDetailDrawer）
  '/es/upload/',      //  62KB — 文件上传 + 拖拽（ImportExportDialog）
  '/es/transfer/',    //  51KB — 穿梭框（暂未用但预留在 antd 主包里）
]

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
        // 函数式 manualChunks（精确路径匹配）：
        // - react/react-dom/react-router-dom → react
        // - @ant-design/icons → antd-icons
        // - antd 重型子模块 → antd-heavy（Table/Form/DatePicker/Upload/Select/Input/Modal）
        // - antd 其余（ConfigProvider/theme/cssinjs/Button/Space/Tag/Typography...）→ antd-core
        // - @tanstack/react-query → tanstack
        manualChunks(id) {
          if (!id.includes('node_modules')) return

          // React 生态
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/') ||
            id.includes('node_modules/react-router-dom/') ||
            id.includes('node_modules/react-router/')
          ) {
            return 'react'
          }

          // @ant-design/icons —— 独立 chunk 便于单独缓存
          if (id.includes('node_modules/@ant-design/icons/')) {
            return 'antd-icons'
          }

          // antd 主包
          if (id.includes('node_modules/antd/')) {
            if (ANTD_HEAVY_ES_MODULES.some(m => id.includes(m))) {
              return 'antd-heavy'
            }
            return 'antd-core'
          }

          // @ant-design/cssinjs/static 是 antd 运行时（ConfigProvider/theme 依赖）
          if (
            id.includes('node_modules/@ant-design/cssinjs/') ||
            id.includes('node_modules/@ant-design/static/')
          ) {
            return 'antd-core'
          }

          // TanStack Query
          if (id.includes('node_modules/@tanstack/')) {
            return 'tanstack'
          }
        },
      },
    },
  },
})
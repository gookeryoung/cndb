import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// ── 前端构建产物同步到 src/cndb/static（保留 .gitkeep）────────────────
// Vite 直接把 outDir 指向 src/cndb/static 且 emptyOutDir=true 时，
// 构建会先清空目标目录，.gitkeep 被抹掉，后续 hatchling 打包失败。
// 这里用中间目录 dist 构建，构建完成后再同步到静态目录，同时保留
// .gitkeep 哨兵文件。
function syncStaticPlugin() {
  return {
    name: 'sync-static',
    closeBundle() {
      // vitest 会复用本配置的插件链，closeBundle 在测试结束时也会触发，
      // 这里跳过，避免运行测试时误同步构建产物
      if (process.env.VITEST) return
      const repoRoot = path.resolve(__dirname, '..')
      const distDir = path.resolve(__dirname, 'dist')
      const staticDir = path.resolve(repoRoot, 'src/cndb/static')
      const gitkeepPath = path.join(staticDir, '.gitkeep')

      // 1) 确保目标目录存在且 .gitkeep 不丢
      fs.mkdirSync(staticDir, { recursive: true })
      const hadGitkeep = fs.existsSync(gitkeepPath)

      // 2) 清空 static 目录下的旧产物（保留 .gitkeep）
      for (const entry of fs.readdirSync(staticDir)) {
        if (entry === '.gitkeep') continue
        const full = path.join(staticDir, entry)
        fs.rmSync(full, { recursive: true, force: true })
      }

      // 3) 把 dist/* 复制过去
      if (fs.existsSync(distDir)) {
        for (const entry of fs.readdirSync(distDir)) {
          fs.cpSync(
            path.join(distDir, entry),
            path.join(staticDir, entry),
            { recursive: true },
          )
        }
      }

      // 4) 兜底保证 .gitkeep 存在
      if (!hadGitkeep) {
        fs.writeFileSync(gitkeepPath, '')
      }

      console.log(
        `[sync-static] ${path.relative(repoRoot, distDir)} → ${path.relative(repoRoot, staticDir)}` +
        (hadGitkeep ? '（.gitkeep 已保留）' : '（.gitkeep 已补回）'),
      )
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    // bundle 体积分析：仅 `vite build --mode analyze`（pnpm analyze）时启用，
    // 报告输出到 frontend/stats.html（dist 外，避免被 syncStaticPlugin 同步到后端 static）
    ...(mode === 'analyze'
      ? [visualizer({
        filename: path.resolve(__dirname, 'stats.html'),
        gzipSize: true,
        brotliSize: true,
        open: false,
      })]
      : []),
    syncStaticPlugin(),
  ],
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
    // 中间构建目录（由 syncStaticPlugin 在 closeBundle 后同步到 src/cndb/static）
    outDir: path.resolve(__dirname, 'dist'),
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
  // ── Vitest 测试配置（不影响构建行为）────────────────────────────────
  test: {
    // antd 5 组件在 happy-dom 下兼容性欠佳，选择 jsdom
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // 每个用例结束后自动 restore 所有 spyOn mock，防止异常分支的 mock 泄漏到后续用例
    restoreMocks: true,
    // 全量并发（16 workers）下 jsdom + antd 渲染负载高，部分含
    // mutation→message→navigate 长链路的用例会超过默认 5s（2026-09 实测
    // 861 例中 8 例偶发超时，单文件运行均在 1s 内）。放宽到 10s 只影响
    // 超时阈值，不改变断言语义。
    testTimeout: 10_000,
    // 单元/组件测试遵循就近放置约定：src 下的 *.test.ts(x)
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // worker 数实测（24 核）：16 最优（24.7s）；23 因 fork 创建+内存压力回吐收益（27.7s）；
    // 12 与默认持平（2026-09 实测数据）。上限 16，低核 CI 机器按核数降档防过订阅
    maxWorkers: Math.min(16, os.availableParallelism()),
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      // 测试设施与类型声明不纳入覆盖率统计
      exclude: [
        'src/test/**',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.spec.{ts,tsx}',
        'src/**/*.d.ts',
        'src/vite-env.d.ts',
      ],
      reporter: ['text', 'json-summary', 'html'],
      reportsDirectory: 'coverage',
    },
  },
}))
import { defineConfig, type Plugin } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// ── 构建产物同步到 src/cndb/static（保留 .gitkeep 哨兵）────────────────
// 直接用 outDir=static 且 emptyOutDir 会抹掉 .gitkeep 导致 hatchling 打包失败，
// 故先构建到中间目录 dist，完成后再同步过去。
function syncStaticPlugin(): Plugin {
  return {
    name: 'sync-static',
    closeBundle() {
      // vitest 复用插件链，测试结束也会触发 closeBundle，故跳过以免误同步
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
        // .vite/manifest.json 供 bundle-budget.mjs 做「超限归因」（模块→chunk 映射），
        // 不参与线上静态资源分发，不同步到后端 static（避免进 wheel）
        if (entry === '.gitkeep' || entry === '.vite') continue
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

// ── 容器 CPU 配额感知的 worker 上限 ──────────────────────────────────
// os.availableParallelism() 只反映宿主核数，而云端容器常见「宿主几十核、配额 2~4 核」，
// 按宿主核数开会严重超订。这里读 cgroup v2/v1 的 CPU 配额求真实核数，无配额时回退宿主核数。
function effectiveCpus(): number {
  const host = os.availableParallelism()
  let quota = Number.POSITIVE_INFINITY
  try {
    const v2 = fs.readFileSync('/sys/fs/cgroup/cpu.max', 'utf8').trim().split(/\s+/)
    if (v2[0] === 'max') {
      // 未设上限，再探 cgroup v1（部分集群 v2 挂了但 v1 仍有值）
      const q = Number(fs.readFileSync('/sys/fs/cgroup/cpu/cpu.cfs_quota_us', 'utf8').trim())
      const p = Number(fs.readFileSync('/sys/fs/cgroup/cpu/cpu.cfs_period_us', 'utf8').trim())
      if (q > 0 && p > 0) quota = q / p
    } else {
      quota = Number(v2[0]) / Number(v2[1] ?? 100_000)
    }
  } catch {
    // 非 Linux 或无 cgroup：忽略，保持宿主核数
  }
  const byQuota = Number.isFinite(quota) ? Math.floor(quota) : host
  return Math.max(1, Math.min(host, byQuota))
}

// worker 数：VITEST_MAX_WORKERS 优先（云端按实例档位注入），否则取 min(16, 配额核数)——
// 16 为本机 24 核实测最优值，上限同时防低核机器超订。
function resolveMaxWorkers(): number {
  const override = Number(process.env.VITEST_MAX_WORKERS)
  if (Number.isFinite(override) && override > 0) return Math.floor(override)
  return Math.min(16, effectiveCpus())
}

// ── chunk 模块级体积归属表 ───────────────────────────────────────────
// bundle-budget.mjs 超限时需归因「哪个源文件导致变大」；Vite 的 build.manifest 只到
// chunk 粒度，故用 Rollup OutputChunk.modules 自建 dist/.vite/chunk-modules.json
// （{ "<chunk>": [{ id, bytes }] }）。该目录不同步到后端 static，不会进 wheel。
function chunkAttributionPlugin(): Plugin {
  return {
    name: 'chunk-attribution',
    apply: 'build',
    generateBundle(_options, bundle) {
      const table: Record<string, Array<{ id: string; bytes: number }>> = {}
      for (const [fileName, chunk] of Object.entries(bundle)) {
        if (chunk.type !== 'chunk') continue
        table[fileName] = Object.entries(chunk.modules ?? {}).map(([id, info]) => ({
          id,
          bytes: info.originalLength ?? 0,
        }))
      }
      const outDir = path.resolve(__dirname, 'dist/.vite')
      fs.mkdirSync(outDir, { recursive: true })
      fs.writeFileSync(path.join(outDir, 'chunk-modules.json'), JSON.stringify(table))
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    // 体积分析：仅 pnpm analyze（--mode analyze）启用，报告写 frontend/stats.html（dist 外，不进后端 static）
    ...(mode === 'analyze'
      ? [visualizer({
        filename: path.resolve(__dirname, 'stats.html'),
        gzipSize: true,
        brotliSize: true,
        open: false,
      })]
      : []),
    chunkAttributionPlugin(),
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
        // 不用 manualChunks：antd 模块间交叉引用多，手动拆分会产生循环依赖，
        // 触发 ES module 暂时性死区 TypeError，交给 Rollup 自行分析依赖图。
      },
    },
  },
  // ── Vitest 测试配置（不影响构建行为）────────────────────────────────
  test: {
    // antd 5 组件在 happy-dom 下兼容性欠佳，选择 jsdom
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // 用例结束后自动 restore spyOn mock，防止 mock 泄漏到后续用例
    restoreMocks: true,
    // 高并发下 jsdom + antd 渲染负载高，长链路用例偶发超过默认 5s；放宽到 10s
    // 仅改超时阈值，不改变断言语义。
    testTimeout: 10_000,
    // 单元/组件测试遵循就近放置约定：src 下的 *.test.ts(x)
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // worker 数按容器真实 CPU 配额求值（见 effectiveCpus），可用 VITEST_MAX_WORKERS 覆盖。
    maxWorkers: resolveMaxWorkers(),
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
      // 恒定只出 text + json-summary（后者供 check-coverage.mjs）；html 会写数百文件，
      // 默认关闭，需要浏览时用 pnpm test:coverage:html（make fcov-html）。
      reporter: ['text', 'json-summary'],
      reportsDirectory: 'coverage',
    },
  },
}))

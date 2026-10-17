import { defineConfig, type Plugin } from 'vitest/config'
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
function syncStaticPlugin(): Plugin {
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
// os.availableParallelism() 只反映宿主 CPU 数，不感知容器 cgroup 配额；云端
// （CodeUp / TRAE 云端容器）常见「宿主几十核、配额 2~4 核」→ 按宿主核数开
// 16 个 worker 会严重超订，上下文切换与内存压力反而更慢。这里读 cgroup
// v2/v1 的 CPU 配额求真实可用核数，非 Linux / 无 cgroup 时回退宿主核数。
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

// worker 数：VITEST_MAX_WORKERS 显式覆盖优先（云端流水线按实例档位注入）；
// 否则取「配额核数」与 16 的较小值——本机 24 核实测 16 最优（23 因 fork
// 创建 + 内存压力回吐收益），上限 16 同时防低核机器超订。
function resolveMaxWorkers(): number {
  const override = Number(process.env.VITEST_MAX_WORKERS)
  if (Number.isFinite(override) && override > 0) return Math.floor(override)
  return Math.min(16, effectiveCpus())
}

// ── chunk 模块级体积归属表 ───────────────────────────────────────────
// scripts/bundle-budget.mjs 超限时需要回答「是哪个源文件让包变大了」。
// Vite 自带的 build.manifest 只有 chunk 粒度（不含模块），故用 Rollup 的
// OutputChunk.modules 自建映射表：dist/.vite/chunk-modules.json
// { "<chunk 文件名>": [{ id, bytes }] }，id 为模块绝对路径，bytes 为原始字节。
// 该目录不参与同步到后端 static（见 syncStaticPlugin），不会被打进 wheel。
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
    // worker 数按「容器真实 CPU 配额」求值（见上方 effectiveCpus），可用
    // VITEST_MAX_WORKERS 覆盖。避免云端容器把宿主核数当核数用导致超订。
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
      // 恒定只出 text + json-summary：前者供终端阅读，后者是 check-coverage.mjs 的输入。
      // html 报告会在 frontend/coverage 下写数百个文件，耗时纯属浪费（本地沙箱还会因
      // 「批量删除 > 50 文件」被 safe-delete shim 拦下），故默认关闭；需要浏览时用
      // `pnpm test:coverage:html`（make fcov-html）经 CLI 追加 html reporter。
      reporter: ['text', 'json-summary'],
      reportsDirectory: 'coverage',
    },
  },
}))

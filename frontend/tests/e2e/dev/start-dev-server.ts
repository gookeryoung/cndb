/**
 * dev 模式 E2E 的 vite dev 托管器（自托管 + 显式轮询端口）.
 *
 * 为什么不用 Playwright 的 webServer 托管 vite：Windows 上经 `pnpm exec`（cmd 包装）
 * 启动时，实测探活命中后进程仍会退场，用例一开始就 `ERR_CONNECTION_REFUSED`，
 * 且无任何 crash 输出。直接 `node vite.js` 裸起 + 轮询 `GET /` 直到 200 最稳。
 *
 * 后端 API 代理：`vite.config.ts` 的 `/api` target 读 `CNDB_API_TARGET`
 * （dev 模式 E2E 指到 e2e-server.py 起的 :8000；开发者本地默认 :8772）。
 */
import { createServer, request as httpRequest } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import process from "node:process";

// import.meta.dirname = tests/e2e/dev → 上三级是 frontend 根
const FRONTEND_DIR = path.resolve(import.meta.dirname, "../../..");
const VITE_BIN = path.join(FRONTEND_DIR, "node_modules", "vite", "bin", "vite.js");

export const DEV_PORT = 5175;
export const DEV_BASE = `http://127.0.0.1:${DEV_PORT}`;
/** Playwright webServer 托管的隔离后端 */
export const API_BASE = "http://127.0.0.1:8000";

let viteProcess: ChildProcess | null = null;

/** 轮询 `GET /` 直到 200（vite dev 首次预热在 Windows 上可能需要数秒）. */
async function waitUntilReady(deadlineMs: number): Promise<void> {
  const deadline = Date.now() + deadlineMs;
  let lastError = "";
  while (Date.now() < deadline) {
    if (viteProcess?.exitCode != null) {
      throw new Error(`vite dev 进程已退出 (code=${viteProcess.exitCode})`);
    }
    const ok = await new Promise<boolean>(resolve => {
      const request = httpRequest(`${DEV_BASE}/`, { timeout: 3000 }, response => {
        response.resume();
        resolve((response.statusCode ?? 500) < 500);
      });
      request.on("error", error => {
        lastError = String(error);
        resolve(false);
      });
      request.on("timeout", () => {
        request.destroy();
        resolve(false);
      });
      request.end();
    });
    if (ok) return;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`vite dev 未在 ${deadlineMs}ms 内就绪（最后错误: ${lastError}）`);
}

/** 起 vite dev 并等到可访问；幂等（已启动则直接复用）. */
export async function startDevServer(): Promise<void> {
  if (viteProcess) return;
  viteProcess = spawn(
    process.execPath,
    [VITE_BIN, "--host", "127.0.0.1", "--port", String(DEV_PORT), "--strictPort"],
    {
      cwd: FRONTEND_DIR,
      env: { ...process.env, CNDB_API_TARGET: API_BASE },
      stdio: "inherit",
    },
  );
  await waitUntilReady(180_000);
}

/** 关闭 vite dev（幂等；TerminateProcess 直接杀，测试进程结束时也无残留）. */
export async function stopDevServer(): Promise<void> {
  const child = viteProcess;
  viteProcess = null;
  if (child && child.exitCode == null) {
    child.kill();
  }
  await new Promise(resolve => setTimeout(resolve, 300));
}

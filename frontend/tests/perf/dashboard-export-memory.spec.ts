/**
 * 超大画布导出的内存峰值剖析（ADR 0023 / 原 0077 P0 遗留问题的深挖，opt-in、非门禁）。
 *
 * 与 `dashboard-export.spec.ts`（耗时）互补，这里只关心内存：
 * - **分类采样**：Linux 上按 `--type=` 把 Chromium 进程分成 browser / renderer / gpu，
 *   25ms 采一次 RSS —— 渲染进程才是画布位图所在，总量会被浏览器主进程摊薄；
 * - **阶段打点**：在页面上 hook `HTMLCanvasElement.prototype.toDataURL`，记录每次
 *   「编码」的入参格式、画布像素、返回 base64 字符串长度与耗时，用来把 RSS 抬升
 *   归因到「捕获 / 编码 / jsPDF 组装」哪一段（PNG 走 `toDataURL('image/png')`，
 *   PDF 走逐页 `pageCanvas.toDataURL('image/jpeg', 0.95)`，见 exportPng/exportPdf）；
 * - **回收验证**：导出完成后再采 +2s / +5s / +10s，判断画布与编码缓冲是否被释放；
 *   并连续导出 5 次，确认 RSS 不随次数单调抬升（避免重复导出 OOM）。
 *
 * 运行：`pnpm e2e:perf --grep 内存` 或 `pnpm e2e:perf tests/perf/dashboard-export-memory.spec.ts`。
 * 结果写入 `test-results/perf/dashboard-export-memory.json`。
 */
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { getAdminToken, getTableId, getWorkspaceId } from "../e2e/helpers/api";
import {
  DASHBOARD_TABLE_NAME,
  DASHBOARD_WS_NAME,
  createDashboardView,
  deleteView,
  openDashboard,
} from "../e2e/helpers/dashboard";
import {
  chromiumProcessStats,
  dashboardOptions,
  hugeWidgets,
  pngSize,
  startHeapSampler,
  stopHeapSampler,
  type ChromiumProcessStats,
} from "./fixtures";

/** 一次 RSS 采样（tMs 为相对点击的毫秒） */
interface RssSample {
  tMs: number;
  totalMb: number;
  rendererMb: number;
  gpuMb: number;
  browserMb: number;
}

/** 页面侧 `toDataURL` 编码打点（startMs / endMs 相对点击） */
interface EncodeMark {
  mime: string;
  width: number;
  height: number;
  /** 返回的 data URL 字符数（base64，约等于字节数） */
  chars: number;
  startMs: number;
  endMs: number;
}

/** 单场景内存结论 */
interface MemoryReport {
  case: string;
  format: "png" | "pdf";
  /** 捕获画布像素尺寸（取导出过程中出现的最大 canvas，PDF 为切片前的主画布） */
  capturePx: { width: number; height: number };
  /** 导出文件内 PNG 的像素尺寸（仅 PNG 可读） */
  canvasPx?: { width: number; height: number };
  /** 理论位图内存：canvas 像素 × 4 字节 */
  bitmapMb: number;
  fileBytes: number;
  elapsedMs: number;
  rssBaseMb: number;
  rssBaseRendererMb: number;
  rssPeakTotalMb: number;
  rssPeakRendererMb: number;
  rssPeakAtMs: number;
  rssDeltaMb: number;
  rendererDeltaMb: number;
  /** 导出完成 +N 秒后的 RSS（回收情况） */
  rssAfterMb: Record<string, number>;
  heapPeakMb: number;
  encode: EncodeMark[];
  samples: RssSample[];
}

const REPORTS: MemoryReport[] = [];

/** 安装页面侧打点（幂等）：`toDataURL` 编码耗时/体积 + 大画布尺寸，不改导出行为只记录 */
async function installEncodeProbe(page: Page): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as {
      __memMarks?: unknown[];
      __memCanvases?: { width: number; height: number }[];
      __memT0?: number;
      __memProbeInstalled?: boolean;
    };
    w.__memMarks = [];
    w.__memCanvases = [];
    w.__memT0 = performance.now();
    if (w.__memProbeInstalled) return;
    w.__memProbeInstalled = true;

    const original = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function (
      this: HTMLCanvasElement,
      ...args: [type?: string, quality?: number]
    ): string {
      const start = performance.now();
      const result = original.apply(this, args);
      const end = performance.now();
      (w.__memMarks as EncodeMark[]).push({
        mime: String(args[0] ?? "image/png"),
        width: this.width,
        height: this.height,
        chars: result.length,
        // 相对探针起点；调用方在点击前复位 __memT0，故等价于相对点击
        startMs: Math.round(start - (w.__memT0 ?? 0)),
        endMs: Math.round(end - (w.__memT0 ?? 0)),
      });
      return result;
    };

    // 记录「大画布」（≥ 1 M px）取上下文的尺寸：html2canvas 主画布与 jsPDF 逐页切片
    // 都在此创建；小画布（图标、图表内部 canvas）忽略，避免噪声。
    // 不去重：同一个页面里 html2canvas 可能复用画布，而每次导出都要重新记录尺寸。
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      contextId: string,
      ...rest: unknown[]
    ) {
      if (this.width * this.height >= 1_000_000) {
        (w.__memCanvases as { width: number; height: number }[]).push({
          width: this.width,
          height: this.height,
        });
      }
      // @ts-expect-error 透传任意上下文类型
      return originalGetContext.call(this, contextId, ...rest);
    };
  });
}

/** 复位打点起点（点击前调用），返回页面侧当前时刻 */
async function resetEncodeProbe(page: Page): Promise<number> {
  return page.evaluate(() => {
    const w = window as unknown as {
      __memMarks?: unknown[];
      __memCanvases?: unknown[];
      __memT0?: number;
    };
    w.__memMarks = [];
    w.__memCanvases = [];
    w.__memT0 = performance.now();
    return w.__memT0;
  });
}

/** 读取编码打点与大画布尺寸 */
async function readEncodeMarks(
  page: Page,
): Promise<{ marks: EncodeMark[]; canvases: { width: number; height: number }[] }> {
  return page.evaluate(() => {
    const w = window as unknown as {
      __memMarks?: EncodeMark[];
      __memCanvases?: { width: number; height: number }[];
    };
    return { marks: w.__memMarks ?? [], canvases: w.__memCanvases ?? [] };
  });
}

/** 启动 25ms RSS 采样，返回采样数组与停止函数（tMs 由调用方按点击时刻换算） */
function startRssSampler(intervalMs = 25) {
  const samples: { atMs: number; stats: ChromiumProcessStats }[] = [];
  const timer = setInterval(() => {
    const stats = chromiumProcessStats();
    if (stats) samples.push({ atMs: Number(process.hrtime.bigint()) / 1e6, stats });
  }, intervalMs);
  return {
    samples,
    stop: () => clearInterval(timer),
  };
}

/** 导出一次并采集内存画像 */
async function profileExport(
  page: Page,
  caseName: string,
  format: "png" | "pdf",
): Promise<MemoryReport> {
  await resetEncodeProbe(page);
  await startHeapSampler(page, 25);
  const baseStats = chromiumProcessStats();
  const sampler = startRssSampler(25);

  const downloadPromise = page.waitForEvent("download", { timeout: 600_000 });
  const clickAtMs = Number(process.hrtime.bigint()) / 1e6;
  const startedAt = process.hrtime.bigint();
  await page.getByTestId(`dashboard-export-${format}`).click();
  const download = await downloadPromise;
  const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;
  const { marks, canvases } = await readEncodeMarks(page);
  const heapBytes = await stopHeapSampler(page);
  sampler.stop();

  const filePath = await download.path();
  expect(filePath, "导出文件应落盘").toBeTruthy();
  const fileBytes = statSync(filePath!).size;
  const canvasPx = format === "png" ? pngSize(readFileSync(filePath!)) : undefined;

  // 回收观察：导出完成后的累计 +2s / +5s / +10s 各采一次
  const rssAfterMb: Record<string, number> = {};
  let waitedMs = 0;
  for (const delay of [2000, 3000, 5000]) {
    await page.waitForTimeout(delay);
    waitedMs += delay;
    const stats = chromiumProcessStats();
    if (stats) rssAfterMb[`+${Math.round(waitedMs / 1000)}s`] = Math.round(stats.totalMb);
  }

  const samples: RssSample[] = sampler.samples.map(({ atMs, stats }) => ({
    tMs: Math.round(atMs - clickAtMs),
    totalMb: Math.round(stats.totalMb),
    rendererMb: Math.round(stats.byKind.renderer ?? 0),
    gpuMb: Math.round(stats.byKind.gpu ?? 0),
    browserMb: Math.round(stats.byKind.browser ?? 0),
  }));
  const peakSample = samples.reduce(
    (best, cur) => (cur.totalMb > best.totalMb ? cur : best),
    samples[0] ?? { tMs: 0, totalMb: 0, rendererMb: 0, gpuMb: 0, browserMb: 0 },
  );
  const peakRenderer = Math.max(...samples.map((s) => s.rendererMb), 0);

  // 主画布取导出过程中出现过的最大画布尺寸：优先用 getContext 打点（PDF 的切片画布会
  // 小于主画布），html2canvas 的主画布是先取上下文再设尺寸的，取不到时回落到 toDataURL
  // 打点（其尺寸即被编码的画布尺寸）
  const candidates = [
    ...canvases,
    ...marks.map((m) => ({ width: m.width, height: m.height })),
  ];
  const capturePx = candidates.reduce(
    (best, cur) => (cur.width * cur.height > best.width * best.height ? cur : best),
    { width: 0, height: 0 },
  );
  const pixelCount = capturePx.width * capturePx.height
    || (canvasPx?.width ?? 0) * (canvasPx?.height ?? 0);

  const report: MemoryReport = {
    case: caseName,
    format,
    capturePx,
    canvasPx,
    bitmapMb: Math.round((pixelCount * 4) / 1024 / 1024),
    fileBytes,
    elapsedMs: Math.round(elapsedMs),
    rssBaseMb: Math.round(baseStats?.totalMb ?? 0),
    rssBaseRendererMb: Math.round(baseStats?.byKind.renderer ?? 0),
    rssPeakTotalMb: peakSample.totalMb,
    rssPeakRendererMb: peakRenderer,
    rssPeakAtMs: peakSample.tMs,
    rssDeltaMb: Math.round(peakSample.totalMb - (baseStats?.totalMb ?? 0)),
    rendererDeltaMb: Math.round(peakRenderer - (baseStats?.byKind.renderer ?? 0)),
    rssAfterMb,
    heapPeakMb: Math.round(heapBytes / 1024 / 1024),
    encode: marks,
    samples,
  };
  REPORTS.push(report);

  const encodeSummary = marks
    .map((m) => `${m.mime.replace("image/", "")} ${m.width}×${m.height} ${(m.chars / 1024 / 1024).toFixed(1)}MB(base64) ${m.startMs}→${m.endMs}ms`)
    .join(" | ");
  console.log(
    `[perf-mem] ${caseName}/${format} · 文件 ${(fileBytes / 1024 / 1024).toFixed(2)}MB · 耗时 ${report.elapsedMs}ms`
    + ` · 捕获画布 ${capturePx.width}×${capturePx.height}（位图理论 ${report.bitmapMb}MB）`
    + ` · RSS 基线 ${report.rssBaseMb}MB（渲染 ${report.rssBaseRendererMb}MB）→ 峰值 ${report.rssPeakTotalMb}MB`
    + `（渲染 ${peakRenderer}MB，+${peakSample.tMs}ms；总增量 ${report.rssDeltaMb}MB / 渲染增量 ${report.rendererDeltaMb}MB）`
    + ` · JS 堆峰值 ${report.heapPeakMb}MB`
    + ` · 回收 ${Object.entries(rssAfterMb).map(([k, v]) => `${k}=${v}MB`).join(" ")}`,
  );
  console.log(`[perf-mem]   编码：${encodeSummary || "无 toDataURL 调用"}`);
  return report;
}

async function seedHugeView(request: import("@playwright/test").APIRequestContext) {
  const wid = await getWorkspaceId(request, DASHBOARD_WS_NAME);
  const tid = await getTableId(request, wid, DASHBOARD_TABLE_NAME);
  const token = await getAdminToken(request);
  const view = await createDashboardView(
    request,
    token,
    wid,
    tid,
    `perf 内存 ${Date.now()}`,
    dashboardOptions(hugeWidgets()),
  );
  return { wid, tid, token, view };
}

test.describe("超大画布导出内存峰值", () => {
  test.describe.configure({ mode: "serial" });

  test.afterAll(() => {
    if (REPORTS.length === 0) return;
    const dir = path.resolve("test-results", "perf");
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, "dashboard-export-memory.json"), JSON.stringify(REPORTS, null, 2));
  });

  test("超大画布 PNG：捕获 / 编码阶段的 RSS 峰值、位图理论值与回收", async ({ page, request }) => {
    const { wid, tid, token, view } = await seedHugeView(request);
    try {
      await openDashboard(page, wid, tid, view.id);
      await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(5000);
      await installEncodeProbe(page);

      // 冷启动一次（导出库动态导入）不计入画像；随后空闲 10s 让画布与编码缓冲回收，
      // 保证热态基线干净（否则上一轮的残留会把峰值增量测小）
      const warmupDownload = page.waitForEvent("download", { timeout: 600_000 });
      await page.getByTestId("dashboard-export-png").click();
      await warmupDownload;
      await page.waitForTimeout(10_000);
      await profileExport(page, "huge", "png");
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("超大画布 PDF：逐页 JPEG 编码的 RSS 峰值与回收", async ({ page, request }) => {
    const { wid, tid, token, view } = await seedHugeView(request);
    try {
      await openDashboard(page, wid, tid, view.id);
      await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(5000);
      await installEncodeProbe(page);
      // 冷启动一次（含 jspdf / html2canvas 动态导入），空闲 10s 后再测热态基线
      const warmupDownload = page.waitForEvent("download", { timeout: 600_000 });
      await page.getByTestId("dashboard-export-pdf").click();
      await warmupDownload;
      await page.waitForTimeout(10_000);
      await profileExport(page, "huge", "pdf");
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("超大画布 PNG 连续导出 5 次：RSS 是否随次数抬升（防重复导出 OOM）", async ({ page, request }) => {
    const { wid, tid, token, view } = await seedHugeView(request);
    try {
      await openDashboard(page, wid, tid, view.id);
      await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(5000);

      const rounds: string[] = [];
      for (let i = 1; i <= 5; i += 1) {
        const base = chromiumProcessStats()?.totalMb ?? 0;
        const downloadPromise = page.waitForEvent("download", { timeout: 600_000 });
        await page.getByTestId("dashboard-export-png").click();
        await downloadPromise;
        await page.waitForTimeout(3000);
        const after = chromiumProcessStats()?.totalMb ?? 0;
        rounds.push(`#${i} ${Math.round(base)}→${Math.round(after)}MB`);
        console.log(`[perf-mem] repeat#${i} · ${Math.round(base)} → ${Math.round(after)}MB（导出后 +3s）`);
      }
      const last = chromiumProcessStats()?.totalMb ?? 0;
      console.log(`[perf-mem] repeat 汇总：${rounds.join(" | ")} · 结束后 ${Math.round(last)}MB`);
      expect(rounds).toHaveLength(5);
      // 只做粗保护：最后一次导出后的 RSS 不应比第一次导出后高出 50% 以上
      const first = Number(rounds[0].split("→")[1].replace("MB", ""));
      expect(last, "连续导出不应显著抬升 RSS").toBeLessThan(Math.max(first * 1.5, first + 200));
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });
});

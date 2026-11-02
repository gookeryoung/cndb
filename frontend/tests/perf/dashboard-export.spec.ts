/**
 * 低配设备整屏导出性能探针（ADR 0023 / 原 0077 P0 的遗留问题验证）。
 *
 * 容器内没有真机，这里用两条可复现的近似手段：
 * 1. **CPU 降速**：CDP `Emulation.setCPUThrottlingRate`（Chromium DevTools 同款），
 *    6×（低端笔记本 / 政务终端的一档近似），只降该页渲染 CPU，不影响自身计时；
 * 2. **内存**：Node 侧采样 Chromium 进程组 RSS（Linux）+ 页面 `performance.memory`
 *    的 JS 堆峰值（已开 `--enable-precise-memory-info`）；分阶段剖析见
 *    `dashboard-export-memory.spec.ts`。
 *
 * 被测口径与用户点「导出 PNG / 导出 PDF」完全一致（`dashboard-export-png/pdf` 按钮
 * → 下载落盘），因此测到的是「点击 → 文件可就绪」的用户可感知耗时，包含导出库
 * 动态导入、html2canvas 捕获、PNG/JPEG 编码与 jsPDF 组装。
 *
 * 运行：`pnpm e2e:perf`（需先 `make frontend-build`；不进 `make e2e` 门禁）。
 * 结果同时打印到 stdout 并写入 `test-results/perf/dashboard-export.json`。
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
  chromiumRssMb,
  dashboardOptions,
  hugeWidgets,
  pngSize,
  startHeapSampler,
  stopHeapSampler,
  typicalWidgets,
} from "./fixtures";

/** 单条测量记录 */
interface ExportMetric {
  scenario: string;
  format: "png" | "pdf";
  /** CPU 降速倍数：1 = 不降速（宿主机基线） */
  cpuRate: number;
  /** 是否本页面首次导出（含导出库动态导入） */
  cold: boolean;
  /** 点击 → 下载落盘 的墙钟耗时（ms） */
  elapsedMs: number;
  /** 导出文件字节数 */
  fileBytes: number;
  /** 捕获画布像素尺寸（PDF 由文件内 JPEG 无法直读，故仅 PNG 给出） */
  canvasPx?: { width: number; height: number };
  /** 导出期间 Chromium 进程组 RSS 峰值（MB，仅 Linux） */
  rssPeakMb?: number;
  /** 导出期间 Chromium 进程组 RSS 增量（峰值 − 导出前基线，MB） */
  rssDeltaMb?: number;
  /** 导出期间页面 JS 堆峰值（MB） */
  heapPeakMb?: number;
}

/** 单次导出测量：点击 → 下载落盘，中途采样 RSS / JS 堆.
 *
 * @param cold 页面首个导出为 true（含导出库动态导入的成本），后续为热态
 */
async function measureExport(
  page: Page,
  scenario: string,
  format: "png" | "pdf",
  cpuRate: number,
  cold: boolean,
): Promise<ExportMetric> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: cpuRate });

  await startHeapSampler(page, 100);
  const rssBaseMb = chromiumRssMb();
  let rssPeakMb = rssBaseMb;
  const rssTimer = setInterval(() => {
    const value = chromiumRssMb();
    if (value !== undefined && (rssPeakMb === undefined || value > rssPeakMb)) rssPeakMb = value;
  }, 100);

  const downloadPromise = page.waitForEvent("download", { timeout: 600_000 });
  const startedAt = process.hrtime.bigint();
  await page.getByTestId(`dashboard-export-${format}`).click();
  const download = await downloadPromise;
  const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;

  clearInterval(rssTimer);
  const heapBytes = await stopHeapSampler(page);
  const filePath = await download.path();
  expect(filePath, "导出文件应落盘").toBeTruthy();
  const fileBytes = statSync(filePath!).size;

  const metric: ExportMetric = {
    scenario,
    format,
    cpuRate,
    cold,
    elapsedMs: Math.round(elapsedMs),
    fileBytes,
  };
  if (format === "png") metric.canvasPx = pngSize(readFileSync(filePath!));
  if (rssBaseMb !== undefined && rssPeakMb !== undefined) {
    metric.rssPeakMb = Math.round(rssPeakMb);
    metric.rssDeltaMb = Math.round(rssPeakMb - rssBaseMb);
  }
  if (heapBytes > 0) metric.heapPeakMb = Math.round(heapBytes / 1024 / 1024);

  // 降速在页面上生效，测完立刻恢复，避免影响后续组合
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  await cdp.detach();
  // 给浏览器一点时间回收画布与编码缓冲，避免下一轮基线被上一轮残留抬高
  await page.waitForTimeout(1000);
  return metric;
}

const RESULTS: ExportMetric[] = [];

function report(metric: ExportMetric) {
  RESULTS.push(metric);
  const parts = [
    `${metric.scenario}`,
    `${metric.format.toUpperCase()} @${metric.cpuRate}x`,
    metric.cold ? "cold" : "warm",
    `${metric.elapsedMs}ms`,
    `${(metric.fileBytes / 1024 / 1024).toFixed(2)}MB`,
  ];
  if (metric.canvasPx) parts.push(`canvas ${metric.canvasPx.width}×${metric.canvasPx.height}`);
  if (metric.rssPeakMb !== undefined) parts.push(`rss ${metric.rssPeakMb}MB(+${metric.rssDeltaMb})`);
  if (metric.heapPeakMb !== undefined) parts.push(`heap ${metric.heapPeakMb}MB`);
  console.log(`[perf] ${parts.join(" · ")}`);
}

async function seedView(
  request: import("@playwright/test").APIRequestContext,
  widgets: unknown[],
  name: string,
) {
  const wid = await getWorkspaceId(request, DASHBOARD_WS_NAME);
  const tid = await getTableId(request, wid, DASHBOARD_TABLE_NAME);
  const token = await getAdminToken(request);
  const view = await createDashboardView(request, token, wid, tid, name, dashboardOptions(widgets));
  return { wid, tid, token, view };
}

test.describe("dashboard 整屏导出性能（低配模拟）", () => {
  test.describe.configure({ mode: "serial" });

  test.afterAll(() => {
    if (RESULTS.length === 0) return;
    const dir = path.resolve("test-results", "perf");
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, "dashboard-export.json"), JSON.stringify(RESULTS, null, 2));
    const byKey = new Map<string, ExportMetric[]>();
    for (const metric of RESULTS) {
      const key = `${metric.scenario}/${metric.format}`;
      byKey.set(key, [...(byKey.get(key) ?? []), metric]);
    }
    console.log("\n[perf] 汇总（同组合取 warm 中位数）");
    for (const [key, list] of byKey) {
      for (const rate of [1, 4, 6]) {
        const warm = list.filter((m) => m.cpuRate === rate && !m.cold);
        if (warm.length === 0) continue;
        const sorted = [...warm].sort((a, b) => a.elapsedMs - b.elapsedMs);
        const median = sorted[Math.floor(sorted.length / 2)];
        const rss = list.filter((m) => m.cpuRate === rate).map((m) => m.rssPeakMb).filter(Boolean);
        console.log(
          `[perf] ${key} @${rate}x · ${median.elapsedMs}ms · ${(median.fileBytes / 1024 / 1024).toFixed(2)}MB`
          + (median.canvasPx ? ` · canvas ${median.canvasPx.width}×${median.canvasPx.height}` : "")
          + (rss.length > 0 ? ` · rss 峰值 ${Math.max(...(rss as number[]))}MB` : ""),
        );
      }
    }
  });

  test("典型画布（2 列 × 3 行）：PNG / PDF 在 1x / 4x / 6x CPU 降速下的导出耗时与内存", async ({ page, request }) => {
    const { wid, tid, token, view } = await seedView(request, typicalWidgets(), `perf 典型 ${Date.now()}`);
    try {
      await openDashboard(page, wid, tid, view.id);
      await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 30_000 });
      // 等数据与图表渲染完成，避免把加载时间算进导出
      await page.waitForTimeout(3000);

      // 页面首个导出记 cold（含导出库动态导入），其余记 warm
      let cold = true;
      for (const format of ["png", "pdf"] as const) {
        for (const cpuRate of [1, 4, 6]) {
          for (let rep = 0; rep < 2; rep += 1) {
            report(await measureExport(page, "typical", format, cpuRate, cold));
            cold = false;
          }
        }
      }
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("超大画布（20 块整行组件 ≈ 1000×8000 CSS px）：PNG / PDF 在 1x / 6x CPU 降速下的导出耗时与内存", async ({ page, request }) => {
    const { wid, tid, token, view } = await seedView(request, hugeWidgets(), `perf 超大 ${Date.now()}`);
    try {
      await openDashboard(page, wid, tid, view.id);
      await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(5000);

      let cold = true;
      for (const format of ["png", "pdf"] as const) {
        for (const cpuRate of [1, 6]) {
          for (let rep = 0; rep < 2; rep += 1) {
            report(await measureExport(page, "huge", format, cpuRate, cold));
            cold = false;
          }
        }
      }
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });
});

/**
 * 导出性能探针的公共夹具：画布场景构造、PNG 尺寸解析、Chromium 内存采样、页面 JS 堆采样。
 *
 * 只在 `tests/perf` 下的 opt-in 探针里使用（不进 `make e2e` / CI 分片）。
 */
import { execFileSync } from "node:child_process";

import type { Page } from "@playwright/test";

import { emptyQuery } from "../e2e/helpers/dashboard";

/** Chromium 各进程类型的 RSS（MB） */
export interface ChromiumProcessStats {
  /** 全部 Chromium 进程 RSS 合计 */
  totalMb: number;
  /** 按 `--type` 分类：browser / renderer / gpu / utility */
  byKind: Record<string, number>;
  /** 各进程明细（调试用） */
  processes: { pid: number; kind: string; rssMb: number }[];
}

/** 判定某个进程是否属于本次探针启动的 Chromium（headless 壳 / chromium / chrome） */
function isChromiumProcess(args: string): boolean {
  const binary = args.trim().split(/\s+/)[0] ?? "";
  const base = binary.split("/").pop() ?? "";
  return /chrom|headless/i.test(base);
}

/**
 * 采样 Chromium 进程组 RSS（Linux）。
 *
 * 按 `--type=` 分类，便于区分「画布位图所在渲染进程」与「浏览器/GPU 进程」：
 * Playwright 的 headless 进程名为 `chrome-headless --headless ...`，renderer 子进程
 * 带 `--type=renderer`（comm 均被截断到 15 字符，所以只能读完整命令行）。
 */
export function chromiumProcessStats(): ChromiumProcessStats | undefined {
  if (process.platform !== "linux") return undefined;
  try {
    const out = execFileSync("ps", ["-eo", "pid=,rss=,args=", "-ww"], {
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    });
    const byKind: Record<string, number> = {};
    const processes: { pid: number; kind: string; rssMb: number }[] = [];
    let totalMb = 0;
    for (const line of out.split("\n")) {
      const match = line.match(/^\s*(\d+)\s+(\d+)\s+(.+)$/);
      if (!match) continue;
      const [, pid, rssKb, args] = match;
      if (!isChromiumProcess(args)) continue;
      const kind = /--type=renderer/.test(args)
        ? "renderer"
        : /--type=gpu-process/.test(args)
          ? "gpu"
          : /--type=/.test(args)
            ? "utility"
            : "browser";
      const rssMb = Number(rssKb) / 1024;
      byKind[kind] = (byKind[kind] ?? 0) + rssMb;
      processes.push({ pid: Number(pid), kind, rssMb: Math.round(rssMb) });
      totalMb += rssMb;
    }
    return { totalMb, byKind, processes };
  } catch {
    return undefined;
  }
}

/** 全部 Chromium 进程 RSS 合计（MB），供粗略采样使用 */
export function chromiumRssMb(): number | undefined {
  const stats = chromiumProcessStats();
  return stats ? stats.totalMb : undefined;
}

/** 启动页面 JS 堆采样（`performance.memory` 需 `--enable-precise-memory-info`） */
export async function startHeapSampler(page: Page, intervalMs = 100): Promise<void> {
  await page.evaluate((interval) => {
    const w = window as unknown as { __heapPeak?: number; __heapTimer?: number };
    const memory = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    w.__heapPeak = memory?.usedJSHeapSize ?? 0;
    w.__heapTimer = window.setInterval(() => {
      const used = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize;
      if (used !== undefined && used > (w.__heapPeak ?? 0)) w.__heapPeak = used;
    }, interval);
  }, intervalMs);
}

/** 停止 JS 堆采样并返回峰值（字节；0 表示环境不支持 `performance.memory`） */
export async function stopHeapSampler(page: Page): Promise<number> {
  return page.evaluate(() => {
    const w = window as unknown as { __heapPeak?: number; __heapTimer?: number };
    if (w.__heapTimer !== undefined) window.clearInterval(w.__heapTimer);
    w.__heapTimer = undefined;
    return w.__heapPeak ?? 0;
  });
}

/** PNG IHDR 宽高（前 33 字节） */
export function pngSize(buf: Buffer): { width: number; height: number } {
  if (buf.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") {
    throw new Error("不是 PNG 文件（魔数不匹配）");
  }
  if (buf.subarray(12, 16).toString("latin1") !== "IHDR") {
    throw new Error("PNG 缺少 IHDR 块");
  }
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

/** 典型画布：2 列 × 3 行（约 2 屏高，日常看板规模） */
export function typicalWidgets() {
  const layouts = [
    { x: 0, y: 0 },
    { x: 6, y: 0 },
    { x: 0, y: 8 },
    { x: 6, y: 8 },
    { x: 0, y: 16 },
    { x: 6, y: 16 },
  ];
  return layouts.map((pos, i) => {
    const layout = { ...pos, w: 6, h: 8 };
    const kind = i % 3;
    if (kind === 0) {
      return {
        id: `w_chart_${i}`,
        type: "chart",
        title: `类别 ${i}`,
        layout,
        query: emptyQuery(),
        chart: {
          type: "bar",
          x: "商品类别",
          y: ["销售额"],
          agg: "sum",
          stack: "none",
          sort: "none",
          dual_axis: false,
          format: {},
        },
      };
    }
    if (kind === 1) {
      return {
        id: `w_kpi_${i}`,
        type: "kpi",
        title: `指标 ${i}`,
        layout,
        query: emptyQuery(),
        kpi: { value: { field: "订单号", agg: "count" } },
      };
    }
    return {
      id: `w_text_${i}`,
      type: "text",
      title: `说明 ${i}`,
      layout,
      query: emptyQuery(),
      text: { content: `第 ${i} 块说明文本，用于导出性能探测。` },
    };
  });
}

/** 超大画布：20 块整行组件、共 200 个行单元高（配置上限内，捕获画布约 1000×8000 CSS px） */
export function hugeWidgets() {
  return Array.from({ length: 20 }, (_, i) => {
    const layout = { x: 0, y: i * 10, w: 12, h: 10 };
    const kind = i % 3;
    if (kind === 0) {
      return {
        id: `w_huge_chart_${i}`,
        type: "chart",
        title: `类别 ${i}`,
        layout,
        query: emptyQuery(),
        chart: {
          type: "bar",
          x: "商品类别",
          y: ["销售额"],
          agg: "sum",
          stack: "none",
          sort: "none",
          dual_axis: false,
          format: {},
        },
      };
    }
    if (kind === 1) {
      return {
        id: `w_huge_kpi_${i}`,
        type: "kpi",
        title: `指标 ${i}`,
        layout,
        query: emptyQuery(),
        kpi: { value: { field: "订单号", agg: "count" } },
      };
    }
    return {
      id: `w_huge_text_${i}`,
      type: "text",
      title: `说明 ${i}`,
      layout,
      query: emptyQuery(),
      text: { content: `第 ${i} 行说明文本，用于超大画布导出性能探测。` },
    };
  });
}

/** 看板视图 options（组件 + 画布设置） */
export function dashboardOptions(widgets: unknown[]) {
  return {
    schema_version: 1,
    widgets,
    global_filters: [],
    settings: { refresh_interval: 0, theme: "inherit" },
  };
}

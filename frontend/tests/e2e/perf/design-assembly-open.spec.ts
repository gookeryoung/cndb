/** 设计装配打开性能基准（ADR 0086 C9）—— @perf 观察期.
 *
 * 夹具：API 注入 1 个零件文件（10 图元）+ 1 个装配文件（200 个 `use` 组件，
 * 闭包累计 2000 图元，恰达 C10 预算上限）。预热开一次后重复打开编辑器 3 次，
 * 取中位数对比四阈值（C9，SPA 内口径——从设计列表点「打开」起算，无整页 reload）：
 * - 编辑器可交互（点击后到 CodeMirror 内容可见）≤ 1000ms
 * - 3D 首帧（canvas 挂载，首帧近似骨架同步渲染）≤ 1500ms
 * - 单次长任务（longtask buffered）≤ 200ms
 * - 侧栏首屏（首个大纲节点可见）≤ 500ms
 *
 * 运行方式与 grid-lcp 一致：@perf 标签，CI 从并行分片剔除、shard 内串行独占。
 * 手动：pnpm e2e --project=chromium-authed tests/e2e/perf/design-assembly-open.spec.ts --workers=1
 */

import { test, expect } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";
import { getAdminToken } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
const WID = 1;

const EDITOR_LIMIT_MS = 1000;
const CANVAS_LIMIT_MS = 1500;
const LONGTASK_LIMIT_MS = 200;
const SIDEBAR_LIMIT_MS = 500;
const RUNS = 3;

async function authHeaders(request: APIRequestContext) {
  const token = await getAdminToken(request);
  return { Authorization: `Bearer ${token}` };
}

/** 零件：1 个 param + 10 图元（union 块）—— 200 组件 × 10 = 2000 图元（恰达预算上限） */
function partContent(): string {
  const lines = ["param w = 20", "union {"];
  for (let i = 0; i < 10; i += 1) {
    lines.push(`  translate([${i * 30}, 0, 0]) box(size = [w, ${8 + i}, ${6 + i}])`);
  }
  lines.push("}");
  return lines.join("\n");
}

/** 装配：200 个 use 组件（≥200 组件、≥2000 图元） */
function assemblyContent(fileKey: string): string {
  const lines = ["constraint c0 fixed(a = c0.origin)"];
  for (let i = 0; i < (process.env.PERF_SMALL ? 1 : 200); i += 1) {
    lines.push(`use "${fileKey}" as c${i}`);
  }
  return lines.join("\n");
}

interface OpenMetrics {
  editorMs: number;
  canvasMs: number;
  sidebarMs: number;
  maxLongTaskMs: number;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)]!;
}

test.describe("性能基准：装配设计打开（ADR 0086 C9）", () => {
  test("200 组件 / 2000 图元装配打开四阈值", { tag: "@perf" }, async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    test.setTimeout(180_000);

    const stamp = Date.now();
    const partKey = `perf_part_${stamp}`;
    const partTitle = `性能零件 ${stamp}`;
    const asmTitle = `性能装配 ${stamp}`;
    const ids: number[] = [];

    // 注入夹具：零件 + 装配（装配依赖零件，IR 一次落库，打开走 I6 快照路径）
    const partRes = await request.post(`/api/v1/workspaces/${WID}/designs`, {
      headers: await authHeaders(request),
      data: { title: partTitle, content: partContent(), kind: "part", file_key: partKey },
    });
    expect(partRes.ok(), `零件创建失败: ${await partRes.text()}`).toBeTruthy();
    const part = (await partRes.json()) as { id: number };
    ids.push(part.id);

    const asmRes = await request.post(`/api/v1/workspaces/${WID}/designs`, {
      headers: await authHeaders(request),
      data: { title: asmTitle, content: assemblyContent(partKey), kind: "assembly" },
    });
    expect(asmRes.ok(), `装配创建失败: ${await asmRes.text()}`).toBeTruthy();
    const asm = (await asmRes.json()) as { id: number };
    ids.push(asm.id);

    try {
      // longtask 观察经 addInitScript 注入：记录 {duration, startTime}，按 SPA 内时间窗过滤
      await page.addInitScript(() => {
        (window as unknown as { __longTasks: Array<{ d: number; t: number }> }).__longTasks = [];
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            (window as unknown as { __longTasks: Array<{ d: number; t: number }> }).__longTasks.push({
              d: entry.duration,
              t: entry.startTime,
            });
          }
        });
        observer.observe({ type: "longtask", buffered: true });
      });

      // 预热（不计入指标）：SPA 落地后自动打开最近更新产品并加载编辑器 chunk；
      // 再切回侧栏产品列表态，模拟用户从列表打开装配的路径（ADR 0109 D3 / D4）。
      // 必须等自动落地到 /design/:id 之后再点「产品列表」：根页只是瞬时列表帧，
      // 落地完成后侧栏会切回结构树态，提前拿到的行会在 2.2s 空闲窗内被卸载。
      await page.goto(`/w/${WID}/design`);
      await page.waitForURL(/\/w\/1\/design\/\d+$/, { timeout: 30_000 });
      await expect(page.getByTestId("sider-designs")).toBeVisible({ timeout: 30_000 });
      const backToProducts = page.getByTestId("design-nav-back");
      await expect(backToProducts).toBeVisible({ timeout: 15_000 });
      await backToProducts.click();
      await expect(page.getByTestId(`design-row-${asm.id}`)).toBeVisible({ timeout: 15_000 });
      // 编辑器 chunk 已在自动落地时加载；留出空闲窗口再开始计时
      await page.waitForTimeout(2200);

      const runs: OpenMetrics[] = [];
      for (let i = 0; i < RUNS; i += 1) {
        // 口径（C9）：「打开装配设计」= SPA 内从列表点击产品行到编辑器可交互
        //（无整页 reload，vendor 求值不计入；这正是用户点开大装配的路径）
        const t0Page = await page.evaluate(() => performance.now());
        await page.getByTestId(`design-row-${asm.id}`).click();
        await expect(page.locator(".cm-content").first()).toBeVisible({ timeout: 15_000 });
        const editorMs = Math.round((await page.evaluate(() => performance.now())) - t0Page);

        const t0Sidebar = await page.evaluate(() => performance.now());
        await expect(
          page.locator('[data-testid^="design-outline-node-"]').first(),
        ).toBeVisible({ timeout: 15_000 });
        const sidebarMs = Math.round((await page.evaluate(() => performance.now())) - t0Sidebar);

        const t0Canvas = await page.evaluate(() => performance.now());
        await expect(page.getByTestId("design-preview-canvas")).toBeVisible({ timeout: 30_000 });
        const canvasMs = Math.round((await page.evaluate(() => performance.now())) - t0Canvas);

        // 时间窗从点击前一刻起算（编辑器挂载渲染均落在窗内）
        const maxLongTaskMs = await page.evaluate(
          ({ since }) => {
            const tasks = (window as unknown as { __longTasks: Array<{ d: number; t: number }> })
              .__longTasks.filter((item) => item.t >= since);
            return tasks.length ? Math.max(...tasks.map((item) => item.d)) : 0;
          },
          { since: t0Page },
        );
        runs.push({ editorMs, canvasMs, sidebarMs, maxLongTaskMs });

        // 返回产品列表（浏览器回退 + 侧栏「产品列表」键，不整页刷新；ADR 0109 D4）。
        // 回退到根页后同样要等自动落地完成，再点「产品列表」，避免停留在瞬时列表帧。
        await page.goBack();
        await page.waitForURL(/\/w\/1\/design\/\d+$/, { timeout: 15_000 });
        const back = page.getByTestId("design-nav-back");
        await expect(back).toBeVisible({ timeout: 15_000 });
        await back.click();
        await expect(page.getByTestId(`design-row-${asm.id}`)).toBeVisible({ timeout: 15_000 });
      }

      const med = {
        editor: median(runs.map((r) => r.editorMs)),
        canvas: median(runs.map((r) => r.canvasMs)),
        sidebar: median(runs.map((r) => r.sidebarMs)),
        longTask: median(runs.map((r) => r.maxLongTaskMs)),
      };
      const detail = runs
        .map((r, i) => `run${i + 1}: editor=${r.editorMs}ms canvas=${r.canvasMs}ms sidebar=${r.sidebarMs}ms longTask=${Math.round(r.maxLongTaskMs)}ms`)
        .join("; ");
      const summary = `中位数 editor=${med.editor}ms canvas=${med.canvas}ms sidebar=${med.sidebar}ms longTask=${Math.round(med.longTask)}ms`;

      // 记录实测基线（ADR 0086 C9：3 次中位数）
      console.log(`[perf design-assembly-open] ${summary} | ${detail}`);

      expect(med.editor, `${summary} | ${detail}`).toBeLessThan(EDITOR_LIMIT_MS);
      expect(med.canvas, `${summary} | ${detail}`).toBeLessThan(CANVAS_LIMIT_MS);
      expect(med.sidebar, `${summary} | ${detail}`).toBeLessThan(SIDEBAR_LIMIT_MS);
      expect(med.longTask, `${summary} | ${detail}`).toBeLessThan(LONGTASK_LIMIT_MS);
    } finally {
      for (const id of ids.reverse()) {
        await request
          .delete(`/api/v1/workspaces/${WID}/designs/${id}`, { headers: await authHeaders(request) })
          .catch(() => undefined);
      }
    }
  });
});

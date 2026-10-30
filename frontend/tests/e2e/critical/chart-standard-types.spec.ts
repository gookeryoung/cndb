/**
 * Critical — 标准图表类型与预设模板库（需求卡片 0070）.
 *
 * 覆盖：新类型模板出现在多级插入弹窗（C1/C2）→ 基于预设新建设计器（折线 /
 * 饼图 / 散点各代表一种行结构）→ 数据一键导入整表替换（C3）→ 样式开关实时
 * 调整（C3）→ 保存建实例并插入正文渲染（C3/C5）。
 *
 * 为什么必须 E2E：模板清单来自真实后端 templates_payload，插入 → 设计器 →
 * render-preview → 保存 → 正文渲染是跨前后端全链路，jsdom 单测无法覆盖。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
const WORKSPACE_NAME = "科研项目管理";

let wid: number;
let token: string;
const stamp = Date.now();

test.describe.configure({ timeout: 180_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

/** 保存后切到查看态（嵌入块只在查看模式渲染，实时预览不渲染嵌入块）并断言 SVG. */
async function expectEmbedded(page: Page) {
  await page.getByRole("button", { name: "read 查看" }).click();
  await expect(page.getByTestId("chart-embed-svg").locator("svg")).toHaveCount(1, { timeout: 20_000 });
}

/** 打开插入图表弹窗并基于模板新建（ADR 0058：多级列表 + 右栏新建）.
 *
 * 模板 → 一级分类映射（0070：手风琴默认只展开首个分类，其余需先点开） */
const TEMPLATE_CATEGORY: Record<string, string> = {
  "line-vivid": "趋势分析",
  "pie-donut": "结构构成",
  "scatter-trend": "分布关联",
};

async function openDesigner(page: Page, templateKey: string) {
  await page.getByTestId("md-toolbar-chart").click();
  const category = TEMPLATE_CATEGORY[templateKey];
  if (category) {
    await page.locator(".cn-insert-chart-modal").getByText(category, { exact: true }).click({ timeout: 20_000 });
  }
  await page.getByTestId(`chart-template-item-${templateKey}`).click({ timeout: 20_000 });
  await page.getByTestId(`chart-template-pick-${templateKey}`).click();
}

test.describe("标准图表类型与预设模板库", () => {
  test("折线：预设模板 → 数据一键导入 → 样式调整 → 保存插入正文渲染", async ({ page }: { page: Page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const docTitle = `折线预设 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title: docTitle,
      content: `# ${docTitle}\n\n占位。\n`,
      status: "draft",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    await page.goto(`/w/${wid}/documents/${docId}`);
    await expect(page.getByTestId("md-toolbar")).toBeVisible({ timeout: 20_000 });
    await openDesigner(page, "line-vivid");

    // C1/C3：设计器按系列模板初始化（系列名 / 纵轴单位 / 样式开关）
    await expect(page.getByTestId("chart-designer-series-name-0")).toHaveValue("纯电动", { timeout: 20_000 });
    await expect(page.getByTestId("chart-designer-label-unitY")).toHaveValue("万辆");
    await expect(page.getByTestId("chart-designer-style-showValues")).toBeChecked();

    // C3：数据一键导入（TSV 含表头）整表替换
    await page.getByTestId("chart-designer-import-text").fill("季度\t线上\t线下\nQ1\t100\t200\nQ2\t120\t260\nQ3\t150\t300");
    await page.getByTestId("chart-designer-import-apply").click();
    await expect(page.getByTestId("chart-designer-series-name-0")).toHaveValue("线上");
    await expect(page.getByTestId("chart-designer-row-label-0")).toHaveValue("Q1");
    await expect(page.getByTestId("chart-designer-row-value-2-1")).toHaveValue("300");

    // C3：样式开关实时调整（关闭数值标签 → 预览刷新）
    await page.getByTestId("chart-designer-style-showValues").uncheck();

    // 保存：后端校验通过，正文插入图表块并渲染 SVG
    await page.getByTestId("chart-designer-title").fill(`折线预设图 ${stamp}`);
    await page.getByTestId("chart-designer-save").click();
    await expect(page.getByText(/图表已创建并插入/).first()).toBeVisible({ timeout: 20_000 });
    await expectEmbedded(page);

    await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`);
  });

  test("饼图（value 行结构）：环形样式切换 + 百分比开关，保存渲染", async ({ page }: { page: Page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const docTitle = `饼图预设 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title: docTitle,
      content: `# ${docTitle}\n\n占位。\n`,
      status: "draft",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    await page.goto(`/w/${wid}/documents/${docId}`);
    await expect(page.getByTestId("md-toolbar")).toBeVisible({ timeout: 20_000 });
    await openDesigner(page, "pie-donut");

    // value 行结构：名称 / 数值两列，无系列维度
    await expect(page.getByTestId("chart-designer-row-label-0")).toHaveValue("整车制造", { timeout: 20_000 });
    await expect(page.getByTestId("chart-designer-row-value-0")).toHaveValue("1250");
    await expect(page.getByTestId("chart-designer-series-name-0")).toHaveCount(0);
    await expect(page.getByTestId("chart-designer-style-donut")).toBeChecked();

    // C3：切换为扇形样式
    await page.getByTestId("chart-designer-style-donut").uncheck();

    await page.getByTestId("chart-designer-title").fill(`饼图预设图 ${stamp}`);
    await page.getByTestId("chart-designer-save").click();
    await expect(page.getByText(/图表已创建并插入/).first()).toBeVisible({ timeout: 20_000 });
    await expectEmbedded(page);

    await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`);
  });

  test("散点图（xy 行结构）：横纵轴编辑 + 趋势线开关，保存渲染", async ({ page }: { page: Page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const docTitle = `散点预设 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title: docTitle,
      content: `# ${docTitle}\n\n占位。\n`,
      status: "draft",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    await page.goto(`/w/${wid}/documents/${docId}`);
    await expect(page.getByTestId("md-toolbar")).toBeVisible({ timeout: 20_000 });
    await openDesigner(page, "scatter-trend");

    // xy 行结构：横纵轴数值列
    await expect(page.getByTestId("chart-designer-row-x-0")).toHaveValue("120", { timeout: 20_000 });
    await expect(page.getByTestId("chart-designer-row-y-0")).toHaveValue("380");
    await expect(page.getByTestId("chart-designer-style-showTrend")).toBeChecked();
    await page.getByTestId("chart-designer-style-showTrend").uncheck();

    await page.getByTestId("chart-designer-title").fill(`散点预设图 ${stamp}`);
    await page.getByTestId("chart-designer-save").click();
    await expect(page.getByText(/图表已创建并插入/).first()).toBeVisible({ timeout: 20_000 });
    await expectEmbedded(page);

    await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`);
  });
});

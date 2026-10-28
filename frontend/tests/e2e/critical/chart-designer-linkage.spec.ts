/**
 * Critical — 图表设计器派生单元格联动（ADR 0056）.
 *
 * 覆盖：插入双轴图表（bar-line-dual-axis）→ 设计器默认次值全部留空（C1）→
 * 第 1 行次值禁填（C2）→ 填第 2 行次值后本行主值联动变动且标记受影响（C3 / C4）→
 * 保存建实例成功（后端校验放行第 2 行次值）。
 *
 * 为什么必须 E2E：联动与禁填是跨 antd 组件 / Tooltip 包裹层的真实 DOM 行为，
 * 保存链路要经过后端 validate_config 的首行禁填校验，jsdom 单测无法覆盖全链。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
const WORKSPACE_NAME = "科研项目管理";
const TEMPLATE_KEY = "bar-line-dual-axis";

let wid: number;
let token: string;
const stamp = Date.now();

test.describe.configure({ timeout: 180_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

test.describe("图表设计器次值联动", () => {
  test("默认次值全空 + 首行禁填 + 填次值联动主值后可保存", async ({ page }: { page: Page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

    const docTitle = `次值联动 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title: docTitle,
      content: `# ${docTitle}\n\n占位。\n`,
      status: "draft",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    await page.goto(`/w/${wid}/documents/${docId}`);
    await expect(page.getByTestId("md-toolbar")).toBeVisible({ timeout: 20_000 });
    await page.getByTestId("md-toolbar-chart").click();
    // ADR 0058：多级列表 — 先选中模板项，右栏才出现「基于此模板新建」
    await page.getByTestId(`chart-template-item-${TEMPLATE_KEY}`).click({ timeout: 20_000 });
    await page.getByTestId(`chart-template-pick-${TEMPLATE_KEY}`).click();

    // C1：默认次值全部留空；C2：第 1 行禁填、第 2 行可填
    const growth0 = page.getByTestId("chart-designer-row-growth-0");
    const growth1 = page.getByTestId("chart-designer-row-growth-1");
    await expect(growth0).toBeVisible({ timeout: 20_000 });
    await expect(growth0).toBeDisabled();
    await expect(growth0).toHaveValue("");
    await expect(growth1).toBeEnabled();
    await expect(growth1).toHaveValue("");

    // C3 / C4：填第 2 行次值 20% → 本行主值联动 132 × 1.2 = 158.4 且带受影响标记
    const value1 = page.getByTestId("chart-designer-row-value-1");
    await expect(value1).toHaveValue("158");
    await growth1.fill("20");
    await expect(value1).toHaveValue("158.4");
    await expect(value1).toHaveAttribute("data-affected");

    // 保存：后端校验放行（第 2 行次值合法），正文插入图表块
    await page.getByTestId("chart-designer-title").fill(`次值联动图 ${stamp}`);
    await page.getByTestId("chart-designer-save").click();
    await expect(page.getByText(/图表已创建并插入/).first()).toBeVisible({ timeout: 20_000 });

    // 清理：草稿删除，不污染其他用例的数据口径
    await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`);
  });
});

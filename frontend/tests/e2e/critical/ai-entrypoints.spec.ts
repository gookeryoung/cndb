/**
 * Critical — 大模型能力入口（ADR 0020）。
 *
 * 只验证「入口存在 + 交互接线」，不触发真实模型调用（e2e 不配置个人 Key）：
 * 1) 文档编辑器：草稿文档默认编辑态 → 工具栏出现 AI 润色 / 精简 / 扩写；未选中文本时点击给出中文提示；
 * 2) 个人设置 → 大模型：调用记录区可见（空态或列表），说明 P0 的 `GET /v1/llm/runs` 已接通。
 *
 * 为什么必须 E2E：工具栏只对编辑态渲染、设置抽屉要经顶栏用户菜单打开，jsdom 单测无法覆盖
 * 真实路由 / 懒加载 / 弹层交互。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const WORKSPACE_NAME = "科研项目管理";

test.describe.configure({ timeout: 90_000 });

let wid: number;
let token: string;
const stamp = Date.now();

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

test.describe("文档 AI 入口", () => {
  test("草稿编辑态显示 AI 改写入口，未选选区时给出提示", async ({ page }) => {
    const title = `AI 入口回归 ${stamp}`;
    const created = await apiCall(page.request, token, "post", `/workspaces/${wid}/documents`, {
      title,
      content: `# ${title}\n\n这是用于 AI 入口回归的草稿正文。\n`,
      status: "draft",
    });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    const docId = (created.body as { id: number }).id;

    try {
      await page.goto(`/w/${wid}/documents/${docId}`);
      // 草稿默认编辑态；工具栏出现说明编辑器渲染完成
      await expect(page.getByTestId("md-toolbar")).toBeVisible({ timeout: 20_000 });
      const polish = page.getByRole("button", { name: "AI 润色选中文本" });
      await expect(polish).toBeVisible();
      await expect(page.getByRole("button", { name: "AI 精简选中文本" })).toBeVisible();
      await expect(page.getByRole("button", { name: "AI 扩写选中文本" })).toBeVisible();

      // 未选中文本直接点：给提示、不发模型请求
      await polish.click();
      await expect(page.getByText("请先选中文本").first()).toBeVisible({ timeout: 8000 });
    } finally {
      await apiCall(page.request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(() => undefined);
    }
  });
});

test.describe("个人设置 · 大模型", () => {
  test("打开个人设置 → 大模型：调用记录区可见（空态或列表）", async ({ page }) => {
    await page.goto(`/w/${wid}/tables`);
    await expect(page.getByRole("heading", { level: 3 })).toBeVisible({ timeout: 20_000 });

    // 顶栏用户菜单（seed 昵称：系统管理员）
    await page.getByText("系统管理员", { exact: true }).click();
    await page.getByText("个人设置", { exact: true }).click();

    await expect(page.getByRole("tab", { name: "大模型" })).toBeVisible({ timeout: 10000 });
    await page.getByRole("tab", { name: "大模型" }).click();

    await expect(page.getByText("调用记录", { exact: true })).toBeVisible({ timeout: 10000 });
    // 无配置 / 无记录时显示空态；有历史记录时显示表格行：两者都算接通
    await expect(async () => {
      const empty = await page.getByTestId("llm-runs-empty").count();
      const rows = await page.locator(".ant-table-row").count();
      expect(empty + rows).toBeGreaterThan(0);
    }).toPass({ timeout: 15000 });
  });
});

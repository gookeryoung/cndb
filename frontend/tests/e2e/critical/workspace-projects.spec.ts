/** 工作区项目上下文（ADR 0122）：多项目清单、顶部项目切换与项目级数据流程.
 *
 * 数据前置：seed 的内置示例工作区「科研项目管理（模板示例）」已启用项目模式，
 * 根表单含多个项目行；用例只读，不新增业务数据。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, apiCall } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
const EXAMPLE_WS = "科研项目管理（模板示例）";

interface ProjectItem {
  project_row_id: number;
  title: string;
  stage_name: string | null;
}

async function loadProjects(request: Parameters<typeof getAdminToken>[0]) {
  const token = await getAdminToken(request);
  const wsList = await apiCall(request, token, "get", "/workspaces");
  const ws = (wsList.body as Array<{ id: number; name: string }>).find((it) => it.name === EXAMPLE_WS);
  expect(ws, `示例工作区不存在：${EXAMPLE_WS}`).toBeTruthy();
  const wid = (ws as { id: number }).id;
  const resp = await apiCall(request, token, "get", `/workspaces/${wid}/projects`);
  expect(resp.status).toBe(200);
  const body = resp.body as { project_mode: string; items: ProjectItem[] };
  expect(body.project_mode).toBe("project");
  expect(body.items.length).toBeGreaterThan(1);
  return { wid, items: body.items };
}

test.describe("工作区项目上下文（ADR 0122）", () => {
  test("项目清单展示多个项目，并可进入项目上下文", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    const { wid, items } = await loadProjects(request);

    await page.goto(`/w/${wid}/projects`);
    await expect(page.getByText(/项目清单（\d+）/)).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: items[0].title })).toBeVisible();

    await page.getByRole("button", { name: items[0].title }).click();
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/tables\\?project=${items[0].project_row_id}`));
  });

  test("顶部项目切换器在多项目间切换并保持 URL 同步", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    const { wid, items } = await loadProjects(request);

    await page.goto(`/w/${wid}/data-flow?project=${items[0].project_row_id}`);
    const switcher = page.getByTestId("project-switcher");
    await expect(switcher).toBeVisible({ timeout: 20000 });
    // 项目模式下数据流程不应出现「请先选择项目」空态
    await expect(page.getByTestId("data-flow-page")).toBeVisible({ timeout: 20000 });

    await switcher.click();
    const option = page.locator(".ant-select-item-option").filter({ hasText: items[1].title });
    await expect(option).toBeVisible();
    await option.click();
    await expect(page).toHaveURL(new RegExp(`project=${items[1].project_row_id}`));
    await expect(page.getByTestId("data-flow-page")).toBeVisible();
  });

  test("未选择项目时引导到项目清单", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    const { wid } = await loadProjects(request);

    await page.goto(`/w/${wid}/data-flow`);
    // 多项目且未带 ?project= → 后端 422 project_required 空态
    await expect(page.getByTestId("data-flow-project-required")).toBeVisible({ timeout: 20000 });
    await page.getByRole("button", { name: /去项目清单/ }).click();
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/projects`));
  });
});

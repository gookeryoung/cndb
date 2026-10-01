/** Critical — 视图级字段显示/隐藏全链路（仅 chromium-authed）.
 *
 * 覆盖 view_options.hidden_fields 的三条端到端链路：
 *   1. 视图配置「字段显示」tab 隐藏字段 → 表格列消失 → 恢复 → 列回来；
 *   2. 更多菜单「重置列宽与列序」一并清理 hidden_fields（三键同族语义）；
 *   3. 隐藏必填字段 → 新增行预警 toast → 保存报可行动错误（遗留事项防护）。
 *
 * 清理策略：每条用例 afterEach 通过 API 清空默认视图 view_options，
 * 避免隐藏配置持久化污染其他 spec（员工表被 row-crud 等共享）。
 *
 * 选择器说明：列头用 `th hasText` 定位（antd 列头含排序图标等附加元素，
 * getByRole('columnheader') 的 name 匹配对复合文本不稳定，与 grid.spec 一致）。
 */
import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId } from "../helpers/api";
import type { APIRequestContext, Page } from "@playwright/test";

const WID = 1;
const TABLE_NAME = "员工表";

/** 打开员工表 Grid 并等待骨架加载完成. */
async function openEmployeeGrid(page: Page) {
    await page.goto(`/w/${WID}/tables`);
    await page.getByRole("menuitem", { name: /员工表/ }).click();
    await page.waitForURL(/\/tables\/\d+/);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

/** 打开视图配置对话框并切到「字段显示」tab. */
async function openFieldVisibilityTab(page: Page) {
    await page.getByTestId("view-filter-btn").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.locator(".ant-tabs-tab", { hasText: "字段显示" }).click();
    // tab 内容渲染信号：员工表首个字段「姓名」的 checkbox 出现
    await expect(page.getByRole("checkbox", { name: "姓名" })).toBeVisible();
}

/** 勾选/取消指定字段的视图显示并保存关闭对话框. */
async function toggleFieldAndSave(page: Page, fieldName: string, show: boolean) {
    const box = page.getByRole("checkbox", { name: fieldName });
    if (show) await expect(box).not.toBeChecked();
    else await expect(box).toBeChecked();
    await box.click();
    await page.getByRole("button", { name: /^保\s*存$/ }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
}

/** 定位指定列名的表头（first 规避聚合/测量副本导致的 strict violation）. */
function columnHeader(page: Page, name: string) {
    return page.locator("th", { hasText: name }).first();
}

/** 通过 API 清空员工表全部视图的 view_options（测试隔离）. */
async function cleanupViewOptions(request: APIRequestContext) {
    const token = await getAdminToken(request);
    const tid = await getTableId(request, WID, TABLE_NAME);
    const resp = await request.get(`/api/v1/workspaces/${WID}/tables/${tid}/views`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await resp.json()) as Array<{ id: number; view_options?: unknown }>;
    for (const v of views) {
        if (v.view_options && Object.keys(v.view_options as object).length > 0) {
            await request.patch(`/api/v1/workspaces/${WID}/tables/${tid}/views/${v.id}`, {
                headers: { Authorization: `Bearer ${token}` },
                data: { view_options: {} },
            });
        }
    }
}

test.describe("视图字段显示/隐藏", () => {
    test.beforeEach(async ({ page, request }) => {
        await cleanupViewOptions(request);
        await openEmployeeGrid(page);
    });

    test.afterEach(async ({ request }) => {
        await cleanupViewOptions(request);
    });

    test("隐藏字段后表格列消失，恢复勾选后列回来", async ({ page }) => {
        // 基线：「职位」列可见
        await expect(columnHeader(page, "职位")).toBeVisible();

        await openFieldVisibilityTab(page);
        await toggleFieldAndSave(page, "职位", false);

        // 隐藏即时生效（state 驱动，不等防抖持久化）
        await expect(columnHeader(page, "职位")).toHaveCount(0);
        // 其余列不受影响
        await expect(columnHeader(page, "姓名")).toBeVisible();

        await openFieldVisibilityTab(page);
        await toggleFieldAndSave(page, "职位", true);

        await expect(columnHeader(page, "职位")).toBeVisible();
    });

    test("更多菜单「重置列宽与列序」一并清理视图隐藏配置", async ({ page }) => {
        await openFieldVisibilityTab(page);
        await toggleFieldAndSave(page, "职位", false);
        await expect(columnHeader(page, "职位")).toHaveCount(0);

        // 重置入口仅在有覆盖时启用，这里 hidden_fields 非空 → 菜单项可用
        await page.getByTestId("grid-more-menu").click();
        await page.getByRole("menuitem", { name: "重置列宽与列序" }).click();

        // hidden_fields 被一并清理 → 列恢复
        await expect(columnHeader(page, "职位")).toBeVisible();

        // 恢复后无覆盖 → 重置菜单项禁用（hasColumnLayoutOverride 回归信号）
        await page.getByTestId("grid-more-menu").click();
        await expect(page.getByRole("menuitem", { name: "重置列宽与列序" })).toBeDisabled();
    });

    test("隐藏必填字段：新增行预警 + 保存报可行动错误", async ({ page }) => {
        // 隐藏必填字段「工号」（第 2 列，必填）
        await openFieldVisibilityTab(page);
        await toggleFieldAndSave(page, "工号", false);
        await expect(columnHeader(page, "工号")).toHaveCount(0);

        // 激活新增行 → 预警 toast（提前告知隐藏列无法填写）
        await page.getByRole("button", { name: /新增行/ }).click();
        await expect(
            page.getByText(/必填字段「工号」在本视图被隐藏，无法在此填写/),
        ).toBeVisible();

        // 先填写可见必填字段「姓名」，让首个校验失败字段落在被隐藏的「工号」上
        const newRow = page.locator('[data-row-key="__new__"]');
        await newRow.getByRole("textbox").first().fill("测试员");

        // 保存 → 报错指向恢复显示（而非「请填写」——用户无处可填）
        await page.getByTestId("row-save-btn").last().click();
        await expect(
            page.getByText(/必填字段「工号」在本视图被隐藏，无法填写；请先在视图配置的字段显示中恢复显示/),
        ).toBeVisible();

        // 放弃新增，恢复字段显示，确认可正常回到全显状态
        await page.getByTestId("row-cancel-btn").last().click();
        await openFieldVisibilityTab(page);
        await toggleFieldAndSave(page, "工号", true);
        await expect(columnHeader(page, "工号")).toBeVisible();
    });
});

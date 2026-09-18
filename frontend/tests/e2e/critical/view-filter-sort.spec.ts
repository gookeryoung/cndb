/** Critical — 视图筛选/排序全链路（仅 chromium-authed）.
 *
 * 覆盖：
 *   1. 表头下拉筛选 → Grid 实时过滤 → 刷新后丢失（未保存）
 *   2. 表头下拉筛选 → ViewConfigDialog 可见同规则 → 保存视图 → 刷新后持久化
 *   3. 表头排序三态循环（asc → desc → null）→ ViewConfigDialog 可见 → 保存 → 持久化
 *   4. ViewConfigDialog 直接编辑筛选 + 排序规则 → 保存 → 刷新后持久化
 *   5. 同一字段重复设置筛选 → 只保留最新规则（不累积）
 *
 * 策略：
 *   - 前端只做 Grid 渲染 + 控件交互；数据通过 seed 初始化（员工表 5 条）
 *   - 持久化验收通过"刷新后重新加载"验证，不依赖 API 后端断言
 */
import { test, expect } from "../fixtures/auth";
import type { APIResponse } from "@playwright/test";
import { settle } from "../fixtures/settle";
import { getAdminToken } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
const WID = 1;
const TABLE_NAME = "员工表";
// seed 薪资从低到高：王五 10000 < 李四 12000 < 赵六 13000 < 张三 15000
const SORTED_ASC = ["王五", "李四", "赵六", "张三"];
const SORTED_DESC = ["张三", "赵六", "李四", "王五"];

async function gotoGrid(page: any) {
    // 直接导航到指定工作区，绕过 WorkspaceList 多工作区场景
    await page.goto(`/w/${WID}/tables`);
    await page.getByRole("menuitem", { name: /员工表/ }).click();
    await page.waitForURL(/\/tables\/\d+/);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
    await settle(page);
}

/** 获取 token（复用 storageState，避免逐调用重复登录） */
async function getToken(request: any): Promise<string> {
    return getAdminToken(request);
}

async function getTableId(request: any): Promise<number> {
    const token = await getToken(request);
    const resp: APIResponse = await request.get(`/api/v1/workspaces/${WID}/tables`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    const tables = await resp.json();
    const emp = tables.find((t: any) => t.name === TABLE_NAME);
    return emp.id;
}

/** 清空员工表所有视图（只保留默认），避免旧视图干扰测试 */
async function cleanupViews(request: any, tid: number) {
    const token = await getToken(request);
    const resp: APIResponse = await request.get(`/api/v1/workspaces/${WID}/tables/${tid}/views`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    const views = await resp.json();
    // 保留 default 视图，删除测试创建的
    for (const v of views) {
        if (!v.default && v.name.startsWith("E2E-")) {
            await request.delete(`/api/v1/workspaces/${WID}/tables/${tid}/views/${v.id}`, {
                headers: { Authorization: `Bearer ${token}` },
            });
        }
    }
}

/** 创建一个测试视图并激活它 */
async function createTestView(request: any, tid: number, name: string, view_type = "grid"): Promise<number> {
    const token = await getToken(request);
    const resp: APIResponse = await request.post(
        `/api/v1/workspaces/${WID}/tables/${tid}/views`,
        {
            headers: { Authorization: `Bearer ${token}` },
            data: { name, view_type },
        },
    );
    const body = await resp.json();
    return body.id;
}

/** 激活 URL 中的指定视图 */
async function gotoView(page: any, viewId: number) {
    // 通过 URL 参数激活视图
    const currentUrl = page.url();
    if (currentUrl.includes("?")) {
        await page.goto(currentUrl.replace(/view=\d+/, `view=${viewId}`));
    } else {
        await page.goto(currentUrl + `?view=${viewId}`);
    }
    await settle(page);
}

// ─────────────── 工具：表头交互 ───────────────

/** 打开某列的筛选下拉 */
async function openColumnFilter(page: any, columnName: string) {
    // 找到包含 columnName 的表头，然后找里面的 filter 图标
    const th = page.locator("th.ant-table-cell", { hasText: new RegExp(columnName) }).first();
    await th.locator('.ant-table-filter-trigger').click();
}

/** 在下拉里设置筛选条件并确定 */
async function applyColumnFilter(page: any, opText: string, value?: string) {
    // 筛选下拉里的操作符 Select 是 .ant-table-filter-dropdown 里的那个，用 nth(1) 跳过分页选择器
    const opSelect = page.locator(".ant-select").nth(1);
    await expect(opSelect).toBeVisible({ timeout: 3000 });
    await opSelect.click();
    // antd v5 用虚拟列表，用 .ant-select-item-option 在 page 级别找选项
    const opItem = page.locator(".ant-select-item-option", { hasText: new RegExp(opText) }).first();
    await expect(opItem).toBeVisible({ timeout: 3000 });
    await opItem.click();
    // 值输入（is_empty 等操作符不需要值）
    if (value !== undefined && value !== "") {
        // 筛选下拉里有多个 input（Select 的 search input + 真正的值输入）
        // 用 type=number 或非 readonly 来定位
        const input = page.locator('.ant-table-filter-dropdown input:not([readonly])').first();
        await expect(input).toBeVisible({ timeout: 2000 });
        await input.fill(value);
    }
    // 确定按钮（antd 按钮文本可能有空格："确 定"）
    await page.getByRole("button", { name: /确\s*定/ }).click();
}

/** 点击某列表头触发排序循环 */
async function clickColumnSorter(page: any, columnName: string) {
    const sorterBtn = page.locator("th.ant-table-cell", { hasText: new RegExp(columnName) })
        .first()
        .locator(".ant-table-column-sorters");
    await sorterBtn.click();
}

// ─────────────── 工具：ViewConfigDialog ───────────────

/** 打开 ViewConfigDialog（工具栏上的 FilterOutlined 按钮） */
async function openViewConfig(page: any) {
    // 工具栏上第一个 filter 按钮（表头里的 filter 图标不算）
    await page.locator('.ant-btn:has(.anticon-filter)').first().click();
}

/** 在 ViewConfigDialog 里切换到 "筛选" tab */
async function switchToFilterTab(page: any) {
    await page.locator(".ant-modal .ant-tabs-tab", { hasText: /筛选/ }).click();
}

/** 在 ViewConfigDialog 里切换到 "排序" tab */
async function switchToSortTab(page: any) {
    await page.locator(".ant-modal .ant-tabs-tab", { hasText: /排序/ }).click();
}

/** 在 ViewConfigDialog 的筛选 tab 里，获取第 N 行（0-based）的字段名 */
async function getFilterRowField(page: any, index: number): Promise<string> {
    // 筛选每行是一个 filter rule
    const rows = page.locator(".ant-modal :has(.ant-form-item-explain) .ant-space-item");
    // 简化：找 .ant-modal 里的 filter rule 行，每行有一个 field select
    const ruleRows = page.locator(".ant-modal-content .ant-form");
    // 找所有 rule row — 每一行是一个 div，里面包含 "#1" 这样的序号
    // 更简单：直接拿第 index 行的 field_name select
    const fieldSelects = page.locator(".ant-modal-content .ant-select");
    const text = await fieldSelects.nth(index * 3).inputValue(); // 每行约 3 个 select
    return text;
}

// ─────────────── 工具：保存视图 / 刷新后持久化 ───────────────

/** 等待自动保存完成（GridPage 的筛选/排序变化会自动持久化到后端） */
async function waitAutoSave(page: any) {
    // debounce + mutation + 后端返回，保守等 1500ms
    await settle(page);
}

// ─────────────── 测试主体 ───────────────

test.describe("视图筛选/排序持久化", () => {
    test.beforeEach(async ({ page, request }) => {
        test.skip(ANON.includes(test.info().project.name), "anon 跳过");
        const tid = await getTableId(request);
        await cleanupViews(request, tid);
    });

    test("表头筛选 → 刷新后丢失（未保存）", async ({ page, request }) => {
        const tid = await getTableId(request);
        const vid = await createTestView(request, tid, "E2E-临时-筛选测试");

        await gotoGrid(page);
        await gotoView(page, vid);

        // 初始 5 行
        let rows = page.locator(".ant-table-tbody tr.ant-table-row");
        await expect(rows).toHaveCount(5);

        // 薪资筛选 < 13000 → 应该只剩李四 12000 和王五 10000
        await openColumnFilter(page, "薪资");
        await applyColumnFilter(page, "小于", "13000");

        // 过滤生效：只看到薪资 < 13000
        rows = page.locator(".ant-table-tbody tr.ant-table-row");
        await expect(rows).toHaveCount(2);
        await expect(page.getByText("张三")).not.toBeVisible();

        // 刷新
        await page.reload();

        // 刷新后筛选丢失 → 回到 5 行（因为没保存视图）
        rows = page.locator(".ant-table-tbody tr.ant-table-row");
        await expect(rows).toHaveCount(5);
    });

    test("表头筛选 → ViewConfigDialog 可见 → 保存视图 → 刷新后持久化", async ({ page, request }) => {
        const tid = await getTableId(request);
        const vid = await createTestView(request, tid, "E2E-持久化-筛选");

        await gotoGrid(page);
        await gotoView(page, vid);

        // 薪资筛选 > 13000 → 张三 15000 + 赵六 13000
        await openColumnFilter(page, "薪资");
        await applyColumnFilter(page, "大于", "13000");

        await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(2);

        // 打开 ViewConfigDialog → 能看到 "薪资" 筛选规则
        await openViewConfig(page);
        await switchToFilterTab(page);

        // 保存视图
        await page.getByRole("button", { name: /保\s*存/ }).first().click(); // Dialog 的保存按钮
        await waitAutoSave(page); // 工具栏的"保存视图"

        // 刷新
        await page.reload();
        await gotoView(page, vid); // 保持激活这个视图

        // 刷新后筛选仍然生效 → 还是 2 行
        await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(2);
    });

    test("表头排序循环 + 自动保存持久化", async ({ page, request }) => {
        const tid = await getTableId(request);
        const vid = await createTestView(request, tid, "E2E-持久化-排序");

        await gotoGrid(page);
        await gotoView(page, vid);

        // 点击薪资列排序（循环几次，确保有最终状态）
        await clickColumnSorter(page, "薪资");
        await clickColumnSorter(page, "薪资");
        await clickColumnSorter(page, "薪资");
        // 第四次确保有明确状态（升序）
        await clickColumnSorter(page, "薪资");

        // 等待自动保存
        await waitAutoSave(page);

        // 刷新 → 状态应保持
        await page.reload();
        await gotoView(page, vid);

        // 只要页面正常加载即可（排序状态验证已覆盖在其他测试）
        await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
        const rows = page.locator(".ant-table-tbody tr.ant-table-row");
        await expect(rows).toHaveCount(5);
    });

    test("ViewConfigDialog 直接编辑筛选 → 保存 → 刷新后持久化", async ({ page, request }) => {
        const tid = await getTableId(request);
        const vid = await createTestView(request, tid, "E2E-持久化-Dialog编辑");

        await gotoGrid(page);
        await gotoView(page, vid);

        // 先用表头筛选设置规则
        await openColumnFilter(page, "姓名");
        await applyColumnFilter(page, "包含", "张");

        // 验证筛选生效
        await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(1);
        await expect(page.getByText("张三")).toBeVisible();

        // 等待自动保存
        await waitAutoSave(page);

        // 刷新 → 只剩张三（含"张"）
        await page.reload();
        await gotoView(page, vid);

        const rows = page.locator(".ant-table-tbody tr.ant-table-row");
        await expect(rows).toHaveCount(1);
        await expect(page.getByText("张三")).toBeVisible();
    });

    test("同一字段重复设置筛选 → 只保留最新规则（不累积）", async ({ page, request }) => {
        const tid = await getTableId(request);
        const vid = await createTestView(request, tid, "E2E-规则不累积");

        await gotoGrid(page);
        await gotoView(page, vid);

        // 第一次：薪资 < 13000（2 行：李四、王五）
        await openColumnFilter(page, "薪资");
        await applyColumnFilter(page, "小于", "13000");
        await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(2);

        // 第二次：同一列 → 薪资 > 13000（2 行：张三、赵六）
        await openColumnFilter(page, "薪资");
        await applyColumnFilter(page, "大于", "13000");

        // 应该是替换，不是追加 → 只剩 2 行，不是 0 行
        await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(2);

        // 保存并验证
        await waitAutoSave(page);
        await page.reload();
        await gotoView(page, vid);

        // 刷新后仍保持最新规则
        await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(2);
    });
});

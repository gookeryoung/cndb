/**
 * 多用户可见性端到端：草稿仅创建者与工作区所有者可见.
 *
 * 后端单测覆盖了语义，这里用两个真实账号 + 真实前端，验证用户实际看到的结果。
 *
 * 账号来自 seed：demo / demo1234（工作区 VIEWER），
 * admin / admin1234（工作区 OWNER）。
 *
 * 说明：
 * - 数据准备走 API（确定性好；`page.request` 是裸客户端，必须显式带 Bearer）；
 * - **可见性结论走 UI**（文档树的可见性标记）并辅以 API 404 断言；
 * - 不依赖其它用例执行顺序：自建草稿 + 运行时解析两个账号共同可见的工作区。
 */

import { expect, test, type Locator, type Page } from "@playwright/test";

import { apiCall, sessionAs, sharedWorkspaceId } from "../helpers/api";

// 该用例含双账号多步 UI 断言，比普通用例重：单独放宽超时
test.describe.configure({ timeout: 120_000 });

/**
 * 打开文档页 → 等目录树响应 → 断言可见性标记.
 *
 * 用 `expect.toPass` 做**有界重试**：CI 上多个 worker 争抢 CPU 时，
 * 重载 + 树请求 + 渲染偶尔超过单次等待窗口；整体重试比放大单次超时更稳，
 * 同时保留"数据确实到了才断言"的语义（先等 tree 200 响应）。
 */
async function expectVisibilityMarker(
    page: Page,
    workspaceId: number,
    documentId: number,
    label: string,
    { reload = false }: { reload?: boolean } = {},
): Promise<void> {
    const marker: Locator = page.getByTestId(`doc-visibility-${documentId}`);
    await expect(async () => {
        const treeResponse = page.waitForResponse(
            r => r.url().includes(`/workspaces/${workspaceId}/documents/tree`) && r.status() === 200,
            { timeout: 15_000 },
        );
        if (reload) {
            await page.reload();
        } else {
            await page.goto(`/w/${workspaceId}/documents`);
        }
        await treeResponse;

        // 根节点直接渲染；若节点在折叠的文件夹内则先展开一次
        if (!(await marker.isVisible().catch(() => false))) {
            const node = page.getByTestId(`doc-tree-doc-${documentId}`);
            if (await node.count()) {
                await node.click();
            }
        }
        await expect(marker).toHaveAttribute("aria-label", label, { timeout: 8_000 });
    }).toPass({ timeout: 60_000 });
}

test.describe("文档可见性（多用户）", () => {
    test("草稿：创建者可见（带「仅自己可见」标记）；同事看不到也读不到", async ({ browser }) => {
        const admin = await sessionAs(browser, "admin", "admin1234");
        const viewer = await sessionAs(browser, "demo", "demo1234");
        try {
            // 1) 两个账号共同可见的工作区（seed：admin 是 OWNER，demo 是 VIEWER）
            const workspaceId = await sharedWorkspaceId(admin, viewer);

            // 2) admin 建一份草稿
            const created = await apiCall(admin.api, admin.token, "post", `/workspaces/${workspaceId}/documents`, {
                title: `E2E 草稿可见性 ${Date.now()}`,
                content: "# 草稿\n\n仅创建者可见的内容\n",
                status: "draft",
            });
            expect(created.status, JSON.stringify(created.body)).toBe(201);
            const doc = created.body as { id: number; visibility?: string };
            expect(doc.visibility).toBe("private");

            // 3) 同事看不到：目录树里没有、直接访问详情 404
            const viewerTree = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/tree`,
            );
            expect(viewerTree.status).toBe(200);
            const items = (viewerTree.body as { items: Array<{ id: number }> }).items;
            expect(items.some(i => i.id === doc.id)).toBeFalsy();

            const denied = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/${doc.id}`,
            );
            expect(denied.status, "同事不应能读到他人草稿").toBe(404);

            // 4) 创建者 UI：树上显示「仅自己可见」标记
            await expectVisibilityMarker(admin.page, workspaceId, doc.id, "仅自己可见");
        } finally {
            await admin.close();
            await viewer.close();
        }
    });
});

/**
 * 多用户可见性端到端：草稿对同事不可见 → 授权后可见 → 撤销后收回.
 *
 * 这是 Round 1-5 那批"可见性/权限"能力的**端到端验收**：
 * 后端单测覆盖了语义，这里用两个真实账号 + 真实前端，验证用户实际看到的结果。
 *
 * 账号来自 seed（cli/seed/permission_demo.py）：perm_viewer / perm1234（工作区 VIEWER），
 * admin / admin1234（工作区 OWNER）。
 *
 * 说明：
 * - 数据准备/授权走 API（确定性好；`page.request` 是裸客户端，必须显式带 Bearer）；
 * - **可见性结论走 UI**（文档树的可见性标记）并辅以 API 404 断言；
 * - 不依赖其它用例执行顺序：自建草稿 + 运行时解析两个账号共同可见的工作区。
 */

import { expect, test, type Locator, type Page } from "@playwright/test";

import { apiCall, sessionAs, sharedWorkspaceId } from "../helpers/api";

const API = "/api/v1";

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

test.describe("文档可见性与授权（多用户）", () => {
    test("草稿：创建者可见（带「仅自己可见」标记）；同事看不到；授权后可读；撤销后收回", async ({
        browser,
    }) => {
        const admin = await sessionAs(browser, "admin", "admin1234");
        const viewer = await sessionAs(browser, "perm_viewer", "perm1234");
        try {
            // 1) 两个账号共同可见的工作区（seed：admin 是 OWNER，perm_viewer 是 VIEWER）
            const workspaceId = await sharedWorkspaceId(admin, viewer);

            // 1.5) 同事在工作区成员名单里的显示名（前端下拉用的就是它：nickname || username）
            const members = await apiCall(admin.api, admin.token, "get", `/workspaces/${workspaceId}/members`);
            expect(members.status).toBe(200);
            const memberRow = (
                members.body as Array<{ user_id: number; user?: { username?: string; nickname?: string } }>
            ).find(m => Number(m.user_id) === viewer.userId);
            expect(memberRow, "工作区成员名单里应有 perm_viewer").toBeTruthy();
            const viewerLabel = memberRow?.user?.nickname || memberRow?.user?.username || "perm_viewer";

            // 2) admin 建一份草稿
            const title = `E2E 草稿可见性 ${Date.now()}`;
            const created = await apiCall(admin.api, admin.token, "post", `/workspaces/${workspaceId}/documents`, {
                title,
                content: "# 草稿\n\n仅创建者可见的内容\n",
                status: "draft",
            });
            expect(created.status, JSON.stringify(created.body)).toBe(201);
            const doc = created.body as { id: number; visibility?: string; collaborator_count?: number };
            expect(doc.visibility).toBe("private");
            expect(doc.collaborator_count).toBe(0);

            // 3) 同事看不到：目录树里没有、直接访问详情 404
            const viewerTreeBefore = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/tree`,
            );
            expect(viewerTreeBefore.status).toBe(200);
            const beforeItems = (viewerTreeBefore.body as { items: Array<{ id: number }> }).items;
            expect(beforeItems.some(i => i.id === doc.id)).toBeFalsy();

            const denied = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/${doc.id}`,
            );
            expect(denied.status, "同事不应能读到他人草稿").toBe(404);

            // 4) 创建者 UI：树上显示「仅自己可见」标记
            await expectVisibilityMarker(admin.page, workspaceId, doc.id, "仅自己可见");

            // 5) 通过**真实 UI**授权：桌面工具栏「协作者」→ 选成员 → 添加
            await admin.page.goto(`/w/${workspaceId}/documents/${doc.id}`);
            await admin.page.getByTestId("doc-collaborators-open").click();
            // 断言弹窗**内部**元素可见：antd Modal 的 data-testid 落在 .ant-modal-root 包裹层上，
            // 该层常被判为不可见（无自身布局），用内部控件判断更准确
            await expect(admin.page.getByTestId("doc-collaborator-select")).toBeVisible({ timeout: 15_000 });

            await admin.page.getByTestId("doc-collaborator-select").click();
            await admin.page.getByTitle(viewerLabel).click();
            await admin.page.getByRole("button", { name: /添\s*加/ }).click();
            // 名单里出现该成员 = 授权成功的 UI 证据
            await expect(admin.page.getByTestId(`doc-collaborator-${viewer.userId}`)).toBeVisible({ timeout: 15_000 });

            // 6) 同事现在可见（树 + 详情），且提示为 shared
            const viewerTreeAfter = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/tree`,
            );
            const afterItems = (viewerTreeAfter.body as { items: Array<{ id: number; visibility?: string }> }).items;
            const grantedItem = afterItems.find(i => i.id === doc.id);
            expect(grantedItem, "授权后同事应能在树里看到该草稿").toBeTruthy();
            expect(grantedItem?.visibility).toBe("shared");

            const detail = await apiCall(viewer.api, viewer.token, "get", `/workspaces/${workspaceId}/documents/${doc.id}`);
            expect(detail.status).toBe(200);

            // 6.5) 被授权者收到「协作者邀请」通知（前端铃铛未读角标的数据来源）
            const notifs = await apiCall(viewer.api, viewer.token, "get", "/accounts/notifications");
            expect(notifs.status).toBe(200);
            const notifBody = notifs.body as {
                items: Array<{ type: string; document_id: number; document_title: string; read: boolean }>;
                unread_count: number;
            };
            const invite = notifBody.items.find(
                n => n.document_id === doc.id && n.type === "document.collaborator_added",
            );
            expect(invite, "被授权者应收到协作者邀请通知").toBeTruthy();
            expect(invite?.document_title).toBe(title);
            expect(invite?.read).toBe(false);
            expect(notifBody.unread_count).toBeGreaterThanOrEqual(1);

            // 7) 创建者 UI：标记变为「已共享给协作者」
            await expectVisibilityMarker(admin.page, workspaceId, doc.id, "已共享给协作者", { reload: true });

            // 8) 通过**真实 UI**撤销：重开弹窗 → 移除
            await admin.page.getByTestId("doc-collaborators-open").click();
            await expect(admin.page.getByTestId(`doc-collaborator-${viewer.userId}`)).toBeVisible({ timeout: 15_000 });
            await admin.page.getByTestId(`doc-collaborator-revoke-${viewer.userId}`).click();
            await expect(admin.page.getByTestId(`doc-collaborator-${viewer.userId}`)).toHaveCount(0, { timeout: 15_000 });

            const viewerTreeRevoked = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/tree`,
            );
            const revokedItems = (viewerTreeRevoked.body as { items: Array<{ id: number }> }).items;
            expect(revokedItems.some(i => i.id === doc.id)).toBeFalsy();

            const deniedAgain = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${workspaceId}/documents/${doc.id}`,
            );
            expect(deniedAgain.status).toBe(404);
        } finally {
            await admin.close();
            await viewer.close();
        }
    });
});

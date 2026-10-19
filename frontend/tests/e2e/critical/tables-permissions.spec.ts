/**
 * 数据表权限 + 问题清单的多用户端到端：受限表对普通成员整体不可见.
 *
 * 目标里"数据表和…问题清单权限、可见性"这条线的端到端验收：
 * 表级读取门槛（TablePermission.read_role）一旦高于普通成员，
 * 该表的**列表项、详情、以及挂在表上的问题清单**都必须一起收口 ——
 * 避免"表看不到但问题清单还能翻到"这类跨入口泄露。
 *
 * 账号来自 seed：admin / admin1234（工作区 OWNER）、demo / demo1234（VIEWER，同工作区）。
 * 数据准备走 API，**结论断言走 UI（列表「受限」标记）与 API（403/列表缺失）**。
 */

import { expect, test } from "@playwright/test";

import { apiCall, sessionAs, sharedWorkspaceId } from "../helpers/api";

test.describe.configure({ timeout: 120_000 });

test.describe("数据表权限与问题清单（多用户）", () => {
    test("受限表：普通成员列表/详情/问题清单全部收口；管理员看到「受限」标记", async ({ browser }) => {
        const admin = await sessionAs(browser, "admin", "admin1234");
        const viewer = await sessionAs(browser, "demo", "demo1234");
        // 临时表登记：用例结束（finally）删除，避免留表污染同工作区的「恰好 N 张表」并行断言
        let createdTable: { wid: number; tid: number } | null = null;
        try {
            const wid = await sharedWorkspaceId(admin, viewer);
            const tableName = `E2E 受限表 ${Date.now()}`;

            // ── 1) admin 建表（含字段/一行数据）并在表上登记一个问题 ──
            const created = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables`, {
                name: tableName,
                description: "端到端权限验证",
            });
            expect(created.status, JSON.stringify(created.body)).toBe(201);
            const tid = (created.body as { id: number }).id;
            createdTable = { wid, tid };

            const field = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables/${tid}/fields`, {
                name: "名称",
                field_type: "text",
                order: 0,
            });
            expect([200, 201]).toContain(field.status);

            const row = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables/${tid}/records`, {
                values: { 名称: "示例行" },
            });
            expect([200, 201]).toContain(row.status);

            const issue = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables/${tid}/issues`, {
                title: "权限验证问题",
                description: "表受限后同事不应看到这条问题",
                category: "question",
            });
            expect(issue.status, JSON.stringify(issue.body)).toBe(201);

            // ── 2) 受限前：同事可见（列表含该表、详情 200、问题清单 200）──
            const before = await apiCall(viewer.api, viewer.token, "get", `/workspaces/${wid}/tables`);
            expect(before.status).toBe(200);
            const beforeRows = before.body as Array<{ id: number; is_restricted?: boolean }>;
            expect(beforeRows.some(t => t.id === tid), "默认门槛下同事应能看到该表").toBeTruthy();
            expect(beforeRows.find(t => t.id === tid)?.is_restricted).toBe(false);

            const detailBefore = await apiCall(viewer.api, viewer.token, "get", `/workspaces/${wid}/tables/${tid}`);
            expect(detailBefore.status).toBe(200);
            const issuesBefore = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${wid}/tables/${tid}/issues`,
            );
            expect(issuesBefore.status, "表可读时问题清单也应可读").toBe(200);

            // ── 3) admin 把读取门槛提到 owner ──
            const perm = await apiCall(
                admin.api,
                admin.token,
                "put",
                `/workspaces/${wid}/tables/${tid}/permissions`,
                { read_role: "owner" },
            );
            expect([200, 201], JSON.stringify(perm.body)).toContain(perm.status);

            // ── 4) 受限后：同事列表不含该表；详情与**问题清单**均 403 ──
            const after = await apiCall(viewer.api, viewer.token, "get", `/workspaces/${wid}/tables`);
            const afterRows = after.body as Array<{ id: number; name: string }>;
            expect(afterRows.some(t => t.id === tid), "受限表不应出现在普通成员的列表里").toBeFalsy();

            const detailAfter = await apiCall(viewer.api, viewer.token, "get", `/workspaces/${wid}/tables/${tid}`);
            expect(detailAfter.status, "受限表详情应拒绝访问").toBe(403);

            const issuesAfter = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${wid}/tables/${tid}/issues`,
            );
            expect(issuesAfter.status, "问题清单必须随表权限一起收口").toBe(403);

            // 直接按问题 id 访问同样不可达
            const issueId = (issue.body as { id: number }).id;
            const issueDirect = await apiCall(
                viewer.api,
                viewer.token,
                "get",
                `/workspaces/${wid}/tables/${tid}/issues/${issueId}`,
            );
            expect(issueDirect.status).toBe(403);

            // ── 5) 管理员：列表含该表且标记为受限；UI 显示「受限」标签 ──
            const adminList = await apiCall(admin.api, admin.token, "get", `/workspaces/${wid}/tables`);
            const adminRow = (adminList.body as Array<{ id: number; read_role?: string; is_restricted?: boolean }>).find(
                t => t.id === tid,
            );
            expect(adminRow, "管理员应能看到受限表").toBeTruthy();
            expect(adminRow?.read_role).toBe("owner");
            expect(adminRow?.is_restricted).toBe(true);

            await admin.page.goto(`/w/${wid}/tables`);
            await expect(admin.page.getByTestId(`table-restricted-${tid}`)).toBeVisible({ timeout: 20_000 });

            // ── 6) 恢复门槛后同事重新可见（收口可逆）──
            const restore = await apiCall(
                admin.api,
                admin.token,
                "put",
                `/workspaces/${wid}/tables/${tid}/permissions`,
                { read_role: "viewer" },
            );
            expect([200, 201]).toContain(restore.status);
            const restored = await apiCall(viewer.api, viewer.token, "get", `/workspaces/${wid}/tables`);
            expect((restored.body as Array<{ id: number }>).some(t => t.id === tid)).toBeTruthy();
        } finally {
            // 软删除临时表（trashed=true，列表接口随之隐藏），保证同轮其它用例看到的表清单干净
            if (createdTable) {
                await apiCall(
                    admin.api,
                    admin.token,
                    "delete",
                    `/workspaces/${createdTable.wid}/tables/${createdTable.tid}`,
                ).catch(() => {});
            }
            await admin.close();
            await viewer.close();
        }
    });
});

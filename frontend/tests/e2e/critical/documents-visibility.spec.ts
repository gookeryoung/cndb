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

import { expect, test, type APIRequestContext, type Browser, type Locator, type Page } from "@playwright/test";

const API = "/api/v1";

// 该用例含双账号多步 UI 断言，比普通用例重：单独放宽超时
test.describe.configure({ timeout: 90_000 });

/**
 * 打开文档页 → 等目录树响应 → 断言可见性标记.
 *
 * 用 `expect.toPass` 做**有界重试**：CI 上 8 个 worker 争抢 CPU 时，
 * 重载 + 树请求 + 渲染偶尔超过单次等待窗口；整体重试比放大单次超时更稳，
 * 也保留了"数据确实到了才断言"的语义（先等 tree 200 响应）。
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

    // 根节点直接渲染；若节点在折叠文件夹内则先展开
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
      // 1) 取两个账号共同可见的工作区（seed：admin 是 OWNER，perm_viewer 是 VIEWER）
      const adminWs = await call(admin.api, admin.token, "get", "/workspaces");
      const viewerWs = await call(viewer.api, viewer.token, "get", "/workspaces");
      expect(adminWs.status).toBe(200);
      expect(viewerWs.status).toBe(200);
      const viewerWsIds = new Set((viewerWs.body as Array<{ id: number }>).map(w => w.id));
      const wid = (adminWs.body as Array<{ id: number }>).find(w => viewerWsIds.has(w.id))?.id;
      expect(wid, "两个账号没有共同工作区").toBeTruthy();

      // 2) admin 建一份草稿
      const title = `E2E 草稿可见性 ${Date.now()}`;
      const created = await call(admin.api, admin.token, "post", `/workspaces/${wid}/documents`, {
        title,
        content: "# 草稿\n\n仅创建者可见的内容\n",
        status: "draft",
      });
      expect(created.status, JSON.stringify(created.body)).toBe(201);
      const doc = created.body as { id: number; visibility?: string; collaborator_count?: number };
      expect(doc.visibility).toBe("private");
      expect(doc.collaborator_count).toBe(0);

      // 3) 同事看不到：目录树里没有、直接访问详情 404
      const viewerTreeBefore = await call(viewer.api, viewer.token, "get", `/workspaces/${wid}/documents/tree`);
      expect(viewerTreeBefore.status).toBe(200);
      const beforeItems = (viewerTreeBefore.body as { items: Array<{ id: number }> }).items;
      expect(beforeItems.some(i => i.id === doc.id)).toBeFalsy();

      const denied = await call(viewer.api, viewer.token, "get", `/workspaces/${wid}/documents/${doc.id}`);
      expect(denied.status, "同事不应能读到他人草稿").toBe(404);

      // 4) 创建者 UI：树上显示「仅自己可见」标记
      await expectVisibilityMarker(admin.page, wid as number, doc.id, "仅自己可见");

      // 5) 授权给同事（viewer：只读）
      const grant = await call(
        admin.api,
        admin.token,
        "post",
        `/workspaces/${wid}/documents/${doc.id}/permissions`,
        { user_id: viewer.userId, role: "viewer" },
      );
      expect(grant.status, JSON.stringify(grant.body)).toBe(201);

      // 6) 同事现在可见（树 + 详情），且提示为 shared
      const viewerTreeAfter = await call(viewer.api, viewer.token, "get", `/workspaces/${wid}/documents/tree`);
      const afterItems = (viewerTreeAfter.body as { items: Array<{ id: number; visibility?: string }> }).items;
      const grantedItem = afterItems.find(i => i.id === doc.id);
      expect(grantedItem, "授权后同事应能在树里看到该草稿").toBeTruthy();
      expect(grantedItem?.visibility).toBe("shared");

      const detail = await call(viewer.api, viewer.token, "get", `/workspaces/${wid}/documents/${doc.id}`);
      expect(detail.status).toBe(200);

      // 7) 创建者 UI：标记变为「已共享给协作者」
      await expectVisibilityMarker(admin.page, wid as number, doc.id, "已共享给协作者", { reload: true });

      // 8) 撤销后立即收回
      const revoke = await call(
        admin.api,
        admin.token,
        "delete",
        `/workspaces/${wid}/documents/${doc.id}/permissions/${viewer.userId}`,
      );
      expect(revoke.status).toBe(204);

      const viewerTreeRevoked = await call(viewer.api, viewer.token, "get", `/workspaces/${wid}/documents/tree`);
      const revokedItems = (viewerTreeRevoked.body as { items: Array<{ id: number }> }).items;
      expect(revokedItems.some(i => i.id === doc.id)).toBeFalsy();

      const deniedAgain = await call(viewer.api, viewer.token, "get", `/workspaces/${wid}/documents/${doc.id}`);
      expect(deniedAgain.status).toBe(404);
    } finally {
      await admin.close();
      await viewer.close();
    }
  });
});

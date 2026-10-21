/**
 * Critical — 文档游客级只读分享（ADR 0017 P2）.
 *
 * 数据准备走 API（确定性好），结论走真实浏览器：
 * - 无登录态的新上下文直达 `/public/share/{token}`，正文可见且 URL 不被重定向到 `/login`；
 * - 公开页只走 `/api/v1/documents/share/*`，不请求任何工作区鉴权接口；
 * - 撤销分享 / 取消发布后同一链接立即显示「链接不存在或已失效」。
 *
 * 为什么必须 E2E：公开页的价值就在「免登录可访问且不触发登录跳转 / 令牌过期提示」，
 * jsdom 单测只能断言组件树，无法验证真实路由守卫、SPA 回退与浏览器导航。
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Browser } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];
/** seed：科研项目管理（admin 为 OWNER；与其它 e2e 用例的文档树互不干扰） */
const WORKSPACE_NAME = "科研项目管理";
const GONE_TEXT = "链接不存在或已失效";

let wid: number;
let token: string;
/** 本轮用例的文档标题都带时间戳，避免与历史数据同名 */
const stamp = Date.now();

test.describe.configure({ timeout: 90_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
	const token0 = await getAdminToken(request);
	token = token0;
	wid = await getWorkspaceId(request, WORKSPACE_NAME);
});

interface Doc {
	id: number;
	title: string;
}

interface Share {
	id: number;
	token: string;
}

async function createPublishedDoc(
	request: APIRequestContext,
	title: string,
): Promise<Doc> {
	const resp = await apiCall(
		request,
		token,
		"post",
		`/workspaces/${wid}/documents`,
		{
			title,
			content: `# ${title}\n\n游客可读正文 ${stamp}\n`,
			status: "published",
		},
	);
	expect(resp.status, JSON.stringify(resp.body)).toBe(201);
	return resp.body as Doc;
}

async function createShare(
	request: APIRequestContext,
	docId: number,
): Promise<Share> {
	const resp = await apiCall(
		request,
		token,
		"post",
		`/workspaces/${wid}/documents/${docId}/share`,
		{ permission: "viewer" },
	);
	expect(resp.status, JSON.stringify(resp.body)).toBe(201);
	const share = resp.body as Share & { document_id: number };
	expect(share.document_id).toBe(docId);
	return share;
}

async function revokeShare(
	request: APIRequestContext,
	docId: number,
	shareId: number,
): Promise<void> {
	const resp = await apiCall(
		request,
		token,
		"delete",
		`/workspaces/${wid}/documents/${docId}/share/${shareId}`,
	);
	expect(resp.status, JSON.stringify(resp.body)).toBe(200);
}

/** 清理本轮创建的文档（失败不改变用例结论） */
async function removeDoc(request: APIRequestContext, docId: number): Promise<void> {
	await apiCall(request, token, "delete", `/workspaces/${wid}/documents/${docId}`);
}

/**
 * 以**无登录态**的新浏览器上下文打开公开页，并收集其发出的全部 `/api/` 请求。
 *
 * 显式传 `baseURL`：`browser.newContext()` 不会继承 config 的 `use.baseURL`；
 * 同时显式传空 `storageState`，避免 test runner 把项目的登录态带进来 ——
 * 「游客没有 token」必须靠上下文真实成立，而不是靠清 localStorage 模拟。
 */
async function openPublicPage(browser: Browser, shareToken: string) {
	const baseURL = test.info().project.use.baseURL;
	const context = await browser.newContext({
		baseURL,
		storageState: { cookies: [], origins: [] },
	});
	const page = await context.newPage();
	const apiPaths: string[] = [];
	page.on("request", (req) => {
		const url = new URL(req.url());
		if (url.pathname.startsWith("/api/")) apiPaths.push(url.pathname);
	});
	await page.goto(`/public/share/${shareToken}`);
	return { context, page, apiPaths };
}

test.describe("文档游客级只读分享", () => {
	test("匿名直达公开页；撤销与取消发布后同一链接失效", async ({
		browser,
		request,
	}) => {
		test.skip(ANON.includes(test.info().project.name), "anon 项目不跑 critical");

		const doc = await createPublishedDoc(request, `游客分享 ${stamp}`);
		const share = await createShare(request, doc.id);
		const unpublishedDoc = await createPublishedDoc(
			request,
			`游客分享下架 ${stamp}`,
		);
		const unpublishedShare = await createShare(request, unpublishedDoc.id);

		try {
			// 1) 无登录态直达公开页：标题 / 正文可见，URL 仍为公开页，且只请求公开端点
			const view = await openPublicPage(browser, share.token);
			try {
				await expect(view.page.getByTestId("public-share-page")).toBeVisible({
					timeout: 20_000,
				});
				await expect(view.page.getByTestId("public-share-page")).toContainText(
					doc.title,
				);
				await expect(
					view.page.getByTestId("public-share-content"),
				).toContainText(`游客可读正文 ${stamp}`);
				await expect(view.page.getByText("只读分享")).toBeVisible();

				const visitorToken = await view.page.evaluate(() =>
					window.localStorage.getItem("cndb_access_token"),
				);
				expect(visitorToken, "游客上下文不应携带登录令牌").toBeNull();

				expect(
					view.page.url(),
					"公开页不得被重定向到登录页",
				).toContain(`/public/share/${share.token}`);
				expect(view.page.url()).not.toContain("/login");
				expect(
					view.apiPaths.filter(p => p.startsWith("/api/v1/workspaces/")),
					"公开页不得请求任何工作区鉴权接口",
				).toEqual([]);
				expect(
					view.apiPaths.some(p => p.startsWith("/api/v1/documents/share/")),
					"公开页应只走公开分享端点",
				).toBeTruthy();
			} finally {
				await view.context.close();
			}

			// 2) 撤销分享：同一 URL 立即失效（公开响应 no-store，不靠缓存兜底）
			await revokeShare(request, doc.id, share.id);
			const revoked = await openPublicPage(browser, share.token);
			try {
				await expect(revoked.page.getByTestId("public-share-gone")).toBeVisible({
					timeout: 20_000,
				});
				await expect(revoked.page.getByText(GONE_TEXT).first()).toBeVisible();
			} finally {
				await revoked.context.close();
			}

			// 3) 取消发布（归档）：既有分享链接同样失效
			const beforeUnpublish = await openPublicPage(
				browser,
				unpublishedShare.token,
			);
			try {
				await expect(
					beforeUnpublish.page.getByTestId("public-share-content"),
				).toContainText(`游客可读正文 ${stamp}`);
			} finally {
				await beforeUnpublish.context.close();
			}

			const archived = await apiCall(
				request,
				token,
				"patch",
				`/workspaces/${wid}/documents/${unpublishedDoc.id}`,
				{ status: "archived" },
			);
			expect(archived.status, JSON.stringify(archived.body)).toBe(200);

			const afterUnpublish = await openPublicPage(
				browser,
				unpublishedShare.token,
			);
			try {
				await expect(
					afterUnpublish.page.getByTestId("public-share-gone"),
				).toBeVisible({ timeout: 20_000 });
			} finally {
				await afterUnpublish.context.close();
			}
		} finally {
			await removeDoc(request, doc.id);
			await removeDoc(request, unpublishedDoc.id);
		}
	});
});

/**
 * 密码管理端到端：用户自助改密 + 管理员重置他人密码.
 *
 * 覆盖 ADR 0050：
 * - 自助改密成功后全部会话失效，前端强制回到登录页；旧密码不可登录、新密码可登录；
 * - 管理员在用户管理页重置他人密码（默认自动生成），生成密码仅展示一次且可用于登录。
 *
 * 数据准备走 API（确定性好）；关键结论走 UI + 登录接口断言。
 * 用例自建临时用户，结束禁用，避免污染 seed 数据。
 */

import { expect, test } from "@playwright/test";

import { apiCall, sessionAs, type Session } from "../helpers/api";

test.describe.configure({ timeout: 120_000 });

const ADMIN_REGISTER = "/accounts/auth/admin-register";
const LOGIN = "/accounts/auth/login";

function unique(prefix: string): string {
    return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
}

async function createUser(admin: Session, username: string, password: string): Promise<number> {
    const r = await apiCall(admin.api, admin.token, "post", ADMIN_REGISTER, {
        username,
        password,
        role: "user",
    });
    expect(r.status, JSON.stringify(r.body)).toBe(201);
    return (r.body as { id: number }).id;
}

/** 用登录接口验证密码是否可用（不走前端，避免干扰页面状态）. */
async function canLogin(admin: Session, username: string, password: string): Promise<number> {
    const res = await admin.api.post(`/api/v1${LOGIN}`, { data: { login: username, password } });
    return res.status();
}

test.describe("密码管理", () => {
    test("用户自助改密：成功后强制回登录页，旧密码失效", async ({ browser }) => {
        const admin = await sessionAs(browser, "admin", "admin1234");
        const username = unique("e2e_pw_self");
        const userId = await createUser(admin, username, "pw1234");
        const user = await sessionAs(browser, username, "pw1234");
        try {
            await user.page.goto("/");
            await user.page.getByTestId("user-menu-trigger").click();
            await user.page.getByText("个人设置", { exact: true }).click();

            // 修改密码表单在「用户资料」页签内（默认页签），直接可见
            await user.page.getByLabel("当前密码").fill("pw1234");
            await user.page.getByLabel("新密码", { exact: true }).fill("newpass123");
            await user.page.getByLabel("确认新密码").fill("newpass123");
            await user.page.getByRole("button", { name: /修改密码/ }).click();

            // 服务端吊销全部会话 + 本地登出 → 回到登录页
            await expect(user.page).toHaveURL(/\/login/, { timeout: 15_000 });
            expect(await canLogin(admin, username, "newpass123")).toBe(200);
            expect(await canLogin(admin, username, "pw1234")).toBe(401);
        } finally {
            await apiCall(admin.api, admin.token, "patch", `/accounts/users/${userId}`, { is_active: false });
            await user.close();
            await admin.close();
        }
    });

    test("管理员重置他人密码：自动生成密码仅展示一次且可登录", async ({ browser }) => {
        const admin = await sessionAs(browser, "admin", "admin1234");
        const username = unique("e2e_pw_reset");
        const userId = await createUser(admin, username, "pw1234");
        let generated = "";
        try {
            await admin.page.goto("/admin");
            const search = admin.page.getByPlaceholder("搜索用户名/邮箱/昵称");
            await search.fill(username);
            await search.press("Enter");

            const row = admin.page.locator("tr").filter({ hasText: username });
            await expect(row).toBeVisible({ timeout: 15_000 });
            await row.getByText("重置密码").click();

            await expect(admin.page.getByText("重置用户密码", { exact: true })).toBeVisible();
            await admin.page.getByRole("button", { name: "生成并重置" }).click();
            await admin.page.getByRole("button", { name: "确认重置" }).click();

            const result = admin.page.getByTestId("reset-password-result");
            await expect(result).toBeVisible({ timeout: 15_000 });
            generated = (await result.locator("code").innerText()).trim();
            expect(generated.length).toBe(12);

            expect(await canLogin(admin, username, generated)).toBe(200);
            expect(await canLogin(admin, username, "pw1234")).toBe(401);
        } finally {
            await apiCall(admin.api, admin.token, "patch", `/accounts/users/${userId}`, { is_active: false });
            await admin.close();
        }
    });
});

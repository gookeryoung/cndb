/**
 * dev 模式回归兜底：登录页的「antd Form ref 链路」与「登录会话竞态」必须真实可用.
 *
 * 背景（2026-10-20）：两类只在 dev 现形、常规 e2e（生产产物）抓不到的回归：
 *
 * 1. `rc-field-form` 摇树补丁把默认导出写成裸组件，丢了 `React.forwardRef` ——
 *    antd 的 Form 拿不到 ref，点登录抛
 *    `Cannot add property current, object is not extensible`。
 *    生产构建走 antd 内部深路径，e2e 全绿也发现不了。
 * 2. 登录接口的 401（密码错误）也会触发 `auth:expired`（500ms 防抖）——
 *    用户输错一次后马上改对提交，延迟的 notifyExpired 会把刚拿到的会话清掉，
 *    用户被弹回登录页（client.ts 已修：鉴权端点的 401 不再走过期流程）。
 *    自动化的连续操作恰好踩中这个窗口。
 *
 * 所以用例刻意串成「错误密码 → 立即改对 → 登录」，并对全程 pageerror 钉死零容忍。
 */
import { test, expect } from "@playwright/test";
import { startDevServer, stopDevServer } from "./start-dev-server";

const DEMO_USER = "demo";
const DEMO_PASS = "demo1234";

/** 与 ref 链路相关、必须一个都不能出现的报错特征 */
const REF_ERROR_MARKERS = [
  "not extensible",
  "cannot be given refs",
  "useImperativeHandle",
];

test.beforeAll(async () => {
  await startDevServer();
});

test.afterAll(async () => {
  await stopDevServer();
});

test("登录页：表单校验 / 提交可用，且无 ref 相关运行期错误", async ({ page }) => {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/login", { waitUntil: "domcontentloaded" });

  // 1) 表单渲染：antd Form + Form.Item 已挂载
  const username = page.getByPlaceholder("用户名或邮箱");
  const password = page.getByPlaceholder("密码");
  const submit = page.getByRole("button", { name: /登\s*录/ });
  await expect(username).toBeVisible();
  await expect(password).toBeVisible();

  // 2) 空提交 → 必填校验（走 Form 实例的 validateFields，ref 断了这里静默无提示）
  await submit.click();
  await expect(page.getByText("请输入用户名或邮箱")).toBeVisible();
  await expect(page.getByText("请输入密码")).toBeVisible();

  // 3) 错误密码 → 错误提示（这一步的 401 不得触发会话过期流程）
  await username.fill(DEMO_USER);
  await password.fill("wrong-password");
  await submit.click();
  await expect(page.getByText("用户名或密码错误")).toBeVisible();

  // 4) 立即改对提交（500ms 防抖窗口内的竞态）→ 必须真正进入 /w，不得被弹回
  await password.fill(DEMO_PASS);
  await submit.click();
  await expect(page).toHaveURL(/\/w$/, { timeout: 30_000 });
  await expect(page.getByTestId("workspace-list")).toBeVisible({ timeout: 30_000 });

  // 5) 全程不得出现 ref 相关报错，也不得有未捕获异常
  const allMessages = [...pageErrors, ...consoleErrors].join("\n");
  for (const marker of REF_ERROR_MARKERS) {
    expect(allMessages, `出现 ref 链路回归特征：${marker}`).not.toContain(marker);
  }
  expect(pageErrors, `存在未捕获异常：\n${pageErrors.join("\n")}`).toEqual([]);
});

test("注册页：同一套 Form 链路在 dev 下也可用", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  await page.goto("/register", { waitUntil: "domcontentloaded" });
  const submit = page.getByRole("button", { name: /注\s*册/ });
  await expect(submit).toBeVisible();

  // 空提交触发必填校验：证明 Form 实例（ref）在被使用
  await submit.click();
  await expect(page.locator(".ant-form-item-explain-error").first()).toBeVisible();

  const allMessages = pageErrors.join("\n");
  for (const marker of REF_ERROR_MARKERS) {
    expect(allMessages).not.toContain(marker);
  }
  expect(pageErrors).toEqual([]);
});

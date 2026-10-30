/**
 * dev 模式回归兜底：数据表「字段编辑」对话框里编辑关联字段，必须能读到已保存的
 * 目标表与引用字段（2026-10-20）.
 *
 * 背景：字段编辑表单用了 `<Form preserve={false}>`，其语义是「字段组件卸载即丢弃其值」。
 * React 开发态 StrictMode 会在挂载后模拟一次「卸载 → 重挂载」，把父层 effect 刚回填进
 * 表单的 config 连带清掉；而同步指纹（seededSigRef）已判定「回填完成」，不会再补一次 ——
 * 于是对话框停在「请先选择目标表 / 暂无引用字段」，目标表的字段列表接口也不会被请求，
 * 用户表现为「编辑关联字段时看不到引用字段数据」。
 *
 * 为什么放 dev 套件：生产构建里 StrictMode 是空实现，该现象不会出现 ——
 * 常规 e2e（生产产物）即便用例写得一模一样也抓不到，只有 vite dev 源码直出才会现形。
 *
 * 数据准备：建在 seed 的「科研项目管理」工作区（与 image-field-upload 同策略，
 * 避免污染 workspace 1 里「恰好 N 张表」这类并行断言），断言走 UI。
 */
import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import { startDevServer, stopDevServer } from "./start-dev-server";
import { apiCall, sessionAs, type ApiResult, type Session } from "../helpers/api";

/** seed：科研项目管理（admin 为 OWNER，无其它 e2e 用例依赖该工作区的表清单） */
const WORKSPACE_NAME = "科研项目管理";
/** 目标表里的业务字段：名称用于确认目标表身份，负责人用作被引用的投影字段 */
const TARGET_FIELDS = ["名称", "负责人"];
/** 被引用（投影）的目标字段名：修复前对话框的「引用字段」区看不到它 */
const REFERENCED_FIELD = "负责人";

let session: Session;
let wid: number;
let targetTid: number;
let linkTid: number;
let targetTableName: string;
/** link 字段名：字段列表行与对话框标题都用它定位 */
const LINK_FIELD_NAME = "关联目标";

/** 断言创建类接口成功并返回响应体（失败时把响应体带进断言信息，便于定位） */
function expectCreated(result: ApiResult, what: string): Record<string, unknown> {
  expect([200, 201], `${what} 失败：${JSON.stringify(result.body)}`).toContain(result.status);
  return result.body as Record<string, unknown>;
}

/** 建表并返回表 id */
async function createTable(name: string): Promise<number> {
  const created = await apiCall(session.api, session.token, "post", `/workspaces/${wid}/tables`, {
    name,
    description: "关联字段编辑回显回归",
  });
  return Number(expectCreated(created, `建表 ${name}`).id);
}

/** 建字段并返回字段 id */
async function createField(tid: number, field: Record<string, unknown>): Promise<number> {
  const created = await apiCall(
    session.api,
    session.token,
    "post",
    `/workspaces/${wid}/tables/${tid}/fields`,
    field,
  );
  return Number(expectCreated(created, `建字段 ${String(field.name)}`).id);
}

test.beforeAll(async ({ browser }) => {
  await startDevServer();
  // 独立登录（不复用 .auth/state.json）：dev 套件不起 e2e:setup，且旧 token 可能指向
  // 上一轮的隔离库
  session = await sessionAs(browser, "admin", "admin" + "1234");

  const workspaces = await apiCall(session.api, session.token, "get", "/workspaces");
  const list = workspaces.body as Array<{ id: number; name: string }>;
  const ws = list.find((w) => w.name === WORKSPACE_NAME) ?? list[0];
  if (!ws) throw new Error(`未找到工作区：${WORKSPACE_NAME}`);
  wid = ws.id;

  // 目标表：含「名称」「负责人」两个业务字段
  const stamp = Date.now();
  targetTableName = `E2E 关联目标表 ${stamp}`;
  targetTid = await createTable(targetTableName);
  const targetFieldIds: Record<string, number> = {};
  for (const [idx, name] of TARGET_FIELDS.entries()) {
    targetFieldIds[name] = await createField(targetTid, { name, field_type: "text", order: idx });
  }

  // 关联表：一个 link 字段指向目标表，并把「负责人」配成引用字段（投影 lookup）
  linkTid = await createTable(`E2E 关联来源表 ${stamp}`);
  await createField(linkTid, { name: "标题", field_type: "text", order: 0 });
  await createField(linkTid, {
    name: LINK_FIELD_NAME,
    field_type: "link",
    order: 1,
    config: {
      target_table_id: targetTid,
      multiple: false,
      reference_fields: [targetFieldIds[REFERENCED_FIELD]],
    },
  });
});

test.afterAll(async () => {
  if (session) {
    // 软删临时表：e2e 数据每轮重建，这里只保证同轮其它用例看到的表列表干净
    for (const tid of [linkTid, targetTid]) {
      if (tid) {
        await apiCall(session.api, session.token, "delete", `/workspaces/${wid}/tables/${tid}`);
      }
    }
    await session.close();
  }
  await stopDevServer();
});

/** 打开表的字段设置页并等字段列表渲染完成 */
async function openFieldSettings(page: Page) {
  await page.goto(`/w/${wid}/tables/${linkTid}/settings?tab=fields`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page.locator(".fm-row").first()).toBeVisible({ timeout: 30_000 });
}

/** 点开 link 字段行的编辑对话框（行内首个操作按钮即编辑，图标按钮无文本） */
async function openLinkEditDialog(page: Page) {
  const row = page.locator(".fm-row").filter({
    has: page.locator(".fm-row-name", { hasText: LINK_FIELD_NAME }),
  });
  await expect(row).toHaveCount(1);
  await row.locator(".fm-row-actions button").first().click();
  // antd 6：Modal 内容容器类改为 .ant-modal-container
  const dialog = page.locator(".ant-modal-container");
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  return dialog;
}

test.describe("字段编辑 · 关联字段配置回显", () => {
  // 用 session.page（登录态已注入 localStorage），而非 fixtures/auth 的 page：
  // dev 套件没有 chromium-authed 项目，也不跑 e2e:setup，框架默认 page 是干净上下文
  test("编辑关联字段：目标表与已配置的引用字段都可见（不被表单卸载清空）", async () => {
    const page = session.page;
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await openFieldSettings(page);
    const dialog = await openLinkEditDialog(page);

    // 1) 基础回填：字段名（同一套 config 回填链路，修复前整体为空）
    await expect(dialog.locator("#name")).toHaveValue(LINK_FIELD_NAME, { timeout: 15_000 });

    // 2) 关联目标表：必须是目标表名，而不是「选择要关联的表」占位
    const targetItem = dialog.locator(".ant-form-item").filter({ hasText: "关联目标表" });
    // antd 6：单选选中值是 .ant-select-content 内的裸文本节点（content-value div 仅 option 带样式时渲染）
    await expect(targetItem.locator(".ant-select-content")).toHaveText(targetTableName, {
      timeout: 15_000,
    });

    // 3) 引用字段区：列出已配置的引用字段名，且不再是空态
    //    （这一条依赖目标表字段列表接口被真正请求，修复前该请求根本不会发出）
    await expect(dialog.locator(".fm-ref-name")).toHaveText([REFERENCED_FIELD], { timeout: 15_000 });
    await expect(dialog.locator(".fm-ref-empty")).toHaveCount(0);

    expect(pageErrors, `存在未捕获异常：\n${pageErrors.join("\n")}`).toEqual([]);
  });
});

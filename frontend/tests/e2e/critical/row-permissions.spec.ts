/** Critical — 行级权限规则（ADR 0004）端到端.
 *
 * 目标里"行级权限"这条线的验收（ADR 0004 §10 e2e 清单）：
 * 1. 规则编辑器增删改：表设置「权限」Tab 的「行级权限」区走完整 UI 流程
 *    （选主体 → 选动作 → 配条件 → 预览命中行数 → 创建 → 编辑 → 删除）；
 * 2. "可看不可改"的行在 Grid 里提交后转为修改申请：编辑者命中 view 规则的行
 *    能看见、可点编辑，保存后提示「已提交修改申请，处理后生效」，且不落库。
 *
 * 数据准备走 API（临时表 + 默认档 row_filters + 三行数据），**结论断言同时覆盖
 * API（可见行集合 / 404 不泄露 / 管理员豁免）与 UI（规则表、Grid 提示）**。
 *
 * 账号来自 seed：admin（工作区 OWNER）、sec_admin（EDITOR，可直编）、demo（VIEWER）。
 * 临时表在 finally 里软删除，避免污染同工作区其它用例的表清单断言。
 */

import { expect, test } from "../fixtures/auth";
import { apiCall, sessionAs, sharedWorkspaceId } from "../helpers/api";
import type { Session } from "../helpers/api";

test.describe.configure({ timeout: 120_000 });

const ANON = ["setup", "chromium-anon"];

/** 默认档：未命中任何规则的成员只看销售部 */
const DEFAULT_DEPT = "销售部";
/** view 规则额外开放给「编辑者」档的部门 */
const RULE_DEPT = "技术部";
/** 两条范围都不命中的部门（对普通成员不可见） */
const HIDDEN_DEPT = "市场部";

interface RowRecord {
  id: number;
  姓名?: string;
  部门?: string;
  [key: string]: unknown;
}

/** 建临时表并返回 id（字段：姓名 / 部门；行：三部门各一人） */
async function setupTempTable(
  admin: Session,
  wid: number,
  name: string,
): Promise<{ tid: number; salesRowId: number; techRowId: number; hiddenRowId: number }> {
  const created = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables`, {
    name,
    description: "行级权限 Playwright 专项用例",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  const tid = (created.body as { id: number }).id;

  for (const [order, fieldName] of ["姓名", "部门"].entries()) {
    const field = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables/${tid}/fields`, {
      name: fieldName,
      field_type: "text",
      order,
    });
    expect([200, 201], JSON.stringify(field.body)).toContain(field.status);
  }

  const rowIds: number[] = [];
  for (const [姓名, 部门] of [
    ["张三", DEFAULT_DEPT],
    ["李四", RULE_DEPT],
    ["王五", HIDDEN_DEPT],
  ] as const) {
    const row = await apiCall(admin.api, admin.token, "post", `/workspaces/${wid}/tables/${tid}/records`, {
      values: { 姓名, 部门 },
    });
    expect([200, 201], JSON.stringify(row.body)).toContain(row.status);
    rowIds.push((row.body as { id: number }).id);
  }

  // 默认档：所有非管理员成员只看「销售部」一行（row_filters 存量能力，I3）
  const perm = await apiCall(admin.api, admin.token, "put", `/workspaces/${wid}/tables/${tid}/permissions`, {
    row_filters: [{ field_name: "部门", op: "=", value: DEFAULT_DEPT }],
    row_filter_type: "AND",
  });
  expect([200, 201], JSON.stringify(perm.body)).toContain(perm.status);

  return { tid, salesRowId: rowIds[0], techRowId: rowIds[1], hiddenRowId: rowIds[2] };
}

/** 记录列表（服务端已按调用者的行读范围裁剪） */
async function listRows(session: Session, wid: number, tid: number): Promise<RowRecord[]> {
  const res = await apiCall(session.api, session.token, "post", `/workspaces/${wid}/tables/${tid}/records/list`, {
    limit: 50,
    offset: 0,
  });
  expect(res.status, JSON.stringify(res.body)).toBe(200);
  return (res.body as { items: RowRecord[] }).items;
}

/** 名称集合（用 Set 比较，规避中文排序差异） */
function namesOf(rows: RowRecord[]): Set<string> {
  return new Set(rows.map((r) => String(r.姓名)));
}

/** 取 antd Select 的可见下拉项（下拉挂在 body 上，需单独定位） */
async function pickOption(page: Session["page"], optionText: string) {
  await page.locator(".ant-select-dropdown:visible .ant-select-item-option", { hasText: optionText }).first().click();
}

test.describe("行级权限规则（ADR 0004）", () => {
  test("规则增删改 + 编辑者『可看不可改』提交转修改申请", async ({ browser }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

    const admin = await sessionAs(browser, "admin", "admin1234");
    const editor = await sessionAs(browser, "sec_admin", "sec1234");
    const viewer = await sessionAs(browser, "demo", "demo1234");
    let temp: { wid: number; tid: number } | null = null;

    try {
      const wid = await sharedWorkspaceId(admin, editor);
      const tableName = `E2E 行权限表 ${Date.now()}`;
      const { tid, salesRowId, techRowId, hiddenRowId } = await setupTempTable(admin, wid, tableName);
      temp = { wid, tid };

      const page = admin.page;

      // ── 1) UI：打开权限 Tab 的「行级权限」区 ──
      await page.goto(`/w/${wid}/tables/${tid}/settings?tab=permissions`);
      await expect(page.getByText(/^行级权限（0）$/)).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("暂无行级权限规则")).toBeVisible();

      // ── 2) UI 新增规则：编辑者档 + 可查看 + 部门包含「技术」 ──
      await page.getByRole("button", { name: "添加规则" }).click();
      const createModal = page.getByRole("dialog");
      await expect(createModal.getByText("新建行级权限规则")).toBeVisible();

      // 授权主体：表级成员档「编辑者」（按有效档位匹配，D5）
      await createModal.locator(".ant-select").first().click();
      await pickOption(page, "编辑者（成员级档）");
      await expect(createModal.getByRole("radio", { name: /可查看/ })).toBeChecked();

      // 命中条件：部门 包含 技术
      await createModal.getByRole("button", { name: "添加筛选条件" }).click();
      const rule = createModal.locator(".vcvd-rule").first();
      await rule.locator(".ant-select").first().click();
      await pickOption(page, "部门");
      await rule.locator("input.ant-input").fill("技术");

      // 预览：admin 为表 owner（D3 豁免），全表范围内命中技术部 1 行
      await createModal.getByRole("button", { name: /预览命中行数/ }).click();
      await expect(page.getByText(/预计命中\s*1\s*行/)).toBeVisible({ timeout: 15_000 });

      // antd 会在两个汉字的按钮文案间插入空格（「保 存」），用正则容忍空白
      await createModal.getByRole("button", { name: /保\s*存/ }).click();
      await expect(page.getByText("已创建行级权限规则")).toBeVisible({ timeout: 15_000 });

      const ruleCard = page.locator(".ant-card").filter({ hasText: "行级权限（" });
      const ruleRow = ruleCard.locator(".ant-table-row").filter({ hasText: "编辑者" });
      await expect(ruleRow).toBeVisible();
      await expect(ruleRow).toContainText("可查看");
      await expect(ruleRow).toContainText("AND");
      await expect(ruleRow).toContainText("部门");

      // ── 3) UI 编辑规则：切到 OR 组合（主体 / 动作创建后不可改）──
      await ruleRow.getByRole("button", { name: /编\s*辑/ }).click();
      const editModal = page.getByRole("dialog");
      await expect(editModal.getByText("编辑行级权限规则")).toBeVisible();
      await expect(editModal.locator(".ant-select").first()).toHaveClass(/ant-select-disabled/);
      await editModal.getByRole("button", { name: "任一满足（OR）" }).click();
      await editModal.getByRole("button", { name: /保\s*存/ }).click();
      await expect(page.getByText("已更新行级权限规则")).toBeVisible({ timeout: 15_000 });
      await expect(ruleRow).toContainText("OR");

      // ── 4) 生效面：编辑者能看到默认档 + view 规则行，看不到市场部 ──
      const editorRows = await listRows(editor, wid, tid);
      expect(namesOf(editorRows)).toEqual(new Set(["张三", "李四"]));

      // 查看者（read 档）不命中 member_role:write 规则，只见默认档一行
      const viewerRows = await listRows(viewer, wid, tid);
      expect(namesOf(viewerRows)).toEqual(new Set(["张三"]));

      // 管理员豁免（D3）：看到全部三行
      const adminRows = await listRows(admin, wid, tid);
      expect(namesOf(adminRows)).toEqual(new Set(["张三", "李四", "王五"]));

      // 越界行按"不存在"处理（I6）：查看者单行写技术部行 → 404，不泄露存在性
      const outOfScope = await apiCall(
        viewer.api,
        viewer.token,
        "patch",
        `/workspaces/${wid}/tables/${tid}/records/${techRowId}`,
        { values: { 姓名: "不应落库" } },
      );
      expect(outOfScope.status, "读范围外的行必须按不存在处理").toBe(404);

      // ── 5) UI：编辑者 Grid 里编辑 view 规则命中的行 → 202 修改申请提示 ──
      await editor.page.goto(`/w/${wid}/tables/${tid}`);
      await expect(editor.page.getByText("张三")).toBeVisible({ timeout: 30_000 });
      await expect(editor.page.getByText("李四")).toBeVisible();
      await expect(editor.page.getByText("王五")).toHaveCount(0);

      const techRow = editor.page.locator(`[data-row-key="${techRowId}"]`);
      await expect(techRow.getByTestId("row-edit-btn")).toBeVisible();
      await techRow.getByTestId("row-edit-btn").click();
      await expect(editor.page.getByTestId("row-save-btn")).toBeVisible();
      // 姓名是第一列（字段 order 0），整行编辑态下第一个输入框即姓名
      await techRow.locator("input.ant-input").first().fill("李四-改");
      await editor.page.getByTestId("row-save-btn").click();
      await expect(editor.page.getByText("已提交修改申请，处理后生效")).toBeVisible({ timeout: 15_000 });

      // 202 不落库：技术部行仍为「李四」
      const afterEdit = await listRows(editor, wid, tid);
      expect(afterEdit.find((r) => r.id === techRowId)?.姓名).toBe("李四");

      // ── 6) UI 删除规则：编辑者随之失去技术部行的读侧开放 ──
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await ruleRow.getByRole("button", { name: /删\s*除/ }).click();
      await page.locator(".ant-popover:visible").getByRole("button", { name: /删\s*除/ }).click();
      await expect(page.getByText("已删除行级权限规则")).toBeVisible({ timeout: 15_000 });
      await expect(ruleCard.getByText("暂无行级权限规则")).toBeVisible();

      // 收紧后编辑者只剩默认档（记录缓存由规则变更事件清空，轮询兼容 5s TTL 兜底）
      await expect
        .poll(async () => namesOf(await listRows(editor, wid, tid)), { timeout: 15_000 })
        .toEqual(new Set(["张三"]));
      expect(namesOf(await listRows(viewer, wid, tid))).toEqual(new Set(["张三"]));

      // 管理员仍全量可见（豁免不受规则增删影响）
      expect(namesOf(await listRows(admin, wid, tid))).toEqual(new Set(["张三", "李四", "王五"]));

      // 默认档行对 owner 直编成功（对照：写范围外为 202、读范围外为 404）
      const directEdit = await apiCall(
        admin.api,
        admin.token,
        "patch",
        `/workspaces/${wid}/tables/${tid}/records/${hiddenRowId}`,
        { values: { 姓名: "王五-owner" } },
      );
      expect(directEdit.status, JSON.stringify(directEdit.body)).toBe(200);
      expect((await listRows(admin, wid, tid)).find((r) => r.id === hiddenRowId)?.姓名).toBe("王五-owner");
    } finally {
      if (temp) {
        await apiCall(admin.api, admin.token, "delete", `/workspaces/${temp.wid}/tables/${temp.tid}`).catch(() => {});
      }
      await admin.close();
      await editor.close();
      await viewer.close();
    }
  });
});

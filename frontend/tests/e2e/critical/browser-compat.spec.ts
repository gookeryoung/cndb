/** Critical — 兼容兜底不得改变现代 Chromium 的原生路径（ADR 0026 C8 / I3）.
 *
 * 旧内核专属机制（flex-gap shim / --cn-mix-* 兜底变量）只在特性探测失败时启用；
 * 本用例在 Playwright 自带 Chromium（现代内核）上反向断言它们没有介入，
 * 同时关键布局仍由原生 color-mix / gap 提供。
 */
import { test, expect } from "../fixtures/auth";
import { getTableId, getWorkspaceId } from "../helpers/api";

test("现代 Chromium 不启用旧内核兜底，且颜色 / 间距保持原生", async ({
  page,
  request,
}) => {
  const wid = await getWorkspaceId(request, "科研项目管理");
  const tid = await getTableId(request, wid, "科研项目");
  await page.goto(`/w/${wid}/tables/${tid}`);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({
    timeout: 10_000,
  });

  const info = await page.evaluate(() => {
    const space = document.querySelector(".ant-space");
    const header = document.querySelector(".cn-app-header");
    return {
      noFlexGap: document.documentElement.classList.contains("cn-no-flex-gap"),
      mixVar: getComputedStyle(document.documentElement)
        .getPropertyValue("--cn-mix-brand-color-10-transparent")
        .trim(),
      spaceGap: space ? getComputedStyle(space).columnGap : "",
      headerBackground: header ? getComputedStyle(header).backgroundImage : "",
    };
  });

  // flex-gap shim 不下载、不生效
  expect(info.noFlexGap).toBe(false);
  // --cn-mix-* 仅由旧内核兜底写入；现代浏览器应为空，继续走原生 color-mix
  expect(info.mixVar).toBe("");
  // 顶栏的品牌色微渐变（原生 color-mix 派生）正常生效
  expect(info.headerBackground).toContain("gradient");
  // antd Space 的间距来自原生 gap，而非兜底补出的 margin
  if (info.spaceGap) expect(info.spaceGap).not.toBe("0px");
});

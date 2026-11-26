/**
 * Critical — 文档知识图谱探索器（需求 0168 / 0182）。
 *
 * 覆盖：
 * 1) 全图渲染：节点数 / 图例与 `links/graph` 返回一致，画布真的画出了节点与标签；
 * 2) 局部图深链 `?focus=&depth=`：节点集按无向邻接收敛，中心标签可清回全图；
 * 3) 筛选栏「只看断链」：断链节点与指向它的源节点一起留下，页脚「显示 X / 共 Y」同步；
 * 4) 单击节点只选中（Inspector 出现）、双击才进入文档。
 *
 * 为什么必须 E2E：图谱页的核心行为都发生在 echarts SVG 内部——
 * 节点坐标由力导向布局实时算出、点击命中依赖真实 geometry、
 * 标签淡化随视图倍率变化。jsdom 单测把 echarts 整体 mock 掉，
 * 只能验 option 结构，验不到「真的点上去有没有反应」。
 *
 * 命中元素的选取：echarts SVG renderer 里节点是「只有 transform 没有 d 的圆形 path」，
 * 边是 fill="none" 的 path，**箭头也是带 fill 的 path**，所以按 `path[fill]` 取第一个
 * 会拿到箭头（点在箭头上没有 item 事件）。这里统一按节点标签 `<text>` 命中——
 * 标签与节点同属一个 item，点标签等价于点节点，且能按标题精确定位。
 *
 * 数据准备走 API（确定性好），断言走真实浏览器。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

/** seed：科研项目管理（admin 为 OWNER） */
const WORKSPACE_NAME = "科研项目管理";
/** 本轮标题都带时间戳：seed 文档正文里不可能出现，保证新建的两个节点不与既有图相连 */
const stamp = Date.now();
const targetTitle = `图谱目标 ${stamp}`;
const sourceTitle = `图谱源 ${stamp}`;

let wid: number;
let token: string;
/** 源文档：引用 target，同时留一处断链 */
let sourceId: number;

// 串行：图谱是工作区级视图，beforeAll 只建一轮数据；并行 worker 各建一套会互相改总数。
test.describe.configure({ timeout: 150_000, mode: "serial" });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
    token = await getAdminToken(request);
    wid = await getWorkspaceId(request, WORKSPACE_NAME);

    const target = await apiCall(request, token, "post", `/workspaces/${wid}/documents`, {
        title: targetTitle,
        content: `# ${targetTitle}\n\n图谱 e2e 目标文档，无出链。\n`,
        status: "published",
    });
    expect(target.status, JSON.stringify(target.body)).toBe(201);

    const source = await apiCall(request, token, "post", `/workspaces/${wid}/documents`, {
        title: sourceTitle,
        // 一条能解析的双链 + 一条指向不存在标题的断链
        content: `# ${sourceTitle}\n\n引用 [[${targetTitle}]]，另有一处 [[不存在的目标 ${stamp}]]。\n`,
        status: "published",
    });
    expect(source.status, JSON.stringify(source.body)).toBe(201);
    sourceId = (source.body as { id: number }).id;
});

type GraphPayload = {
    nodes: Array<{ id: number; title: string; broken: boolean }>;
    edges: Array<{ source: number; target: number; broken: boolean }>;
    truncated: boolean;
    total: number;
};

/** 页脚「显示 X / 共 Y 个节点 · 关系 Z」里的 X / Y */
async function footerCounts(page: Page): Promise<{ shown: number; total: number }> {
    const text = (await page.getByTestId("graph-footer-stats").innerText()) ?? "";
    const m = text.match(/显示\s*(\d+)\s*\/\s*共\s*(\d+)/);
    if (!m) throw new Error(`页脚统计格式不符：${text}`);
    return { shown: Number(m[1]), total: Number(m[2]) };
}

/**
 * 打开图谱页并等到 `links/graph` 落地（不靠固定 sleep）。
 *
 * 返回页面自己那次响应的真值来断言：图谱是工作区级视图，若另发一次接口请求，
 * 两次之间工作区里新增的文档会让「接口说 9 个 / 页面显示 11 个」错位。
 */
async function openGraph(page: Page, query = ""): Promise<GraphPayload> {
    const graphResponse = page.waitForResponse(
        (r) => r.url().includes(`/workspaces/${wid}/documents/links/graph`) && r.status() === 200,
        { timeout: 30_000 },
    );
    await page.goto(`/w/${wid}/documents/graph${query}`);
    const payload = (await (await graphResponse).json()) as GraphPayload;
    await expect(page.getByTestId("graph-footer-stats")).toBeVisible({ timeout: 20_000 });
    return payload;
}

/** 画布里的节点标签（每个已渲染节点一条，力导向布局落位后才有） */
function graphLabels(page: Page) {
    return page.locator('[data-testid="document-graph-canvas"] svg text');
}

test("全图渲染：统计与接口一致，图例按格式列出", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    const graph = await openGraph(page);
    expect(graph.truncated, "节点数超过上限时本用例的「共 Y」口径不成立").toBeFalsy();

    const { shown, total } = await footerCounts(page);
    expect(total).toBe(graph.nodes.length);
    expect(shown).toBe(graph.nodes.length);

    // 图例：新文档都是 markdown，至少这一项必须在且未被隐藏
    await expect(page.getByTestId("graph-legend")).toBeVisible();
    await expect(page.getByTestId("graph-legend-markdown")).toHaveAttribute("aria-pressed", "true");

    // 画布真的画出了标签（力导向布局需要一帧以上），且本轮两个文档都在
    await expect(graphLabels(page).filter({ hasText: sourceTitle })).toBeVisible({ timeout: 20_000 });
    await expect(graphLabels(page).filter({ hasText: targetTitle })).toBeVisible();
});

test("局部图深链：?focus=&depth= 收敛节点集，中心标签可清回全图", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    // 先看全图节点数，作为「局部图必须更少」的对照
    const fullGraph = await openGraph(page);
    expect(fullGraph.truncated, "节点数超过上限时局部图口径不成立").toBeFalsy();
    const full = await footerCounts(page);
    expect(full.shown).toBe(fullGraph.nodes.length);

    // source 只与 target 相连（断链那条指向的节点不是图内节点），所以应当收敛
    const focusedGraph = await openGraph(page, `?focus=${sourceId}&depth=1`);
    const focused = await footerCounts(page);
    expect(focused.total).toBe(focusedGraph.nodes.length);
    expect(focused.shown).toBeLessThan(full.shown);
    expect(focused.shown).toBeGreaterThanOrEqual(2); // 至少含中心自身与被引用方

    // 中心标签写明中心是谁、几跳
    const focusTag = page.getByTestId("graph-focus-tag");
    await expect(focusTag).toBeVisible();
    await expect(focusTag).toContainText("1 跳");

    // 关掉中心标签的 × 后回到全图。
    //
    // 这里刻意不断言「节点数回到最初那个总数」：图谱数据由 React Query 按 workspaceId 缓存，
    // 清掉 focus 只是前端重新过滤、不会再发请求（拿不到新总数），
    // 而且本 spec 与其他 spec 并行跑在同一工作区，中间可能有别的用例新建文档。
    // 因此只断言与漂移无关的三件事：中心标签消失、URL 清空、显示数明显回升。
    await focusTag.locator(".ant-tag-close-icon").click();
    await expect(page.getByTestId("graph-focus-tag")).toHaveCount(0);
    await expect(page).not.toHaveURL(/focus=/);
    await expect
        .poll(async () => (await footerCounts(page)).shown, { timeout: 15_000 })
        .toBeGreaterThan(focused.shown);
});

test("筛选栏「只看断链」：保留断链与源节点，页脚显示数同步下降", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    const fullGraph = await openGraph(page);
    expect(fullGraph.truncated, "节点数超过上限时筛选口径不成立").toBeFalsy();
    // 前置：本轮的 source 确实产生了断链（否则用例没有意义）
    expect(
        fullGraph.nodes.find((n) => n.broken && n.title.includes(String(stamp))),
        "未生成预期的断链节点，接口解析口径可能变了",
    ).toBeTruthy();
    const full = await footerCounts(page);

    await page.getByTestId("graph-filter-broken").click();
    await expect
        .poll(async () => (await footerCounts(page)).shown, { timeout: 15_000 })
        .toBeLessThan(full.shown);

    // 断链节点 + 指向它的源文档都要留下（只留断链会画成一堆孤点）
    const filtered = await footerCounts(page);
    expect(filtered.shown).toBeGreaterThanOrEqual(2);
    await expect(graphLabels(page).filter({ hasText: sourceTitle })).toBeVisible({ timeout: 15_000 });

    // 取消筛选回到全量
    await page.getByTestId("graph-filter-broken").click();
    await expect
        .poll(async () => (await footerCounts(page)).shown, { timeout: 15_000 })
        .toBe(full.shown);
});

test("单击节点只选中并打开 Inspector，双击才进入文档", async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    // 用局部图把节点压到 2 个，减少力导向布局里点错目标的概率
    const graph = await openGraph(page, `?focus=${sourceId}&depth=1`);
    expect(graph.truncated, "节点数超过上限时点选定位不可靠").toBeFalsy();


    const node = graphLabels(page).filter({ hasText: sourceTitle });
    await expect(node).toBeVisible({ timeout: 20_000 });

    await node.click();
    // 单击：Inspector 出现并显示的是被点的文档，URL 不变（原「单击即跳转」已下线）
    await expect(page.getByTestId("graph-inspector-detail")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("graph-inspector-title")).toContainText(sourceTitle);
    await expect(page).toHaveURL(/\/documents\/graph/);

    await node.dblclick();
    await expect(page).toHaveURL(new RegExp(`/w/${wid}/documents/\\d+`), { timeout: 20_000 });
});

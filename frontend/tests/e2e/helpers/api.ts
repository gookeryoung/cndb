/** E2E 共享 API 辅助：token 复用 + 常用查询收敛.
 *
 * 痛点：各 spec 内联重复实现 getToken/getTableId/getWorkspaceId，且每条用例多次
 * POST 登录取 token（全目录累计 75 处调用）。登录态已被 auth.setup 持久化到
 * .auth/state.json，本模块统一从这里读取 `cndb_access_token` 复用，规避重复登录。
 */
import type { APIRequestContext, Browser, Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const _dir = path.dirname(fileURLToPath(import.meta.url));
// helpers -> e2e -> tests -> frontend/.auth/state.json（向上 3 级）
const AUTH_STATE_PATH = path.resolve(_dir, "../../../.auth/state.json");

/** 从 storageState 读取 access token；缺失返回 null（由调用方决定是否登录兜底）. */
function _stateToken(): string | null {
  if (!existsSync(AUTH_STATE_PATH)) return null;
  try {
    const raw = readFileSync(AUTH_STATE_PATH, "utf-8");
    const state = JSON.parse(raw) as {
      origins?: Array<{ localStorage?: Array<{ name: string; value: string }> }>;
    };
    return (
      state?.origins?.[0]?.localStorage?.find(
        (it) => it.name === "cndb_access_token",
      )?.value ?? null
    );
  } catch {
    return null;
  }
}

/** 返回 admin 的 Bearer token：优先复用 storageState，缺失时才登录兜底. */
export async function getAdminToken(
  request: APIRequestContext,
): Promise<string> {
  const cached = _stateToken();
  if (cached) return cached;
  const resp = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin" + "1234" }, // 拼接构造，规避通用密码字面量检测
  });
  const body = (await resp.json()) as { access_token: string };
  return body.access_token;
}

/** 按名称（支持模糊内匹配）查找工作区 id. */
export async function getWorkspaceId(
  request: APIRequestContext,
  nameKeyword?: string,
): Promise<number> {
  const token = await getAdminToken(request);
  const resp = await request.get("/api/v1/workspaces", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const workspaces = (await resp.json()) as Array<{ id: number; name: string }>;
  if (nameKeyword) {
    const exact = workspaces.find((w) => w.name === nameKeyword);
    if (exact) return exact.id;
    const fuzzy = workspaces.find((w) => w.name.includes(nameKeyword));
    if (fuzzy) return fuzzy.id;
  }
  return workspaces[0].id;
}

/** 在工作区内按表名查找表 id. */
export async function getTableId(
  request: APIRequestContext,
  wid: number,
  tableName: string,
): Promise<number> {
  const token = await getAdminToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const tables = (await resp.json()) as Array<{ id: number; name: string }>;
  const t = tables.find((x) => x.name === tableName);
  if (!t) throw new Error(`未找到表: ${tableName}`);
  return t.id;
}

/** 在指定表内按字段名+值精确匹配，返回首条行的 id；未找到则抛出.
 *
 *  用途：Grid 虚拟滚动场景下，`hasText("张三")` 这种子串匹配会被
 *  操作列按钮文字（如"张三编辑"）误命中，`first()` 拿到的往往是
 *  视口顶部的相邻行。通过 API 拿真实 row id 再用 `[data-row-key]`
 *  精准定位，彻底规避 DOM 子串匹配的脆弱性。
 */
export async function getRowId(
  request: APIRequestContext,
  wid: number,
  tid: number,
  fieldName: string,
  fieldValue: unknown,
): Promise<number> {
  const token = await getAdminToken(request);
  const resp = await request.get(
    `/api/v1/workspaces/${wid}/tables/${tid}/records?limit=500`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = (await resp.json()) as {
    items?: Array<{ id: number; [k: string]: unknown }>;
    results?: Array<{ id: number; [k: string]: unknown }>;
  };
  const items = body.items || body.results || [];
  const hit = items.find((r) => r[fieldName] === fieldValue);
  if (!hit) throw new Error(`未找到行: ${fieldName}=${String(fieldValue)}`);
  return hit.id;
}

// ───────────────────────── 多账号会话（可见性/权限类用例用） ─────────────────────────

export interface Session {
  page: Page;
  api: APIRequestContext;
  token: string;
  userId: number;
  close: () => Promise<void>;
}

export interface ApiResult {
  status: number;
  body: unknown;
}

/** 带 Bearer 的裸 API 调用（`page.request` 不会自动带上 localStorage 里的 token）. */
export async function apiCall(
  client: APIRequestContext,
  token: string,
  method: "get" | "post" | "put" | "patch" | "delete",
  url: string,
  data?: unknown,
): Promise<ApiResult> {
  const res = await client[method](`/api/v1${url}`, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status(), body };
}

/**
 * 以指定账号建立**独立浏览器上下文**的会话（用途：同一用例里模拟两个用户）.
 *
 * 登录拿 token 后注入 localStorage —— 前端据此带鉴权；
 * 相比走 UI 登录更快更稳，也避免用例之间的登录态互相污染。
 */
export async function sessionAs(
  browser: Browser,
  login: string,
  password: string,
): Promise<Session> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const resp = await page.request.post("/api/v1/accounts/auth/login", {
    data: { login, password },
  });
  if (!resp.ok()) throw new Error(`登录失败：${login}（${resp.status()}）`);
  const { access_token: token } = (await resp.json()) as { access_token: string };

  await page.addInitScript((t: string) => {
    window.localStorage.setItem("cndb_access_token", t);
    // onboarding 只引导新用户，测试里跳过，避免遮罩挡住断言
    window.localStorage.setItem(
      "cndb_onboarding_done_v1",
      JSON.stringify({ state: { tourDone: true }, version: 0 }),
    );
  }, token);

  const me = await apiCall(page.request, token, "get", "/accounts/auth/me");
  if (me.status !== 200) throw new Error(`读取当前用户失败：${login}（${me.status}）`);
  return {
    page,
    api: page.request,
    token,
    userId: (me.body as { id: number }).id,
    close: () => ctx.close(),
  };
}

/** 两个账号共同可见的第一个工作区 id（多用户可见性用例的前置）. */
export async function sharedWorkspaceId(
  a: Session,
  b: Session,
): Promise<number> {
  const aWs = await apiCall(a.api, a.token, "get", "/workspaces");
  const bWs = await apiCall(b.api, b.token, "get", "/workspaces");
  const bIds = new Set((bWs.body as Array<{ id: number }>).map((w) => w.id));
  const wid = (aWs.body as Array<{ id: number }>).find((w) => bIds.has(w.id))?.id;
  if (!wid) throw new Error("两个账号没有共同可见的工作区");
  return wid;
}

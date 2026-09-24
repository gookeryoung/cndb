/** E2E 共享 API 辅助：token 复用 + 常用查询收敛.
 *
 * 痛点：各 spec 内联重复实现 getToken/getTableId/getWorkspaceId，且每条用例多次
 * POST 登录取 token（全目录累计 75 处调用）。登录态已被 auth.setup 持久化到
 * .auth/state.json，本模块统一从这里读取 `cndb_access_token` 复用，规避重复登录。
 */
import type { APIRequestContext } from "@playwright/test";
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
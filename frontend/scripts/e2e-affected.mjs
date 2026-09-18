#!/usr/bin/env node
/* global console, process */
/**
 * 只跑 affected E2E —— 按 git 变更筛选受影响的 spec，仅运行这些用例，缩短 PR/本地回归时间.
 *
 * 用法：
 *   pnpm e2e:affected                  # 对比上次提交 HEAD~1
 *   E2E_BASE_REF=origin/main pnpm e2e:affected   # 对比远程分支（PR 场景推荐）
 *
 * 行为：
 *   - 收集 base..HEAD 间变更的 `tests/e2e` 下 `*.spec.ts` 文件；
 *   - 有变更：只跑这些 spec（含未删除的）；无变更：回退跑 smoke 冒烟；
 *   - 剩余参数原样透传给 playwright（如 --headed / --grep）。
 *
 * 说明：新增且未 git add 的 spec 不会被 diff 捕获，需显式提交或改用 base 覆盖。
 */
import { execSync, spawnSync } from "node:child_process";

const BASE_REF = process.env.E2E_BASE_REF || "HEAD~1";

let changed = [];
try {
  changed = execSync(
    `git diff --relative --name-only ${BASE_REF} -- tests/e2e`,
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  )
    .split("\n")
    .map((f) => f.trim())
    .filter(Boolean)
    .filter((f) => f.endsWith(".spec.ts"));
} catch {
  console.warn(`[e2e-affected] 无法解析 base '${BASE_REF}'，回退跑 smoke`);
}

let targets;
if (changed.length > 0) {
  targets = changed;
  console.log(`[e2e-affected] 命中受影响的 spec ${changed.length} 个：`);
  for (const t of changed) console.log(`  - ${t}`);
} else {
  targets = ["tests/e2e/smoke"];
  console.log(`[e2e-affected] 无受影响的 spec（base=${BASE_REF}），回退跑 smoke`);
}

const args = ["test", ...targets, ...process.argv.slice(2)];
const r = spawnSync("playwright", args, { stdio: "inherit" });
process.exit(r.status ?? 1);
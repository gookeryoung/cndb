#!/usr/bin/env node
/* global process */
/**
 * 只跑 affected E2E —— 按 git 变更筛选受影响的 spec（需求 0181 C7）.
 *
 * 用法：
 *   pnpm e2e:affected                            # 对比上次提交 HEAD~1
 *   E2E_BASE_REF=origin/main pnpm e2e:affected   # 对比远程分支（PR 场景推荐）
 *   pnpm e2e:affected --headed                   # 其余参数原样透传给 playwright
 *
 * 筛选规则（宁可多跑，不可漏跑）：
 *   1. `tests/e2e` 下变更或新增的 `*.spec.ts` → 必跑（未跟踪的新 spec 也算，走 git ls-files）；
 *   2. 源码变更（`frontend/src` 或后端 `src/cndb`）→ 从路径提取关键词，匹配 spec 文件名；
 *      命中多个关键词的 spec 也算，只要能对上一条就纳入；
 *   3. 一条都没筛出来 → 回退 smoke 冒烟（登录 + 工作区 + 表格基础路径）。
 *
 * 为什么按文件名匹配而不是 import 图：e2e 走真实浏览器点界面，spec 不 import 被测源码
 * （全仓只有 fixtures/auth.ts 一处 `@/` 引用且是注释），静态依赖图在这里没有信息量；
 * 而 spec 命名本身就带有模块语义（row-crud / dashboard-edit / design-library…），
 * 用它做映射比维护一张手写对照表更不容易腐烂。
 *
 * 注意：这是**本地快速反馈**的定向筛选，不能替代 `make check` 的全量 e2e 门禁。
 */
import { execSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const BASE_REF = process.env.E2E_BASE_REF || "HEAD~1";
const E2E_DIR = "tests/e2e";

// git 永远在仓库根求 diff（pnpn e2e:affected 的 cwd 是 frontend/，直接 diff 得到的是相对路径，
// 与「从根看」的路径语义不一致，会把前后端源码路径混成一类）。故显式定位根并用前缀换算。
const REPO_ROOT = execSync("git rev-parse --show-toplevel", { encoding: "utf8" }).trim();
const CWD_PREFIX = path
  .relative(REPO_ROOT, process.cwd())
  .split(path.sep)
  .join("/");
/** 仓库根相对 → 当前进程 cwd 相对（playwright 的 spec 路径是 cwd 相对的） */
const fromRoot = (file) => (CWD_PREFIX ? file.slice(CWD_PREFIX.length + 1) : file);

/** 源码路径里这些词没有定位价值，参与匹配只会把全部 spec 拉进来 */
const STOP_WORDS = new Set([
  "src", "cndb", "frontend", "pages", "components", "component", "hooks", "hook",
  "utils", "util", "api", "store", "theme", "layouts", "layout", "test", "tests", "spec",
  "index", "types", "type", "shared", "common", "core", "models", "model", "app",
  "static", "main", "app", "use", "view", "views", "lib", "const", "constants",
  "dialog", "modal", "drawer", "panel", "page", "ts", "tsx", "py", "ts_", "d",
]);

/** 后端路径里有意义的分段（插件目录名 / 模块名）直接当关键词 */
const SOURCE_ROOTS = ["frontend/src/", "src/cndb/"];

function git(args) {
  return execSync(`git ${args}`, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim();
}

/** base..工作区（含未跟踪）的变更文件；路径统一成 posix 且相对仓库根 */
function changedFiles() {
  let tracked = [];
  try {
    tracked = git(`diff --name-only ${BASE_REF}`).split("\n").map((line) => line.trim()).filter(Boolean);
  } catch {
    console.warn(`[e2e-affected] 无法解析 base '${BASE_REF}'，按「无源码变更」处理`);
  }
  let untracked = [];
  try {
    untracked = git("ls-files --others --exclude-standard").split("\n").map((line) => line.trim()).filter(Boolean);
  } catch {
    // 非 git 环境：忽略
  }
  return [...new Set([...tracked, ...untracked])];
}

function splitWords(text) {
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[^A-Za-z0-9]+/)
    .map((word) => word.toLowerCase())
    .filter((word) => word.length > 2 && !STOP_WORDS.has(word));
}

/** 全部 spec 及其文件名关键词 */
function allSpecs() {
  const specs = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".spec.ts")) {
        const rel = full.split(path.sep).join("/");
        specs.push({ rel, words: new Set(splitWords(entry.name.replace(/\.spec\.ts$/, ""))) });
      }
    }
  };
  walk(E2E_DIR);
  return specs;
}

const changed = changedFiles();
// 仓库根相对的 e2e 目录前缀（如 frontend/tests/e2e/）
const e2eRoot = `${CWD_PREFIX ? `${CWD_PREFIX}/` : ""}${E2E_DIR}/`;

// 1) e2e 自身变更（含未跟踪的新 spec）
const directSpecs = changed.filter((file) => file.startsWith(e2eRoot) && file.endsWith(".spec.ts"));
// e2e 公共设施（fixtures/helpers/reporters/setup）：改动会影响所有 spec，直接跑 critical 全量
const e2eShared = changed.filter(
  (file) =>
    file.startsWith(e2eRoot) &&
    !file.endsWith(".spec.ts") &&
    !file.endsWith(".md") &&
    !file.includes("/perf/"),
);

const sourceFiles = changed.filter((file) => SOURCE_ROOTS.some((root) => file.startsWith(root)));

const keywords = new Set();
for (const file of sourceFiles) {
  // 去掉源码根前缀与扩展名后逐段切词：src/pages/grid/views/ChartView.tsx → grid / chart / view…
  const stripped = file.replace(/\.(?:tsx?|py|css|json)$/, "");
  for (const word of splitWords(stripped)) keywords.add(word);
}

const specs = allSpecs();
const matched = new Set();
if (keywords.size > 0) {
  for (const spec of specs) {
    for (const word of spec.words) {
      if (keywords.has(word)) {
        matched.add(spec.rel);
        break;
      }
    }
  }
}

// spec 路径统一用 cwd 相对（playwright 的 test 参数按 cwd 解析）
const targets = new Set(directSpecs.map(fromRoot));
// e2e 公共设施改动：critical 目录全跑（它承载绝大多数真实链路），而不是靠关键词猜
if (e2eShared.length > 0) {
  for (const spec of specs) if (spec.rel.includes("/critical/")) targets.add(spec.rel);
}
for (const spec of matched) targets.add(spec);

if (targets.size === 0) {
  console.log(
    `[e2e-affected] base=${BASE_REF}：变更 ${changed.length} 个文件，未筛出受影响的 spec，回退跑 smoke`,
  );
  if (changed.length > 0) {
    console.log("[e2e-affected] 变更文件（前 10 个）：");
    for (const file of changed.slice(0, 10)) console.log(`  · ${file}`);
  }
  targets.add(`${E2E_DIR}/smoke`);
} else {
  console.log(`[e2e-affected] base=${BASE_REF}：变更 ${changed.length} 个文件 → 命中 ${targets.size} 个 spec`);
  if (directSpecs.length > 0) console.log(`  · e2e 自身变更 ${directSpecs.length} 个`);
  if (e2eShared.length > 0) console.log(`  · e2e 公共设施变更 → critical 全跑（${e2eShared.join(", ")}）`);
  if (keywords.size > 0) console.log(`  · 源码关键词 ${[...keywords].sort().join(" ")}`);
}

// --dry-run / E2E_AFFECTED_PLAN=1：只打印筛选结果不执行，便于核对规则与排查误筛
if (process.argv.includes("--dry-run") || process.env.E2E_AFFECTED_PLAN === "1") {
  console.log("[e2e-affected] 计划执行（未真正运行）：");
  for (const target of [...targets].sort()) console.log(`  → ${target}`);
  process.exit(0);
}

const args = ["test", ...[...targets].sort(), ...process.argv.slice(2)];
// 不能直接 spawnSync("playwright")：Windows 上 node_modules/.bin 里只有 .cmd / sh shim，
// CreateProcess 找不到裸命令（实测 spawnSync ENOENT，status 为 null 却不报原因）。
// 用 node 直接执行 @playwright/test 的 CLI 入口，不依赖 PATH，也不走 shell。
const cliPath = createRequire(import.meta.url).resolve("@playwright/test/cli");
const result = spawnSync(process.execPath, [cliPath, ...args], { stdio: "inherit" });
if (result.error) {
  console.error(`[e2e-affected] 启动 playwright 失败：${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);

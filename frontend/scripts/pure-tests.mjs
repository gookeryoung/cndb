#!/usr/bin/env node
/**
 * 生成「纯逻辑测试」清单（需求 0181 C5）——这些用例可以脱离 jsdom 跑。
 *
 * 背景：前端 293 个测试文件全部跑在 jsdom + 全局 setup 下，实测 79 个不碰 DOM 的测试
 * 在这套环境里要 18.6s，换 node 环境 + 极简 setup 只要 2.6s（setup 65% / environment 29% /
 * tests 5% 的耗时结构决定了瓶颈在环境而不是用例）。所以按环境拆两个 vitest project。
 *
 * 判定不只看测试文件本身，而是**沿本地 import 图递归**看实现代码：
 * 只扫测试文件会把「实现内部用到 document」的用例误判成纯逻辑（实测 analyticsModel /
 * designIndent 就是这样挂掉的），漏判只会让用例继续跑 jsdom（慢但不错），误判才会红。
 * 因此本脚本从严：命中任一信号即不算纯逻辑。
 *
 * 用法：
 *   node scripts/pure-tests.mjs           # 生成/更新 src/test/pure-tests.json
 *   node scripts/pure-tests.mjs --check   # 只校验清单是否漂移（CI / 门禁用），漂移退出 1
 *   node scripts/pure-tests.mjs --list    # 打印清单与判定原因
 */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "src");
const OUT = path.join(SRC, "test", "pure-tests.json");

/** 依赖这些包即视为需要 DOM / 浏览器环境 */
const DOM_PACKAGES = [
  "@testing-library/",
  "@ant-design/",
  "antd",
  "react-dom",
  "msw",
  "@codemirror/view",
  "@dnd-kit/",
];

/** 源码里出现这些全局即视为需要浏览器环境 */
const DOM_GLOBALS =
  /\b(?:document|window|navigator|localStorage|sessionStorage|getComputedStyle|matchMedia|requestAnimationFrame|IntersectionObserver|ResizeObserver|HTMLElement|documentElement)\b/;

/** 测试文件里出现这些即视为需要测试环境设施（RTL / MSW / 渲染） */
const DOM_TEST_API = /\b(?:render|renderHook|screen|fireEvent|userEvent|@\/test\/msw|@testing-library)\b/;

const MODULE_EXT = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"];

/** 把 import 说明符解析成仓库内绝对路径；解析不到（第三方包）返回 null */
/** 把 import 说明符解析成仓库内绝对路径；解析不到（第三方包）返回 null */
function resolveLocal(spec, fromFile) {
  let base;
  if (spec.startsWith("@/")) base = path.join(SRC, spec.slice(2));
  else if (spec.startsWith("./") || spec.startsWith("../")) base = path.resolve(path.dirname(fromFile), spec);
  else return null;

  const candidates = [base, ...MODULE_EXT.map((ext) => base + ext)];
  for (const candidate of candidates) {
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch {
      // 不存在就继续找下一个候选
    }
  }
  return null;
}

const IMPORT_RE =
  /(?:^|\n)\s*(?:import|export)\s+([\s\S]*?)\s+from\s+["']([^"']+)["']|require\(\s*["']([^"']+)["']\s*\)|import\(\s*["']([^"']+)["']\s*\)/g;

/** 沿本地 import 图递归，返回 (是否需要 DOM, 首个原因) */
function needsDom(file, seen = new Set()) {
  if (seen.has(file)) return null;
  seen.add(file);
  if (file.endsWith(".tsx")) return `${path.relative(ROOT, file)} 是 .tsx（React 组件 / 含 JSX）`;

  let source;
  try {
    source = fs.readFileSync(file, "utf8");
  } catch {
    return `${path.relative(ROOT, file)} 不可读`;
  }

  if (DOM_GLOBALS.test(source)) {
    const hit = source.match(DOM_GLOBALS)?.[0];
    return `${path.relative(ROOT, file)} 使用浏览器全局 ${hit}`;
  }

  for (const match of source.matchAll(IMPORT_RE)) {
    const clause = (match[1] ?? "").trim();
    const spec = match[2] ?? match[3] ?? match[4];
    if (!spec) continue;
    // `import type { X } from '@/api'` 只在类型层引用，运行时不会加载该模块，跳过
    if (/^type\b/.test(clause)) continue;
    if (DOM_PACKAGES.some((pkg) => spec === pkg || spec.startsWith(pkg))) {
      return `${path.relative(ROOT, file)} 引入浏览器相关依赖 ${spec}`;
    }
    const local = resolveLocal(spec, file);
    if (!local) continue;
    const reason = needsDom(local, seen);
    if (reason) return reason;
  }
  return null;
}

/** 收集全部测试文件 */
function testFiles() {
  const out = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "__snapshots__" || entry.name === "node_modules") continue;
        walk(full);
      } else if (/\.(?:test|spec)\.(?:ts|tsx)$/.test(entry.name)) {
        out.push(full);
      }
    }
  };
  walk(SRC);
  return out.sort();
}

function classify() {
  const pure = [];
  const reasons = new Map();
  for (const file of testFiles()) {
    const rel = path.relative(ROOT, file).split(path.sep).join("/");
    const head = fs.readFileSync(file, "utf8").slice(0, 4000);
    if (DOM_TEST_API.test(head)) {
      reasons.set(rel, "测试自身使用 RTL / MSW 等浏览器侧设施");
      continue;
    }
    const reason = needsDom(file);
    if (reason) reasons.set(rel, reason);
    else pure.push(rel);
  }
  return { pure, reasons, total: pure.length + reasons.size };
}

function build() {
  const { pure, total } = classify();
  return {
    // 说明写进文件，避免有人手工乱改后看不出它是生成物
    _comment:
      "由 frontend/scripts/pure-tests.mjs 生成：这些用例不碰 DOM，跑 node 环境（快约 7 倍）。改代码后请运行 pnpm test:pure:sync 重新生成。",
    total,
    pure,
  };
}

function main(argv) {
  const check = argv.includes("--check");
  const list = argv.includes("--list");
  const { pure, reasons, total } = classify();
  const payload = build();

  if (list) {
    console.log(`[pure-tests] 共 ${total} 个测试文件，纯逻辑 ${pure.length} 个：`);
    for (const rel of pure) console.log(`  ✓ ${rel}`);
    console.log("\n需要 jsdom 的（原因取一条）：");
    for (const [rel, reason] of reasons) console.log(`  · ${rel} — ${reason}`);
    return 0;
  }

  const text = `${JSON.stringify(payload, null, 2)}\n`;
  if (check) {
    const current = fs.existsSync(OUT) ? fs.readFileSync(OUT, "utf8") : "";
    if (current !== text) {
      console.error(
        "[pure-tests] 清单已漂移：源码的 import 图变了但 src/test/pure-tests.json 未更新。\n" +
          "          运行 `pnpm test:pure:sync` 重新生成并提交（漏更新只会让用例继续走 jsdom，不会漏跑）。",
      );
      return 1;
    }
    console.log(`[pure-tests] 清单一致（${pure.length}/${total} 个纯逻辑测试）。`);
    return 0;
  }

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, text);
  console.log(`[pure-tests] 已写入 ${path.relative(ROOT, OUT)}：${pure.length}/${total} 个纯逻辑测试。`);
  return 0;
}

process.exit(main(process.argv.slice(2)));

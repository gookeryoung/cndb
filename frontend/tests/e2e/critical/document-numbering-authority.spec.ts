/**
 * Critical — 标题编号单一权威（ADR 0186 I1 / I2 / I3 / H72）.
 *
 * 覆盖端到端链路（jsdom 单测覆盖不到真实 docx 字节）：
 * 1) `mode=auto`（默认）：正文自带显式序号 → 模板编号让位，导出不叠加；
 * 2) `mode=auto`：正文是无序号语义标题 → 模板编号照常生成；
 * 3) `mode=force`：即使正文自带序号也强制叠加（升级前行为，显式选择）；
 * 4) `mode=off`：始终不编号；
 * 5) `format=md` 不写序号（I3 / D9）—— 三条 md 导出字节完全一致，与模板 mode 无关。
 *
 * 为什么必须 E2E：编号发生在 docx 渲染期，只有拿到真实 docx 字节解开 word/document.xml
 * 才能判定「究竟有没有叠加」；用 API 造文档 + 导出，避免依赖编辑器 UI 的懒加载 chunk。
 */
import { expect, test } from "../fixtures/auth";
import type { APIRequestContext } from "@playwright/test";
import { inflateRawSync } from "node:zlib";

import { apiCall, getAdminToken, getWorkspaceId } from "../helpers/api";

const WORKSPACE_NAME = "科研项目管理";
const stamp = Date.now();
const TEMPLATE_NAME = `E2E 编号模板 ${stamp}`;

/** 正文自带显式序号的文档（「一、」「3.1」两种前缀都覆盖） */
const EXPLICIT_CONTENT = `## 一、项目背景

正文第一段。

## （二）研究目标

正文第二段。

### 3.1 关键技术

正文第三段。
`;

/** 正文为语义标题、不含任何序号的文档 */
const PLAIN_CONTENT = `## 项目背景

正文第一段。

## 研究目标

正文第二段。

### 关键技术

正文第三段。
`;

let wid: number;
let token: string;
let templateRef: string;
let explicitDocId: number;
let plainDocId: number;

/**
 * 从 docx 字节里取出 word/document.xml 的纯文本内容。
 *
 * docx 是 zip：这里只实现「定位 local file header → 判断 deflate → 解压」的最小读法，
 * 不引第三方 zip 库（e2e 依赖面越小越稳）。文件名匹配 `word/document.xml`。
 */
function docxDocumentXml(bytes: Buffer): string {
  let offset = 0;
  while (offset + 30 <= bytes.length) {
    // local file header 签名 PK\x03\x04
    if (bytes.readUInt32LE(offset) !== 0x04034b50) break;
    const method = bytes.readUInt16LE(offset + 8);
    let compressedSize = bytes.readUInt32LE(offset + 18);
    const nameLen = bytes.readUInt16LE(offset + 26);
    const extraLen = bytes.readUInt16LE(offset + 28);
    const nameStart = offset + 30;
    const name = bytes.subarray(nameStart, nameStart + nameLen).toString("utf8");
    const dataStart = nameStart + nameLen + extraLen;
    // 使用了 data descriptor（bit 3）：尺寸写在数据之后，这里不支持 —— 我方导出不会产生
    if (compressedSize === 0) throw new Error(`docx 条目 ${name} 缺少尺寸（data descriptor 未支持）`);
    const data = bytes.subarray(dataStart, dataStart + compressedSize);
    if (name === "word/document.xml") {
      return method === 0 ? data.toString("utf8") : inflateRawSync(data).toString("utf8");
    }
    offset = dataStart + compressedSize;
  }
  throw new Error("docx 中未找到 word/document.xml");
}

/** 去掉 XML 标签，得到文档纯文本（用于断言「一、」是否出现一次 / 两次） */
function xmlText(xml: string): string {
  return xml
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

async function exportDocx(
  request: APIRequestContext,
  docId: number,
  extraQuery = "",
): Promise<string> {
  const res = await request.get(
    `/api/v1/workspaces/${wid}/documents/${docId}/export?format=docx${extraQuery}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(res.status(), await res.text()).toBe(200);
  return xmlText(docxDocumentXml(Buffer.from(await res.body())));
}

async function exportMarkdown(request: APIRequestContext, docId: number): Promise<string> {
  const res = await request.get(
    `/api/v1/workspaces/${wid}/documents/${docId}/export?format=md`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(res.status()).toBe(200);
  return await res.text();
}

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
  token = await getAdminToken(request);
  wid = await getWorkspaceId(request, WORKSPACE_NAME);

  // 自定义模板：关掉编号，随后逐条 PATCH mode 验证三档语义
  const created = await apiCall(request, token, "post", `/workspaces/${wid}/documents/templates`, {
    name: TEMPLATE_NAME,
    description: "e2e 自动创建（ADR 0186）",
    preset_key: "official",
  });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  templateRef = (created.body as { ref: string }).ref;

  const explicit = await apiCall(request, token, "post", `/workspaces/${wid}/documents`, {
    title: `编号权威-有序号 ${stamp}`,
    content: EXPLICIT_CONTENT,
    status: "published",
  });
  expect(explicit.status, JSON.stringify(explicit.body)).toBe(201);
  explicitDocId = (explicit.body as { id: number }).id;

  const plain = await apiCall(request, token, "post", `/workspaces/${wid}/documents`, {
    title: `编号权威-无序号 ${stamp}`,
    content: PLAIN_CONTENT,
    status: "published",
  });
  expect(plain.status, JSON.stringify(plain.body)).toBe(201);
  plainDocId = (plain.body as { id: number }).id;
});

test.afterAll(async ({ request }: { request: APIRequestContext }) => {
  if (templateRef) {
    await apiCall(request, token, "delete", `/workspaces/${wid}/documents/templates/${templateRef}`).catch(
      () => undefined,
    );
  }
  for (const docId of [explicitDocId, plainDocId]) {
    if (docId) {
      await apiCall(request, token, "delete", `/workspaces/${wid}/documents/${docId}`).catch(() => undefined);
    }
  }
});

/** 把模板编号档位改为指定 mode（同时发 heading，避免 extra="forbid" 的 422） */
async function setNumberingMode(
  request: APIRequestContext,
  mode: "auto" | "force" | "off",
  heading = "cn_ordinal",
): Promise<void> {
  const resp = await apiCall(request, token, "patch", `/workspaces/${wid}/documents/templates/${templateRef}`, {
    config: { numbering: { heading, mode } },
  });
  expect(resp.status, JSON.stringify(resp.body)).toBe(200);
}

test.describe("标题编号单一权威（ADR 0186）", () => {
  test("auto：正文自带序号时模板编号让位，不出现叠加", async ({ request }) => {
    await setNumberingMode(request, "auto");
    const text = await exportDocx(request, explicitDocId, `&template=${encodeURIComponent(templateRef)}`);

    // 正文的「一、」只出现一次（若叠加会变成「（一） 一、」或「一、 一、」）
    expect(text.match(/一、/g)?.length ?? 0).toBe(1);
    expect(text).toContain("项目背景");
    // 不应出现模板的 cn_ordinal 产物（「一、」）与正文序号并排叠加
    expect(text).not.toMatch(/一、\s*一、/);
  });

  test("auto：正文无序号时模板编号照常生成", async ({ request }) => {
    await setNumberingMode(request, "auto");
    const text = await exportDocx(request, plainDocId, `&template=${encodeURIComponent(templateRef)}`);

    // 语义标题 + cn_ordinal 模板编号 → 标题前出现「一、」这类序号，且原文标题仍在
    expect(text).toMatch(/一、\s*项目背景/);
    expect(text).toMatch(/二、\s*研究目标/);
  });

  test("force：显式选择后即使正文有序号也强制叠加（升级前行为）", async ({ request }) => {
    await setNumberingMode(request, "force");
    const text = await exportDocx(request, explicitDocId, `&template=${encodeURIComponent(templateRef)}`);

    // 强制叠加：正文「一、项目背景」前多了模板生成的同形序号，两者同时出现
    // （这正是 ADR 0186 §4#8 说的「force 的显式后果」，不是缺陷）
    expect(text).toMatch(/一、\s*一、\s*项目背景/);
  });

  test("off：始终不编号，正文原样导出", async ({ request }) => {
    await setNumberingMode(request, "off");
    const plain = await exportDocx(request, plainDocId, `&template=${encodeURIComponent(templateRef)}`);
    // 无序号正文在 off 下不得出现模板编号
    expect(plain).not.toMatch(/一、\s*项目背景/);
    expect(plain).toContain("项目背景");

    const explicit = await exportDocx(request, explicitDocId, `&template=${encodeURIComponent(templateRef)}`);
    expect(explicit.match(/一、/g)?.length ?? 0).toBe(1);
  });

  test("md 导出不编号：与模板 mode 无关，字节一致（I3 / D9）", async ({ request }) => {
    await setNumberingMode(request, "force");
    const forced = await exportMarkdown(request, plainDocId);

    await setNumberingMode(request, "off");
    const off = await exportMarkdown(request, plainDocId);

    await setNumberingMode(request, "auto", "arabic_multilevel");
    const auto = await exportMarkdown(request, plainDocId);

    // md 是源文快照：三种模板档位下完全一致，且不含模板生成的序号
    expect(off).toBe(forced);
    expect(auto).toBe(forced);
    expect(forced).toContain("## 项目背景");
    expect(forced).not.toMatch(/##\s*[一1][、.]\s*项目背景/);
  });
});

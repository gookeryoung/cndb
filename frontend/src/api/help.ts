/** 帮助文档 API — /api/v1/help/*
 *
 * 典型示例清单与 CSV 下载（ADR 0029 P1）：清单由后端静态常量唯一提供，
 * 前端只渲染返回值；下载需携带 Authorization，故统一走 axios 取 blob。
 */

import api from './client'

/** 示例中的一张 CSV 表 */
export interface HelpExampleTable {
  file: string
  title: string
  description: string
  /** 示例说明用的近似行数 */
  rows: number
}

/** 一个示例场景 */
export interface HelpExample {
  key: string
  name: string
  summary: string
  tables: HelpExampleTable[]
  highlights: string[]
  steps: string[]
}

export interface HelpExampleList {
  items: HelpExample[]
}

/** 一张帮助图示的元信息（ADR 0030） */
export interface HelpFigureMeta {
  key: string
  title: string
  caption: string
  /** 所属帮助部分 key（quick-start / tutorials / examples / configuration / troubleshooting） */
  section: string
  /** 内容指纹：源码或数据源变化即变，用作 SVG 请求的缓存键 */
  fingerprint: string
  /** 生成时间（Unix 秒） */
  generatedAt: number
}

export interface HelpFigureList {
  items: HelpFigureMeta[]
  generatedAt: number
}

const EXAMPLES_URL = '/v1/help/examples'
const FIGURES_URL = '/v1/help/figures'

export const helpApi = {
  /** 拉取典型示例清单（登录即可） */
  listExamples: () => api.get<HelpExampleList>(EXAMPLES_URL).then((res) => res.data),

  /** 下载清单登记的示例 CSV（返回 Blob，调用方负责触发浏览器下载） */
  downloadExampleFile: (scenario: string, filename: string) =>
    api
      .get<Blob>(`${EXAMPLES_URL}/${encodeURIComponent(scenario)}/files/${encodeURIComponent(filename)}`, {
        responseType: 'blob',
      })
      .then((res) => res.data),

  /** 拉取图示例清单（含指纹与生成时间） */
  listFigures: () => api.get<HelpFigureList>(FIGURES_URL).then((res) => res.data),

  /** 取单张图示 SVG 文本（不解析 JSON，交给内联渲染） */
  getFigureSvg: (key: string) =>
    api
      .get<string>(`${FIGURES_URL}/${encodeURIComponent(key)}.svg`, {
        responseType: 'text',
        transformResponse: [(data: string) => data],
      })
      .then((res) => res.data),

  /** 立即重建全部图示（运维 / 内容核验用） */
  refreshFigures: () => api.post<{ rebuilt: number }>(`${FIGURES_URL}/refresh`).then((res) => res.data),
}

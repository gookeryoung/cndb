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

const EXAMPLES_URL = '/v1/help/examples'

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
}

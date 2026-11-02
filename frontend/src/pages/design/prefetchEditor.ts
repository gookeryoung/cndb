/** 设计编辑器 chunk 预取 —— 装配打开性能（ADR 0086 C9）
 *
 * 编辑器 route chunk（含 CodeMirror）与 3D 预览 chunk（含 three）此前在
 * 第一次点击「打开」时才开始下载 + 解析，首次打开编辑器可交互耗时贴近 1s 阈值。
 * 设计列表页空闲时预取这两个 chunk，把成本移出点击路径（对齐 SPA 路由预取惯例）。
 * 幂等：只预取一次，重复调用零开销。
 */

let prefetched = false

export function prefetchDesignEditorChunks(): void {
  if (prefetched) return
  prefetched = true
  // 动态 import 与路由 lazy 指向同一 chunk，浏览器去重；此处只为提前触发下载解析
  void import('./DesignEditorPage')
  void import('./PreviewCanvas')
}

/** 仅测试使用：重置幂等标记 */
export function resetPrefetchForTest(): void {
  prefetched = false
}

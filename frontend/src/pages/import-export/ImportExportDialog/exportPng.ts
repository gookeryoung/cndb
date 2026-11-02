/** 视图内容导出 PNG —— 与 PDF 共用同一条视觉快照链路（ADR 0023 / 原 0077 P0）.
 *
 * 捕获逻辑在 `exportPdf.captureElement`，本模块只负责 PNG 编码与触发下载，
 * 避免 dashboard 再复制一份滚动展开 / 包围盒测量 / 旧内核垫片实现。
 * html2canvas-pro 仍在导出点击时动态导入，不进入首屏 chunk。
 */

import { captureElement } from './exportPdf'

/** 将目标元素渲染为 PNG 并触发下载.
 *
 * @param target 待捕获的 DOM 容器（调用方须已确保数据就绪）
 * @param filename 下载文件名（需以 .png 结尾）
 * @param backgroundColor 捕获背景色；默认白色
 * @throws 渲染或编码失败时向上抛出原始错误，由调用方提示
 */
export async function exportElementToPng(
  target: HTMLElement,
  filename: string,
  backgroundColor: string = '#ffffff',
): Promise<void> {
  const { canvas } = await captureElement(target, backgroundColor)
  const url = canvas.toDataURL('image/png')
  if (!url || url === 'data:,') throw new Error('PNG 导出失败：画面为空')
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

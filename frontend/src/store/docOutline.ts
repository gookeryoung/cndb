/** 当前打开文档的标题大纲 —— DocumentEditorPage 实时同步，MainLayout 文档结构侧栏消费.
 *
 * 大纲由编辑器从（含未保存编辑的）当前内容解析后写入；离开编辑器时清空，
 * 侧栏据此回退为文档列表，避免展示过期结构。
 */

import { create } from 'zustand'

import type { OutlineItem } from '@/components/Document/outline'

/** 侧栏 → 编辑器的锚点跳转事件名：detail 为目标锚点 id */
export const DOC_OUTLINE_JUMP_EVENT = 'doc-outline-jump'

interface DocOutlineState {
  outline: OutlineItem[]
  setOutline: (items: OutlineItem[]) => void
  clearOutline: () => void
}

export const useDocOutlineStore = create<DocOutlineState>((set) => ({
  outline: [],
  setOutline: outline => set({ outline }),
  clearOutline: () => set({ outline: [] }),
}))

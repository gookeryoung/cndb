/** 大纲条目列表：抽屉与右侧常驻栏共用，避免两套样式与 testid 漂移.
 *
 * 层级以引线树渲染（参考 Obsidian 大纲风格）：
 * - 每个层级一条细竖引线贯穿子级区域，无折线记号，直观呈现嵌套深度；
 * - 悬停行时该行引线以品牌色高亮，行背景浮现浅色底；
 * - 有子级标题的条目在引线末端悬停浮现折叠箭头（默认全展开），
 *   点箭头仅切换折叠态，点正文仍为锚点跳转。
 * 悬停高亮与箭头显隐样式见 index.css 的 `cn-outline-*` 段。
 */

import { useMemo, useState } from 'react'

import type { OutlineItem } from '@/components/Document/outline'
import { RightOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import { WEIGHT } from '@/theme/tokens'

const { Text } = Typography

const CELL = 14

interface OutlineNode {
  item: OutlineItem
  /** 平铺列表中的原始下标（保持 testid 稳定） */
  index: number
  children: OutlineNode[]
}

/** 平铺标题序列 → 树（虚拟根森林）：level 不大于栈顶的标题回退为祖先的子级，同级互为兄弟 */
function buildTree(outline: OutlineItem[]): OutlineNode[] {
  const virtualRoot: OutlineNode = {
    item: { level: 0, text: '', anchor: '', line: -1 },
    index: -1,
    children: [],
  }
  const stack: OutlineNode[] = [virtualRoot]
  for (let i = 0; i < outline.length; i++) {
    const node: OutlineNode = { item: outline[i], index: i, children: [] }
    while (stack.length > 1 && stack[stack.length - 1].item.level >= node.item.level) {
      stack.pop()
    }
    stack[stack.length - 1].children.push(node)
    stack.push(node)
  }
  return virtualRoot.children
}

/** 树 → 可见节点序列（按折叠集合过滤子孙） */
function collectVisible(nodes: OutlineNode[], collapsed: Set<string>, out: OutlineNode[]): void {
  for (const node of nodes) {
    out.push(node)
    const key = `${node.item.anchor}-${node.index}`
    if (node.children.length > 0 && !collapsed.has(key)) {
      collectVisible(node.children, collapsed, out)
    }
  }
}

/** 单元格：withLine 为 true 时绘制贯穿竖引线（Obsidian 缩进参考线风格） */
function GuideCell({ withLine }: { withLine: boolean }) {
  return (
    <span style={{ position: 'relative', flexShrink: 0, width: CELL, alignSelf: 'stretch' }}>
      {withLine && (
        <span
          className="cn-outline-guide-line"
          style={{
            position: 'absolute',
            left: Math.floor(CELL / 2),
            top: 0,
            bottom: 0,
            width: 1,
            background: 'var(--cn-border, #d1d5db)',
          }}
        />
      )}
    </span>
  )
}

export default function OutlineList({
  outline,
  onAnchorClick,
}: {
  outline: OutlineItem[]
  onAnchorClick: (anchor: string) => void
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const visible = useMemo(() => {
    const out: OutlineNode[] = []
    collectVisible(buildTree(outline), collapsed, out)
    return out
  }, [outline, collapsed])

  if (outline.length === 0) {
    return <Text type="secondary">暂无标题（用 # 起首行添加，编辑时实时更新）</Text>
  }

  const toggle = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <>
      {visible.map((node, idx) => {
        const { item: o, index: i } = node
        const key = `${o.anchor}-${i}`
        const level = o.level
        const hasChildren = node.children.length > 0
        const expanded = hasChildren && !collapsed.has(key)

        // 引线列 c 是否有祖先（level === c）存在：向前找第一个 level <= c 的可见标题
        const lines: boolean[] = []
        for (let c = 1; c < level; c++) {
          let withLine = false
          for (let j = idx - 1; j >= 0; j--) {
            const lv = visible[j].item.level
            if (lv <= c) {
              withLine = lv === c
              break
            }
          }
          lines.push(withLine)
        }

        return (
          <div
            key={key}
            className="cn-outline-row"
            data-testid={`doc-outline-item-${i}`}
            style={{
              paddingRight: 8,
              paddingTop: 2,
              paddingBottom: 2,
              fontSize: level <= 2 ? 13 : 12,
              fontWeight: level === 1 ? WEIGHT.semibold : WEIGHT.regular,
              color: level <= 2 ? 'var(--cn-text, inherit)' : 'var(--cn-text-secondary, #666)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'stretch',
              borderRadius: 4,
            }}
            onClick={() => onAnchorClick(o.anchor)}
          >
            {/* 祖先引线列：1..level-1 */}
            {lines.map((withLine, k) => (
              <GuideCell key={k} withLine={withLine} />
            ))}
            {/* 折叠箭头列：有子级时悬停浮现，叶子为空占位 */}
            <span
              style={{ flexShrink: 0, width: CELL, display: 'flex', alignSelf: 'stretch' }}
            >
              {hasChildren && (
                <span
                  className={expanded ? 'cn-outline-caret cn-outline-caret-expanded' : 'cn-outline-caret'}
                  data-testid={`doc-outline-toggle-${i}`}
                  aria-label={expanded ? '收起子标题' : '展开子标题'}
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation()
                    toggle(key)
                  }}
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--cn-text-tertiary, #999)',
                    userSelect: 'none',
                  }}
                >
                  <RightOutlined className="cn-outline-caret-icon" style={{ fontSize: 8 }} />
                </span>
              )}
            </span>
            <span
              style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              {o.text}
            </span>
          </div>
        )
      })}
    </>
  )
}

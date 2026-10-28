/** 大纲条目列表：抽屉与右侧常驻栏共用，避免两套样式与 testid 漂移.
 *
 * 层级以引线树渲染：子级标题通过竖线 / 折线（├ └）与父级相连，直观展示层级；
 * 有子级标题的条目在引线末端显示圆形 +/− 折叠按钮（默认全展开），
 * 点按钮仅切换折叠态，点正文仍为锚点跳转。
 */

import { useMemo, useState } from 'react'

import type { OutlineItem } from '@/components/Document/outline'
import { Typography } from 'antd'
import { WEIGHT } from '@/theme/tokens'

const { Text } = Typography

const CELL = 14
const LINE_COLOR = 'var(--cn-border, #e8e8e8)'

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

/** 引线单元格：parent 指定后绘制竖线，elbow 为 true 时追加横向引线（├ └ 形） */
function GuideCell({ parent, elbow }: { parent?: number; elbow?: boolean }) {
  return (
    <span
      style={{ position: 'relative', flexShrink: 0, width: CELL, height: 18, alignSelf: 'stretch' }}
    >
      {parent === 1 && (
        <span
          style={{
            position: 'absolute',
            left: 6,
            top: 0,
            height: elbow ? '50%' : '100%',
            width: 1,
            background: LINE_COLOR,
          }}
        />
      )}
      {parent === -1 && (
        <span
          style={{
            position: 'absolute',
            left: 6,
            top: 0,
            bottom: 0,
            width: 1,
            background: LINE_COLOR,
          }}
        />
      )}
      {elbow && (
        <span
          style={{
            position: 'absolute',
            left: 6,
            right: 0,
            top: '50%',
            height: 1,
            background: LINE_COLOR,
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

        // 父级所在引线列：向前找第一个 level 更小的可见标题
        let parentCol = 0
        for (let j = idx - 1; j >= 0; j--) {
          if (visible[j].item.level < level) {
            parentCol = visible[j].item.level
            break
          }
        }
        // 是否为父级最后一个子级（后面没有同级或更深标题）
        const isLast = !visible.slice(idx + 1).some((n) => n.item.level >= level)

        return (
          <div
            key={key}
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
            {Array.from({ length: level - 1 }, (_, c) => c + 1).map((c) => {
              if (c > parentCol) return <GuideCell key={c} />
              if (c === parentCol) {
                return (
                  <GuideCell key={c} parent={isLast ? 1 : -1} elbow />
                )
              }
              // c < parentCol：该祖先的子树在本行下方仍有更深层级则引线贯穿
              const continues = visible
                .slice(idx + 1)
                .some((n) => n.item.level > c)
              return <GuideCell key={c} parent={continues ? -1 : 0} />
            })}
            {/* 自身折叠按钮列：有子级时为圆形 +/− 按钮，叶子为空占位 */}
            {hasChildren ? (
              <span
                data-testid={`doc-outline-toggle-${i}`}
                aria-label={expanded ? '收起子标题' : '展开子标题'}
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation()
                  toggle(key)
                }}
                style={{
                  flexShrink: 0,
                  width: CELL,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  alignSelf: 'stretch',
                  userSelect: 'none',
                }}
              >
                <span
                  style={{
                    width: 12,
                    height: 12,
                    lineHeight: '10px',
                    textAlign: 'center',
                    fontSize: 11,
                    color: 'var(--cn-text-tertiary, #999)',
                    border: '1px solid var(--cn-border-strong, #bbb)',
                    borderRadius: '50%',
                    boxSizing: 'border-box',
                  }}
                >
                  {expanded ? '−' : '+'}
                </span>
              </span>
            ) : (
              <span style={{ flexShrink: 0, width: CELL }} />
            )}
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

/** 数据标签自动配色工具.
 *
 * 配色完全基于 Ant Design v5 官方预设色板（不自行定义任何 HEX）.
 * - 基础预设 13 种（blue/purple/cyan/green/magenta/pink/red/orange/yellow/volcano/geekblue/lime/gold）
 * - inverse 变体 13 种（如 blue-inverse）
 * - status 预设 5 种（success/processing/error/default/warning）
 * 合计 31 种稳定色名；通过字符串 hash 映射，同值同色.
 *
 * 增强：支持从后端 SelectOption.color 取已存储颜色，以及前端语义实时推荐.
 */

/** Ant Design v5 完整预设色名清单（基础 + inverse + status） */
const ANTD_COLOR_NAMES: readonly string[] = [
  // —— 13 种基础预设 ——
  'blue', 'purple', 'cyan', 'green', 'magenta', 'pink', 'red',
  'orange', 'yellow', 'volcano', 'geekblue', 'lime', 'gold',
  // —— 13 种 inverse 变体 ——
  'blue-inverse', 'purple-inverse', 'cyan-inverse', 'green-inverse',
  'magenta-inverse', 'pink-inverse', 'red-inverse',
  'orange-inverse', 'yellow-inverse', 'volcano-inverse',
  'geekblue-inverse', 'lime-inverse', 'gold-inverse',
  // —— 5 种 status 预设 ——
  'success', 'processing', 'error', 'default', 'warning',
]

/** 前端智能配色专用调色板（语义不匹配时 fallback） */
const _PALETTE: readonly string[] = ['blue', 'green', 'orange', 'purple', 'cyan', 'magenta', 'gold', 'red']

/** 标签值到 hash 颜色索引的缓存，保证同值同色 */
const valueIndexCache = new Map<string, number>()

/** 选项级别的语义推荐缓存（label → color） */
const semanticCache = new Map<string, string | null>()

/** 简单字符串 hash（djb2 变种） */
function hashString(str: string): number {
  let h = 5381
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h) + str.charCodeAt(i)
    h |= 0 // 转有符号 32 位
  }
  return Math.abs(h)
}

// ─────────────── 前端版语义匹配（与后端 smart_color.py 规则表对齐） ─────────

type _SemanticRule = { color: string; keywords: string[]; weight: number }

const _SEMANTIC_RULES: _SemanticRule[] = [
  // 布尔 / 是或否
  { color: 'green', keywords: ['是', 'yes', 'true', '对', '同意', '通过', 'ok', 'done', '已完成', '完成'], weight: 10 },
  { color: 'default', keywords: ['否', 'no', 'false', '错', '拒绝', '不通过', '未完成', 'pending', '待处理', '待办'], weight: 10 },
  // 状态
  { color: 'processing', keywords: ['进行中', '处理中', '执行中', 'ongoing', 'running', 'in_progress', 'active'], weight: 10 },
  { color: 'success', keywords: ['已完成', '完成', '已解决', '已处理', 'closed', 'resolved', 'finished'], weight: 10 },
  { color: 'error', keywords: ['已取消', '取消', '废弃', '已关闭', '驳回', 'rejected', 'canceled', 'abandoned'], weight: 10 },
  // 优先级 / 紧急度
  { color: 'red', keywords: ['紧急', 'urgent', 'critical', 'p0', '最高优先级', '立即处理', '立即'], weight: 15 },
  { color: 'orange', keywords: ['高优先级', '较高', 'high', 'p2', '重要', '优先', '高'], weight: 10 },
  { color: 'gold', keywords: ['中等', 'medium', 'normal', '一般', 'p3', '普通', '常规', '中'], weight: 10 },
  { color: 'blue', keywords: ['低优先级', '较低', 'low', 'p4', 'p5', '次要', 'minimal', '不急', '低'], weight: 10 },
  // 进度
  { color: 'green', keywords: ['100%', '全部', '完全', 'full', 'complete'], weight: 10 },
  { color: 'cyan', keywords: ['75%', '大部分', 'mostly', '多数'], weight: 10 },
  { color: 'gold', keywords: ['50%', '一半', 'half'], weight: 10 },
  { color: 'orange', keywords: ['25%', '小部分', '少量'], weight: 10 },
  { color: 'default', keywords: ['0%', '无', 'none', '空', 'empty'], weight: 10 },
  // 风险
  { color: 'error', keywords: ['极高风险', '高风险', '风险极高', '危险'], weight: 10 },
  { color: 'warning', keywords: ['中风险', '较高风险', '有风险'], weight: 10 },
  { color: 'green', keywords: ['低风险', '安全', 'safe', '无风险'], weight: 10 },
  // 评分
  { color: 'red', keywords: ['极差', '很差', 'failed', '非常差', '糟糕', 'terrible', 'bad'], weight: 10 },
  { color: 'orange', keywords: ['较差', '及格', 'poor', 'pass', '勉强'], weight: 10 },
  { color: 'gold', keywords: ['中等', '平均', 'ok', 'average'], weight: 10 },
  { color: 'green', keywords: ['良好', '优秀', '很好', 'excellent', 'great', 'perfect', '出色'], weight: 10 },
  // 金额
  { color: 'red', keywords: ['免费', 'free', '零元', '无偿', '赠送'], weight: 10 },
  { color: 'orange', keywords: ['昂贵', 'expensive', 'premium', '高价', '很贵', '贵'], weight: 10 },
  { color: 'green', keywords: ['便宜', '廉价', 'cheap', '低价', '实惠', '划算', '不贵'], weight: 10 },
  // 频率
  { color: 'red', keywords: ['从不', 'never', '零次', '完全不'], weight: 10 },
  { color: 'orange', keywords: ['偶尔', '很少', 'rarely', 'seldom', '罕见', '极少'], weight: 10 },
  { color: 'gold', keywords: ['有时', 'sometimes'], weight: 10 },
  { color: 'blue', keywords: ['经常', 'often', '频繁', '时常'], weight: 10 },
  { color: 'green', keywords: ['总是', '每天', 'always', 'daily', 'hourly', '每次'], weight: 10 },
  // 角色
  { color: 'purple', keywords: ['管理员', 'admin', 'administrator', 'root', '超级管理员', 'owner', '所有者'], weight: 10 },
  { color: 'blue', keywords: ['编辑', 'editor', '写权限', '可编辑'], weight: 10 },
  { color: 'default', keywords: ['只读', 'read_only', '查看', 'reader', 'viewer', '访客', 'guest', '浏览'], weight: 10 },
  // 待定/未知
  { color: 'processing', keywords: ['待定', '待确认', 'tbd', 'unknown', '未知', '未确定'], weight: 10 },
]

/** 数字等级 → 颜色映射 */
const _NUMBER_LEVEL_COLORS: Record<number, string> = { 1: 'red', 2: 'orange', 3: 'gold', 4: 'blue', 5: 'green' }
/** 等级字母 → 颜色映射 */
const _GRADE_LETTER_COLORS: Record<string, string> = { a: 'green', b: 'cyan', c: 'gold', d: 'orange', e: 'red', f: 'red' }

function _normalizeText(text: string): string {
  return text.trim().toLowerCase().replace(/[（），：\u3000]/g, '')
}

function _extractNumber(text: string): number | null {
  const m = text.match(/(\d+)\s*$/)
  return m ? parseInt(m[1]!, 10) : null
}

/** 前端语义匹配：给定 label 返回推荐色名，无匹配返回 null. */
export function suggestColorForLabel(label: string): string | null {
  if (!label) return null
  const cacheKey = label.trim().toLowerCase()
  const cached = semanticCache.get(cacheKey)
  if (cached !== undefined) return cached

  const text = _normalizeText(label)
  let bestColor: string | null = null
  let bestScore = 0

  for (const rule of _SEMANTIC_RULES) {
    let score = 0
    for (const kw of rule.keywords) {
      if (text.includes(kw)) score += rule.weight
    }
    if (score === 0) continue
    // 数字辅助加权
    const num = _extractNumber(text)
    if (num !== null) {
      if ((rule.keywords.some(k => k.includes('紧急') || k.includes('最高'))) && num <= 2) score += 5
      else if ((rule.keywords.some(k => k.includes('低') || k.includes('次要'))) && num >= 4) score += 5
    }
    if (score > bestScore) { bestScore = score; bestColor = rule.color }
  }

  // 路径 2: 纯数字等级
  if (!bestColor) {
    const num = _extractNumber(text)
    if (num !== null) {
      const hasCtx = /等级|级别|优先级|level|priority|\bp/.test(text)
      if (hasCtx || text.length <= 10) {
        bestColor = _NUMBER_LEVEL_COLORS[num] ?? null
      }
    }
  }

  // 路径 3: 等级字母完整单词匹配
  if (!bestColor) {
    const m = text.match(/(?:grade\s*|等级\s*|级别\s*|level\s*|^)([a-fA-F])(?:\s*级|\s*$|\b)/)
    if (m) {
      bestColor = _GRADE_LETTER_COLORS[m[1]!.toLowerCase()] ?? null
    }
  }

  semanticCache.set(cacheKey, bestColor)
  return bestColor
}

// ─────────────── 核心 API ───────────────────────────────────────────────────

/** 根据标签值返回稳定的 Ant Design 预设色名字符串.
 *
 * 直接传给 <Tag color={name}> 即可由 antd 渲染，主题切换自动适配.
 *
 * 注：纯 hash 随机配色，不感知 option.color。需感知后端已存颜色时使用
 * {@link resolveTagColor}。
 */
export function getTagColorName(value: string | number): string {
  const key = String(value).trim()
  if (!key) return ANTD_COLOR_NAMES[0]!
  let idx = valueIndexCache.get(key)
  if (idx === undefined) {
    idx = hashString(key) % ANTD_COLOR_NAMES.length
    valueIndexCache.set(key, idx)
  }
  return ANTD_COLOR_NAMES[idx]!
}

/** 兼容旧 API — 同 getTagColorName */
export function getTagColor(value: string | number): string {
  return getTagColorName(value)
}

/** 从选项配置中查找值对应的已存颜色；找不到则 fallback 语义推荐 → hash.
 *
 * @param value 单元格显示值（label 文本）
 * @param options 字段配置中的选项列表（可以是 string[] 或 {label, value, color}[]）
 * @param index 在选项列表中的位置（fallback 调色板用）
 */
export function resolveTagColor(
  value: string | number,
  options?: unknown,
  index: number = 0,
): string {
  const key = String(value).trim()
  if (!key) return 'default'

  // 路径 1: 从 options 中查已存 color
  if (Array.isArray(options)) {
    for (const opt of options) {
      if (typeof opt === 'string') {
        if (opt === key) {
          // 纯字符串选项本身没有 color 字段，跳过
          break
        }
      } else if (opt && typeof opt === 'object') {
        const o = opt as { label?: string; value?: unknown; color?: string }
        const optLabel = String(o.label ?? o.value ?? '')
        if (optLabel === key && o.color) {
          return o.color  // 后端已存颜色，直接使用
        }
      }
    }
  }

  // 路径 2: 前端语义匹配推荐（和后端 smart_color 规则对齐）
  const semantic = suggestColorForLabel(key)
  if (semantic) return semantic

  // 路径 3: 调色板 fallback 或 hash
  return _PALETTE[index % _PALETTE.length]
}

/** 清空所有颜色缓存（hash + 语义），用于测试或热更新场景. */
export function __resetTagColorCache(): void {
  valueIndexCache.clear()
  semanticCache.clear()
}

/** 导出 antd 预设色名清单供外部校验 */
export { ANTD_COLOR_NAMES }

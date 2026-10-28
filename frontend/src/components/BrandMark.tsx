import { useId } from 'react'

/**
 * 晶格（CNDB）品牌 LOGO 组件 —— 实心六边形晶格徽标。
 *
 * 与 public/favicon.svg 同源设计：实心蓝→青渐变六边形底，
 * 内部反白晶格网格与发光中心节点，寓意数据在晶格中规整排列、彼此关联。
 * 实心底自然融入页面背景，无边框/投影等「贴片」观感。
 * 各使用处（顶栏 / 认证页）通过 size 控制尺寸，随 SVG 等比缩放；
 * 渐变 id 用 useId 生成，避免同页多实例 id 冲突。
 */
export function BrandMark({ size = 24 }: { size?: number }) {
  const uid = useId()
  const brandGrad = `cn-brand-grad-${uid}`
  const glowGrad = `cn-brand-glow-${uid}`
  return (
    <svg
      className="cn-brand-logo"
      width={size}
      height={size}
      viewBox="0 0 1024 1024"
      aria-hidden
      focusable="false"
    >
      <defs>
        {/* 品牌渐变：左下蓝 → 右上青 */}
        <linearGradient id={brandGrad} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="#2E6BF0" />
          <stop offset="55%" stopColor="#2BA8E8" />
          <stop offset="100%" stopColor="#3BE8DC" />
        </linearGradient>
        {/* 中心节点光晕 */}
        <radialGradient id={glowGrad} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.9" />
          <stop offset="45%" stopColor="#FFFFFF" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* 实心六边形底（stroke 同渐变 + round join 软化尖角） */}
      <polygon
        points="512,152 824,332 824,692 512,872 200,692 200,332"
        fill={`url(#${brandGrad})`}
        stroke={`url(#${brandGrad})`}
        strokeWidth="40"
        strokeLinejoin="round"
      />

      {/* 反白晶格网格：竖向 + 两斜向 */}
      <g stroke="#FFFFFF" strokeWidth="26" strokeLinecap="round" fill="none" opacity="0.92">
        <path d="M512 260 V764" />
        <path d="M300 384 L724 640" />
        <path d="M724 384 L300 640" />
      </g>

      {/* 中心发光节点 */}
      <circle cx="512" cy="512" r="130" fill={`url(#${glowGrad})`} />
      <circle cx="512" cy="512" r="58" fill="#4FE8F4" />
    </svg>
  )
}

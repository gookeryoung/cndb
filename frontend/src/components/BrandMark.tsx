import { useId } from 'react'

/**
 * 晶格（CNDB）品牌 LOGO 组件 —— 六边形晶格徽标。
 *
 * 与 public/favicon.svg 同源设计：蓝→青渐变六边形轮廓，
 * 内部三向晶格网格与发光中心节点，寓意数据在晶格中规整排列、彼此关联。
 * 各使用处（顶栏 / 认证页）通过 size 控制尺寸，随 SVG 等比缩放；
 * 渐变 id 用 useId 生成，避免同页多实例 id 冲突。
 */
export function BrandMark({ size = 24 }: { size?: number }) {
  const uid = useId()
  const brandGrad = `cn-brand-grad-${uid}`
  const glowGrad = `cn-brand-glow-${uid}`
  const hexClip = `cn-brand-hex-${uid}`
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
          <stop offset="0%" stopColor="#45E8F0" stopOpacity="0.85" />
          <stop offset="45%" stopColor="#45E8F0" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#45E8F0" stopOpacity="0" />
        </radialGradient>
        {/* 网格裁剪：六边形内域（略内缩） */}
        <clipPath id={hexClip}>
          <polygon points="512,168 800,336 800,688 512,856 224,688 224,336" />
        </clipPath>
      </defs>

      {/* 三向晶格网格（裁剪在六边形内） */}
      <g clipPath={`url(#${hexClip})`} stroke={`url(#${brandGrad})`} strokeWidth="14" strokeLinecap="round" fill="none">
        {/* 竖向 */}
        <path d="M356 168 V856" />
        <path d="M512 168 V856" />
        <path d="M668 168 V856" />
        {/* 斜向 +（左上 → 右下） */}
        <path d="M164 292 L860 732" />
        <path d="M164 472 L708 802" />
        <path d="M316 222 L860 552" />
        {/* 斜向 -（右上 → 左下） */}
        <path d="M860 292 L164 732" />
        <path d="M860 472 L316 802" />
        <path d="M708 222 L164 552" />
      </g>

      {/* 六边形轮廓 */}
      <polygon
        points="512,152 824,332 824,692 512,872 200,692 200,332"
        fill="none"
        stroke={`url(#${brandGrad})`}
        strokeWidth="46"
        strokeLinejoin="round"
      />

      {/* 外围节点：顶点 + 边中点 */}
      <g fill={`url(#${brandGrad})`}>
        <circle cx="512" cy="152" r="22" />
        <circle cx="824" cy="332" r="22" />
        <circle cx="824" cy="692" r="22" />
        <circle cx="512" cy="872" r="22" />
        <circle cx="200" cy="692" r="22" />
        <circle cx="200" cy="332" r="22" />
        <circle cx="668" cy="242" r="24" />
        <circle cx="824" cy="512" r="24" />
        <circle cx="668" cy="782" r="24" />
        <circle cx="356" cy="782" r="24" />
        <circle cx="200" cy="512" r="24" />
        <circle cx="356" cy="242" r="24" />
      </g>

      {/* 内环节点 */}
      <g fill={`url(#${brandGrad})`}>
        <circle cx="512" cy="332" r="24" />
        <circle cx="668" cy="422" r="24" />
        <circle cx="668" cy="602" r="24" />
        <circle cx="512" cy="692" r="24" />
        <circle cx="356" cy="602" r="24" />
        <circle cx="356" cy="422" r="24" />
      </g>

      {/* 中心发光节点 */}
      <circle cx="512" cy="512" r="120" fill={`url(#${glowGrad})`} />
      <circle cx="512" cy="512" r="46" fill="#4FE8F4" />
    </svg>
  )
}

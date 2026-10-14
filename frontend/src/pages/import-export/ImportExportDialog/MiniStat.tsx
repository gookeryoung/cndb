/** 迷你统计卡片 —— 导入进度面板与数据质量面板共用. */

export default function MiniStat({ label, value, color, compact }: { label: string; value: number | string; color: string; compact?: boolean }) {
    return compact ? (
        <div style={{
            padding: '6px 12px', background: color + '12', borderRadius: 6,
            borderLeft: `3px solid ${color}`, minWidth: 72, textAlign: 'center',
        }}>
            <div style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</div>
            <div style={{ fontSize: 11, color: 'var(--cn-text-muted)' }}>{label}</div>
        </div>
    ) : (
        <div style={{
            padding: '8px 14px', background: color + '10', borderRadius: 6,
            borderLeft: `3px solid ${color}`, minWidth: 90,
        }}>
            <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
            <div style={{ fontSize: 11, color: 'var(--cn-text-muted)' }}>{label}</div>
        </div>
    )
}

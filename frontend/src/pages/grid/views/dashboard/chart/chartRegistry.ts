/** dashboard 图表类型注册表（ADR 0023 P2 / D7）.
 *
 * 新增一类图 = 本表加一条 def + 一个 buildOption + 一个快照测试；
 * 属性面板按 `supports` 决定字段与开关可见性，校验按 `roles` 口径（dashboardModel）。
 */

import {
  buildBoxplotDataset,
  buildCategoryDataset,
  buildFunnelDataset,
  buildGaugeDataset,
  buildHeatmapDataset,
  buildHistogramDataset,
  buildPieDataset,
  buildRadarDataset,
  buildScatterDataset,
  buildTreemapDataset,
} from './dataset'
import { buildDatasetOption } from './option'
import type { ChartTypeDef, Dataset } from './types'
import type { DashboardChartType } from '../dashboardModel'

/** 分组中文名（属性面板按组展示类型下拉） */
export const CHART_GROUP_LABELS: Record<ChartTypeDef['group'], string> = {
  comparison: '对比',
  trend: '趋势',
  composition: '构成',
  distribution: '分布',
  relation: '关系',
  finance: '指标',
}

type Supports = ChartTypeDef['supports']

const SUPPORTS_BASE: Supports = { agg: true, multiY: true, stack: false, dualAxis: false, series: true }

function def(
  type: DashboardChartType,
  label: string,
  group: ChartTypeDef['group'],
  buildDataset: ChartTypeDef['buildDataset'],
  extra: { supports?: Partial<Supports>; minSize?: ChartTypeDef['minSize'] } = {},
): ChartTypeDef {
  return {
    type,
    label,
    group,
    supports: { ...SUPPORTS_BASE, ...extra.supports },
    minSize: extra.minSize ?? { w: 4, h: 6 },
    buildDataset,
    buildOption: (data, cfg, theme, display) => buildDatasetOption(data, cfg, theme, display),
  }
}

export const CHART_TYPE_DEFS: readonly ChartTypeDef[] = [
  def('bar', '柱状图', 'comparison', buildCategoryDataset, { supports: { stack: true }, minSize: { w: 4, h: 6 } }),
  def('line', '折线图', 'trend', buildCategoryDataset, { supports: { stack: true }, minSize: { w: 6, h: 6 } }),
  def('area', '面积图', 'trend', buildCategoryDataset, { supports: { stack: true }, minSize: { w: 6, h: 6 } }),
  def('stack', '堆叠图', 'composition', buildCategoryDataset, { supports: { stack: true }, minSize: { w: 6, h: 6 } }),
  def('combo', '组合双轴', 'relation', buildCategoryDataset, {
    supports: { stack: false, dualAxis: true }, minSize: { w: 6, h: 6 },
  }),
  def('pie', '饼图', 'composition', buildPieDataset, {
    supports: { multiY: false, series: false }, minSize: { w: 4, h: 6 },
  }),
  def('scatter', '散点图', 'relation', (rows, _fields, cfg) => buildScatterDataset(rows, cfg), {
    supports: { agg: false, multiY: false, series: false }, minSize: { w: 5, h: 6 },
  }),
  def('histogram', '直方图', 'distribution', (rows, _fields, cfg) => buildHistogramDataset(rows, cfg), {
    supports: { agg: false, multiY: false, series: false }, minSize: { w: 5, h: 6 },
  }),
  def('boxplot', '箱线图', 'distribution', buildBoxplotDataset, {
    supports: { agg: false, multiY: false, series: false }, minSize: { w: 5, h: 6 },
  }),
  def('radar', '雷达图', 'comparison', buildRadarDataset, { minSize: { w: 5, h: 6 } }),
  def('funnel', '漏斗图', 'composition', buildFunnelDataset, {
    supports: { multiY: false, series: false }, minSize: { w: 4, h: 6 },
  }),
  def('gauge', '仪表盘', 'finance', (rows, _fields, cfg) => buildGaugeDataset(rows, cfg), {
    supports: { multiY: false, series: false }, minSize: { w: 3, h: 4 },
  }),
  def('heatmap', '热力图', 'relation', buildHeatmapDataset, {
    supports: { multiY: false }, minSize: { w: 6, h: 7 },
  }),
  def('treemap', '矩形树图', 'composition', buildTreemapDataset, {
    supports: { multiY: false }, minSize: { w: 5, h: 7 },
  }),
]

export const CHART_TYPE_OPTIONS = CHART_TYPE_DEFS.map((d) => ({
  value: d.type,
  label: d.label,
  group: d.group,
}))

const REGISTRY = new Map<DashboardChartType, ChartTypeDef>(CHART_TYPE_DEFS.map((d) => [d.type, d]))

/** 取类型定义（未知类型回退柱状图，保证渲染不中断） */
export function getChartTypeDef(type: DashboardChartType): ChartTypeDef {
  return REGISTRY.get(type) ?? CHART_TYPE_DEFS[0]
}

/** 按 data.kind 找到可复用 option 的类型定义（快照测试用） */
export function chartDefForKind(kind: Dataset['kind']): ChartTypeDef {
  return CHART_TYPE_DEFS.find((d) => {
    const built = d.type === 'pie' ? 'pie'
      : d.type === 'scatter' ? 'scatter'
        : d.type === 'histogram' ? 'histogram'
          : d.type === 'boxplot' ? 'boxplot'
            : d.type === 'radar' ? 'radar'
              : d.type === 'funnel' ? 'funnel'
                : d.type === 'gauge' ? 'gauge'
                  : d.type === 'heatmap' ? 'heatmap'
                    : d.type === 'treemap' ? 'treemap' : 'category'
    return built === kind
  }) ?? CHART_TYPE_DEFS[0]
}

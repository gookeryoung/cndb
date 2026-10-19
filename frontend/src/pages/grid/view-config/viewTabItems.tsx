/** 视图配置对话框的四个 Tab 内容（筛选 / 排序 / 字段显示 / 视图专属设置）.
 *
 * 从 ViewConfigDialog 的 viewTabItems useMemo（原 246 行）按 Tab 拆成四个纯构造函数；
 * memo 化仍留在组件侧，依赖数组逐项不变，因此重算时机与拆分前完全一致。
 */

import { Button, Checkbox, Segmented, Select, Tooltip } from 'antd'
import { DeleteOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import type { Dispatch, ReactNode, SetStateAction } from 'react'

import type { Field } from '@/api'
import HelpTip from '@/components/HelpTip'
import { optionColSpan } from './viewOptionSchema'
import { useChartListDraft } from './useChartListDraft'
import ViewOptionItem from './ViewOptionItem'
import FilterConditionEditor from './FilterConditionEditor'
import type { FilterRule, SortRule } from './ViewConfigDialog'

export type ViewTabItem = { key: string; label: ReactNode; children: ReactNode }

export function buildFilterTab({
  draftFilterLogic,
  draftFilters,
  filterableFields,
  setDraftFilters,
  setDraftFilterLogic,
}: {
  draftFilterLogic: 'AND' | 'OR'
  draftFilters: FilterRule[]
  filterableFields: Field[]
  setDraftFilters: (rules: FilterRule[]) => void
  setDraftFilterLogic: (logic: 'AND' | 'OR') => void
}): ViewTabItem {
  return       {
        key: 'filter',
        label: (
          <span>
            筛选{draftFilters.filter(f => f.field_name).length ? ` (${draftFilters.filter(f => f.field_name).length})` : ''}
            <HelpTip title="筛选规则：只显示满足条件的行，不改变表内数据；多个条件可用 AND / OR 组合" />
          </span>
        ),
        children: (
          <div className="vcvd-tab-body">
            <FilterConditionEditor
              fields={filterableFields}
              rules={draftFilters}
              logic={draftFilterLogic}
              onLogicChange={setDraftFilterLogic}
              onChange={setDraftFilters}
            />
          </div>
        ),
      }
}

export function buildSortTab({
  addSort,
  draftSorts,
  removeSort,
  sortableFields,
  updateSort,
}: {
  addSort: () => void
  draftSorts: SortRule[]
  removeSort: (idx: number) => void
  sortableFields: Field[]
  updateSort: (idx: number, patch: Partial<SortRule>) => void
}): ViewTabItem {
  return       {
        key: 'sort',
        label: (
          <span>
            排序{draftSorts.filter(s => s.field_name).length ? ` (${draftSorts.filter(s => s.field_name).length})` : ''}
            <HelpTip title="排序规则：按字段升序/降序排列行；多条规则自上而下依次生效" />
          </span>
        ),
        children: (
          <div className="vcvd-tab-body">
            {draftSorts.length === 0 && (
              <div className="vcvd-empty">暂无排序规则</div>
            )}
            {draftSorts.map((rule, idx) => (
              <div key={idx} className="vcvd-rule">
                <span className="vcvd-rule-index">#{idx + 1}</span>
                <Select size="small" value={rule.field_name || undefined}
                  onChange={(v) => updateSort(idx, { field_name: v })}
                  placeholder="字段" style={{ flex: 1 }}
                  options={sortableFields.map(f => ({ value: f.name, label: f.name }))} />
                <Select size="small" value={rule.direction}
                  onChange={(v: 'asc' | 'desc') => updateSort(idx, { direction: v })}
                  style={{ width: 100 }}
                  options={[{ value: 'asc', label: '升序 ↑' }, { value: 'desc', label: '降序 ↓' }]} />
                <Tooltip title="删除这条排序规则">
                  <Button size="small" type="text" danger icon={<DeleteOutlined />}
                    className="vcvd-rule-del" onClick={() => removeSort(idx)} />
                </Tooltip>
              </div>
            ))}
            <div className="vcvd-rule-actions">
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addSort}>添加排序</Button>
            </div>
          </div>
        ),
      }
}

export function buildFieldsTab({
  fields,
  setDraftOpt,
  viewHiddenFieldIds,
}: {
  fields: Field[]
  setDraftOpt: Dispatch<SetStateAction<Record<string, unknown>>>
  viewHiddenFieldIds: Set<string>
}): ViewTabItem {
  return {
        key: 'fields',
        label: (
          <span>
            字段显示
            <HelpTip title="取消勾选的字段仅在本视图的表格中不显示（列布局），不影响筛选、排序与行详情；字段管理器的「隐藏」为全局开关" />
          </span>
        ),
        children: (
          <div className="vcvd-tab-body">
            {fields.length === 0 && <div className="vcvd-empty">暂无字段</div>}
            <div className="vcvd-field-list">
              {fields.map(f => {
                const fid = String(f.id)
                const viewHidden = viewHiddenFieldIds.has(fid)
                return (
                  <div key={fid} className="vcvd-field-item">
                    <Checkbox
                      checked={!viewHidden}
                      disabled={!!f.hidden}
                      onChange={e => {
                        const next = new Set(viewHiddenFieldIds)
                        if (e.target.checked) next.delete(fid)
                        else next.add(fid)
                        setDraftOpt(prev => {
                          const arr = [...next]
                          const p = { ...prev }
                          if (arr.length) p.hidden_fields = arr
                          else delete p.hidden_fields
                          return p
                        })
                      }}
                    >
                      {f.name}
                    </Checkbox>
                    {f.hidden && <span className="vcvd-field-locked-tag">字段已隐藏</span>}
                    {!f.hidden && viewHidden && f.required && (
                      <Tooltip title="必填字段在本视图隐藏后，内联新增行将无法填写该字段、无法保存">
                        <span className="vcvd-field-warn-tag">必填</span>
                      </Tooltip>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )
      }
}

export function buildViewTab({
  activeChartOpts,
  activeIdx,
  chartDraft,
  chartList,
  collapsed,
  fields,
  isChartView,
  setCollapsed,
  setDraftOpt,
  viewSections,
  viewType,
}: {
  activeChartOpts: Record<string, unknown>
  activeIdx: number
  chartDraft: ReturnType<typeof useChartListDraft>
  chartList: ReturnType<typeof useChartListDraft>['list']
  collapsed: Record<string, boolean>
  fields: Field[]
  isChartView: boolean
  setCollapsed: Dispatch<SetStateAction<Record<string, boolean>>>
  setDraftOpt: Dispatch<SetStateAction<Record<string, unknown>>>
  viewSections: ReturnType<typeof import('./viewOptionSchema').groupOptionSchema>
  viewType: string
}): ViewTabItem {
  return {
        key: 'view',
        label: `${viewType} 专属设置`,
        children: (
          <div className="vcvd-tab-body">
            {isChartView && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                <Segmented
                  size="small"
                  value={activeIdx}
                  onChange={(v) => chartDraft.setActiveIdx(Number(v))}
                  options={chartList.map((_, i) => ({ label: `图表 ${i + 1}`, value: i }))}
                />
                <Tooltip title={chartList.length >= 6 ? '最多 6 个图表' : '新增一个图表条目'}>
                  <Button size="small" type="dashed" icon={<PlusOutlined />} disabled={chartList.length >= 6} onClick={chartDraft.addEntry}>
                    添加图表
                  </Button>
                </Tooltip>
                <Tooltip title={chartList.length <= 1 ? '至少保留一个图表' : '删除当前图表'}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={chartList.length <= 1} onClick={chartDraft.removeEntry}>
                    删除当前图表
                  </Button>
                </Tooltip>
              </div>
            )}
            {viewSections.map(section => {
              const isCollapsed = !!collapsed[section.label]
              return (
                <section key={section.label} className={`vcvd-section${isCollapsed ? ' collapsed' : ''}`}>
                  <button
                    type="button"
                    className="vcvd-section-head"
                    aria-expanded={!isCollapsed}
                    onClick={() => setCollapsed(prev => ({ ...prev, [section.label]: !prev[section.label] }))}
                  >
                    <RightOutlined className="vcvd-section-chevron" />
                    <span>{section.label}</span>
                  </button>
                  {!isCollapsed && (
                    <div className="vcvd-section-body vcvd-grid">
                      {section.items.map(opt => (
                        <div
                          key={opt.key}
                          className={optionColSpan(opt.kind) === 2 ? 'vcvd-col-2' : 'vcvd-col-1'}
                        >
                          <ViewOptionItem
                            opt={opt}
                            fields={fields}
                            opts={activeChartOpts}
                            onSet={(key, value) => {
                              if (isChartView) { chartDraft.patchEntry({ [key]: value }); return }
                              setDraftOpt(prev => ({ ...prev, [key]: value }))
                            }}
                            onPatch={(patch) => {
                              if (isChartView) { chartDraft.patchEntry(patch); return }
                              setDraftOpt(prev => {
                                const next = { ...prev }
                                for (const [k, v] of Object.entries(patch)) {
                                  if (v === undefined) delete next[k]
                                  else next[k] = v
                                }
                                return next
                              })
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )
            })}
          </div>
        )
      }
}

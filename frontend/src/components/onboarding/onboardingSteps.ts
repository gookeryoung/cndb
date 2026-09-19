/** 新手引导步骤定义 — 纯数据 + 纯函数，便于单测.
 *
 * 单 Tour 策略：引导在进入 GridPage 后触发（MainLayout 同屏可高亮
 * Header / Sider / GridPage 工具栏的全部核心元素）。
 * 目标元素不存在时 driver.js 自动降级为居中展示，
 * 因此 description 使用条件式文案兜底。
 */

/** 引导步骤锚点（data-testid 选择器） */
export const TOUR_SELECTORS = {
  workspaceSwitch: '[data-testid="ws-switch-btn"]',
  siderTables: '[data-testid="sider-tables"]',
  addRow: '[data-testid="add-row-btn"]',
  viewModeSwitch: '[data-testid="view-mode-switch"]',
  tableSettings: '[data-testid="table-settings-btn"]',
  importExport: '[data-testid="import-export-btn"]',
  helpBtn: '[data-testid="help-btn"]',
} as const

/** driver.js 步骤形状（仅声明我们用到的字段，避免与库类型强耦合） */
export interface TourStep {
  element?: string
  popover: {
    title: string
    description: string
  }
}

/** 构建引导步骤列表（纯函数；接受可选的覆盖便于测试） */
export function buildSteps(): TourStep[] {
  return [
    {
      // 无 element → 居中弹窗
      popover: {
        title: '欢迎使用 cndb',
        description: 'cndb 是一个表格数据库：用「工作区」组织数据，用「数据表」存储管理，用「视图」多角度看同一份数据。花一分钟了解界面核心功能。',
      },
    },
    {
      element: TOUR_SELECTORS.workspaceSwitch,
      popover: {
        title: '切换工作区',
        description: '点击左上角的下拉框可以切换或进入工作区。「报表」「工作区设置」等按钮都作用于这里选中的工作区。',
      },
    },
    {
      element: TOUR_SELECTORS.siderTables,
      popover: {
        title: '数据表导航',
        description: '左侧列出当前工作区的所有数据表，点击即可切换。若这里还是空的，请先到工作区的「数据表」页面创建或导入一张表。',
      },
    },
    {
      element: TOUR_SELECTORS.addRow,
      popover: {
        title: '新增一行',
        description: '在表格末尾添加一条空记录，逐格填写后回车保存。也可以通过「导入 / 导出」批量导入数据。',
      },
    },
    {
      element: TOUR_SELECTORS.viewModeSwitch,
      popover: {
        title: '切换视图',
        description: '同一份数据可用表格、看板、日历、画廊、甘特图等多种方式查看。若这里只有一个表格视图，可点击视图栏左侧的 + 新建其他类型视图。',
      },
    },
    {
      element: TOUR_SELECTORS.tableSettings,
      popover: {
        title: '表设置',
        description: '管理这张表的字段结构、视图列表和权限授权。字段类型（如日期、单选、关联）都在这里定义。',
      },
    },
    {
      element: TOUR_SELECTORS.importExport,
      popover: {
        title: '导入 / 导出数据',
        description: '支持 CSV、Excel、JSON 的导入与导出；导入时可按匹配键更新已有数据（upsert），不用手动重复录入。',
      },
    },
    {
      element: TOUR_SELECTORS.helpBtn,
      popover: {
        title: '随时查看帮助',
        description: '右上角的问号按钮打开帮助中心：快速上手、视图说明、权限角色、常见问题都在里面。完成本引导后也可从这里重新播放。',
      },
    },
  ]
}

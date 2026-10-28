/** 浅色主题：modern / github-light / minimal / ocean / forest / sepia / sakura */

import type { ThemeConfig } from 'antd'

import { commonFont, switchTokens } from './common'

/** 现代（默认浅色） */
export const modernTheme: ThemeConfig = {
  token: {
    colorPrimary: '#3b82f6',
    borderRadius: 6,
    colorBgBase: '#ffffff',
    colorTextBase: '#1f2937',
    colorBorder: '#d1d5db',
    colorBorderSecondary: '#d1d5db',
    colorSplit: '#d1d5db',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#f5f7fa',
      headerHeight: 44,
    },
  },
}

/** GitHub Light */
export const githubLightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0969da',
    borderRadius: 6,
    colorBgBase: '#ffffff',
    colorTextBase: '#1f2328',
    colorBgContainer: '#f6f8fa',
    colorBgElevated: '#ffffff',
    colorBorder: '#d0d7de',
    colorBorderSecondary: '#d0d7de',
    colorSplit: '#d0d7de',
    colorTextSecondary: '#59636e',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f6f8fa',
      defaultColor: '#1f2328',
      defaultBorderColor: '#d0d7de',
      defaultHoverBg: '#d0d7de',
    },
    Table: {
      headerBg: '#f6f8fa',
      headerColor: '#59636e',
      rowHoverBg: '#f6f8fa',
      rowSelectedBg: '#ddf4ff',
      borderColor: '#d0d7de',
      headerBorderRadius: 0,
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#f6f8fa',
      bodyBg: '#ffffff',
      headerHeight: 44,
    },
  },
}

/** 极简 — 中性灰、无装饰 */
export const minimalTheme: ThemeConfig = {
  token: {
    colorPrimary: '#525252',
    borderRadius: 2,
    colorBgBase: '#fafafa',
    colorTextBase: '#262626',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#d4d4d4',
    colorBorderSecondary: '#d4d4d4',
    colorSplit: '#d4d4d4',
    colorTextSecondary: '#737373',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#ffffff',
      defaultColor: '#262626',
      defaultBorderColor: '#d4d4d4',
      defaultHoverBg: '#f5f5f5',
    },
    Table: {
      headerBg: '#fafafa',
      headerColor: '#737373',
      rowHoverBg: '#f5f5f5',
      rowSelectedBg: '#f0f0f0',
      borderColor: '#d4d4d4',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#d4d4d4',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#fafafa',
      headerHeight: 44,
    },
  },
}

/** 海洋 — 青蓝清爽浅色系 */
export const oceanTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0891b2',
    borderRadius: 8,
    colorBgBase: '#ffffff',
    colorTextBase: '#0f3a45',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#cfe2e8',
    colorBorderSecondary: '#cfe2e8',
    colorSplit: '#cfe2e8',
    colorTextSecondary: '#5b7c88',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f0f8fa',
      defaultColor: '#0f3a45',
      defaultBorderColor: '#cfe2e8',
      defaultHoverBg: '#e0f0f5',
    },
    Table: {
      headerBg: '#eef7f9',
      headerColor: '#5b7c88',
      rowHoverBg: '#f0f8fa',
      rowSelectedBg: '#d5f0f6',
      borderColor: '#cfe2e8',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#cfe2e8',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#eef7f9',
      bodyBg: '#f0f8fa',
      headerHeight: 44,
    },
  },
}

/** 森野 — 翠绿自然浅色系 */
export const forestTheme: ThemeConfig = {
  token: {
    colorPrimary: '#16a34a',
    borderRadius: 8,
    colorBgBase: '#ffffff',
    colorTextBase: '#14301b',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#d3e4d5',
    colorBorderSecondary: '#d3e4d5',
    colorSplit: '#d3e4d5',
    colorTextSecondary: '#5c7560',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f3f8f4',
      defaultColor: '#14301b',
      defaultBorderColor: '#d3e4d5',
      defaultHoverBg: '#e6f2e9',
    },
    Table: {
      headerBg: '#eef6ef',
      headerColor: '#5c7560',
      rowHoverBg: '#f3f8f4',
      rowSelectedBg: '#d8f0de',
      borderColor: '#d3e4d5',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#d3e4d5',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#eef6ef',
      bodyBg: '#f2f7f3',
      headerHeight: 44,
    },
  },
}

/** 纸感 — 米黄纸调，温润护眼 */
export const sepiaTheme: ThemeConfig = {
  token: {
    colorPrimary: '#a16207',
    borderRadius: 4,
    colorBgBase: '#fbf6ea',
    colorTextBase: '#43341f',
    colorBgContainer: '#fbf6ea',
    colorBgElevated: '#fffdf7',
    colorBorder: '#ddcfae',
    colorBorderSecondary: '#ddcfae',
    colorSplit: '#ddcfae',
    colorTextSecondary: '#7a6a4d',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#f3ecd9',
      defaultColor: '#43341f',
      defaultBorderColor: '#ddcfae',
      defaultHoverBg: '#ebe0c6',
    },
    Table: {
      headerBg: '#f3ecd9',
      headerColor: '#7a6a4d',
      rowHoverBg: '#f6f0e0',
      rowSelectedBg: '#efe4c8',
      borderColor: '#ddcfae',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#ddcfae',
    },
    Input: {
      colorBgContainer: '#fffdf7',
    },
    Select: {
      colorBgContainer: '#fffdf7',
    },
    Layout: {
      headerBg: '#fbf6ea',
      siderBg: '#f3ecd9',
      bodyBg: '#efe7d2',
      headerHeight: 44,
    },
  },
}

/** 樱粉 — 柔和粉色，轻盈亲和 */
export const sakuraTheme: ThemeConfig = {
  token: {
    colorPrimary: '#db2777',
    borderRadius: 10,
    colorBgBase: '#ffffff',
    colorTextBase: '#3d2230',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#f2d9e5',
    colorBorderSecondary: '#f2d9e5',
    colorSplit: '#f2d9e5',
    colorTextSecondary: '#92708a',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#fdf3f8',
      defaultColor: '#3d2230',
      defaultBorderColor: '#f2d9e5',
      defaultHoverBg: '#fae7f1',
    },
    Table: {
      headerBg: '#fceff6',
      headerColor: '#92708a',
      rowHoverBg: '#fdf3f8',
      rowSelectedBg: '#f8dceb',
      borderColor: '#f2d9e5',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#f2d9e5',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fceff6',
      bodyBg: '#fdf5f9',
      headerHeight: 44,
    },
  },
}

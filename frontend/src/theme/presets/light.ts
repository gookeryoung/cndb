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
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#f5f7fa',
      headerHeight: 52,
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
      headerHeight: 52,
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
    colorBorderSecondary: '#e5e5e5',
    colorSplit: '#e5e5e5',
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
      borderColor: '#e5e5e5',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e5e5e5',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#fafafa',
      headerHeight: 52,
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
    colorBorderSecondary: '#e3eef2',
    colorSplit: '#e3eef2',
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
      borderColor: '#dcebf0',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e3eef2',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#eef7f9',
      bodyBg: '#f0f8fa',
      headerHeight: 52,
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
    colorBorderSecondary: '#e7f0e8',
    colorSplit: '#e7f0e8',
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
      borderColor: '#e0ece2',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e7f0e8',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#eef6ef',
      bodyBg: '#f2f7f3',
      headerHeight: 52,
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
    colorBorderSecondary: '#e8dec6',
    colorSplit: '#e8dec6',
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
      borderColor: '#e3d8bd',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#e8dec6',
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
      headerHeight: 52,
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
    colorBorderSecondary: '#f8e7ef',
    colorSplit: '#f8e7ef',
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
      borderColor: '#f5e0eb',
      headerBorderRadius: 0,
    },
    Card: {
      colorBorderSecondary: '#f8e7ef',
    },
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fceff6',
      bodyBg: '#fdf5f9',
      headerHeight: 52,
    },
  },
}

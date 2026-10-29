/** 深色主题：github-dark / midnight / oled */

import type { ThemeConfig } from 'antd'

import { commonFont, switchTokens } from './common'

/** GitHub Dark — 颜色完全对齐 Primer 深色主题 */
export const githubDarkTheme: ThemeConfig = {
  token: {
    colorPrimary: '#58a6ff',
    borderRadius: 6,
    colorBgBase: '#0d1117',
    colorTextBase: '#e6edf3',
    colorBgContainer: '#161b22',
    colorBgElevated: '#21262d',
    colorBorder: '#8b949e',
    colorBorderSecondary: '#21262d',
    colorSplit: '#21262d',
    colorTextSecondary: '#8b949e',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#21262d',
      defaultColor: '#e6edf3',
      defaultBorderColor: '#8b949e',
      defaultHoverBg: '#3d444d',
    },
    Card: {
      colorBorderSecondary: '#3d444d',
    },
    Table: {
      headerBg: '#0d1117',
      headerColor: '#8b949e',
      headerSortActiveBg: '#0d1117',
      headerSortHoverBg: '#161b22',
      rowHoverBg: '#161b22',
      rowSelectedBg: '#1f2937',
      borderColor: '#8b949e',
      headerBorderRadius: 0,
    },
    Modal: {
      contentBg: '#161b22',
      headerBg: '#161b22',
    },
    Input: {
      colorBgContainer: '#0d1117',
      activeBorderColor: '#58a6ff',
      hoverBorderColor: '#8b949e',
    },
    Select: {
      colorBgContainer: '#0d1117',
      optionSelectedBg: '#1f2937',
    },
    Layout: {
      headerBg: '#0d1117',
      siderBg: '#0d1117',
      bodyBg: '#010409',
      headerHeight: 44,
    },
  },
}

/** 午夜紫 — 深紫夜色，沉浸低扰 */
export const midnightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#a78bfa',
    borderRadius: 6,
    colorBgBase: '#15121f',
    colorTextBase: '#e9e4f5',
    colorBgContainer: '#1d1830',
    colorBgElevated: '#26203a',
    colorBorder: '#383150',
    colorBorderSecondary: '#383150',
    colorSplit: '#2a2440',
    colorTextSecondary: '#a299c2',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#26203a',
      defaultColor: '#e9e4f5',
      defaultBorderColor: '#383150',
      defaultHoverBg: '#332b52',
    },
    Card: {
      colorBorderSecondary: '#383150',
    },
    Table: {
      headerBg: '#15121f',
      headerColor: '#a299c2',
      headerSortActiveBg: '#15121f',
      headerSortHoverBg: '#1d1830',
      rowHoverBg: '#1d1830',
      rowSelectedBg: '#332a55',
      borderColor: '#383150',
      headerBorderRadius: 0,
    },
    Modal: {
      contentBg: '#1d1830',
      headerBg: '#1d1830',
    },
    Input: {
      colorBgContainer: '#15121f',
      activeBorderColor: '#a78bfa',
      hoverBorderColor: '#383150',
    },
    Select: {
      colorBgContainer: '#15121f',
      optionSelectedBg: '#332a55',
    },
    Layout: {
      headerBg: '#15121f',
      siderBg: '#15121f',
      bodyBg: '#100d1a',
      headerHeight: 44,
    },
  },
}

/** 极夜黑 — 纯黑高对比，AMOLED 友好 */
export const oledTheme: ThemeConfig = {
  token: {
    colorPrimary: '#22d3ee',
    borderRadius: 6,
    colorBgBase: '#000000',
    colorTextBase: '#f5f5f5',
    colorBgContainer: '#0a0a0a',
    colorBgElevated: '#161616',
    colorBorder: '#262626',
    colorBorderSecondary: '#262626',
    colorSplit: '#1a1a1a',
    colorTextSecondary: '#a3a3a3',
    fontFamily: commonFont,
  },
  components: {
    Switch: switchTokens,
    Button: {
      defaultBg: '#161616',
      defaultColor: '#f5f5f5',
      defaultBorderColor: '#2a2a2a',
      defaultHoverBg: '#262626',
    },
    Card: {
      colorBorderSecondary: '#262626',
    },
    Table: {
      headerBg: '#000000',
      headerColor: '#a3a3a3',
      headerSortActiveBg: '#000000',
      headerSortHoverBg: '#0a0a0a',
      rowHoverBg: '#141414',
      rowSelectedBg: '#1f1f1f',
      borderColor: '#262626',
      headerBorderRadius: 0,
    },
    Modal: {
      contentBg: '#0a0a0a',
      headerBg: '#0a0a0a',
    },
    Input: {
      colorBgContainer: '#000000',
      activeBorderColor: '#22d3ee',
      hoverBorderColor: '#262626',
    },
    Select: {
      colorBgContainer: '#000000',
      optionSelectedBg: '#1f1f1f',
    },
    Layout: {
      headerBg: '#000000',
      siderBg: '#000000',
      bodyBg: '#000000',
      headerHeight: 44,
    },
  },
}

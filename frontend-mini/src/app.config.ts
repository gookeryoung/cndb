/** 微信小程序全局配置 —— 严格遵循微信 app.json schema. */
export default defineAppConfig({
  pages: [
    'pages/login/index',
    'pages/workspaces/index',
    'pages/tables/[wid]/index',
    'pages/grid/[wid]/[tid]/index',
    'pages/record/[wid]/[tid]/[rid]/index',
    'pages/record/new/[wid]/[tid]/index',
    'pages/me/index',
  ],

  tabBar: {
    color: '#6b7280',
    selectedColor: '#1677ff',
    backgroundColor: '#ffffff',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'pages/workspaces/index',
        text: '工作区',
        iconPath: 'assets/tab/workspace.png',
        selectedIconPath: 'assets/tab/workspace-active.png',
      },
      {
        pagePath: 'pages/me/index',
        text: '我的',
        iconPath: 'assets/tab/me.png',
        selectedIconPath: 'assets/tab/me-active.png',
      },
    ],
  },

  window: {
    backgroundTextStyle: 'dark',
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTitleText: 'cndb',
    navigationBarTextStyle: 'black',
    backgroundColor: '#f5f5f5',
  },

  style: 'v2',
})

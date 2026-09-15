const path = require('path')

module.exports = function (merge) {
  const config = {
    projectName: 'cndb-mini',
    date: '2026-09-15',
    designWidth: 750,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      828: 1.81 / 2,
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: [],
    defineConstants: {},
    copy: { patterns: [], options: {} },
    framework: 'react',
    compiler: 'webpack5',
    cache: { enable: false },

    // 路径别名 —— 让 webpack 识别 @/*
    alias: {
      '@': path.resolve(__dirname, '..', 'src'),
    },

    mini: {
      postcss: {
        pxtransform: { enable: true, config: {} },
        url: { enable: true, config: { limit: 1024 } },
        cssModules: { enable: false },
      },
      optimizeMainPackage: { enable: true },
      minimize: true,
    },

    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      postcss: {
        autoprefixer: { enable: true },
        cssModules: { enable: false },
      },
    },
  }

  if (process.env.NODE_ENV === 'development') {
    return merge({}, config, require('./dev'))
  }
  return merge({}, config, require('./prod'))
}

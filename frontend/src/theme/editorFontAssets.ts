/** 编辑器可选等宽字体的本地资产（离线部署，不引 CDN）.
 *
 * 只被「个人设置 → 编辑器」与 CodeMirror 编辑器 chunk 引用，不进入 main.tsx：
 * 新增等宽字体各带完整 latin 字形，若塞进首屏会突破 ADR 0116 的入口字体预算。
 * 浏览器只会真正下载当前 `font-family` 命中的那一份 @font-face 资源。
 */

import '@fontsource/cascadia-code/latin-400.css'
import '@fontsource/maple-mono/latin-400.css'

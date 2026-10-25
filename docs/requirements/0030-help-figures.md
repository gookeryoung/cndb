# 需求卡片：帮助文档增加图示例（后台定期生成，避免代码更新后过期）

- 编号：0030（与 ADR `docs/adr/0030-help-figures.md` 同号）
- 来源 / 提出人：用户
- 日期：2026-10-25
- 关联 ADR：`docs/adr/0030-help-figures.md`

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 请为帮助文档增加更多的图示例，最好支持后台定期实时生成，避免软件代码更新后过期。

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 增加更多的图示例 | 帮助文档正文从「纯文字」升级为「图文」：快速入门、教程、典型示例、系统配置四部分都要有图；每张图有标题与图注，图能独立看懂 | `frontend/src/pages/help/`、`src/cndb/plugins/help/` | 组件测试：各主题渲染出对应的 figure testid；导航内每个主题至少一张图或明确不需要图 |
| C2 | 图示例 | 图必须是**可判读的结构 / 流程 / 数据预览图**，不是装饰插图：结构图（工作区）、流程图（上手五步 / 导入）、枚举清单图（字段类型 / 权限 / 调度模式）、真实数据预览表 | `src/cndb/plugins/help/services/figures/builders.py` | 构建器测试：字段类型图覆盖注册表全部 label、示例预览含真实 CSV 行数 |
| C3 | 支持后台定期生成 | 提供后台线程按周期重建图示快照，周期可配置（环境变量），关闭后不影响读路径 | `src/cndb/plugins/help/services/figures/store.py`、`src/cndb/app.py`、`src/cndb/core/config.py` | 单测：线程可 start / stop 幂等；`HELP_FIGURES_ENABLED=False` 时不启动 |
| C4 | 实时生成 | 图示内容变化必须**在下次访问时立即生效**（不依赖定时轮次）：请求期比对指纹，不一致就重建 | `store.py`、`registry.py` | 单测：改 CSV 后首次 `get` 即返回新内容且指纹变化 |
| C5 | 避免软件代码更新后过期 | 图的真相源必须是代码 / 数据本身（字段类型注册表、权限枚举、调度枚举、示例 CSV），不得手抄一份；构建代码改动同样要触发重建 | `builders.py`、`registry.py` | 单测：注册表 / 枚举 / CSV 任一变化 → 指纹变化；构建函数源码变化 → 指纹变化 |
| C6 | （需求澄清）图的形式 | 服务端生成 **SVG 文本**并快照落盘；前端内联渲染（不是截图、不是图片二进制），颜色走 `--cn-*` 设计令牌，浅色 / 暗色主题都成立 | `builders.py`、`frontend/src/pages/help/HelpFigure.tsx`、`frontend/src/index.css` | 单测：接口 `Content-Type: image/svg+xml`；组件测试：内联 SVG 节点存在 |
| C7 | （需求澄清）访问范围与降级 | 图示接口仅登录用户可用；单张图失败不影响正文（降级为一行提示），不阻塞帮助页其余内容 | `routers/figures.py`、`HelpFigure.tsx` | 接口 401 用例；组件失败 / 未知 key 降级用例 |

约束编号在 ADR 中原样引用；不重编号、不合并。

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 帮助正文全部为纯文字（`Typography` + `Table`） | `frontend/src/pages/help/content/*.tsx` | 需插入图示例 |
| 2 | 字段类型说明写死「共 16 种」，与注册表 19 种不一致 | `content/tutorials.tsx` | 已过期的典型：改为图驱动 |
| 3 | 帮助只有示例清单 / CSV 下载两个接口 | `src/cndb/plugins/help/routers/` | 新增图示清单与 SVG 端点 |
| 4 | 无缓存目录约定 | `settings.CACHE_DIR` | 快照放 `CACHE_DIR/help-figures` |
| 5 | 已有后台线程范式 | `src/cndb/core/storage_refresh.py` | 图示线程同款线程模型 |
| 6 | 示例数据源 | `examples/datasets`、`plugins/help/services/assets.py` | 预览图直接读真实 CSV |
| 7 | 字段类型 / 角色 / 调度模式的真相源 | `tables/field_types/default_registry`、`workspaces.models`、`datasource.models` | 图示数据来源 |
| 8 | `/help` 页面结构与懒加载体积预算 | `frontend/src/pages/help/HelpDocsPage.tsx`、`frontend/scripts/bundle-budget.json` | 图示不引入新依赖，不影响预算 |

## 未决问题

- 无。已确认：图用服务端生成的 SVG（可 diff、可随主题变色、体积小），不用浏览器截图；定期重建 + 请求期即时重建两者都做。

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

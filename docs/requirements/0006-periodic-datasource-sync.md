# 需求卡片：周期性外部数据同步与数据分析

- 编号：0006（与 ADR `docs/adr/0006-periodic-datasource-sync.md` 同号）
- 来源 / 提出人：项目负责人（工作区需求）
- 日期：2026-10-20
- 关联 ADR：[ADR 0006](../adr/0006-periodic-datasource-sync.md)

> 本卡片是**需求原文与约束编号的唯一副本**：ADR 只引用 C1..Cn，不复制原文；需求澄清后先改这里，再同步 ADR「口径」表。

## 需求原句（逐字）

> 按开发流程推进周期性外部数据同步与数据分析方案落地。

> 方案目标（立项原句，2026-10-20 提出，唯一副本）：
> 「在工作区内提供通用的『定期拉取外部数据 → 规范化 / 幂等同步进数据表 → 面向时序的分析可视化』能力。股票日线、天气、新闻日报等均作为该框架的场景实例，而非专门功能。」

## 可实施约束（C1..Cn）

| # | 需求句（原文片段） | 可实施约束 | 涉及模块 | 验收方式 |
|---|---|---|---|---|
| C1 | 定期拉取外部数据 | 同步任务可持久化调度（`daily@HH:MM` / `interval` / `cron`），进程内调度器与 CLI `cndb sync run` 共用同一 tick 入口，靠 DB 租约保证同一任务单飞 | `plugins/datasource`、`cli/sync.py` | 单测：到期判定 / 租约互斥 / 退避；集成：连续两轮只执行一次 |
| C2 | 规范化 / 幂等同步进数据表 | 落库统一走 `Normalizer`（字段映射 + 类型归一）→ `Importer` 按 job 级 `match_keys` upsert；目标为 tables 动态表；重复运行不产生重复行 | `plugins/datasource/services/`、`plugins/tables` | 单测：同批重复行 / 跨轮重复运行；集成：二次运行 `updated` 计数而非 `inserted` |
| C3 | 面向时序的分析可视化 | 公式引擎支持分区 + 排序窗口函数（`prev/lag/lead`、`ma`、`rolling_*`、`cumsum`、`rank`、`pct_change`、`diff`）+ 通用分析模板（趋势 / 分布 / 占比 / 比率 / 概览） | `plugins/analytics`、`frontend/src/pages/analytics` | 单测：窗口函数数值与空值边界；e2e：同步数据一键套模板出图 |
| C4 | 通用：股票 / 天气 / 新闻只是场景实例 | 调度 / 游标 / 分页 / 幂等 / 重试代码内不出现 symbol、city、stock 等领域词；领域差异只落在 Provider 配置 | `plugins/datasource` | 代码审查 + 单测用「城市气温」假源覆盖同一管线 |
| C5 | 声明式优先、适配器兜底 | `http_json` provider 支持请求模板（占位符 / 分页 / 时间分片）+ 解析路径 + 字段映射，零代码接入；特殊格式由 `SourceProvider` 子类封装并注册进 `PROVIDERS` | `plugins/datasource/providers/` | 单测：模板求值（缺参 / 转义）、分页终止、分片边界；集成：假 JSON 源接入 |

## 现状影响面（候选，待 ADR 核实）

| # | 疑似受影响能力 | 候选位置 | 备注 |
|---|---|---|---|
| 1 | 插件装载机制 | `src/cndb/core/plugin_registry.py:61` | 新插件按目录自动发现，无需改装载器 |
| 2 | HTTP 抓取内核（SSRF / 重试 / 编码 / 处理器注册表） | `src/cndb/plugins/tables/services/importing/api_fetch.py:467` | 缺请求模板化、分页、时间分片 |
| 3 | 幂等 upsert | `src/cndb/plugins/tables/services/importing/importer.py:167`、`.../core/records.py:855` | `match_keys` 需由任务级配置传入 |
| 4 | 自动建表 | `src/cndb/plugins/tables/services/transfer/table_create.py:403` | 不支持复合唯一索引，需明确幂等口径 |
| 5 | 后台任务 | `src/cndb/plugins/tables/services/importing/import_tasks.py:611` | 一次性导入，无持久化任务定义 |
| 6 | 统一事件流 | `src/cndb/core/events.py:105` | 新增 `datasource.*` 动作 |
| 7 | 公式引擎 | `src/cndb/plugins/analytics/services/formula.py:379` | 纯逐行求值，无分区排序上下文 |
| 8 | 工作区备份 | `src/cndb/plugins/workspaces/routers/workspaces.py:333`、`.../services/backup_io.py:79` | 新表需纳入导出 / 导入并升版本 |
| 9 | 前端入口 | `frontend/src/layouts/MainLayout.tsx:141` | 页签硬编码，需注册新页 |

## 未决问题

- [x] ~~调度形态选哪个~~ → ADR 0006 D3：CLI + cron 为生产默认，内置调度器供单机，共用租约互斥
- [x] ~~是否引入外部任务队列~~ → 否，见 D3 被否决项
- [x] ~~分析侧是否另建时序引擎~~ → 否，扩展公式引擎，见 D5

## 卡点

- [x] 每条需求句都有 C 编号约束（无遗漏、无「待定」）
- [x] 未决问题全部有结论，需求方确认

> 「决策记录表无待定」是 ADR 的卡点，不在本卡片判定。

# 用户文档地图

> 本文件只做映射：**功能 → 应用内帮助深链 → 需求 / ADR**。不复制帮助正文。
> 应用内地址 = 部署基址 + 下表的 `/help/...` 路径；正文以应用内帮助为唯一真相源（ADR 0036 I2）。
> 维护者术语见 [CONTEXT.md](../CONTEXT.md)；用户入口见 [README.md](../README.md#用户入口)。

## 上手与界面

| 功能 | 帮助路径 | 来源 |
|---|---|---|
| 十分钟上手（工作区 → 数据表 → 视图 → 文档） | `/help/quick-start/workflow` | ADR 0105 |
| 顶栏、页签、视图栏与常用入口 | `/help/quick-start/ui-tour` | ADR 0105 |
| 主页「我的工作区 / 我的团队 / 我的视图」 | `/help/quick-start/ui-tour#help-entries--home` | 0160、0162 |
| 默认落地页顺序 | `/help/configuration/personal#help-landing` | 0161 |

## 协作与权限

| 功能 | 帮助路径 | 来源 |
|---|---|---|
| 角色与视图可见性 | `/help/tutorials/roles` | ADR 0003、0047 |
| 团队与工作区的关系 | `/help/tutorials/teams-and-access#help-team-model` | 0153、0157 |
| 成员与角色（显式成员优先于团队授权） | `/help/tutorials/teams-and-access#help-members-and-roles` | 0153、0161 |
| 团队数据授权（只读 / 可编辑、有效期） | `/help/tutorials/teams-and-access#help-team-grant` | 0154、0163 |
| 私有工作区的可见范围 | `/help/tutorials/teams-and-access#help-private-visibility` | 0161 |
| 工作区链接的申请、批准、使用与到期 | `/help/tutorials/workspace-links#help-link-lifecycle` | 0154 |
| 链接表只读网格 | `/help/tutorials/workspace-links#help-readonly-grid` | 0154 |
| 跨工作区分析（union / join） | `/help/tutorials/workspace-links#help-cross-workspace-analytics` | 0158、0159 |
| 断链检测与修复 | `/help/tutorials/workspace-links#help-broken-links` | 0156 |

## 数据表与记录

| 功能 | 帮助路径 | 来源 |
|---|---|---|
| 视图类型与矩阵评分录入 | `/help/tutorials/view-types`、`/help/tutorials/view-config#help-choose` | 0136 |
| 表分组 | `/help/tutorials/table-organization#help-table-groups` | 0137 |
| 批量编辑 | `/help/tutorials/table-organization#help-bulk-edit` | 0149 |
| DDL 变更影响预估 | `/help/tutorials/table-organization#help-ddl-impact` | 0150 |
| 行回收站（恢复 / 清空） | `/help/tutorials/record-lifecycle#help-row-recycle-bin` | 0139 |
| 行历史与回滚 | `/help/tutorials/record-lifecycle#help-row-history` | 0144 |
| 并发冲突与写入幂等 | `/help/tutorials/record-lifecycle#help-concurrency` | 0140、0145 |
| 导入表头识别与预览 | `/help/tutorials/import-export` | 0018 |

## 文档与文件

| 功能 | 帮助路径 | 来源 |
|---|---|---|
| 文档树、编辑与版本回滚 | `/help/tutorials/documents#help-tree`、`#help-edit--versions` | ADR 0113、0125 |
| 多文件 / 纯文本导入、Obsidian 库导入 | `/help/tutorials/documents#help-import` | 0135、0138 |
| 上传 PDF / Office / 图片与格式图标 | `/help/tutorials/documents#help-upload` | 0025 |
| PPTX 异步高清预览 | `/help/tutorials/documents#help-pptx-pdf-preview` | 0129 |
| 内容模板与从模板新建（文档区页签「内容模板」；含内置库「科研项目管理」只读预设与另存为） | `/help/tutorials/documents#help-content-templates` | 0169、0177、0185 |
| 导出模板（文档区页签「导出模板」） | `/help/tutorials/documents#help-export-view--templates` | 0152、0177 |
| 本文档默认排版模板（单篇指定导出模板） | `/help/tutorials/documents#help-export-view--template-bind` | 0177 |
| 知识图谱（双链关系图） | `/help/tutorials/documents#help-graph` | 0168 |
| 创建副本 | `/help/tutorials/documents#help-duplicate` | 0172 |
| 附件管理与孤儿回收 | `/help/tutorials/documents#help-attachments` | 0174 |
| PDF / 图片方向与镜像纠偏 | `/help/tutorials/documents#help-export-view--rotation` | 0164 |
| 游客只读分享 | `/help/tutorials/documents#help-share` | 0017 |
| 敏感内容质量检查 | `/help/tutorials/quality-checks` | 0102 |

## 配置与排障

| 功能 | 帮助路径 | 来源 |
|---|---|---|
| 数据同步与对外推送 | `/help/configuration/datasource` | 0099 |
| 空间分配（后台快照） | `/help/configuration/admin#help-storage` | 0024 |
| 审计留存期与清理 | `/help/configuration/admin#help-events--retention` | 0143 |
| 系统备份与恢复 | `/help/configuration/admin#help-backup`、`#help-restore` | 0075 |
| 看不到工作区 / 团队授权归因 | `/help/troubleshooting/guide#help-permission--missing-table` | 0047、0163 |
| 链接过期 / 被撤销 | `/help/troubleshooting/guide#help-permission--link-expired` | 0154 |
| 误删行、保存冲突 | `/help/troubleshooting/guide#help-records` | 0139、0140 |
| PPTX 预览未切换 / 方向不对 | `/help/troubleshooting/guide#help-document--pdf-preview` | 0129、0164 |

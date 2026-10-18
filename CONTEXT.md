# Context

## Glossary

| Term | Meaning | Notes |
|---|---|---|
| 问题（Issue） | 数据表级反馈条目：任何工作区成员可提交（标题 + 描述 + 类别 data_error/suggestion/question/other），用于反馈数据错误、改进建议或提问；owner/editor（或创建者本人）可关闭/重开 | 评论与状态事件（created/closed/reopened）独立流水，详情页展示「谁在何时关闭/重开」 |
| 修改申请（ChangeRequest） | 数据表级变更载体：所有成员可发起（查看者编辑自动生成，owner/editor 可手动创建），含 op（create/update/delete）+ 行增量 values + 提交时基准快照 base_values；仅 owner/editor 可 merge（落库）/close/reopen | 区别于旧「变更单」：同行允许多个 open 申请并存，冲突按字段级基准漂移检测标记，处理时逐项 apply/skip 决策 |
| 双轨制写入 | owner/editor（且工作区 allow_edit 开启）编辑直编直存；viewer 或 allow_edit 关闭时编辑自动生成修改申请（后端返回 202 + change_request 载荷） | 分派逻辑在 records 写路径 `dispatch_change_request`；批量删除生成含多个 delete item 的单条申请 |
| 三区布局 | 工作区与数据表权限页的成员展示形态：所有者区（含转让入口）/ 编辑者区 / 查看者区，各自独立卡片与添加成员入口 | 门控收敛为 owner（工作区设置与成员管理仅 owner 可操作）；角色三级 owner/editor/viewer |
| 三入口 | 网格编辑的三个入口：单元格双击速编、行双击 Drawer 全行编辑、操作列整行编辑按钮 | viewer 在三入口保存均转修改申请，提示「已提交修改申请 #N，处理后生效」 |
| 编辑中标识 | 操作列中的行级修改申请状态位 | 派生自 change_requests 开放查询（status=open），按 row_id 聚合；merge 落库后同行其余 open 申请标记 stale，提交人可 update-base 刷新基准 |
| 文档种子 | `examples/datasets/<工作区>/documents/` 目录树：子目录 → 文档文件夹节点、`*.md` → Markdown 文档；文件头 `---` 元数据块声明 status/tags/author/summary，seed 入库前剥离 | 反面示例工作区（工作区-低质量数据）不提供 documents/，即不生成典型文档 |
| 数据表动态引用 | 文档正文中独占段落的占位符 `{{table:表名\|view=视图名\|limit=N}}`，前端渲染为实时数据表 | seed 阶段把符号表名/视图名解析为该工作区真实数字 ID（前端 `tableRef.ts` 只接受数字 ID） |
| 文档导出 | `GET /{wid}/documents/{doc_id}/export?format=md\|docx\|pdf`：把文档最新版本正文渲染为 Markdown / Word / PDF 文件下载 | 工作区成员即可导出；文件夹与非法格式返回 400；渲染器在 `documents/services/export/`（原 reports 插件的 docx/pdf 渲染器迁入，去掉主题与模板变量，改用默认视觉预设） |
| 文档修改申请（DocumentChangeRequest） | 文档级待审载体：viewer（或关闭直编的 editor）保存正文时自动生成（后端 202 + change_request 载荷），只存 `proposed_content` 待审全文、不写 `document_versions`；owner/editor 通过后落库为新版本，提交人可删除草稿 | 记录 `base_version_number` 作为内容基准，文档版本前进后其余 open 申请置 stale（需 `update-base` 刷新）；同文档可并存多个 open 申请，先合并者生效 |
| 文档双轨制写入 | 与数据表同源分派：owner 恒直编；editor 需工作区 `allow_edit` 开启；viewer 一律转修改申请（202） | 分派在 `documents/services/change_requests.resolve_write_mode`，保存端点 `PUT /{wid}/documents/{doc_id}/content`；文件夹不参与（409） |
| 文档区二级导航 | 进入 `/w/:wid/documents*` 时在工作区 Tabs 右侧以竖线分割渲染「文档」根入口 + 二级页签（修改申请 / 问题清单），形式与表级页签（`cn-table-crumb` / `cn-table-tab`）一致 | 页签路由 `/w/:wid/documents/change-requests`、`/w/:wid/documents/issues`；静态段优先于 `:docId`，编辑器页显示根入口但无子页激活 |
| 文档问题清单（DocumentIssue） | 文档级反馈条目：所有成员可提交（标题 + 描述 + 类别）与评论，owner/editor 或创建者可关闭/重开；随文档级联清理 | 表 `documents_issue` / `documents_issuecomment` / `documents_issueevent`，端点 `/{wid}/document-issues`；类别/状态取值与数据表问题清单一致 |
| 数据分析（Analytics） | 工作区级分析模块：分析模板（公式 + 图表 + 分组汇总配置，存后端）→ 受限公式引擎逐行派生指标 → 分组汇总（维度 × 聚合，可排序 Top N）与 ChartCard 可视化 | 页面 `/w/:wid/analytics`，支持 `?template=<id>` 深链；统计/数据/汇总可导出 CSV，图表可导出 PNG |
| 字段智能推荐（Analytics Recommendation） | 选表后按字段类型与抽样画像给出角色（metric/dimension/time/identifier/ignored）、基数、非空率、推荐公式/图表/分组汇总与典型示例 | 端点 `GET /{wid}/analytics/recommendations?table_id=`；只读成员即可用，取数复用行级权限与字段隐藏；结果确定性、一次抽样 1000 行 |
| 典型示例（Recommend Example） | 基于当前表字段动态生成的整套分析配置（分类对比 / 数值分布 / 占比构成 / 时间趋势 / 比率分析 / 数据概览），一键应用到编辑态 | 随推荐接口返回；每个示例的公式、图表、汇总均可直接通过模板配置校验并落库 |
| 分析列表（Analytics Manager） | 已保存分析的集中管理入口：列表展示、打开、复制（服务端默认「原名 副本」并重名递增）、删除、新建 | Drawer 入口在页面顶栏；复制端点 `POST /{wid}/analytics/templates/{id}/duplicate`，与保存/另存为共用未保存修改确认 |

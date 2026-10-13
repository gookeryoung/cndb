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

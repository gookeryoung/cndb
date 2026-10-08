# 数据导出范围（当前视图 / 全表）

## 需求来源

用户需求：完善导出功能，支持当前视图数据导出和全部数据导出，默认当前视图数据。对应能力由前端「更新/导出」对话框的导出 Tab 承载。

## 行为定义

- [x] 导出 Tab 提供范围开关，两个取值：
  - 按当前视图筛选导出（默认）：导出请求携带 `view_id`，后端按该视图的 `filters` / `sortings` / `filter_type` 过滤后导出；
  - 全表导出：不携带 `view_id`，忽略视图筛选。
- [x] 当前无激活视图（`viewId == null`）时不渲染范围开关，导出即全表。
- [x] 导出格式 json / csv / xlsx 三选一，与范围开关独立。

## 接口约定

- `GET /api/v1/workspaces/{wid}/tables/{tid}/export?format={json|csv|xlsx}&view_id={vid}`
  - `view_id` 可选；传入但不属于当前表时返回 404「视图不存在或不属于当前表」。
  - 实现见 `src/cndb/plugins/tables/routers/bulk.py` 的 `export_table`。
- 前端 API 客户端：`frontend/src/api/importExport.ts` 的 `exportApi.download(wid, tid, format, viewId?)`。

## 组件职责与数据流

- `GridPage.tsx`：持有激活视图状态（`activeViewId` / `activeView`），打开「更新/导出」对话框时把 `viewId` / `viewName` 传入 `ImportExportDialog`。
- `ImportExportDialog/index.tsx`：仅透传 `viewId` / `viewName` 给 `ExportPanel`。
- `ExportPanel.tsx`：内聚范围开关（默认开 = 按当前视图）、格式选择与 Blob 下载；文件名优先取后端 `Content-Disposition`（RFC 5987）。

## 测试覆盖

- GridPage 接线回归：`frontend/src/pages/grid/GridPage.importExportView.test.tsx`（有激活视图传 `viewId`/`viewName`；无激活视图传 null）。
- 对话框与导出面板行为：`frontend/src/pages/import-export/ImportExportDialog.test.tsx`（默认带 `view_id` 请求、下载成功/失败提示）。
- 后端视图过滤导出：`tests/` 下 export 相关用例覆盖 `view_id` 过滤语义。

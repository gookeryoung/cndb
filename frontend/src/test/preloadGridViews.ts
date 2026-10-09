/**
 * 预加载 GridPage 空闲预取的懒加载视图模块.
 *
 * GridPage 挂载后会在空闲时预取非 grid 视图 chunk；负载高时这些动态导入
 * 可能在测试环境销毁后才 resolve，触发偶发 EnvironmentTeardownError。
 * 在测试的 beforeAll 中调用本函数，把模块预先加载为已缓存模块，
 * 使预取变为同步 no-op，消除竞态。
 */
export async function preloadGridViews(): Promise<void> {
    await Promise.all([
        import('@/pages/grid/views/KanbanView'),
        import('@/pages/grid/views/CalendarView'),
        import('@/pages/grid/views/GanttView'),
        import('@/pages/grid/views/WbsView'),
        import('@/pages/grid/views/MatrixView'),
    ])
}

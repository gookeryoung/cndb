/* 主应用脚本：工作区 → 表 → 视图 → Grid/看板/日历（只读渲染 + 分页） */

"use strict";

const state = {
  workspaces: [],
  workspaceId: null,
  tables: [],
  tableId: null,
  views: [],
  viewId: null,
  page: 1,
  pageSize: 50,
  rows: [],
  total: 0,
  calendarYear: new Date().getFullYear(),
  calendarMonth: new Date().getMonth() + 1,
};

const els = {
  workspaceSelect: document.getElementById("workspace-select"),
  tableList: document.getElementById("table-list"),
  viewTabs: document.getElementById("view-tabs"),
  rowStats: document.getElementById("row-stats"),
  gridStatus: document.getElementById("grid-status"),
  formHint: document.getElementById("form-hint"),
  kanbanBoard: document.getElementById("kanban-board"),
  calendarView: document.getElementById("calendar-view"),
  calTitle: document.getElementById("cal-title"),
  calGrid: document.getElementById("cal-grid"),
  calPrev: document.getElementById("cal-prev"),
  calNext: document.getElementById("cal-next"),
  gridWrap: document.getElementById("grid-wrap"),
  gridHead: document.getElementById("grid-head"),
  gridBody: document.getElementById("grid-body"),
  pager: document.getElementById("pager"),
  pagePrev: document.getElementById("page-prev"),
  pageNext: document.getElementById("page-next"),
  pageInfo: document.getElementById("page-info"),
  logoutBtn: document.getElementById("logout-btn"),
};

/** 带 CSRF 的 API 请求封装：非 2xx 抛错（401 跳登录页） */
async function api(url, options = {}) {
  const headers = Object.assign({ "X-CSRFToken": getCookie("csrftoken") }, options.headers || {});
  const response = await fetch(url, Object.assign({ headers }, options));
  if (response.status === 401 || response.status === 403) {
    window.location.href = "/login/";
    throw new Error("未登录");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data && data.detail ? data.detail : `请求失败: ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[2]) : "";
}

/** 当前选中的表对象（含内嵌字段元数据） */
function currentTable() {
  return state.tables.find((t) => t.id === state.tableId) || null;
}

/** 当前选中的视图对象 */
function currentView() {
  return state.views.find((v) => v.id === state.viewId) || null;
}

/** 加载工作区列表并选中第一个 */
async function loadWorkspaces() {
  const data = await api("/api/workspaces/");
  state.workspaces = data.results || [];
  state.workspaceId = state.workspaces.length ? state.workspaces[0].id : null;
  renderWorkspaces();
  if (state.workspaceId) {
    await loadTables();
  } else {
    setStatus("暂无工作区，请先由管理员添加");
  }
}

/** 加载当前工作区的表列表并选中第一个 */
async function loadTables() {
  const data = await api(`/api/workspaces/${state.workspaceId}/tables/`);
  state.tables = data.results || [];
  state.tableId = state.tables.length ? state.tables[0].id : null;
  renderTables();
  if (state.tableId) {
    await loadViews();
  } else {
    state.views = [];
    state.viewId = null;
    renderViews();
    renderGrid();
  }
}

/** 加载当前表的视图列表并选中第一个 */
async function loadViews() {
  const data = await api(`/api/workspaces/${state.workspaceId}/tables/${state.tableId}/views/`);
  state.views = data.results || [];
  state.viewId = state.views.length ? state.views[0].id : null;
  state.page = 1;
  renderViews();
  if (state.viewId) {
    await loadRows();
  } else {
    state.rows = [];
    state.total = 0;
    renderGrid();
  }
}

/** 按当前视图规则加载行数据（grid 分页 / kanban 分桶 / calendar 月范围 / form 提示） */
async function loadRows() {
  const view = currentView();
  const viewType = view ? view.view_type : "grid";
  if (viewType === "kanban") {
    await loadKanban();
  } else if (viewType === "calendar") {
    await loadCalendar();
  } else if (viewType === "form") {
    state.rows = [];
    state.total = 0;
    renderGrid();
    renderFormHint(view);
  } else {
    const { workspaceId, tableId, viewId, page, pageSize } = state;
    const data = await api(`/api/workspaces/${workspaceId}/tables/${tableId}/views/${viewId}/rows/?page=${page}&page_size=${pageSize}`);
    state.rows = data.results || [];
    state.total = data.count;
    renderGrid();
  }
}

/** 看板：group_by 自动取第一个 single_select 字段，分桶渲染 */
async function loadKanban() {
  const table = currentTable();
  const selectField = table
    ? table.fields.find((f) => f.field_type === "single_select" && !f.trashed)
    : null;
  if (!selectField) {
    showPanels("kanban");
    els.kanbanBoard.innerHTML = "";
    setStatus("看板需要单选字段，当前表暂无");
    return;
  }
  const { workspaceId, tableId, viewId } = state;
  const data = await api(
    `/api/workspaces/${workspaceId}/tables/${tableId}/views/${viewId}/kanban/?group_by=${encodeURIComponent(selectField.name)}&per_group=50`
  );
  showPanels("kanban");
  els.kanbanBoard.innerHTML = "";
  const columns = [...data.groups, data.ungrouped];
  for (const group of columns) {
    const column = document.createElement("div");
    column.className = "kanban-column";
    const head = document.createElement("div");
    head.className = "kanban-column-head";
    head.textContent = `${group.value || "未分组"}（${group.count}）`;
    column.appendChild(head);
    for (const row of group.rows) {
      const card = document.createElement("div");
      card.className = "kanban-card";
      card.textContent = rowSummary(table, row, selectField.name);
      column.appendChild(card);
    }
    els.kanbanBoard.appendChild(column);
  }
  setStatus("");
}

/** 行摘要：取第一个非分组文本字段值作卡片标题 */
function rowSummary(table, row, excludeName) {
  const fields = table
    ? table.fields.filter((f) => !f.trashed && f.name !== excludeName).sort((a, b) => a.order - b.order)
    : [];
  for (const field of fields) {
    const value = row[field.name];
    if (value !== null && value !== undefined && String(value) !== "") {
      return String(value);
    }
  }
  return `#${row.id}`;
}

/** 日历：date_field 自动取第一个 date 字段，按当月范围加载 */
async function loadCalendar() {
  const table = currentTable();
  const dateField = table ? table.fields.find((f) => f.field_type === "date" && !f.trashed) : null;
  if (!dateField) {
    showPanels("calendar");
    els.calGrid.innerHTML = "";
    setStatus("日历需要日期字段，当前表暂无");
    return;
  }
  const { workspaceId, tableId, viewId, calendarYear, calendarMonth } = state;
  const start = `${calendarYear}-${String(calendarMonth).padStart(2, "0")}-01`;
  const endDate = new Date(calendarYear, calendarMonth, 0);
  const end = `${endDate.getFullYear()}-${String(endDate.getMonth() + 1).padStart(2, "0")}-${String(endDate.getDate()).padStart(2, "0")}`;
  const data = await api(
    `/api/workspaces/${workspaceId}/tables/${tableId}/views/${viewId}/calendar/?date_field=${encodeURIComponent(dateField.name)}&start=${start}&end=${end}`
  );
  renderCalendar(dateField.name, data.results || []);
}

/** 渲染月历：周一为首列，行事件挂到日期格 */
function renderCalendar(dateFieldName, rows) {
  showPanels("calendar");
  els.calTitle.textContent = `${state.calendarYear} 年 ${state.calendarMonth} 月`;
  els.calGrid.innerHTML = "";
  const weekHead = ["一", "二", "三", "四", "五", "六", "日"];
  for (const day of weekHead) {
    const head = document.createElement("div");
    head.className = "cal-head";
    head.textContent = day;
    els.calGrid.appendChild(head);
  }
  const byDate = {};
  for (const row of rows) {
    const value = row[dateFieldName];
    if (!value) continue;
    (byDate[value] = byDate[value] || []).push(row);
  }
  const firstDay = new Date(state.calendarYear, state.calendarMonth - 1, 1);
  const leading = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(state.calendarYear, state.calendarMonth, 0).getDate();
  for (let i = 0; i < leading; i++) {
    els.calGrid.appendChild(document.createElement("div"));
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const cell = document.createElement("div");
    cell.className = "cal-cell";
    const label = document.createElement("div");
    label.className = "cal-day";
    label.textContent = day;
    cell.appendChild(label);
    const key = `${state.calendarYear}-${String(state.calendarMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    for (const row of byDate[key] || []) {
      const event = document.createElement("div");
      event.className = "cal-event";
      event.textContent = rowSummary(currentTable(), row, dateFieldName);
      cell.appendChild(event);
    }
    els.calGrid.appendChild(cell);
  }
  setStatus("");
}

/** 表单视图提示：展示公开链接（仅已公开时） */
function renderFormHint(view) {
  showPanels("form");
  els.formHint.innerHTML = "";
  if (view.public && view.slug) {
    const text = document.createElement("span");
    text.textContent = "公开链接：";
    const link = document.createElement("a");
    link.href = `/forms/${view.slug}/`;
    link.target = "_blank";
    link.textContent = `${location.origin}/forms/${view.slug}/`;
    els.formHint.append(text, link);
  } else {
    els.formHint.textContent = "表单未公开，开启公开后可分享链接";
  }
}

/** 按视图类型切换内容面板与分页可见性 */
function showPanels(viewType) {
  els.gridWrap.hidden = viewType !== "grid";
  els.kanbanBoard.hidden = viewType !== "kanban";
  els.calendarView.hidden = viewType !== "calendar";
  els.formHint.hidden = viewType !== "form";
  els.pager.hidden = viewType !== "grid";
}

function setStatus(message) {
  els.gridStatus.textContent = message;
}

function renderWorkspaces() {
  els.workspaceSelect.innerHTML = "";
  for (const ws of state.workspaces) {
    const option = document.createElement("option");
    option.value = ws.id;
    option.textContent = ws.name;
    option.selected = ws.id === state.workspaceId;
    els.workspaceSelect.appendChild(option);
  }
}

function renderTables() {
  els.tableList.innerHTML = "";
  for (const table of state.tables) {
    const item = document.createElement("li");
    item.textContent = table.name;
    item.classList.toggle("active", table.id === state.tableId);
    item.addEventListener("click", async () => {
      if (state.tableId === table.id) return;
      state.tableId = table.id;
      state.page = 1;
      renderTables();
      await loadViews();
    });
    els.tableList.appendChild(item);
  }
}

function renderViews() {
  els.viewTabs.innerHTML = "";
  for (const view of state.views) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "view-tab" + (view.id === state.viewId ? " active" : "");
    tab.textContent = view.name;
    tab.addEventListener("click", async () => {
      if (state.viewId === view.id) return;
      state.viewId = view.id;
      state.page = 1;
      renderViews();
      await loadRows();
    });
    els.viewTabs.appendChild(tab);
  }
}

/** 渲染 Grid：表头取未隐藏字段，行按字段名取值 */
function renderGrid() {
  const table = currentTable();
  const view = currentView();
  showPanels(view && view.view_type !== "grid" ? "" : "grid");
  els.gridHead.innerHTML = "";
  els.gridBody.innerHTML = "";

  const fields = table ? table.fields.filter((f) => !f.trashed) : [];
  const options = view ? view.field_options || {} : {};
  const visible = fields
    .filter((f) => !(options[f.name] && options[f.name].hidden))
    .sort((a, b) => a.order - b.order);

  const idHead = document.createElement("th");
  idHead.textContent = "#";
  els.gridHead.appendChild(idHead);
  for (const field of visible) {
    const th = document.createElement("th");
    th.textContent = field.name;
    if (options[field.name] && options[field.name].width) {
      th.style.minWidth = `${options[field.name].width}px`;
    }
    els.gridHead.appendChild(th);
  }

  for (const row of state.rows) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    idCell.textContent = row.id;
    tr.appendChild(idCell);
    for (const field of visible) {
      const td = document.createElement("td");
      const value = row[field.name];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    }
    els.gridBody.appendChild(tr);
  }

  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  els.rowStats.textContent = state.total ? `共 ${state.total} 行` : "";
  els.pageInfo.textContent = `第 ${state.page} / ${totalPages} 页`;
  els.pagePrev.disabled = state.page <= 1;
  els.pageNext.disabled = state.page >= totalPages;
  if (table && !state.views.length) setStatus("当前表暂无视图");
  else setStatus("");
}

els.workspaceSelect.addEventListener("change", async () => {
  state.workspaceId = Number(els.workspaceSelect.value);
  state.page = 1;
  await loadTables();
});

els.pagePrev.addEventListener("click", async () => {
  if (state.page > 1) {
    state.page -= 1;
    await loadRows();
  }
});

els.pageNext.addEventListener("click", async () => {
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (state.page < totalPages) {
    state.page += 1;
    await loadRows();
  }
});

els.calPrev.addEventListener("click", async () => {
  shiftMonth(-1);
  await loadCalendar();
});

els.calNext.addEventListener("click", async () => {
  shiftMonth(1);
  await loadCalendar();
});

/** 日历月份切换（跨年回绕） */
function shiftMonth(delta) {
  state.calendarMonth += delta;
  if (state.calendarMonth < 1) {
    state.calendarMonth = 12;
    state.calendarYear -= 1;
  } else if (state.calendarMonth > 12) {
    state.calendarMonth = 1;
    state.calendarYear += 1;
  }
}

els.logoutBtn.addEventListener("click", async () => {
  await api("/api/auth/logout/", { method: "POST" });
  window.location.href = "/login/";
});

loadWorkspaces().catch((err) => setStatus(`加载失败: ${err.message}`));

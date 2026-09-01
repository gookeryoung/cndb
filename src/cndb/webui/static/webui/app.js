/* 主应用脚本：工作区 → 表 → 视图 → Grid 行数据（只读渲染 + 分页） */

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
};

const els = {
  workspaceSelect: document.getElementById("workspace-select"),
  tableList: document.getElementById("table-list"),
  viewTabs: document.getElementById("view-tabs"),
  rowStats: document.getElementById("row-stats"),
  gridStatus: document.getElementById("grid-status"),
  gridHead: document.getElementById("grid-head"),
  gridBody: document.getElementById("grid-body"),
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

/** 按当前视图规则读取行数据（分页） */
async function loadRows() {
  const { workspaceId, tableId, viewId, page, pageSize } = state;
  const data = await api(`/api/workspaces/${workspaceId}/tables/${tableId}/views/${viewId}/rows/?page=${page}&page_size=${pageSize}`);
  state.rows = data.results || [];
  state.total = data.count;
  renderGrid();
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

els.logoutBtn.addEventListener("click", async () => {
  await api("/api/auth/logout/", { method: "POST" });
  window.location.href = "/login/";
});

loadWorkspaces().catch((err) => setStatus(`加载失败: ${err.message}`));

/* 共享视图页脚本：匿名分页读取共享视图行数据 */

"use strict";

const state = { slug: document.body.dataset.slug, page: 1, pageSize: 50, total: 0 };
const fieldNames = Array.from(document.querySelectorAll("thead th")).slice(1).map((th) => th.textContent);
const body = document.getElementById("share-body");
const info = document.getElementById("share-info");
const prev = document.getElementById("share-prev");
const next = document.getElementById("share-next");

/** 拉取当前页行数据并渲染 */
async function load() {
  const response = await fetch(`/api/views/${state.slug}/rows/?page=${state.page}&page_size=${state.pageSize}`);
  if (!response.ok) {
    info.textContent = `加载失败: ${response.status}`;
    return;
  }
  const data = await response.json();
  state.total = data.count;
  body.innerHTML = "";
  for (const row of data.results || []) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    idCell.textContent = row.id;
    tr.appendChild(idCell);
    for (const name of fieldNames) {
      const td = document.createElement("td");
      const value = row[name];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  info.textContent = `第 ${state.page} / ${totalPages} 页（共 ${state.total} 行）`;
  prev.disabled = state.page <= 1;
  next.disabled = state.page >= totalPages;
}

prev.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    load();
  }
});

next.addEventListener("click", () => {
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  if (state.page < totalPages) {
    state.page += 1;
    load();
  }
});

load();

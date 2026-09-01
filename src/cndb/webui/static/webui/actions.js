/* 编辑与管理动作：建表/加字段/视图管理/行编辑/导入导出/工作区与成员（依赖 app.js 先加载） */

"use strict";

/* ---------- 通用对话框 ---------- */

const modalMask = document.getElementById("modal-mask");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalClose = document.getElementById("modal-close");

/** 打开对话框：title 标题，builder 以容器构建表单内容 */
function openModal(title, builder) {
  modalTitle.textContent = title;
  modalBody.innerHTML = "";
  builder(modalBody);
  modalMask.hidden = false;
}

/** 关闭对话框 */
function closeModal() {
  modalMask.hidden = true;
}

modalClose.addEventListener("click", closeModal);
modalMask.addEventListener("click", (event) => {
  if (event.target === modalMask) closeModal();
});

/** 在对话框内展示行内错误信息 */
function modalError(message) {
  let box = modalBody.querySelector(".modal-error");
  if (!box) {
    box = document.createElement("p");
    box.className = "modal-error";
    modalBody.prepend(box);
  }
  box.textContent = message;
}

/* ---------- 字段类型与控件 ---------- */

const FIELD_TYPES = [
  ["text", "单行文本"],
  ["long_text", "长文本"],
  ["number", "数值"],
  ["boolean", "布尔"],
  ["date", "日期"],
  ["single_select", "单选"],
  ["multi_select", "多选"],
  ["email", "邮箱"],
  ["url", "URL"],
];

/** select 选项类型的 choices 展示为逗号分隔 */
function choicesToText(config) {
  return ((config || {}).choices || []).join(",");
}

/** 逗号分隔文本解析为去空 choices */
function textToChoices(text) {
  return text.split(/[,，]/).map((item) => item.trim()).filter(Boolean);
}

/** 构造字段输入控件（带类型分派），value 为编辑初值 */
function buildFieldControl(field, value) {
  const type = field.field_type;
  let control;
  if (type === "long_text") {
    control = document.createElement("textarea");
  } else if (type === "boolean") {
    control = document.createElement("input");
    control.type = "checkbox";
    control.checked = value === true;
    return control;
  } else if (type === "single_select") {
    control = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "（空）";
    control.appendChild(empty);
    for (const choice of (field.config || {}).choices || []) {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice;
      control.appendChild(option);
    }
  } else if (type === "multi_select") {
    control = document.createElement("div");
    control.className = "multi-group";
    for (const choice of (field.config || {}).choices || []) {
      const line = document.createElement("label");
      line.className = "checkbox-line";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = choice;
      box.checked = Array.isArray(value) && value.includes(choice);
      line.append(box, document.createTextNode(` ${choice}`));
      control.appendChild(line);
    }
    return control;
  } else if (type === "number") {
    control = document.createElement("input");
    control.type = "number";
    control.step = "any";
  } else if (type === "date") {
    control = document.createElement("input");
    control.type = "date";
  } else if (type === "email") {
    control = document.createElement("input");
    control.type = "email";
  } else if (type === "url") {
    control = document.createElement("input");
    control.type = "url";
  } else {
    control = document.createElement("input");
    control.type = "text";
  }
  if (value !== null && value !== undefined) {
    control.value = String(value);
  }
  // 浏览器原生必填校验（boolean/multi_select 已提前 return，不适用原生 required）
  control.required = Boolean(field.required);
  return control;
}

/** 收集字段控件值（空文本返回 null 表示不提交），field 用于类型分派 */
function collectFieldControl(control, field) {
  const type = field.field_type;
  if (type === "boolean") {
    return control.checked;
  }
  if (type === "multi_select") {
    const picked = Array.from(control.querySelectorAll("input:checked")).map((item) => item.value);
    return picked.length ? picked : null;
  }
  const value = control.value.trim();
  if (value === "") {
    return null;
  }
  if (type === "number") {
    return Number(value);
  }
  return value;
}

/* ---------- 行编辑 ---------- */

/** 行新增/编辑对话框：row 为 null 表示新增 */
function openRowModal(row) {
  const table = currentTable();
  if (!table) {
    setStatus("请先选择数据表");
    return;
  }
  const fields = table.fields.filter((f) => !f.trashed).sort((a, b) => a.order - b.order);
  openModal(row ? `编辑行 #${row.id}` : "添加行", (body) => {
    const form = document.createElement("form");
    const controls = [];
    for (const field of fields) {
      const label = document.createElement("label");
      label.className = "field-label";
      label.textContent = field.name;
      const control = buildFieldControl(field, row ? row[field.name] : null);
      controls.push({ field, control });
      form.append(label, control);
    }
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "保存";
    form.appendChild(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {};
      for (const { field, control } of controls) {
        const value = collectFieldControl(control, field);
        // 必填兜底：multi_select 无原生 required；编辑时清空原值、新增缺填一并拦截
        if (value === null && field.required) {
          const original = row ? row[field.name] : null;
          if (!row || (original !== null && original !== undefined && !(Array.isArray(original) && !original.length))) {
            control.focus();
            modalError(`字段「${field.name}」为必填`);
            return;
          }
        }
        if (value !== null) {
          payload[field.name] = value;
        } else if (row && row[field.name] !== null && row[field.name] !== undefined) {
          payload[field.name] = null; // 编辑时清空原值
        }
      }
      const base = `/api/workspaces/${state.workspaceId}/tables/${state.tableId}/records/`;
      try {
        if (row) {
          await api(`${base}${row.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
        } else {
          await api(base, { method: "POST", body: JSON.stringify(payload) });
        }
        closeModal();
        closeRowDetail();
        await loadRows();
      } catch (err) {
        modalError(`保存失败: ${err.message}`);
      }
    });
    body.appendChild(form);
  });
}

/** 删除行（确认后 DELETE） */
async function deleteRow(row) {
  if (!window.confirm(`确认删除行 #${row.id}？`)) {
    return;
  }
  try {
    await api(`/api/workspaces/${state.workspaceId}/tables/${state.tableId}/records/${row.id}/`, { method: "DELETE" });
    closeRowDetail();
    await loadRows();
  } catch (err) {
    setStatus(`删除失败: ${err.message}`);
  }
}

/* ---------- 建表与加字段 ---------- */

/* ---------- 表管理 ---------- */

/** 编辑表对话框：改名与删除入口 */
function openTableEditModal(table) {
  openModal(`编辑表 ${table.name}`, (body) => {
    const form = document.createElement("form");
    const nameInput = labeledInput(form, "表名", "text", table.name);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "保存";
    form.appendChild(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api(`/api/workspaces/${state.workspaceId}/tables/${table.id}/`, {
          method: "PATCH",
          body: JSON.stringify({ name: nameInput.value.trim() }),
        });
        closeModal();
        await loadTables(table.id);
      } catch (err) {
        modalError(`保存失败: ${err.message}`);
      }
    });
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "btn-danger";
    deleteBtn.textContent = "删除表";
    deleteBtn.addEventListener("click", () => deleteTable(table));
    form.appendChild(deleteBtn);
    body.appendChild(form);
  });
}

/** 删除表（确认后 DELETE，物理表与元数据同删） */
async function deleteTable(table) {
  if (!window.confirm(`确认删除表 ${table.name}？表结构与全部数据将被删除，不可恢复。`)) {
    return;
  }
  try {
    await api(`/api/workspaces/${state.workspaceId}/tables/${table.id}/`, { method: "DELETE" });
    closeModal();
    await loadTables();
  } catch (err) {
    modalError(`删除失败: ${err.message}`);
  }
}

// 侧边栏表项操作按钮（编辑/删除）事件委托
document.getElementById("table-list").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-act]");
  if (!btn) return;
  const table = state.tables.find((t) => t.id === Number(btn.dataset.id));
  if (!table) return;
  if (btn.dataset.act === "edit") {
    openTableEditModal(table);
  } else {
    deleteTable(table);
  }
});

/* ---------- 字段管理 ---------- */

/** 字段类型码转中文文案 */
function fieldTypeText(fieldType) {
  const found = FIELD_TYPES.find(([value]) => value === fieldType);
  return found ? found[1] : fieldType;
}

/** 字段管理对话框：字段列表 + 编辑/删除 + 新增入口 */
function openFieldManagerModal() {
  const table = currentTable();
  if (!table) {
    setStatus("请先选择数据表");
    return;
  }
  openModal(`字段管理：${table.name}`, (body) => {
    const listBox = document.createElement("div");
    listBox.className = "def-rows";
    body.appendChild(listBox);
    const fields = table.fields.slice().sort((a, b) => a.order - b.order);
    for (const field of fields) {
      const line = document.createElement("div");
      line.className = "def-row";
      const info = document.createElement("span");
      info.className = "field-mgr-info";
      const marks = [fieldTypeText(field.field_type)];
      if (field.required) marks.push("必填");
      if (field.trashed) marks.push("已回收");
      info.textContent = `${field.name}（${marks.join("，")}）`;
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn-ghost btn-mini";
      editBtn.textContent = "编辑";
      editBtn.addEventListener("click", () => openFieldEditModal(field));
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn-ghost btn-mini";
      delBtn.textContent = "删除";
      delBtn.addEventListener("click", () => deleteField(field));
      line.append(info, editBtn, delBtn);
      listBox.appendChild(line);
    }
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn-ghost";
    addBtn.textContent = "+ 新增字段";
    addBtn.addEventListener("click", openFieldModal);
    body.appendChild(addBtn);
  });
}

/** 编辑字段对话框：改名/改类型/改选项/改必填（改类型走后端重建表） */
function openFieldEditModal(field) {
  openModal(`编辑字段 ${field.name}`, (body) => {
    const form = document.createElement("form");
    const nameInput = labeledInput(form, "字段名", "text", field.name);
    const typeLabel = objectLabel("类型");
    const typeEl = document.createElement("select");
    for (const [value, text] of FIELD_TYPES) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      option.selected = value === field.field_type;
      typeEl.appendChild(option);
    }
    form.append(typeLabel, typeEl);
    const choicesLabel = objectLabel("选项（逗号分隔，选填）");
    const choicesInput = document.createElement("input");
    choicesInput.type = "text";
    choicesInput.value = choicesToText(field.config);
    form.append(choicesLabel, choicesInput);
    const requiredLine = document.createElement("label");
    requiredLine.className = "checkbox-line";
    const requiredBox = document.createElement("input");
    requiredBox.type = "checkbox";
    requiredBox.checked = Boolean(field.required);
    requiredLine.append(requiredBox, document.createTextNode(" 必填"));
    form.appendChild(requiredLine);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "保存";
    form.appendChild(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = { name: nameInput.value.trim(), field_type: typeEl.value, required: requiredBox.checked };
      if (typeEl.value === "single_select" || typeEl.value === "multi_select") {
        const choices = textToChoices(choicesInput.value);
        if (!choices.length) {
          modalError("选项字段需要至少一个选项");
          return;
        }
        payload.config = { choices };
      }
      try {
        await api(`/api/workspaces/${state.workspaceId}/tables/${state.tableId}/fields/${field.id}/`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        closeModal();
        await loadTables(state.tableId); // 刷新字段元数据与行数据
      } catch (err) {
        modalError(`保存失败: ${err.message}`);
      }
    });
    body.appendChild(form);
  });
}

/** 删除字段（确认后 DELETE，联动物理列删除） */
async function deleteField(field) {
  if (!window.confirm(`确认删除字段 ${field.name}？该列数据将被删除，不可恢复。`)) {
    return;
  }
  try {
    await api(`/api/workspaces/${state.workspaceId}/tables/${state.tableId}/fields/${field.id}/`, {
      method: "DELETE",
    });
    closeModal();
    await loadTables(state.tableId);
  } catch (err) {
    modalError(`删除失败: ${err.message}`);
  }
}

/* ---------- 建表 ---------- */

/** 建表对话框：表名 + 动态字段定义行 */
function openTableModal() {
  if (!state.workspaceId) {
    setStatus("请先创建工作区");
    return;
  }
  openModal("新建表", (body) => {
    const form = document.createElement("form");
    const nameInput = labeledInput(form, "表名", "text");
    const rowsBox = document.createElement("div");
    rowsBox.className = "def-rows";
    form.append(objectLabel("字段定义"), rowsBox);

    /** 追加一行字段定义（名称/类型/选项） */
    const addDefRow = () => {
      const rowLine = document.createElement("div");
      rowLine.className = "def-row";
      const nameEl = document.createElement("input");
      nameEl.type = "text";
      nameEl.placeholder = "字段名";
      const typeEl = document.createElement("select");
      for (const [value, text] of FIELD_TYPES) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        typeEl.appendChild(option);
      }
      const choicesEl = document.createElement("input");
      choicesEl.type = "text";
      choicesEl.placeholder = "选项（逗号分隔，选填）";
      choicesEl.hidden = true;
      typeEl.addEventListener("change", () => {
        choicesEl.hidden = !["single_select", "multi_select"].includes(typeEl.value);
      });
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "btn-ghost btn-mini";
      removeBtn.textContent = "移除";
      removeBtn.addEventListener("click", () => {
        if (rowsBox.children.length > 1) rowLine.remove();
      });
      rowLine.append(nameEl, typeEl, choicesEl, removeBtn);
      rowsBox.appendChild(rowLine);
    };
    addDefRow();

    const addFieldBtn = document.createElement("button");
    addFieldBtn.type = "button";
    addFieldBtn.className = "btn-ghost";
    addFieldBtn.textContent = "+ 字段";
    addFieldBtn.addEventListener("click", addDefRow);
    form.appendChild(addFieldBtn);

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "创建";
    form.appendChild(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const fields = [];
      for (const rowLine of rowsBox.querySelectorAll(".def-row")) {
        const [nameEl, typeEl, choicesEl] = rowLine.querySelectorAll("input, select");
        const name = nameEl.value.trim();
        if (!name) continue;
        const def = { name, field_type: typeEl.value };
        if (!choicesEl.hidden) {
          const choices = textToChoices(choicesEl.value);
          if (!choices.length) {
            modalError(`字段 ${name} 需要至少一个选项`);
            return;
          }
          def.config = { choices };
        }
        fields.push(def);
      }
      if (!fields.length) {
        modalError("至少需要一个字段");
        return;
      }
      try {
        const created = await api(`/api/workspaces/${state.workspaceId}/tables/`, {
          method: "POST",
          body: JSON.stringify({ name: nameInput.value.trim(), fields }),
        });
        closeModal();
        await loadTables(created.id);
      } catch (err) {
        modalError(`创建失败: ${err.message}`);
      }
    });
    body.appendChild(form);
  });
}

/** 加字段对话框 */
function openFieldModal() {
  const table = currentTable();
  if (!table) {
    setStatus("请先选择数据表");
    return;
  }
  openModal("新增字段", (body) => {
    const form = document.createElement("form");
    const nameInput = labeledInput(form, "字段名", "text");
    const typeLabel = objectLabel("类型");
    const typeEl = document.createElement("select");
    for (const [value, text] of FIELD_TYPES) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      typeEl.appendChild(option);
    }
    form.append(typeLabel, typeEl);
    const choicesLabel = objectLabel("选项（逗号分隔，选填）");
    const choicesInput = document.createElement("input");
    choicesInput.type = "text";
    choicesInput.hidden = true;
    typeEl.addEventListener("change", () => {
      choicesInput.hidden = !["single_select", "multi_select"].includes(typeEl.value);
      choicesLabel.hidden = choicesInput.hidden;
    });
    form.append(choicesLabel, choicesInput);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "创建";
    form.appendChild(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const def = { name: nameInput.value.trim(), field_type: typeEl.value };
      if (!choicesInput.hidden) {
        const choices = textToChoices(choicesInput.value);
        if (!choices.length) {
          modalError("选项字段需要至少一个选项");
          return;
        }
        def.config = { choices };
      }
      try {
        await api(`/api/workspaces/${state.workspaceId}/tables/${state.tableId}/fields/`, {
          method: "POST",
          body: JSON.stringify(def),
        });
        closeModal();
        await loadTables(state.tableId); // 刷新内嵌字段元数据并保持当前表选中
      } catch (err) {
        modalError(`创建失败: ${err.message}`);
      }
    });
    body.appendChild(form);
  });
}

/* ---------- 视图管理 ---------- */

const FILTER_OPS = [
  ["eq", "等于"],
  ["ne", "不等于"],
  ["gt", "大于"],
  ["gte", "大于等于"],
  ["lt", "小于"],
  ["lte", "小于等于"],
  ["contains", "包含"],
  ["is_null", "为空"],
];

/** 新建/编辑视图对话框：view 为 null 表示新建 */
function openViewModal(view) {
  const table = currentTable();
  if (!table) {
    setStatus("请先选择数据表");
    return;
  }
  const fields = table.fields.filter((f) => !f.trashed).sort((a, b) => a.order - b.order);
  if (!fields.length) {
    setStatus("表暂无字段，请先添加字段");
    return;
  }
  const base = `/api/workspaces/${state.workspaceId}/tables/${state.tableId}/views/`;
  const initialPublic = view ? Boolean(view.public) : false;
  openModal(view ? `编辑视图 ${view.name}` : "新建视图", (body) => {
    const form = document.createElement("form");
    const nameInput = labeledInput(form, "视图名", "text", view ? view.name : "");
    if (!view) {
      const typeLabel = objectLabel("类型");
      const typeEl = document.createElement("select");
      for (const [value, text] of [["grid", "表格"], ["kanban", "看板"], ["calendar", "日历"], ["form", "表单"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        typeEl.appendChild(option);
      }
      form.append(typeLabel, typeEl);
      form.dataset.createType = "grid";
      typeEl.addEventListener("change", () => {
        form.dataset.createType = typeEl.value;
        syncTypeSections(); // 联动表单配置/公开共享区块可见性（调用时已过声明）
      });
    }

    // 筛选条件编辑器
    form.append(objectLabel("筛选条件"));
    const filterBox = document.createElement("div");
    filterBox.className = "def-rows";
    form.appendChild(filterBox);
    const filterTypeLabel = objectLabel("条件组合");
    const filterTypeEl = document.createElement("select");
    for (const [value, text] of [["AND", "全部满足"], ["OR", "任一满足"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      filterTypeEl.appendChild(option);
    }
    filterTypeEl.value = view ? view.filter_type : "AND";
    form.append(filterTypeLabel, filterTypeEl);

    /** 追加一行筛选（field/op/value） */
    const addFilterRow = (init) => {
      const rowLine = document.createElement("div");
      rowLine.className = "def-row";
      const fieldEl = document.createElement("select");
      for (const field of fields) {
        const option = document.createElement("option");
        option.value = field.name;
        option.textContent = field.name;
        fieldEl.appendChild(option);
      }
      const opEl = document.createElement("select");
      for (const [value, text] of FILTER_OPS) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        opEl.appendChild(option);
      }
      const valueEl = document.createElement("input");
      valueEl.type = "text";
      valueEl.placeholder = "值";
      if (init) {
        fieldEl.value = init.field;
        opEl.value = init.op;
        valueEl.value = init.value === null || init.value === undefined ? "" : String(init.value);
      }
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "btn-ghost btn-mini";
      removeBtn.textContent = "移除";
      removeBtn.addEventListener("click", () => rowLine.remove());
      rowLine.append(fieldEl, opEl, valueEl, removeBtn);
      filterBox.appendChild(rowLine);
    };
    for (const init of view ? view.filters || [] : []) {
      addFilterRow(init);
    }
    const addFilterBtn = document.createElement("button");
    addFilterBtn.type = "button";
    addFilterBtn.className = "btn-ghost";
    addFilterBtn.textContent = "+ 筛选";
    addFilterBtn.addEventListener("click", () => addFilterRow(null));
    form.appendChild(addFilterBtn);

    // 排序编辑器
    form.append(objectLabel("排序"));
    const sortBox = document.createElement("div");
    sortBox.className = "def-rows";
    form.appendChild(sortBox);
    /** 追加一行排序（field/desc） */
    const addSortRow = (init) => {
      const rowLine = document.createElement("div");
      rowLine.className = "def-row";
      const fieldEl = document.createElement("select");
      for (const field of fields) {
        const option = document.createElement("option");
        option.value = field.name;
        option.textContent = field.name;
        fieldEl.appendChild(option);
      }
      const descEl = document.createElement("select");
      const asc = document.createElement("option");
      asc.value = "false";
      asc.textContent = "升序";
      const desc = document.createElement("option");
      desc.value = "true";
      desc.textContent = "降序";
      descEl.append(asc, desc);
      if (init) {
        fieldEl.value = init.field;
        descEl.value = init.desc ? "true" : "false";
      }
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "btn-ghost btn-mini";
      removeBtn.textContent = "移除";
      removeBtn.addEventListener("click", () => rowLine.remove());
      rowLine.append(fieldEl, descEl, removeBtn);
      sortBox.appendChild(rowLine);
    };
    for (const init of view ? view.sortings || [] : []) {
      addSortRow(init);
    }
    const addSortBtn = document.createElement("button");
    addSortBtn.type = "button";
    addSortBtn.className = "btn-ghost";
    addSortBtn.textContent = "+ 排序";
    addSortBtn.addEventListener("click", () => addSortRow(null));
    form.appendChild(addSortBtn);

    // 字段显隐编辑器（field_options.hidden）
    form.append(objectLabel("字段显示"));
    const visibilityBox = document.createElement("div");
    visibilityBox.className = "checkbox-grid";
    form.appendChild(visibilityBox);
    for (const field of fields) {
      const option = view ? (view.field_options || {})[field.name] : null;
      const line = document.createElement("label");
      line.className = "checkbox-line";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.className = "visibility-box";
      box.dataset.field = field.name;
      box.checked = !(option && option.hidden);
      line.append(box, document.createTextNode(` ${field.name}`));
      visibilityBox.appendChild(line);
    }

    // 表单配置（仅表单视图）
    const formSection = document.createElement("div");
    formSection.className = "form-section";
    form.appendChild(formSection);
    const existingFormOptions = view ? view.form_options || {} : {};
    const formTitle = labeledInput(formSection, "表单标题", "text", existingFormOptions.title || "");
    const formDesc = labeledInput(formSection, "表单描述", "text", existingFormOptions.description || "");
    const formSubmitText = labeledInput(formSection, "提交按钮文案", "text", existingFormOptions.submit_text || "");
    formSection.append(objectLabel("表单字段（启用/必填）"));
    const formFieldsBox = document.createElement("div");
    formFieldsBox.className = "checkbox-grid";
    formSection.appendChild(formFieldsBox);
    for (const field of fields) {
      const init = (existingFormOptions.fields || {})[field.name] || {};
      const line = document.createElement("div");
      line.className = "form-field-line";
      const enabledBox = document.createElement("input");
      enabledBox.type = "checkbox";
      enabledBox.dataset.field = field.name;
      enabledBox.checked = Boolean(init.enabled);
      const requiredBox = document.createElement("input");
      requiredBox.type = "checkbox";
      requiredBox.dataset.field = field.name;
      requiredBox.checked = Boolean(init.required);
      requiredBox.disabled = !enabledBox.checked;
      enabledBox.addEventListener("change", () => {
        requiredBox.disabled = !enabledBox.checked;
        if (!enabledBox.checked) requiredBox.checked = false; // 未启用不可必填
      });
      line.append(
        enabledBox,
        document.createTextNode(` 启用 ${field.name}`),
        requiredBox,
        document.createTextNode(" 必填"),
      );
      formFieldsBox.appendChild(line);
    }

    // 公开共享（仅表格/表单视图生成匿名链接）
    const publicSection = document.createElement("div");
    form.appendChild(publicSection);
    publicSection.append(objectLabel("公开共享"));
    const publicLine = document.createElement("label");
    publicLine.className = "checkbox-line";
    const publicBox = document.createElement("input");
    publicBox.type = "checkbox";
    publicBox.checked = initialPublic;
    publicLine.append(publicBox, document.createTextNode(" 公开分享（生成匿名访问链接）"));
    publicSection.appendChild(publicLine);

    /** 按视图形态切换表单配置/公开共享区块可见性 */
    const syncTypeSections = () => {
      const viewType = view ? view.view_type : form.dataset.createType || "grid";
      formSection.hidden = viewType !== "form";
      publicSection.hidden = viewType !== "grid" && viewType !== "form";
    };
    syncTypeSections();

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "保存";
    form.appendChild(submit);

    if (view) {
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "btn-danger";
      deleteBtn.textContent = "删除视图";
      deleteBtn.addEventListener("click", async () => {
        if (!window.confirm(`确认删除视图 ${view.name}？`)) return;
        try {
          await api(`${base}${view.id}/`, { method: "DELETE" });
          closeModal();
          await loadViews();
        } catch (err) {
          modalError(`删除失败: ${err.message}`);
        }
      });
      form.appendChild(deleteBtn);
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const filters = [];
      for (const rowLine of filterBox.querySelectorAll(".def-row")) {
        const [fieldEl, opEl, valueEl] = rowLine.querySelectorAll("select, input");
        const filter = { field: fieldEl.value, op: opEl.value };
        if (opEl.value === "is_null") {
          filter.value = null;
        } else if (valueEl.value !== "") {
          const field = fields.find((f) => f.name === fieldEl.value);
          filter.value = field && field.field_type === "number" ? Number(valueEl.value) : valueEl.value;
        } else {
          continue; // 非 is_null 且值为空：跳过该条件
        }
        filters.push(filter);
      }
      const sortings = [];
      for (const rowLine of sortBox.querySelectorAll(".def-row")) {
        const [fieldEl, descEl] = rowLine.querySelectorAll("select");
        sortings.push({ field: fieldEl.value, desc: descEl.value === "true" });
      }
      const viewType = view ? view.view_type : form.dataset.createType || "grid";
      const payload = { name: nameInput.value.trim(), filter_type: filterTypeEl.value, filters, sortings };
      if (!view) {
        payload.view_type = viewType;
      }
      // 字段显隐 → field_options
      const fieldOptions = {};
      for (const box of visibilityBox.querySelectorAll(".visibility-box")) {
        fieldOptions[box.dataset.field] = { hidden: !box.checked };
      }
      payload.field_options = fieldOptions;
      // 表单配置（仅表单视图）
      if (viewType === "form") {
        const fieldsConfig = {};
        for (const line of formFieldsBox.querySelectorAll(".form-field-line")) {
          const [enabledBox, requiredBox] = line.querySelectorAll("input");
          if (enabledBox.checked) {
            fieldsConfig[enabledBox.dataset.field] = { enabled: true, required: requiredBox.checked };
          }
        }
        payload.form_options = {
          title: formTitle.value.trim(),
          description: formDesc.value.trim(),
          submit_text: formSubmitText.value.trim() || "提交",
          fields: fieldsConfig,
        };
      }
      // 公开共享（仅表格/表单视图）
      if (viewType === "grid" || viewType === "form") {
        payload.public = publicBox.checked;
      }
      try {
        const saved = view
          ? await api(`${base}${view.id}/`, { method: "PATCH", body: JSON.stringify(payload) })
          : await api(base, { method: "POST", body: JSON.stringify(payload) });
        closeModal();
        await loadViews(saved.id);
        // 首次开启公开时展示分享链接
        if (saved.public && saved.slug && !initialPublic) {
          const path = saved.view_type === "form" ? `/forms/${saved.slug}/` : `/share/${saved.slug}/`;
          openModal("分享链接", (linkBody) => {
            const link = document.createElement("a");
            link.href = path;
            link.target = "_blank";
            link.textContent = `${location.origin}${path}`;
            linkBody.appendChild(link);
          });
        }
      } catch (err) {
        modalError(`保存失败: ${err.message}`);
      }
    });
    body.appendChild(form);
  });
}

/* ---------- 导入导出 ---------- */

/** 导出：选择格式后浏览器直接下载（同源会话认证，导出应用当前可见范围） */
function exportRows() {
  if (!state.tableId) {
    setStatus("请先选择数据表");
    return;
  }
  openModal("导出数据", (body) => {
    const hint = document.createElement("p");
    hint.className = "section-hint";
    hint.textContent = "导出内容应用行级权限与隐藏字段（即当前可见范围）";
    body.appendChild(hint);
    const line = document.createElement("div");
    line.className = "def-row";
    for (const kind of ["csv", "json"]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-ghost";
      btn.textContent = kind.toUpperCase();
      btn.addEventListener("click", () => {
        closeModal();
        window.location.href = `/api/workspaces/${state.workspaceId}/tables/${state.tableId}/export/?format=${kind}`;
      });
      line.appendChild(btn);
    }
    body.appendChild(line);
  });
}

/** 导入：选 CSV 文件后 multipart 上传，展示结果与错误行 */
const importFile = document.getElementById("import-file");

function importRows() {
  if (!state.tableId) {
    setStatus("请先选择数据表");
    return;
  }
  importFile.value = "";
  importFile.click();
}

importFile.addEventListener("change", async () => {
  const file = importFile.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const data = await api(`/api/workspaces/${state.workspaceId}/tables/${state.tableId}/import/`, {
      method: "POST",
      body: formData,
    });
    const errors = data.errors || [];
    const summary = `导入完成：新增 ${data.created} 行` + (errors.length ? `，失败 ${errors.length} 行` : "，无失败");
    openModal("导入结果", (body) => {
      const head = document.createElement("p");
      head.textContent = summary;
      body.appendChild(head);
      if (errors.length) {
        const box = document.createElement("div");
        box.className = "import-errors";
        for (const error of errors.slice(0, 100)) {
          const line = document.createElement("div");
          line.textContent = `第 ${error.row} 行：${error.detail}`;
          box.appendChild(line);
        }
        body.appendChild(box);
      }
    });
    await loadRows();
  } catch (err) {
    setStatus(`导入失败: ${err.message}`);
  }
});

/* ---------- 工作区与成员 ---------- */

/** 新建工作区对话框 */
function openWorkspaceModal() {
  openModal("新建工作区", (body) => {
    const form = document.createElement("form");
    const nameInput = labeledInput(form, "名称", "text");
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn-primary";
    submit.textContent = "创建";
    form.appendChild(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api("/api/workspaces/", { method: "POST", body: JSON.stringify({ name: nameInput.value.trim() }) });
        closeModal();
        await loadWorkspaces();
        // loadWorkspaces 选中第一个；切换到新建的（最后一个）
        if (state.workspaces.length > 1) {
          state.workspaceId = state.workspaces[state.workspaces.length - 1].id;
          renderWorkspaces();
          await loadTables();
        }
      } catch (err) {
        modalError(`创建失败: ${err.message}`);
      }
    });
    body.appendChild(form);
  });
}

const MEMBER_ROLES = [
  ["admin", "管理员"],
  ["editor", "编辑者"],
  ["commenter", "评论者"],
  ["viewer", "查看者"],
];

/** 角色码转中文（owner 不在下拉中，单独映射） */
function roleText(role) {
  const found = MEMBER_ROLES.find(([value]) => value === role);
  if (found) return found[1];
  return role === "owner" ? "所有者" : role;
}

/** 成员管理对话框：列表 + 改角色 + 移除 + 添加成员 */
function openMemberModal() {
  if (!state.workspaceId) {
    setStatus("请先创建工作区");
    return;
  }
  openModal("工作区成员", async (body) => {
    let members = [];
    try {
      const data = await api(`/api/workspaces/${state.workspaceId}/members/`);
      members = data.results || data;
    } catch (err) {
      body.textContent = `加载失败: ${err.message}`;
      return;
    }
    /** 成员显示名：用户名（昵称） */
    const memberName = (member) => {
      const username = member.user && member.user.username !== undefined ? member.user.username : member.user;
      const nickname = member.user ? member.user.nickname : member.nickname;
      return nickname ? `${username}（${nickname}）` : String(username);
    };
    /** 重绘成员列表：默认只读展示（角色徽章），编辑/移除收进 hover 操作 */
    let editing = null; // 正在编辑角色的成员对象
    const render = () => {
      const listBox = body.querySelector(".member-list");
      if (!listBox) return;
      listBox.innerHTML = "";
      for (const member of members) {
        if (editing === member) {
          // 编辑态：角色下拉 + 保存/取消
          const editLine = document.createElement("div");
          editLine.className = "def-row";
          const roleSel = document.createElement("select");
          for (const [value, text] of MEMBER_ROLES) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = text;
            option.selected = member.role === value;
            roleSel.appendChild(option);
          }
          const saveBtn = document.createElement("button");
          saveBtn.type = "button";
          saveBtn.className = "btn-primary btn-mini";
          saveBtn.textContent = "保存";
          saveBtn.addEventListener("click", async () => {
            try {
              await api(`/api/workspaces/${state.workspaceId}/members/${member.id}/`, {
                method: "PATCH",
                body: JSON.stringify({ role: roleSel.value }),
              });
              member.role = roleSel.value;
              editing = null;
              render();
              setStatus(`已将 ${memberName(member)} 角色改为${roleText(member.role)}`);
            } catch (err) {
              setStatus(`修改角色失败: ${err.message}`);
            }
          });
          const cancelBtn = document.createElement("button");
          cancelBtn.type = "button";
          cancelBtn.className = "btn-ghost btn-mini";
          cancelBtn.textContent = "取消";
          cancelBtn.addEventListener("click", () => {
            editing = null;
            render();
          });
          editLine.append(roleSel, saveBtn, cancelBtn);
          listBox.appendChild(editLine);
          continue;
        }
        const line = document.createElement("div");
        line.className = "member-line";
        const name = document.createElement("span");
        name.textContent = memberName(member);
        const roleSpan = document.createElement("span");
        roleSpan.className = "role-badge";
        roleSpan.textContent = roleText(member.role);
        line.append(name, roleSpan);
        if (member.role !== "owner") {
          // 操作按钮 hover 才显示，主界面保持只读
          const ops = document.createElement("span");
          ops.className = "member-ops";
          const editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "btn-ghost btn-mini";
          editBtn.textContent = "编辑";
          editBtn.addEventListener("click", () => {
            editing = member;
            render();
          });
          const removeBtn = document.createElement("button");
          removeBtn.type = "button";
          removeBtn.className = "btn-ghost btn-mini";
          removeBtn.textContent = "移除";
          removeBtn.addEventListener("click", async () => {
            try {
              await api(`/api/workspaces/${state.workspaceId}/members/${member.id}/`, { method: "DELETE" });
              members = members.filter((m) => m.id !== member.id);
              render();
              setStatus(`已移除成员 ${memberName(member)}`);
            } catch (err) {
              setStatus(`移除失败: ${err.message}`);
            }
          });
          ops.append(editBtn, removeBtn);
          line.appendChild(ops);
        }
        listBox.appendChild(line);
      }
    };
    const listBox = document.createElement("div");
    listBox.className = "member-list";
    body.appendChild(listBox);
    render();

    // 添加成员：候选用户下拉（后端排除已是成员的用户）
    body.appendChild(objectLabel("添加成员"));
    const addLine = document.createElement("div");
    addLine.className = "def-row";
    const userInput = document.createElement("select");
    const loadingOption = document.createElement("option");
    loadingOption.textContent = "加载中...";
    loadingOption.disabled = true;
    loadingOption.selected = true;
    userInput.appendChild(loadingOption);
    let list = []; // 候选用户列表（含昵称），供添加成功后的状态提示取名
    try {
      const candidates = await api(`/api/workspaces/${state.workspaceId}/members/candidates/`);
      userInput.innerHTML = "";
      list = candidates.results || [];
      if (!list.length) {
        const empty = document.createElement("option");
        empty.textContent = "暂无可添加用户";
        empty.disabled = true;
        empty.selected = true;
        userInput.appendChild(empty);
      } else {
        for (const candidate of list) {
          const option = document.createElement("option");
          option.value = candidate.username;
          option.textContent = candidate.nickname
            ? `${candidate.username}（${candidate.nickname}）`
            : candidate.username;
          userInput.appendChild(option);
        }
      }
    } catch (err) {
      userInput.innerHTML = "";
      const denied = document.createElement("option");
      denied.textContent = `无权添加（${err.message}）`;
      denied.disabled = true;
      denied.selected = true;
      userInput.appendChild(denied);
    }
    const roleSel = document.createElement("select");
    for (const [value, text] of MEMBER_ROLES) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      roleSel.appendChild(option);
    }
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn-primary";
    addBtn.textContent = "添加";
    addBtn.addEventListener("click", async () => {
      const username = userInput.value;
      if (!username || !userInput.selectedOptions[0]?.value) return;
      try {
        const member = await api(`/api/workspaces/${state.workspaceId}/members/`, {
          method: "POST",
          body: JSON.stringify({ username, role: roleSel.value }),
        });
        members.push(member);
        // 添加成功后从候选下拉中移除该用户
        const used = userInput.querySelector(`option[value="${CSS.escape(username)}"]`);
        if (used) used.remove();
        render();
        const added = userInput.selectedOptions[0];
        if (!added?.value) {
          // 候选已空：恢复占位提示
          const empty = document.createElement("option");
          empty.textContent = "暂无可添加用户";
          empty.disabled = true;
          empty.selected = true;
          userInput.appendChild(empty);
        }
        const chosen = list.find((c) => c.username === username);
        const displayName = chosen?.nickname ? `${username}（${chosen.nickname}）` : username;
        setStatus(`已添加 ${displayName} 为${roleText(member.role)}`);
      } catch (err) {
        modalError(`添加失败: ${err.message}`);
      }
    });
    addLine.append(userInput, roleSel, addBtn);
    body.appendChild(addLine);
  });
}

/* ---------- 小工具 ---------- */

/** 生成纯展示标签 */
function objectLabel(text) {
  const label = document.createElement("div");
  label.className = "field-label";
  label.textContent = text;
  return label;
}

/** 生成 label + input 组合并挂到容器 */
function labeledInput(parent, text, type, initial) {
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = text;
  const input = document.createElement("input");
  input.type = type;
  if (initial !== undefined && initial !== null) {
    input.value = initial;
  }
  parent.append(label, input);
  return input;
}

/* ---------- 事件绑定 ---------- */

document.getElementById("workspace-create-btn").addEventListener("click", openWorkspaceModal);
document.getElementById("table-create-btn").addEventListener("click", openTableModal);
document.getElementById("field-mgr-btn").addEventListener("click", openFieldManagerModal);
document.getElementById("field-add-btn").addEventListener("click", openFieldModal);

// Escape 关闭对话框
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !modalMask.hidden) {
    closeModal();
  }
});
document.getElementById("view-create-btn").addEventListener("click", () => openViewModal(null));
document.getElementById("view-edit-btn").addEventListener("click", () => {
  const view = currentView();
  if (!view) {
    setStatus("请先选择视图");
    return;
  }
  openViewModal(view);
});
document.getElementById("export-btn").addEventListener("click", exportRows);
document.getElementById("import-btn").addEventListener("click", importRows);
document.getElementById("member-btn").addEventListener("click", openMemberModal);
document.getElementById("row-detail-edit").addEventListener("click", () => {
  if (state.detailRow) {
    openRowModal(state.detailRow);
  }
});

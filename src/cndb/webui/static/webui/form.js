/* 公开表单页脚本：收集控件值提交到公开表单 API（匿名，无 CSRF） */

"use strict";

const form = document.getElementById("public-form");
const message = document.getElementById("form-message");

/** 按控件类型收集单个字段值（空值返回 null 跳过提交） */
function collectValue(control) {
  const type = control.dataset.type;
  if (type === "boolean") {
    return control.checked;
  }
  if (type === "multi_select") {
    return Array.from(control.querySelectorAll("input:checked")).map((item) => item.value);
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {};
  for (const control of form.querySelectorAll("[data-name]")) {
    const value = collectValue(control);
    if (value !== null) {
      payload[control.dataset.name] = value;
    }
  }
  const response = await fetch(`/api/forms/${form.dataset.slug}/submit/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  message.hidden = false;
  if (response.ok) {
    message.className = "public-message ok";
    message.textContent = data && data.detail ? data.detail : "提交成功";
    form.reset();
  } else {
    message.className = "public-message err";
    message.textContent = data && data.detail ? data.detail : `提交失败: ${response.status}`;
  }
});

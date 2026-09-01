/* 登录/注册页脚本：模式切换与表单提交（Session 认证，需带 CSRF） */

"use strict";

const MODE_LOGIN = "login";
const MODE_REGISTER = "register";
let mode = MODE_LOGIN;

const tabLogin = document.getElementById("tab-login");
const tabRegister = document.getElementById("tab-register");
const form = document.getElementById("auth-form");
const nicknameInput = document.getElementById("id-nickname");
const emailInput = document.getElementById("id-email");
const submitBtn = document.getElementById("auth-submit");
const errorBox = document.getElementById("auth-error");

/** 切换登录/注册模式，控制仅注册需要的输入与按钮文案 */
function switchMode(next) {
  mode = next;
  tabLogin.classList.toggle("active", mode === MODE_LOGIN);
  tabRegister.classList.toggle("active", mode === MODE_REGISTER);
  nicknameInput.disabled = mode === MODE_LOGIN;
  emailInput.disabled = mode === MODE_LOGIN;
  submitBtn.textContent = mode === MODE_LOGIN ? "登录" : "注册";
  errorBox.hidden = true;
}

tabLogin.addEventListener("click", () => switchMode(MODE_LOGIN));
tabRegister.addEventListener("click", () => switchMode(MODE_REGISTER));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  const payload = { username: form.username.value.trim(), password: form.password.value };
  if (mode === MODE_REGISTER) {
    payload.nickname = form.nickname.value.trim();
    payload.email = form.email.value.trim();
  }
  const response = await fetch(`/api/auth/${mode}/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
    },
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    window.location.href = "/";
    return;
  }
  const data = await response.json().catch(() => null);
  errorBox.textContent = data ? (data.detail || Object.values(data).flat().join("; ")) : "请求失败，请重试";
  errorBox.hidden = false;
});

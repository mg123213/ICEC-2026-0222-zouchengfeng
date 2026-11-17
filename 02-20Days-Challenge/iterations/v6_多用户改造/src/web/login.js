/* 登录 / 注册页 */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* 线上发布后网关要求每个请求带 sharecode */
const SHARE_CODE =
  window.__SHARE_CODE__ || new URLSearchParams(location.search).get("sharecode") || "";

function withShare(path) {
  if (!SHARE_CODE) return path;
  return path + (path.includes("?") ? "&" : "?") + "sharecode=" + encodeURIComponent(SHARE_CODE);
}

let mode = "login";

const MESSAGES = {
  invalid_student_id: "学号应为 8–12 位数字",
  weak_password: "密码至少 6 位，且需同时包含字母和数字",
  student_exists: "该学号已注册，请直接登录",
  invalid_credentials: "学号或密码不正确",
  too_many_attempts: "失败次数过多，请 5 分钟后再试",
  empty_input: "请填写学号和密码",
};

function setMode(next) {
  mode = next;
  $("#tab-login").classList.toggle("active", next === "login");
  $("#tab-register").classList.toggle("active", next === "register");
  $("#confirm-wrap").hidden = next !== "register";
  $("#btn-submit").textContent = next === "login" ? "登录" : "注册并登录";
  $("#auth-msg").textContent = "";
  $("#auth-msg").className = "auth-msg";
}

$("#tab-login").addEventListener("click", () => setMode("login"));
$("#tab-register").addEventListener("click", () => setMode("register"));

function showMessage(text, ok = false) {
  const el = $("#auth-msg");
  el.textContent = text;
  el.className = "auth-msg" + (ok ? " ok" : "");
}

$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const studentId = $("#student-id").value.trim();
  const password = $("#password").value;
  const password2 = $("#password2").value;

  if (!studentId || !password) {
    showMessage(MESSAGES.empty_input);
    return;
  }
  if (mode === "register" && password !== password2) {
    showMessage("两次输入的密码不一致");
    return;
  }

  const btn = $("#btn-submit");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = mode === "login" ? "登录中…" : "注册中…";

  try {
    if (mode === "register") {
      const res = await fetch(withShare("/api/register"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: studentId, password }),
      });
      const data = await res.json();
      if (!data.ok) {
        showMessage(MESSAGES[data.error] || "注册失败，请重试");
        return;
      }
      showMessage("注册成功，正在登录…", true);
    }

    const res = await fetch(withShare("/api/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId, password }),
    });
    const data = await res.json();

    if (data.ok) {
      showMessage("登录成功，正在进入…", true);
      // reload 而不是跳转：保持地址栏里的 sharecode 不丢
      setTimeout(() => location.reload(), 260);
    } else {
      showMessage(MESSAGES[data.error] || "登录失败，请重试");
    }
  } catch (err) {
    showMessage("网络错误：" + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
});

setMode("login");

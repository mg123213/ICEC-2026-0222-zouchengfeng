/* 管理后台 */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const SHARE_CODE =
  window.__SHARE_CODE__ || new URLSearchParams(location.search).get("sharecode") || "";

function withShare(path) {
  if (!SHARE_CODE) return path;
  return path + (path.includes("?") ? "&" : "?") + "sharecode=" + encodeURIComponent(SHARE_CODE);
}

async function api(path) {
  const res = await fetch(withShare(path));
  if (res.status === 401 || res.status === 403) {
    location.href = "/" + (SHARE_CODE ? "?sharecode=" + encodeURIComponent(SHARE_CODE) : "");
    throw new Error("无权限");
  }
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

/* 返回工作台的链接要带上 sharecode，否则会被网关拦下 */
const back = $("#back-link");
if (SHARE_CODE) back.href = "/?sharecode=" + encodeURIComponent(SHARE_CODE);

$("#btn-logout").addEventListener("click", async () => {
  try {
    await fetch(withShare("/api/logout"), { method: "POST" });
  } finally {
    location.href = "/" + (SHARE_CODE ? "?sharecode=" + encodeURIComponent(SHARE_CODE) : "");
  }
});

/* ------------------------------------------------------------ 标签 */
$$(".admin-tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".admin-tabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".admin-panel").forEach((p) =>
      p.classList.toggle("active", p.id === `view-${tab.dataset.view}`)
    );
  });
});

/* ------------------------------------------------------------ 概览 */
async function loadOverview() {
  const data = await api("/api/admin/overview");

  $("#stat-grid").innerHTML = `
    <div class="stat-card accent"><b>${data.users}</b><span>注册用户</span></div>
    <div class="stat-card"><b>${data.students}</b><span>学生账号</span></div>
    <div class="stat-card"><b>${data.tasks}</b><span>待办总数</span></div>
    <div class="stat-card warn"><b>${data.open_tasks}</b><span>未完成</span></div>
    <div class="stat-card"><b>${data.tasks_with_deadline}</b><span>含截止时间</span></div>
    <div class="stat-card"><b>${data.feedback}</b><span>反馈条数</span></div>
    <div class="stat-card"><b>${data.avg_score || "–"}</b><span>平均评分</span></div>
    <div class="stat-card"><b>${data.telemetry.events}</b><span>日志事件</span></div>`;

  const tel = data.telemetry;
  $("#tel-summary").textContent = `覆盖 ${tel.days} 天 · 错误 ${tel.errors} 条`;

  if (tel.daily.length) {
    const max = Math.max(...tel.daily.map((d) => d.events), 1);
    $("#tel-bars").innerHTML = tel.daily
      .map(
        (d) => `<div class="bar-row">
          <span class="muted">${esc(d.date.slice(5))}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${Math.round(
            (d.events / max) * 100
          )}%"></span></span>
          <span class="bar-num">${d.events}</span>
        </div>`
      )
      .join("");
  } else {
    $("#tel-bars").innerHTML = `<div class="empty-row">暂无运行日志</div>`;
  }

  const counter = {};
  tel.daily.forEach((d) => {
    Object.entries(d.event_counts || {}).forEach(([key, value]) => {
      counter[key] = (counter[key] || 0) + value;
    });
  });
  const rows = Object.entries(counter).sort((a, b) => b[1] - a[1]);
  $("#tel-events").innerHTML = rows.length
    ? `<thead><tr><th>事件</th><th>次数</th></tr></thead><tbody>${rows
        .map(([key, value]) => `<tr><td>${esc(key)}</td><td class="num">${value}</td></tr>`)
        .join("")}</tbody>`
    : "";
}

/* ------------------------------------------------------------ 用户 */
async function loadUsers() {
  const data = await api("/api/admin/users");
  const users = data.users || [];
  $("#users-count").textContent = `共 ${users.length} 人`;

  $("#users-table").innerHTML = users.length
    ? `<thead><tr>
         <th>学号</th><th>角色</th><th>注册时间</th><th>最近登录</th>
         <th>待办</th><th>未完成</th><th>反馈</th>
       </tr></thead>
       <tbody>${users
         .map(
           (u) => `<tr>
             <td>${esc(u.student_id)}</td>
             <td>${u.role === "admin" ? '<span class="role-tag">管理员</span>' : "学生"}</td>
             <td>${esc(u.created_at)}</td>
             <td>${esc(u.last_login || "从未登录")}</td>
             <td class="num">${u.task_count}</td>
             <td class="num">${u.open_count}</td>
             <td class="num">${u.feedback_count}</td>
           </tr>`
         )
         .join("")}</tbody>`
    : `<tbody><tr><td class="empty-row">还没有用户注册</td></tr></tbody>`;
}

/* ------------------------------------------------------------ 待办 */
async function loadTasks() {
  const data = await api("/api/admin/tasks");
  const tasks = data.tasks || [];
  $("#tasks-count").textContent = `共 ${tasks.length} 条`;

  $("#tasks-table").innerHTML = tasks.length
    ? `<thead><tr>
         <th>学号</th><th>标题</th><th>截止</th><th>状态</th><th>创建</th>
       </tr></thead>
       <tbody>${tasks
         .map(
           (t) => `<tr>
             <td>${esc(t.student_id)}</td>
             <td>${esc(t.title.slice(0, 34))}${t.title.length > 34 ? "…" : ""}</td>
             <td>${esc(t.deadline || "—")}</td>
             <td>${t.done ? '<span class="pill ok">已完成</span>' : '<span class="pill open">进行中</span>'}</td>
             <td>${esc(t.created_at || "")}</td>
           </tr>`
         )
         .join("")}</tbody>`
    : `<tbody><tr><td class="empty-row">还没有待办记录</td></tr></tbody>`;
}

/* ------------------------------------------------------------ 反馈 */
async function loadFeedback() {
  const data = await api("/api/admin/feedback");
  const items = data.feedback || [];
  $("#feedback-count").textContent = `共 ${items.length} 条`;

  $("#feedback-table").innerHTML = items.length
    ? `<thead><tr>
         <th>时间</th><th>学号</th><th>身份</th><th>评分</th><th>用上的功能</th><th>意见</th>
       </tr></thead>
       <tbody>${items
         .map(
           (f) => `<tr>
             <td>${esc(f.created_at)}</td>
             <td>${esc(f.student_id)}</td>
             <td>${esc(f.role)}</td>
             <td class="num">${f.score}</td>
             <td>${esc((f.useful || []).join("、") || "—")}</td>
             <td style="white-space:normal;max-width:280px">${esc(f.comment || "—")}</td>
           </tr>`
         )
         .join("")}</tbody>`
    : `<tbody><tr><td class="empty-row">还没有反馈</td></tr></tbody>`;
}

/* ------------------------------------------------------------ 启动 */
async function boot() {
  try {
    const me = await fetch(withShare("/api/me")).then((r) => r.json());
    if (me.ok) {
      $("#user-id").textContent = me.student_id;
      $("#user-avatar").textContent = me.student_id.slice(-2);
    }
  } catch {
    /* 忽略 */
  }

  await loadOverview();
  await loadUsers();
  await loadTasks();
  await loadFeedback();
}

boot();

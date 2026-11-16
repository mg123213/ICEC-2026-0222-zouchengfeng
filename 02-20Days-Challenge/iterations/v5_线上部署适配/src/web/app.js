/* 校园通知雷达 —— 前端交互（原生 JS，无依赖） */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** 转义后再插入 DOM，避免通知原文里的尖括号破坏页面 */
function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* 线上发布后网关要求每个请求都带 sharecode，否则 403。
   服务端渲染首页时注入了 window.__SHARE_CODE__，这里统一附加。 */
const SHARE_CODE =
  window.__SHARE_CODE__ || new URLSearchParams(location.search).get("sharecode") || "";

function withShare(path) {
  if (!SHARE_CODE) return path;
  return path + (path.includes("?") ? "&" : "?") + "sharecode=" + encodeURIComponent(SHARE_CODE);
}

async function api(path, options = {}) {
  const res = await fetch(withShare(path), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/* ------------------------------------------------------------ 标签页 */
function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.panel === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  if (name === "tasks") loadTasks();
  if (name === "feedback") loadFeedbackCount();
}

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.panel));
});

/* ------------------------------------------------------------ 样例 */
const SAMPLE_NOTICE = `关于开展2026-2027学年第一学期学生困难补助申请的通知

各班级：
根据学校学生资助工作要求，现开展本学期困难补助申请工作。请符合条件的同学于11月21日17:00前将以下材料交至行政楼302室学生服务大厅：
1.《学生困难补助申请表》一式两份，需班主任签字
2.身份证复印件1份
3.上一学年成绩单1份（教务系统打印）
4.家庭经济困难佐证材料复印件各1份
联系人：李老师 0755-8888 0000
逾期不再受理，请相互转告。`;

const SAMPLE_LENT = `编号,器材名称,借用人,数量,借出日期,应还日期
MJ-001,游标卡尺,陈俊杰,1,2026-11-10,2026-11-17
MJ-002,千分尺,陈俊杰,1,2026-11-10,2026-11-17
MJ-003,游标卡尺,林晓婷,2,2026-11-12,2026-11-17
MJ-004,千分尺,林晓婷,1,2026-11-12,2026-11-17
MJ-005,扭矩扳手,黄志强,1,2026-11-14,2026-11-21
MJ-006,游标卡尺,吴雨桐,1,2026-11-15,2026-11-18
MJ-007,千分尺,吴雨桐,1,2026-11-15,2026-11-18
MJ-008,内六角扳手,周浩然,3,2026-11-13,2026-11-16`;

const SAMPLE_RETURNED = `编号,器材名称,归还人,数量,归还日期
MJ-001,游标卡尺,陈俊杰,1,2026-11-16
MJ-003,游标卡尺,林晓婷,1,2026-11-16
MJ-005,扭矩扳手,黄志强,1,2026-11-16
MJ-008,内六角扳手,周浩然,1,2026-11-16
MJ-009,游标卡尺,郑凯,1,2026-11-16`;

$("#btn-sample").addEventListener("click", () => {
  $("#notice-text").value = SAMPLE_NOTICE;
  updateCharCount();
});

$("#btn-inv-sample").addEventListener("click", () => {
  $("#lent-text").value = SAMPLE_LENT;
  $("#returned-text").value = SAMPLE_RETURNED;
});

/* ------------------------------------------------------------ 字计数 */
function updateCharCount() {
  const len = $("#notice-text").value.length;
  $("#char-count").textContent = `${len} 字`;
}
$("#notice-text").addEventListener("input", updateCharCount);

$("#btn-clear").addEventListener("click", () => {
  $("#notice-text").value = "";
  updateCharCount();
  $("#result-body").hidden = true;
  $("#result-empty").hidden = false;
  currentResult = null;
});

/* ------------------------------------------------------------ 解析 */
let currentResult = null;

function deadlineClass(urgency) {
  return { overdue: "overdue", today: "today", soon: "soon", normal: "" }[urgency] ?? "none";
}

function renderResult(data) {
  currentResult = data;
  const box = $("#result-body");
  const dl = data.deadline;

  const deadlineHtml = dl
    ? `<div class="deadline-box ${deadlineClass(data.urgency)}">
         <div class="deadline-main">
           <span class="deadline-date">${esc(dl.date)} ${esc(dl.time)}</span>
           <span class="deadline-left">${esc(data.deadline_human)}</span>
         </div>
         <div class="deadline-raw">原文：${esc(dl.raw)} · 置信度 ${Math.round(dl.confidence * 100)}%${
           dl.assumed_midnight ? " · 原文未写时刻，按 23:59 计" : ""
         }</div>
       </div>`
    : `<div class="deadline-box none">
         <div class="deadline-main"><span class="deadline-date">未识别到截止时间</span></div>
         <div class="deadline-raw">可以先看下方「文中出现的所有时间」，或手动补一个</div>
       </div>`;

  const materialsHtml = data.materials.length
    ? `<ul class="mat-list">${data.materials
        .map(
          (m) =>
            `<li>${esc(m.name)}${m.qty ? ` <span class="mat-qty">×${m.qty}${esc(m.unit || "")}</span>` : ""}</li>`
        )
        .join("")}</ul>`
    : `<span class="hint">未识别到材料清单</span>`;

  const contactsHtml = data.contacts.length
    ? data.contacts
        .map((c) => [c.name, c.phone].filter(Boolean).join(" "))
        .join("、")
    : "—";

  const warningHtml = data.warnings.length
    ? `<div class="warn-box"><ul>${data.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`
    : "";

  const candidatesHtml = data.candidates.length
    ? `<details class="evidence"><summary>文中出现的所有时间（${
        data.candidates.length
      } 个）</summary><pre>${data.candidates
        .map((c) => `${c.iso}  ←「${c.raw}」 ${Math.round(c.confidence * 100)}%`)
        .join("\n")}</pre></details>`
    : "";

  box.innerHTML = `
    <div class="res-title">${esc(data.title)}</div>
    ${deadlineHtml}
    <dl class="kv">
      <dt>提交地点</dt><dd>${esc(data.location) || "—"}</dd>
      <dt>材料清单</dt><dd>${materialsHtml}</dd>
      <dt>联系人</dt><dd>${esc(contactsHtml)}</dd>
      <dt>要做的事</dt><dd>${
        data.actions.length
          ? data.actions.map((a) => esc(a)).join("<br>")
          : "—"
      }</dd>
    </dl>
    ${data.tags.length ? `<div class="chip-list">${data.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
    ${warningHtml}
    <details class="evidence"><summary>查看原文依据</summary><pre>${esc(
      (data.evidence?.deadline || "") + "\n" + (data.evidence?.materials || []).join("\n")
    )}</pre></details>
    ${candidatesHtml}
    <div class="result-actions">
      <button class="btn primary" id="btn-save-task">保存为待办</button>
      <button class="btn ghost" id="btn-reset">重新粘贴</button>
    </div>`;

  $("#result-empty").hidden = true;
  box.hidden = false;

  $("#btn-save-task").addEventListener("click", saveTask);
  $("#btn-reset").addEventListener("click", () => $("#notice-text").focus());
}

async function doParse() {
  const text = $("#notice-text").value.trim();
  if (!text) {
    $("#notice-text").focus();
    return;
  }
  const btn = $("#btn-parse");
  btn.disabled = true;
  btn.textContent = "解析中…";
  try {
    const data = await api("/api/parse", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    if (!data.ok) {
      alert(data.error === "empty_input" ? "请先粘贴通知内容" : "解析失败，请重试");
      return;
    }
    renderResult(data);
  } catch (err) {
    alert("请求失败：" + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "解析通知";
  }
}

$("#btn-parse").addEventListener("click", doParse);
$("#notice-text").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") doParse();
});

async function saveTask() {
  const text = $("#notice-text").value.trim();
  if (!text) return;
  try {
    const data = await api("/api/parse", {
      method: "POST",
      body: JSON.stringify({ text, save: true }),
    });
    if (data.ok) {
      const btn = $("#btn-save-task");
      btn.textContent = "已存入待办 ✓";
      btn.disabled = true;
      loadTasks();
    }
  } catch (err) {
    alert("保存失败：" + err.message);
  }
}

/* ------------------------------------------------------------ 待办 */
function urgencyOf(deadline) {
  if (!deadline) return "normal";
  const diff = new Date(deadline.replace(" ", "T")).getTime() - Date.now();
  if (diff < 0) return "urgent";
  if (diff < 24 * 3600e3) return "urgent";
  if (diff < 72 * 3600e3) return "soon";
  return "normal";
}

function humanLeft(deadline) {
  if (!deadline) return "";
  const diff = new Date(deadline.replace(" ", "T")).getTime() - Date.now();
  const abs = Math.abs(diff);
  const day = Math.floor(abs / 86400e3);
  const hour = Math.floor((abs % 86400e3) / 3600e3);
  const text = day ? `${day} 天 ${hour} 小时` : `${hour} 小时`;
  return diff < 0 ? `已逾期 ${text}` : `还剩 ${text}`;
}

async function loadTasks() {
  const data = await api("/api/tasks");
  const tasks = data.tasks || [];
  const open = tasks.filter((t) => !t.done);
  $("#task-count").textContent = open.length;

  const list = $("#task-list");
  if (!tasks.length) {
    list.innerHTML = `<div class="empty" style="min-height:180px"><p>还没有待办</p><span>在「通知解析」里保存一条试试</span></div>`;
    return;
  }

  const sorted = [...tasks].sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    return (a.deadline || "9999").localeCompare(b.deadline || "9999");
  });

  list.innerHTML = sorted
    .map((t) => {
      const cls = t.done ? "done" : urgencyOf(t.deadline);
      const due = t.deadline
        ? `<span class="due">${esc(t.deadline)}（${humanLeft(t.deadline)}）</span>`
        : `<span class="due">无截止时间</span>`;
      return `<div class="task ${cls}">
        <div class="task-body">
          <div class="task-title">${esc(t.title)}</div>
          <div class="task-meta">
            ${due}
            ${t.location ? `<span>${esc(t.location)}</span>` : ""}
            ${t.materials?.length ? `<span>材料 ${t.materials.length} 项</span>` : ""}
            ${(t.tags || []).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}
          </div>
        </div>
        <div class="task-actions">
          <button class="icon-btn" data-done="${esc(t.id)}" title="${t.done ? "标记未完成" : "标记完成"}">${
            t.done ? "↺" : "✓"
          }</button>
          <button class="icon-btn" data-del="${esc(t.id)}" title="删除">×</button>
        </div>
      </div>`;
    })
    .join("");

  $$("[data-done]", list).forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.done;
      const task = tasks.find((t) => t.id === id);
      await api("/api/tasks/complete", {
        method: "POST",
        body: JSON.stringify({ id, done: !task.done }),
      });
      loadTasks();
    })
  );

  $$("[data-del]", list).forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("删除这条待办？")) return;
      await api("/api/tasks/delete", {
        method: "POST",
        body: JSON.stringify({ id: btn.dataset.del }),
      });
      loadTasks();
    })
  );
}

$("#btn-refresh-tasks").addEventListener("click", loadTasks);
$("#btn-ics").addEventListener("click", () => window.open(withShare("/api/export.ics"), "_blank"));

/* ------------------------------------------------------------ 器材 */
let invRows = [];

$("#btn-check-inv").addEventListener("click", async () => {
  const lent = $("#lent-text").value.trim();
  const returned = $("#returned-text").value.trim();
  if (!lent) {
    $("#inv-status").textContent = "请先粘贴借出登记表";
    return;
  }
  const btn = $("#btn-check-inv");
  btn.disabled = true;
  btn.textContent = "核对中…";
  try {
    const data = await api("/api/inventory", {
      method: "POST",
      body: JSON.stringify({ lent, returned }),
    });
    if (!data.ok) {
      $("#inv-status").textContent = data.message || "核对失败";
      return;
    }
    invRows = data.rows;
    renderInventory(data);
    $("#inv-status").textContent = "";
  } catch (err) {
    $("#inv-status").textContent = "请求失败：" + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "开始核对";
  }
});

function renderInventory(data) {
  const s = data.summary;
  $("#inv-summary").innerHTML = `
    <div class="mini-stat"><b>${s.pairs}</b><span>核对条目</span></div>
    <div class="mini-stat"><b>${s.qty_lent}</b><span>借出件数</span></div>
    <div class="mini-stat"><b>${s.qty_returned}</b><span>已还件数</span></div>
    <div class="mini-stat ${s.qty_outstanding ? "alert" : ""}"><b>${s.qty_outstanding}</b><span>未还件数</span></div>
    <div class="mini-stat ${s.people_overdue ? "warn" : ""}"><b>${s.people_overdue}</b><span>超期人数</span></div>
    <div class="mini-stat ${s.anomalies ? "alert" : ""}"><b>${s.anomalies}</b><span>异常记录</span></div>`;

  const statusClass = (row) => {
    if (row.status === "已还清") return "ok";
    if (row.overdue_days > 0) return "overdue";
    if (row.status === "部分归还") return "partial";
    return "open";
  };

  $("#inv-table").innerHTML = `
    <thead><tr>
      <th>编号</th><th>器材</th><th>借用人</th><th>借出</th><th>已还</th>
      <th>未还</th><th>应还日期</th><th>状态</th>
    </tr></thead>
    <tbody>${data.rows
      .map(
        (r) => `<tr>
          <td>${esc(r.code)}</td>
          <td>${esc(r.item)}</td>
          <td>${esc(r.person)}</td>
          <td class="num">${r.borrowed}</td>
          <td class="num">${r.returned}</td>
          <td class="num">${r.outstanding || "—"}</td>
          <td>${esc(r.due_at) || "—"}</td>
          <td><span class="pill ${statusClass(r)}">${
          r.overdue_days > 0 ? `超期 ${r.overdue_days} 天` : esc(r.status)
        }</span></td>
        </tr>`
      )
      .join("")}</tbody>`;

  $("#inv-message").textContent = data.message;
  $("#inv-anomalies").innerHTML = data.anomalies.length
    ? data.anomalies.map((a) => `<div class="anomaly">异常：${esc(a)}</div>`).join("")
    : "";
  $("#inv-result-card").hidden = false;
}

$("#btn-copy-msg").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#inv-message").textContent);
    $("#btn-copy-msg").textContent = "已复制 ✓";
    setTimeout(() => ($("#btn-copy-msg").textContent = "复制"), 1500);
  } catch {
    alert("复制失败，请手动选中文本复制");
  }
});

$("#btn-export-inv").addEventListener("click", async () => {
  const res = await fetch(withShare("/api/export"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: invRows }),
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "inventory-check.csv";
  a.click();
  URL.revokeObjectURL(url);
});

/* ------------------------------------------------------------ 反馈 */
let fbScore = 0;

$$("#fb-stars button").forEach((btn) => {
  btn.addEventListener("click", () => {
    fbScore = Number(btn.dataset.score);
    $$("#fb-stars button").forEach((b) =>
      b.classList.toggle("on", Number(b.dataset.score) <= fbScore)
    );
    $("#fb-score-label").textContent = `${fbScore} / 5`;
  });
});

/* 线上部署时 hostname 不是回环地址，反馈要多给一份可带走的副本 */
const IS_CLOUD = !["127.0.0.1", "localhost", "::1"].includes(location.hostname);
if (IS_CLOUD) {
  const mode = $("#foot-mode");
  if (mode) mode.textContent = "线上演示版";
}

$("#btn-feedback").addEventListener("click", async () => {
  if (!fbScore) {
    $("#fb-score-label").textContent = "先点个分吧";
    return;
  }
  const useful = $$("#fb-useful input:checked").map((i) => i.value);
  try {
    const data = await api("/api/feedback", {
      method: "POST",
      body: JSON.stringify({
        role: $("#fb-role").value,
        score: fbScore,
        useful,
        comment: $("#fb-comment").value.trim(),
        would_use: $("#fb-would").checked,
      }),
    });
    if (!data.ok) return;

    $("#fb-thanks").hidden = false;
    $("#fb-thanks").textContent = data.persisted
      ? `已记录，本机累计 ${data.count} 条反馈，谢谢。`
      : "已收到，谢谢。";

    // 云端：给一份可复制的原始记录，容器重建也不至于把反馈弄丢
    const wrap = $("#fb-echo-wrap");
    if (IS_CLOUD || !data.persisted) {
      $("#fb-echo").textContent = data.line || "";
      wrap.hidden = false;
    } else {
      wrap.hidden = true;
    }

    $("#fb-comment").value = "";
    loadFeedbackCount();
  } catch (err) {
    alert("提交失败：" + err.message);
  }
});

$("#btn-copy-fb").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#fb-echo").textContent);
    $("#btn-copy-fb").textContent = "已复制 ✓";
    setTimeout(() => ($("#btn-copy-fb").textContent = "复制这条反馈"), 1600);
  } catch {
    alert("复制失败，请手动选中文本复制");
  }
});

async function loadFeedbackCount() {
  try {
    const data = await api("/api/feedback/count");
    $("#fb-count").textContent = `已收集 ${data.count} 条`;
  } catch {
    /* 计数失败不影响使用 */
  }
}

/* ------------------------------------------------------------ 统计 */
async function loadStats() {
  try {
    const data = await api("/api/stats");
    const today = data.days[data.days.length - 1] || { events: 0, avg_ms: 0, errors: 0 };
    $("#stat-events").textContent = today.events;
    $("#stat-avg").textContent = today.avg_ms ? `${Math.round(today.avg_ms)}ms` : "–";
    $("#stat-err").textContent = today.errors;
    $("#stat-days").textContent = data.totals.days;
    $("#foot-stat").textContent = `累计 ${data.totals.events} 次调用 · 日志 ${data.log_dir}/`;
  } catch {
    /* 首屏统计失败不阻塞主流程 */
  }
}

async function loadVersion() {
  try {
    const data = await api("/api/health");
    $("#version").textContent = "v" + data.version;
  } catch {
    /* 版本号取不到就保留页面里的占位 */
  }
}

updateCharCount();
loadVersion();
loadStats();
loadTasks();
setInterval(loadStats, 30000);

/* 演示模式：?demo=1 自动填示例并解析，?tab=xxx 直达某个标签页。
   只影响前端填充，不改变任何业务逻辑。 */
const params = new URLSearchParams(location.search);
const startTab = params.get("tab");
if (startTab) switchTab(startTab);

if (params.get("demo") === "1") {
  if (!startTab || startTab === "parse") {
    $("#notice-text").value = SAMPLE_NOTICE;
    updateCharCount();
    setTimeout(doParse, 300);
  }
  if (startTab === "inventory") {
    $("#lent-text").value = SAMPLE_LENT;
    $("#returned-text").value = SAMPLE_RETURNED;
    setTimeout(() => $("#btn-check-inv").click(), 250);
  }
}

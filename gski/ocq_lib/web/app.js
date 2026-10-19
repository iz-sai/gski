const COLORS = {
  pending: "var(--pending)",
  running: "var(--running)",
  reported: "var(--reported)",
  done: "var(--done)",
  failed: "var(--failed)",
};
const ORDER = ["running", "reported", "failed", "pending", "done"];
const LIMIT = 200;

let st = {
  path: null,
  run: null,
  filter: "all",
  open: new Set(),
  details: {},
  data: null,
  limit: LIMIT,
  brief: false,
};
let runs = [];
let sig = "";

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c])
  );

const now = () => Math.floor(Date.now() / 1000);

function ago(t) {
  if (!t) return "";
  const d = now() - t;
  if (d < 60) return "just now";
  if (d < 3600) return Math.floor(d / 60) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
}

function dur(s) {
  if (s == null || s < 0) return "";
  const h = Math.floor(s / 3600),
    m = Math.floor((s % 3600) / 60),
    x = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${x}s` : `${x}s`;
}

const money = (c) => "$" + (c || 0).toFixed(2);

function kn(n) {
  n = n || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k";
  return String(n);
}

const tout = (tk) => ((tk && tk.output) || 0) + ((tk && tk.reasoning) || 0);
const tsum = (tk) =>
  tk
    ? (tk.input || 0) +
      tout(tk) +
      (tk.cache_read || 0) +
      (tk.cache_write || 0)
    : 0;

function tokFull(tk) {
  if (!tk) return "";
  return `input ${kn(tk.input)} · output ${kn(tk.output)} · reasoning ${kn(
    tk.reasoning
  )} · cache read ${kn(tk.cache_read)} · cache write ${kn(tk.cache_write)}`;
}

function tokShort(tk) {
  if (!tk || !tsum(tk)) return "";
  const inTokens = (tk.input || 0) + (tk.cache_read || 0);
  const outTokens = tout(tk);
  return `<span title="${esc(tokFull(tk))}">${kn(inTokens)} in · ${kn(
    outTokens
  )} out</span>`;
}

async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

const q = (o) => new URLSearchParams(o).toString();

function bar(counts, total, big) {
  if (!total) return `<div class="bar${big ? " big" : ""}"></div>`;
  const seg = ["done", "reported", "running", "failed", "pending"]
    .map((s) =>
      counts[s]
        ? `<span style="width:${
            (counts[s] / total) * 100
          }%;background:${COLORS[s]}"></span>`
        : ""
    )
    .join("");
  return `<div class="bar${big ? " big" : ""}">${seg}</div>`;
}

function pill(s) {
  return `<span class="pill" style="color:${
    COLORS[s]
  };background:color-mix(in srgb, ${COLORS[s]} 16%, transparent)">${s}</span>`;
}

function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  st.path = h.get("p");
  st.run = h.get("r");
}

function writeHash() {
  const h = new URLSearchParams();
  if (st.path) h.set("p", st.path);
  if (st.run) h.set("r", st.run);
  history.replaceState(null, "", "#" + h.toString());
}

async function loadProjects() {
  let d;
  try {
    d = await get("/api/projects");
  } catch {
    document.getElementById("srv").className = "dot";
    return;
  }
  document.getElementById("srv").className = "dot" + (d.server ? " on" : "");
  document.getElementById("srv").title = d.server
    ? "opencode server online"
    : "opencode server offline";
  if (!st.path && d.projects.length) {
    st.path = d.projects[0].path;
    writeHash();
    loadProject();
  }
  document.getElementById("projects").innerHTML =
    d.projects
      .map(
        (p) => `
    <div class="proj${
      p.path === st.path ? " sel" : ""
    }" data-path="${esc(p.path)}">
      <div class="name">${
        p.running ? '<span class="dot busy"></span>' : ""
      }${esc(p.name)}</div>
      <div class="path muted mono">${esc(p.path)}</div>
      <div class="meta muted">${p.runs} run${p.runs > 1 ? "s" : ""}${
          p.running ? ` · ${p.running} running` : ""
        } · ${ago(p.last)}</div>
    </div>`
      )
      .join("") ||
    '<div class="muted" style="padding:0 12px">No projects.</div>';
  document.querySelectorAll(".proj").forEach((el) => {
    el.onclick = () => {
      st.path = el.dataset.path;
      st.run = null;
      st.open.clear();
      st.filter = "all";
      st.data = null;
      writeHash();
      loadProjects();
      loadProject();
    };
  });
}

function renderIfChanged() {
  const s = JSON.stringify([
    st.path,
    st.run,
    runs,
    st.data,
    st.details,
    [...st.open],
    st.filter,
    st.limit,
  ]);
  if (s !== sig) {
    sig = s;
    render();
  }
}

async function loadProject() {
  if (!st.path) return;
  try {
    runs = await get("/api/project?" + q({ path: st.path }));
  } catch {
    runs = [];
  }
  if (!st.run && runs.length) {
    st.run = runs[0].name;
    writeHash();
  }
  await loadRun();
}

async function loadRun() {
  if (!st.path || !st.run) {
    st.data = null;
    renderIfChanged();
    return;
  }
  try {
    st.data = await get("/api/run?" + q({ path: st.path, run: st.run }));
  } catch {
    st.data = null;
  }
  renderIfChanged();
}

async function loadDetail(id) {
  try {
    st.details[id] = await get(
      "/api/task?" + q({ path: st.path, run: st.run, id })
    );
  } catch {}
  renderIfChanged();
}

function taskLine(t) {
  if (t.worker && t.status !== "running")
    return `<span class="ws" style="color:${
      t.worker === "done" ? COLORS.done : COLORS.failed
    }">${esc(t.worker)}</span>${esc(t.note)}${
      t.artifact ? ` <span class="muted mono">→ ${esc(t.artifact)}</span>` : ""
    }`;
  const act = t.activity
    ? `<div class="act mono">${
        t.live === "idle"
          ? "finished, waiting for orchestrator"
          : "▸ " + esc(t.activity)
      }</div>`
    : "";
  return `<span class="muted">${esc(t.task)}</span>${act}`;
}

function taskTime(t) {
  if (t.status === "running" && t.started)
    return `<span class="ticker" data-start="${t.started}">${dur(
      now() - t.started
    )}</span>`;
  if (t.started && t.finished && t.finished >= t.started)
    return dur(t.finished - t.started);
  return "";
}

function detail(id) {
  const d = st.details[id];
  if (!d) return `<div class="detail muted">Loading…</div>`;
  const row = (k, v, mono) =>
    v
      ? `<div class="k muted">${k}</div><pre${
          mono ? ' class="mono"' : ""
        }>${esc(v)}</pre>`
      : "";
  return `<div class="detail">
    ${row("Task", d.task)}
    ${row("Report", d.note)}
    ${row("Artifact", d.artifact, true)}
    ${row("Tokens", tokFull(d.tokens))}
    ${row("Feedback", d.feedback)}
    ${row("Denied", (d.denied || []).join("\n"), true)}
    ${row("Last reply", d.reply)}
    ${row("Session", d.session, true)}
  </div>`;
}

function render() {
  const main = document.getElementById("main");
  if (!st.path) {
    main.innerHTML = '<div class="empty muted">No runs yet.</div>';
    return;
  }
  const cards = runs
    .map(
      (r) => `
    <div class="runcard${
      r.name === st.run ? " sel" : ""
    }" data-run="${esc(r.name)}">
      <div class="name">${
        r.counts.running ? '<span class="dot busy"></span> ' : ""
      }${esc(r.name)}</div>
      ${bar(r.counts, r.total)}
      <div class="meta muted">${r.counts.done || 0}/${r.total} done · ${money(
        r.cost
      )} · ${ago(r.last)}</div>
    </div>`
    )
    .join("");
  const d = st.data;
  let body = '<div class="empty muted">Select a run.</div>';
  if (d) {
    const c = d.counts;
    const stat = (n, l, col) =>
      `<div class="stat"><div class="n" style="${
        col ? `color:${col}` : ""
      }">${n}</div><div class="l muted">${l}</div></div>`;
    let tasks = d.tasks
      .slice()
      .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
    if (st.filter !== "all")
      tasks = tasks.filter((t) => t.status === st.filter);
    const shown = tasks.slice(0, st.limit);
    const chip = (k, n) =>
      `<button class="chip${
        st.filter === k ? " sel" : ""
      }" data-f="${k}">${k} ${n}</button>`;
    const tk = d.tokens || {};
    const inTok = (tk.input || 0) + (tk.cache_read || 0);
    const outTok = tout(tk);
    body = `
      <h1>${esc(d.name)}</h1>
      <div class="sub muted">${esc(d.agent || "")}${
      d.model ? " · " + esc(d.model) : ""
    } · concurrency ${esc(d.concurrency ?? 1)}${
      d.server ? "" : ' · <span style="color:var(--failed)">server offline</span>'
    }</div>
      <div class="stats">
        ${stat(
          `${c.done || 0}<span class="muted" style="font-size:1.2rem"> / ${
            d.total
          }</span>`,
          "done"
        )}
        ${stat(c.running || 0, "running", c.running ? COLORS.running : "")}
        ${stat(c.reported || 0, "to review", c.reported ? COLORS.reported : "")}
        ${stat(c.failed || 0, "failed", c.failed ? COLORS.failed : "")}
        ${stat(c.pending || 0, "pending")}
        ${stat(money(d.cost), "cost")}
        ${stat(kn(inTok), "tokens in")}
        ${stat(kn(outTok), "tokens out")}
      </div>
      ${
        tsum(tk)
          ? `<div class="muted" style="margin-top:10px;font-size:.9rem">${tokFull(
              tk
            )}</div>`
          : ""
      }
      ${bar(c, d.total, true)}
      ${
        d.brief
          ? `<details class="brief"${
              st.brief ? " open" : ""
            }><summary>Brief</summary><pre>${esc(d.brief)}</pre></details>`
          : ""
      }
      <div class="chips">${chip("all", d.total)}${ORDER.filter((s) => c[s])
      .map((s) => chip(s, c[s]))
      .join("")}</div>
      ${shown
        .map(
          (t) => `
        <div class="task" data-id="${esc(t.id)}">
          <div class="top">
            <span class="id mono">${esc(t.id)}</span>
            ${pill(t.status)}
            ${
              t.live
                ? `<span class="dot ${
                    t.live === "idle"
                      ? ""
                      : t.live === "retry"
                      ? "retry"
                      : "busy"
                  }" title="${esc(t.live)}"></span>`
                : ""
            }
            ${t.denied ? `<span class="badge">denied ${t.denied}</span>` : ""}
            <span class="right muted">
              ${t.todos ? `<span>todos ${esc(t.todos)}</span>` : ""}
              ${t.attempts > 1 ? `<span>attempt ${t.attempts}</span>` : ""}
              ${tokShort(t.tokens)}
              ${t.cost ? `<span>${money(t.cost)}</span>` : ""}
              <span class="mono">${taskTime(t)}</span>
            </span>
          </div>
          <div class="line">${taskLine(t)}</div>
          ${st.open.has(t.id) ? detail(t.id) : ""}
        </div>`
        )
        .join("")}
      ${
        tasks.length > shown.length
          ? `<button class="chip more" id="more">show ${Math.min(
              LIMIT,
              tasks.length - shown.length
            )} more of ${tasks.length - shown.length}</button>`
          : ""
      }`;
  }
  main.innerHTML = `<div class="runs">${cards}</div>${body}`;
  const br = main.querySelector("details.brief");
  if (br)
    br.ontoggle = () => {
      st.brief = br.open;
    };
  main.querySelectorAll(".runcard").forEach((el) => {
    el.onclick = () => {
      st.run = el.dataset.run;
      st.open.clear();
      st.filter = "all";
      st.limit = LIMIT;
      writeHash();
      loadRun();
    };
  });
  main.querySelectorAll(".chip[data-f]").forEach((el) => {
    el.onclick = () => {
      st.filter = el.dataset.f;
      st.limit = LIMIT;
      render();
    };
  });
  const more = document.getElementById("more");
  if (more)
    more.onclick = () => {
      st.limit += LIMIT;
      render();
    };
  main.querySelectorAll(".task").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest(".detail")) return;
      const id = el.dataset.id;
      if (st.open.has(id)) st.open.delete(id);
      else {
        st.open.add(id);
        loadDetail(id);
      }
      render();
    };
  });
}

setInterval(
  () =>
    document
      .querySelectorAll(".ticker")
      .forEach((el) => (el.textContent = dur(now() - +el.dataset.start))),
  1000
);
setInterval(loadProjects, 5000);
setInterval(async () => {
  await loadProject();
  st.open.forEach((id) => loadDetail(id));
}, 3000);
window.onhashchange = () => {
  readHash();
  loadProjects();
  loadProject();
};
readHash();
loadProjects();
loadProject();

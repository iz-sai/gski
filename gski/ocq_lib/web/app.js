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
  actOpen: new Set(),
  details: {},
  data: null,
  limit: LIMIT,
  brief: false,
  allRuns: false,
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

function tokFull(tk) {
  if (!tk) return "";
  return `input ${kn(tk.input)} · output ${kn(tk.output)} · reasoning ${kn(
    tk.reasoning
  )} · cache read ${kn(tk.cache_read)} · cache write ${kn(tk.cache_write)}`;
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
      st.actOpen.clear();
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
    [...st.actOpen],
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

function actBox(t) {
  const raw = Array.isArray(t.activity)
    ? t.activity
    : t.activity
    ? [{ text: t.activity, status: "running" }]
    : [];
  const items =
    t.live === "idle"
      ? [{ text: "finished, waiting for orchestrator", status: "completed" }, ...raw]
      : raw;
  if (!items.length) return "";
  const open = st.actOpen.has(t.id);
  const cnt = items.length > 1 ? `${items.length} ` : "";
  if (!open) {
    const one = items[0].text.replace(/\s+/g, " ");
    return `<div class="act mono"><span class="act-one">▸ ${esc(
      one
    )}</span><span class="act-cnt">${cnt}▾</span></div>`;
  }
  const rows = items
    .map((a, i) => {
      const cls =
        a.status === "error"
          ? "err"
          : a.status === "running"
          ? "run"
          : "done";
      const ic = a.status === "error" ? "✗" : a.status === "running" ? "▸" : "✓";
      return `<div class="act-row ${cls}"><span class="act-ic">${ic}</span><span class="act-txt">${esc(
        a.text
      )}</span>${i === 0 ? `<span class="act-cnt">${cnt}▴</span>` : ""}</div>`;
    })
    .join("");
  return `<div class="act mono open">${rows}</div>`;
}

function taskLine(t) {
  if (t.status === "running") {
    const ping = t.ping
      ? `<div class="ping"><b>ping</b>${esc(t.ping)}</div>`
      : "";
    return `<div class="sum">${esc(t.task)}</div>${ping}${actBox(t)}`;
  }
  const ws =
    t.status === "reported" && t.worker
      ? `<span class="ws" style="color:${
          t.worker === "done" ? COLORS.done : COLORS.failed
        }">${esc(t.worker)}</span>`
      : "";
  return `<div class="sum${t.status === "done" ? " muted" : ""}">${ws}${esc(
    (t.status !== "pending" && t.note) || t.task
  )}</div>`;
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

function inline(s) {
  return s
    .split(/(`[^`]+`)/)
    .map((p, k) =>
      k % 2
        ? `<code>${p.slice(1, -1)}</code>`
        : p
            .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener">${t}</a>`)
            .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
            .replace(/(^|[^\w*])\*([^*\s](?:[^*]*[^*\s])?)\*(?!\w)/g, "$1<i>$2</i>")
    )
    .join("");
}

const FENCE = /^\s*```/;
const HEAD = /^(#{1,6})\s+(.*)$/;
const LI = /^(\s*)([-*+]|\d+[.)])\s+/;
const QUOTE = /^\s*>\s?/;
const HR = /^\s*([-*_])(\s*\1){2,}\s*$/;
const TSEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

function list(items) {
  let html = "";
  const stack = [];
  for (const it of items) {
    while (stack.length && it.ind < stack[stack.length - 1].ind)
      html += `</li></${stack.pop().tag}>`;
    const top = stack[stack.length - 1];
    if (!top || it.ind > top.ind) {
      const tag = it.ord ? "ol" : "ul";
      stack.push({ ind: it.ind, tag });
      html += `<${tag}><li>`;
    } else html += "</li><li>";
    html += inline(esc(it.text));
  }
  while (stack.length) html += `</li></${stack.pop().tag}>`;
  return html;
}

function md(src) {
  const lines = String(src ?? "").replace(/\r/g, "").split("\n");
  const table = (i) => /^\s*\|/.test(lines[i]) && TSEP.test(lines[i + 1] || "");
  const block = (i) => {
    const l = lines[i];
    return !l.trim() || FENCE.test(l) || HEAD.test(l) || LI.test(l) || QUOTE.test(l) || HR.test(l) || table(i);
  };
  const cells = (r) =>
    r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(esc(c.trim())));
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    let m;
    if (!l.trim()) {
      i++;
    } else if (FENCE.test(l)) {
      const buf = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre class="code">${esc(buf.join("\n"))}</pre>`);
    } else if ((m = l.match(HEAD))) {
      const n = m[1].length;
      out.push(`<h${n}>${inline(esc(m[2]))}</h${n}>`);
      i++;
    } else if (HR.test(l)) {
      out.push("<hr>");
      i++;
    } else if (table(i)) {
      const head = cells(l);
      const rows = [];
      i += 2;
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(
        `<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows
          .map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`)
          .join("")}</tbody></table>`
      );
    } else if (QUOTE.test(l)) {
      const buf = [];
      while (i < lines.length && QUOTE.test(lines[i])) buf.push(lines[i++].replace(QUOTE, ""));
      out.push(`<blockquote>${md(buf.join("\n"))}</blockquote>`);
    } else if (LI.test(l)) {
      const items = [];
      while (i < lines.length) {
        const mm = lines[i].match(LI);
        if (mm) items.push({ ind: mm[1].length, ord: /\d/.test(mm[2]), text: lines[i].slice(mm[0].length) });
        else if (/^\s+\S/.test(lines[i])) items[items.length - 1].text += " " + lines[i].trim();
        else break;
        i++;
      }
      out.push(list(items));
    } else {
      const buf = [l];
      i++;
      while (i < lines.length && !block(i)) buf.push(lines[i++]);
      out.push(`<p>${inline(esc(buf.join(" ")))}</p>`);
    }
  }
  return out.join("");
}

function detail(id) {
  const d = st.details[id];
  if (!d) return `<div class="detail muted">Loading…</div>`;
  const row = (k, v, kind) =>
    v
      ? `<div class="k muted">${k}</div>${
          kind === "md"
            ? `<div class="md">${md(v)}</div>`
            : `<pre${kind ? ' class="mono"' : ""}>${esc(v)}</pre>`
        }`
      : "";
  return `<div class="detail">
    ${row("Report", d.worker ? `**${d.worker}**: ${d.note || ""}` : d.note, "md")}
    ${row("Artifact", d.artifact, "mono")}
    ${row("Ping", d.ping, "md")}
    ${row("Task", d.task, "md")}
    ${row("Feedback", d.feedback, "md")}
    ${row("Denied", (d.denied || []).join("\n"), "mono")}
    ${row("Tokens", tokFull(d.tokens))}
    ${row("Last reply", d.reply, "md")}
    ${row("Session", d.session, "mono")}
  </div>`;
}

function render() {
  const main = document.getElementById("main");
  if (!st.path) {
    main.innerHTML = '<div class="empty muted">No runs yet.</div>';
    return;
  }
  const live = (r) => r.counts.running || r.counts.pending || r.counts.reported;
  const visible = st.allRuns
    ? runs
    : runs.filter((r) => live(r) || r.name === st.run);
  const hidden = runs.length - visible.length;
  const cards =
    visible
      .map(
        (r) => `
    <div class="runcard${r.name === st.run ? " sel" : ""}${
          live(r) ? " live" : ""
        }" data-run="${esc(r.name)}">
      <div class="name">${
        r.counts.running ? '<span class="dot busy"></span> ' : ""
      }${esc(r.name)}</div>
      ${bar(r.counts, r.total)}
      <div class="meta">${
        r.counts.running
          ? `<span style="color:${COLORS.running}">${r.counts.running} running</span> · `
          : ""
      }${
        r.counts.reported
          ? `<span style="color:${COLORS.reported}">${r.counts.reported} to review</span> · `
          : ""
      }<span class="muted">${r.counts.done || 0}/${r.total} done · ${money(
          r.cost
        )} · ${ago(r.last)}</span></div>
    </div>`
      )
      .join("") +
    (hidden || st.allRuns
      ? `<button class="chip runtoggle" id="allruns">${
          st.allRuns ? "hide finished" : `+ ${hidden} finished`
        }</button>`
      : "");
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
      ${bar(c, d.total, true)}
      ${
        d.brief
          ? `<details class="brief"${
              st.brief ? " open" : ""
            }><summary>Brief</summary><div class="md">${md(d.brief)}</div></details>`
          : ""
      }
      <div class="chips">${chip("all", d.total)}${ORDER.filter((s) => c[s])
      .map((s) => chip(s, c[s]))
      .join("")}</div>
      ${shown
        .map(
          (t) => `
        <div class="task${st.open.has(t.id) ? " open" : ""}" data-id="${esc(
            t.id
          )}" style="--c:${COLORS[t.status]}">
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
              ${t.cost ? `<span>${money(t.cost)}</span>` : ""}
              <span class="mono">${taskTime(t)}</span>
              <span class="chev">${st.open.has(t.id) ? "▾" : "▸"}</span>
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
      st.actOpen.clear();
      st.filter = "all";
      st.limit = LIMIT;
      writeHash();
      loadRun();
    };
  });
  main.querySelectorAll(".act").forEach((el) => {
    el.onclick = (e) => {
      e.stopPropagation();
      if (window.getSelection && String(window.getSelection())) return;
      const id = el.closest(".task").dataset.id;
      if (st.actOpen.has(id)) st.actOpen.delete(id);
      else st.actOpen.add(id);
      render();
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
  const ar = document.getElementById("allruns");
  if (ar)
    ar.onclick = () => {
      st.allRuns = !st.allRuns;
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

const light = () =>
  (document.documentElement.dataset.theme ||
    (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")) ===
  "light";
function themeButton() {
  const b = document.getElementById("theme");
  b.textContent = light() ? "☾" : "☀";
  b.title = light() ? "dark theme" : "light theme";
}
document.getElementById("theme").onclick = () => {
  const next = light() ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("ocq-theme", next);
  themeButton();
};
themeButton();

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

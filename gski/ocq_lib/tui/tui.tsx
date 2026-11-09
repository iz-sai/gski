import { existsSync, readdirSync, readFileSync, statSync } from "node:fs"
import { dirname, join } from "node:path"
import { Plugin } from "@opencode/plugin/tui"
import { TextAttributes, type RGBA, type ScrollBoxRenderable } from "@opentui/core"
import { useTerminalDimensions } from "@opentui/solid"
import { createEffect, createMemo, createSignal, For, on, onCleanup, Show } from "solid-js"

const ROUTE = "ocq"
const ORDER = ["running", "reported", "failed", "pending", "done"]
const BAR = ["done", "reported", "running", "failed", "pending"]
const HEAD = 12
const ROW = 4
const STRIP = 5

type Tokens = { input: number; output: number; reasoning: number; cache_read: number; cache_write: number }
type Task = Record<string, any> & { id: string; status: string; attempts: number; cost: number }
type Run = {
  name: string
  dir: string
  cfg: Record<string, any>
  tasks: Task[]
  counts: Record<string, number>
  total: number
  cost: number
  last: number
  brief: string
}
type Act = { text: string; status: string }
type Live = { state: string; cost: number; tokens?: Tokens; activity: Act[] }

const now = () => Math.floor(Date.now() / 1000)
const round4 = (n: number) => Math.round(n * 1e4) / 1e4
const money = (c: number) => "$" + (c || 0).toFixed(2)
const flat = (s: any) => String(s ?? "").replace(/\s+/g, " ").trim()

function dur(s?: number) {
  if (s == null || s < 0) return ""
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const x = s % 60
  return h ? `${h}h ${m}m` : m ? `${m}m ${x}s` : `${x}s`
}

function kn(n?: number) {
  n = n || 0
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M"
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k"
  return String(n)
}

function sumTokens(items: any[]): Tokens {
  const out = { input: 0, output: 0, reasoning: 0, cache_read: 0, cache_write: 0 }
  for (const tk of items) {
    if (!tk) continue
    const cache = tk.cache || {}
    out.input += tk.input || 0
    out.output += tk.output || 0
    out.reasoning += tk.reasoning || 0
    out.cache_read += tk.cache_read ?? cache.read ?? 0
    out.cache_write += tk.cache_write ?? cache.write ?? 0
  }
  return out
}

function fold(text: string) {
  const tasks = new Map<string, Task>()
  for (const line of text.split("\n")) {
    if (!line.trim()) continue
    let ev: any
    try {
      ev = JSON.parse(line)
    } catch {
      continue
    }
    if (!ev || ev.id == null) continue
    let t = tasks.get(ev.id)
    if (!t) {
      t = { id: ev.id, attempts: 0, cost: 0, status: "pending" }
      tasks.set(ev.id, t)
    }
    const { t: ts, denied, cost, tokens, ...rest } = ev
    t.updated = ts
    if (denied) (t.denied ??= []).push(denied)
    t.cost = round4(t.cost + (cost || 0))
    if (tokens) t.tokens = sumTokens([t.tokens, tokens])
    Object.assign(t, rest)
  }
  return tasks
}

function findRoot(dir: string) {
  let d = dir
  while (true) {
    try {
      if (statSync(join(d, ".ocq")).isDirectory()) return d
    } catch {}
    const p = dirname(d)
    if (p === d) return undefined
    d = p
  }
}

const stamp = (p: string) => {
  try {
    const s = statSync(p)
    return `${s.mtimeMs}:${s.size}`
  } catch {
    return ""
  }
}

const cache = new Map<string, { key: string; run: Run }>()

function loadRun(dir: string, name: string): Run | undefined {
  const lp = join(dir, "ledger.jsonl")
  const rp = join(dir, "run.json")
  const bp = join(dir, "brief.md")
  const key = [stamp(lp), stamp(rp), stamp(bp)].join("|")
  const hit = cache.get(dir)
  if (hit && hit.key === key) return hit.run
  let cfg: Record<string, any> = {}
  try {
    cfg = JSON.parse(readFileSync(rp, "utf8"))
  } catch {}
  const tasks = existsSync(lp) ? [...fold(readFileSync(lp, "utf8")).values()] : []
  const counts: Record<string, number> = {}
  for (const t of tasks) counts[t.status] = (counts[t.status] || 0) + 1
  let last = 0
  try {
    last = Math.floor(statSync(existsSync(lp) ? lp : rp).mtimeMs / 1000)
  } catch {}
  const run: Run = {
    name,
    dir,
    cfg,
    tasks,
    counts,
    total: tasks.length,
    cost: round4(tasks.reduce((a, t) => a + (t.cost || 0), 0)),
    last,
    brief: existsSync(bp) ? readFileSync(bp, "utf8").slice(0, 20000) : "",
  }
  cache.set(dir, { key, run })
  return run
}

function scan(root: string): Run[] {
  const base = join(root, ".ocq", "runs")
  let names: string[] = []
  try {
    names = readdirSync(base)
  } catch {
    return []
  }
  return names
    .filter((n) => existsSync(join(base, n, "run.json")))
    .map((n) => loadRun(join(base, n), n))
    .filter((r): r is Run => !!r)
    .sort((a, b) => b.last - a.last)
}

const isLive = (r: Run) => !!(r.counts.running || r.counts.pending || r.counts.reported)
const runLabel = (r: Run) =>
  ` ${r.name} ${r.counts.done || 0}/${r.total}${r.counts.running ? ` ${r.counts.running}▸` : ""}${r.counts.reported ? ` ${r.counts.reported}?` : ""} `

function assistants(msgs: any[]) {
  return msgs.filter((m) => m?.type === "assistant")
}

function activity(msgs: any[], limit = 10): Act[] {
  const out: Act[] = []
  for (const m of assistants(msgs)) {
    for (const c of [...(m.content || [])].reverse()) {
      if (c.type === "tool") {
        const st = c.state || {}
        const inp = st.input || {}
        const what = inp.command || inp.path || inp.filePath || inp.pattern || inp.url || inp.query || ""
        out.push({ text: `${c.name}: ${what}`.slice(0, 2000), status: st.status || "completed" })
        if (out.length >= limit) return out
      } else if (!out.length && c.type === "text" && String(c.text || "").trim()) {
        out.push({ text: c.text.trim().slice(0, 2000), status: "completed" })
      }
    }
  }
  return out
}

function lastText(msgs: any[]) {
  for (const m of assistants(msgs)) {
    const txt = (m.content || [])
      .filter((c: any) => c.type === "text")
      .map((c: any) => c.text || "")
      .join("\n")
      .trim()
    if (txt) return txt
  }
  return ""
}

const listOf = (res: any) => (Array.isArray(res) ? res : res?.data || [])

export default Plugin.define({
  id: "gski.ocq",
  setup(context) {
    const [root, setRoot] = createSignal<string>()
    const [runs, setRuns] = createSignal<Run[]>([])
    const [live, setLive] = createSignal<Record<string, Live>>({})
    const [replies, setReplies] = createSignal<Record<string, string>>({})
    const [doneTokens, setDoneTokens] = createSignal<Record<string, Tokens>>({})
    const [server, setServer] = createSignal(true)
    const [clock, setClock] = createSignal(now())
    const [opened, setOpened] = createSignal(false)

    const [selRun, setSelRun] = createSignal<string>()
    const [selId, setSelId] = createSignal<string>()
    const [brief, setBrief] = createSignal(false)
    const [pane, setPane] = createSignal(true)
    const [zoom, setZoom] = createSignal(false)

    const statusColor = (s: string): RGBA => {
      const t = context.theme
      if (s === "running") return t.text.feedback.info.base
      if (s === "reported") return t.text.feedback.warning.base
      if (s === "done") return t.text.feedback.success.base
      if (s === "failed") return t.text.feedback.error.base
      return t.text.muted
    }

    const currentDir = () => {
      const route = context.ui.router.current()
      const sid = route.type === "session" ? route.sessionID : (route as any).data?.sessionID
      const d = sid ? (context.data.session.get(sid) as any)?.location?.directory : undefined
      return d || context.location?.directory || context.data.location.default()?.directory || process.cwd()
    }

    const refreshFiles = () => {
      const r = findRoot(currentDir())
      if (r !== root()) setRoot(r)
      setRuns(r ? scan(r) : [])
    }

    const current = createMemo(() => {
      const rs = runs()
      return rs.find((r) => r.name === selRun()) ?? rs.find(isLive) ?? rs[0]
    })

    let busy = false
    const refreshLive = async () => {
      const run = current()
      const r = root()
      if (busy || !run || !r) return
      busy = true
      try {
        const active: Record<string, any> = (await context.client.session.active()) ?? {}
        setServer(true)
        const running = run.tasks.filter((t) => t.status === "running" && t.session)
        const shells = running.length
          ? listOf(await context.client.shell.list({ location: { directory: r } }).catch(() => undefined))
          : []
        const next: Record<string, Live> = {}
        await Promise.all(
          running.map(async (t) => {
            const sid = t.session as string
            const [info, msgs] = await Promise.all([
              context.client.session.get({ sessionID: sid }).catch(() => undefined),
              context.client.message
                .list({ sessionID: sid, limit: 15, order: "desc" })
                .then(listOf)
                .catch(() => []),
            ])
            let state = active[sid] ? (active[sid].type === "retry" ? "retry" : "busy") : "idle"
            let acts = activity(msgs)
            if (state === "idle") {
              const bg = shells.filter(
                (s: any) => s.status === "running" && (s.metadata || {}).sessionID === sid,
              )
              if (bg.length) {
                state = "waiting"
                acts = [...bg.map((b: any) => ({ text: `bg shell: ${b.command}`, status: "running" })), ...acts]
              }
            }
            next[t.id] = { state, cost: (info as any)?.cost || 0, tokens: (info as any)?.tokens, activity: acts }
          }),
        )
        setLive(next)
        const missing = run.tasks.filter(
          (t) => t.session && t.status !== "running" && t.status !== "pending" && !t.tokens && !doneTokens()[t.session],
        )
        for (const t of missing.slice(0, 20)) {
          const info: any = await context.client.session.get({ sessionID: t.session }).catch(() => undefined)
          if (info) setDoneTokens((d) => ({ ...d, [t.session]: sumTokens([info.tokens]) }))
        }
      } catch {
        setServer(false)
      } finally {
        busy = false
      }
    }

    const fetchReply = async (t?: Task) => {
      if (!t?.session) return
      if (replies()[t.session] !== undefined && t.status !== "running") return
      const msgs = await context.client.message
        .list({ sessionID: t.session, limit: 30, order: "desc" })
        .then(listOf)
        .catch(() => undefined)
      if (msgs) setReplies((r) => ({ ...r, [t.session]: lastText(msgs).slice(0, 8000) }))
    }

    const rows = createMemo(() => {
      const run = current()
      if (!run) return []
      const lv = live()
      const dt = doneTokens()
      return run.tasks
        .map((t) => {
          const l = t.status === "running" ? lv[t.id] : undefined
          return {
            ...t,
            live: l,
            cost: round4((t.cost || 0) + (l?.cost || 0)),
            tokens: l ? sumTokens([t.tokens, l.tokens]) : t.tokens || (t.session ? dt[t.session] : undefined),
          }
        })
        .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
    })

    const shown = rows
    const selIndex = createMemo(() => Math.max(0, shown().findIndex((t) => t.id === selId())))
    const selected = createMemo(() => shown()[selIndex()])

    const tick = setInterval(() => {
      refreshFiles()
      if (opened()) void refreshLive()
    }, 2000)
    const sec = setInterval(() => opened() && setClock(now()), 1000)
    refreshFiles()

    createEffect(
      on(selected, (t) => {
        if (opened()) void fetchReply(t)
      }),
    )

    const route = () => context.ui.router.current()
    const close = () => {
      const r = route()
      if (r.type !== "plugin" || r.name !== ROUTE) return
      context.ui.router.navigate((r.data?.returnRoute as any) ?? { type: "home" })
    }
    const toggle = () => {
      const r = route()
      if (r.type === "plugin" && r.name === ROUTE) return close()
      refreshFiles()
      context.ui.dialog.clear()
      const returnRoute =
        r.type === "session"
          ? { type: "session", sessionID: r.sessionID }
          : r.type === "plugin"
            ? { type: "plugin", id: r.id, name: r.name, ...(r.data ? { data: { ...r.data } } : {}) }
            : { type: "home" }
      context.ui.router.navigate({
        type: "plugin",
        name: ROUTE,
        data: { returnRoute, sessionID: r.type === "session" ? r.sessionID : undefined },
      })
    }

    function Bar(props: { counts: Record<string, number>; total: number; width: number }) {
      const segs = () => {
        const w = Math.max(1, props.width)
        if (!props.total) return [{ s: "pending", n: w, ch: "░" }]
        let acc = 0
        let used = 0
        return BAR.map((s) => {
          acc += props.counts[s] || 0
          const end = Math.round((acc / props.total) * w)
          const n = end - used
          used = end
          return { s, n, ch: s === "pending" ? "░" : "█" }
        }).filter((x) => x.n > 0)
      }
      return (
        <text wrapMode="none">
          <For each={segs()}>{(x) => <span style={{ fg: statusColor(x.s) }}>{x.ch.repeat(x.n)}</span>}</For>
        </text>
      )
    }

    function Footer() {
      const lr = createMemo(() => runs().filter(isLive))
      return (
        <Show when={lr()[0]}>
          {(r) => (
            <box flexShrink={0} onMouseUp={toggle}>
              <text fg={context.theme.text.muted} wrapMode="none">
                <span style={{ fg: context.theme.text.base }}>ocq </span>
                {r().name}{" "}
                <Show when={r().counts.running}>
                  <span style={{ fg: statusColor("running") }}>{r().counts.running}▸ </span>
                </Show>
                <Show when={r().counts.reported}>
                  <span style={{ fg: statusColor("reported") }}>{r().counts.reported}? </span>
                </Show>
                <Show when={r().counts.failed}>
                  <span style={{ fg: statusColor("failed") }}>{r().counts.failed}✗ </span>
                </Show>
                {r().counts.done || 0}/{r().total} {money(r().cost)}
                {lr().length > 1 ? ` +${lr().length - 1}` : ""}
              </text>
            </box>
          )}
        </Show>
      )
    }

    function summary(t: any) {
      if (t.status === "running") {
        if (t.ping) return "ping: " + t.ping
        if (t.live?.state === "idle") return "finished, waiting for orchestrator"
        const a = t.live?.activity?.[0]
        return a ? (a.status === "error" ? "✗ " : a.status === "running" ? "▸ " : "✓ ") + a.text : t.task
      }
      if (t.status === "reported" && t.worker) return `${t.worker}: ${t.note || ""}`
      return (t.status !== "pending" && t.note) || t.task
    }

    function time(t: any) {
      if (t.status === "running" && t.started) return dur(clock() - t.started)
      if (t.started && t.finished && t.finished >= t.started) return dur(t.finished - t.started)
      return ""
    }

    function TaskRow(props: { t: any; sel: boolean }) {
      const t = () => props.t
      const dot = () => {
        const s = t().live?.state
        if (!s) return ""
        return s === "idle" ? " ○" : s === "waiting" ? " ◐" : " ●"
      }
      const meta = () =>
        [
          t().attempts > 1 ? `a${t().attempts}` : "",
          t().denied?.length ? `denied ${t().denied.length}` : "",
          t().cost ? money(t().cost) : "",
          time(t()),
        ]
          .filter(Boolean)
          .join("  ")
      return (
        <box
          height={ROW}
          flexShrink={0}
          flexDirection="row"
          backgroundColor={props.sel ? context.theme.background.raised.high : undefined}
          onMouseUp={() => setSelId(t().id)}
        >
          <box width={1} flexShrink={0} backgroundColor={props.sel ? statusColor(t().status) : undefined} />
          <box flexDirection="column" flexGrow={1} minWidth={0} paddingLeft={2} paddingRight={2} paddingTop={1}>
            <box flexDirection="row" height={1}>
              <text wrapMode="none" flexGrow={1} minWidth={0} truncate>
                <span style={{ fg: context.theme.text.base, attributes: TextAttributes.BOLD }}>{t().id}</span>{" "}
                <span style={{ fg: statusColor(t().status) }}>
                  {t().status}
                  {dot()}
                </span>
              </text>
              <text wrapMode="none" fg={context.theme.text.muted} flexShrink={0}>
                {meta()}
              </text>
            </box>
            <text
              wrapMode="none"
              truncate
              fg={t().status === "done" ? context.theme.text.muted : context.theme.text.base}
            >
              {flat(summary(t()))}
            </text>
          </box>
        </box>
      )
    }

    function Detail(props: { t: any; ref: (s: ScrollBoxRenderable) => void }) {
      const t = () => props.t
      const tk = () => t().tokens as Tokens | undefined
      const sections = () => {
        const x = t()
        const reply = x.session ? replies()[x.session] : undefined
        return [
          ["Report", x.worker ? `${x.worker}: ${x.note || ""}` : x.note],
          ["Artifact", x.artifact],
          ["Ping", x.ping],
          [
            "Activity",
            x.live?.activity
              ?.map((a: Act) => (a.status === "error" ? "✗ " : a.status === "running" ? "▸ " : "✓ ") + flat(a.text))
              .join("\n"),
          ],
          ["Task", x.task],
          ["Feedback", x.feedback],
          ["Denied", (x.denied || []).join("\n")],
          [
            "Tokens",
            tk()
              ? `in ${kn(tk()!.input)} · out ${kn(tk()!.output)} · reasoning ${kn(tk()!.reasoning)} · cache r ${kn(tk()!.cache_read)} w ${kn(tk()!.cache_write)}`
              : "",
          ],
          ["Last reply", reply === undefined && x.session ? "loading…" : reply],
          ["Session", x.session],
        ].filter(([, v]) => v)
      }
      return (
        <scrollbox ref={props.ref} flexGrow={1} scrollbarOptions={{ visible: false }}>
          <box flexDirection="column" paddingLeft={2} paddingRight={1} paddingTop={1} gap={1}>
            <text>
              <span style={{ fg: context.theme.text.base, attributes: TextAttributes.BOLD }}>{t().id}</span>{" "}
              <span style={{ fg: statusColor(t().status) }}>{t().status}</span>
              <span style={{ fg: context.theme.text.muted }}>
                {"  "}attempt {t().attempts || 0}
                {t().cost ? "  " + money(t().cost) : ""}
                {time(t()) ? "  " + time(t()) : ""}
              </span>
            </text>
            <For each={sections()}>
              {([k, v]) => (
                <box flexDirection="column">
                  <text fg={context.theme.text.muted}>{k}</text>
                  <text fg={context.theme.text.base} wrapMode="word">
                    {String(v)}
                  </text>
                </box>
              )}
            </For>
          </box>
        </scrollbox>
      )
    }

    function Page() {
      const dims = useTerminalDimensions()
      const [offset, setOffset] = createSignal(0)
      let detail: ScrollBoxRenderable | undefined

      setOpened(true)
      setClock(now())
      void refreshLive()
      void fetchReply(selected())
      onCleanup(() => setOpened(false))

      const wide = () => dims().width >= 110
      const split = () => wide() && pane() && !zoom()
      const listWidth = () => (split() ? Math.floor(dims().width * 0.55) : dims().width)
      const perPage = () => Math.max(1, Math.floor((dims().height - HEAD) / ROW))
      const win = createMemo(() => {
        const n = perPage()
        const i = selIndex()
        let off = Math.min(offset(), Math.max(0, shown().length - n))
        if (i < off) off = i
        if (i >= off + n) off = i - n + 1
        return off
      })
      createEffect(() => setOffset(win()))
      createEffect(on(selected, () => detail?.scrollTo(0)))

      const pageRows = createMemo(() => shown().slice(win(), win() + perPage()))
      const strip = createMemo(() => {
        const list = runs()
        const sel = Math.max(0, list.findIndex((r) => r.name === current()?.name))
        const start = sel < STRIP ? 0 : sel - STRIP + 1
        const items = list.slice(start, start + STRIP)
        return { start, items, more: list.length - start - items.length }
      })

      const select = (i: number) => {
        const list = shown()
        if (!list.length) return
        setSelId(list[Math.max(0, Math.min(list.length - 1, i))].id)
      }
      const move = (d: number) => select(selIndex() + d)
      const pickRun = (d: number) => {
        const list = runs()
        if (!list.length) return
        const i = list.findIndex((r) => r.name === current()?.name)
        const next = list[Math.max(0, Math.min(list.length - 1, i + d))]
        if (next.name === current()?.name) return
        setSelRun(next.name)
        setSelId(undefined)
        setLive({})
        void refreshLive()
      }
      const openSession = () => {
        const t = selected()
        if (!t?.session) return context.ui.toast.show({ message: "No session for this task", variant: "warning" })
        context.ui.router.navigate({ type: "session", sessionID: t.session })
      }
      const half = () => Math.max(1, Math.floor(perPage() / 2))

      context.keymap.layer(() => ({
        priority: 10,
        commands: [
          { bind: "j,down", title: "Next task", group: "ocq", run: () => move(1) },
          { bind: "k,up", title: "Previous task", group: "ocq", run: () => move(-1) },
          { bind: "gg,home", title: "First task", group: "ocq", run: () => select(0) },
          { bind: "shift+g,end", title: "Last task", group: "ocq", run: () => select(shown().length - 1) },
          { bind: "ctrl+d,pagedown", title: "Half page down", group: "ocq", run: () => move(half()) },
          { bind: "ctrl+u,pageup", title: "Half page up", group: "ocq", run: () => move(-half()) },
          { bind: "l,right", title: "Next run", group: "ocq", run: () => pickRun(1) },
          { bind: "h,left", title: "Previous run", group: "ocq", run: () => pickRun(-1) },
          { bind: "shift+j", title: "Scroll detail down", group: "ocq", run: () => detail?.scrollBy(3) },
          { bind: "shift+k", title: "Scroll detail up", group: "ocq", run: () => detail?.scrollBy(-3) },
          { bind: "return,o", title: "Open worker session", group: "ocq", run: openSession },
          { bind: "space", title: "Zoom detail", group: "ocq", run: () => setZoom((z) => !z) },
          { bind: "p", title: "Toggle detail pane", group: "ocq", run: () => setPane((v) => !v) },
          { bind: "b", title: "Toggle brief", group: "ocq", run: () => setBrief((v) => !v) },
          {
            bind: "r",
            title: "Refresh",
            group: "ocq",
            run: () => {
              refreshFiles()
              void refreshLive()
              setReplies({})
              void fetchReply(selected())
            },
          },
          { bind: "q,escape", title: "Close ocq", group: "ocq", run: close },
          { id: "app.exit", title: "Close ocq", group: "ocq", run: close },
        ],
      }))

      const muted = () => context.theme.text.muted
      const base = () => context.theme.text.base

      const Body = () => (
        <Show
          when={!brief()}
          fallback={
            <scrollbox ref={(s: ScrollBoxRenderable) => (detail = s)} flexGrow={1}>
              <box paddingLeft={1} paddingRight={1}>
                <text fg={base()} wrapMode="word">
                  {current()?.brief || "No brief."}
                </text>
              </box>
            </scrollbox>
          }
        >
          <Show
            when={!zoom()}
            fallback={
              <Show when={selected()} fallback={<text fg={muted()}> No task.</text>}>
                {(t) => <Detail t={t()} ref={(s) => (detail = s)} />}
              </Show>
            }
          >
            <box flexDirection="row" flexGrow={1} minHeight={0}>
              <box flexDirection="column" width={listWidth()} flexShrink={0}>
                <Show when={shown().length} fallback={<text fg={muted()}> No tasks.</text>}>
                  <For each={pageRows()}>{(t) => <TaskRow t={t} sel={t.id === selected()?.id} />}</For>
                </Show>
              </box>
              <Show when={split()}>
                <box
                  flexGrow={1}
                  minWidth={0}
                  border={["left"]}
                  borderColor={context.theme.border.base}
                  flexDirection="column"
                >
                  <Show when={selected()}>{(t) => <Detail t={t()} ref={(s) => (detail = s)} />}</Show>
                </box>
              </Show>
            </box>
          </Show>
        </Show>
      )

      return (
        <box
          width="100%"
          height="100%"
          flexDirection="column"
          backgroundColor={context.theme.background.base}
          paddingLeft={2}
          paddingRight={2}
          paddingTop={1}
        >
          <box flexDirection="row" height={1} flexShrink={0}>
            <text wrapMode="none" flexGrow={1} minWidth={0} truncate>
              <span style={{ fg: base(), attributes: TextAttributes.BOLD }}>ocq</span>
              <span style={{ fg: muted() }}>{"   " + (root() ? context.ui.format.path(root()!) : "no .ocq here")}</span>
            </text>
            <text wrapMode="none" flexShrink={0}>
              <span style={{ fg: server() ? statusColor("done") : statusColor("failed") }}>●</span>
              <span style={{ fg: muted() }}>{server() ? " server" : " server offline"}</span>
            </text>
          </box>
          <box height={1} flexShrink={0} />
          <text wrapMode="none" truncate height={1} flexShrink={0}>
            <span style={{ fg: muted() }}>{strip().start ? `‹ ${strip().start}   ` : ""}</span>
            <For each={strip().items}>
              {(r) => {
                const sel = () => r.name === current()?.name
                return (
                  <>
                    <span
                      style={{
                        fg: sel() ? base() : muted(),
                        bg: sel() ? context.theme.background.raised.high : undefined,
                        attributes: sel() ? TextAttributes.BOLD : 0,
                      }}
                    >
                      {runLabel(r)}
                    </span>
                    <span>{"   "}</span>
                  </>
                )
              }}
            </For>
            <span style={{ fg: muted() }}>{strip().more ? `${strip().more} ›` : ""}</span>
          </text>
          <box height={1} flexShrink={0} />
          <Show
            when={current()}
            fallback={
              <box paddingTop={1}>
                <text fg={muted()}>No ocq runs in this project.</text>
              </box>
            }
          >
            {(run) => {
              const tk = createMemo(() => sumTokens(rows().map((t) => t.tokens)))
              const cost = createMemo(() => rows().reduce((a, t) => a + (t.cost || 0), 0))
              const c = () => run().counts
              const stat = (n: any, label: string, color?: RGBA) => (
                <>
                  <span style={{ fg: color ?? base(), attributes: TextAttributes.BOLD }}>{String(n)}</span>
                  <span style={{ fg: muted() }}>{` ${label}     `}</span>
                </>
              )
              return (
                <>
                  <text wrapMode="none" truncate height={1} flexShrink={0}>
                    <span style={{ fg: base(), attributes: TextAttributes.BOLD }}>{run().name}</span>
                    <span style={{ fg: muted() }}>
                      {run().cfg.agent ? "  " + run().cfg.agent : ""}
                      {run().cfg.model ? " · " + run().cfg.model : ""} · concurrency {run().cfg.concurrency ?? 1}
                    </span>
                  </text>
                  <text wrapMode="none" truncate height={1} flexShrink={0}>
                    {stat(`${c().done || 0}/${run().total}`, "done")}
                    {stat(c().running || 0, "running", c().running ? statusColor("running") : undefined)}
                    {stat(c().reported || 0, "review", c().reported ? statusColor("reported") : undefined)}
                    {stat(c().failed || 0, "failed", c().failed ? statusColor("failed") : undefined)}
                    {stat(c().pending || 0, "pending")}
                    {stat(money(cost()), "")}
                    {stat(kn(tk().input + tk().cache_read), "in")}
                    {stat(kn(tk().output + tk().reasoning), "out")}
                  </text>
                  <box height={1} flexShrink={0} />
                  <box height={1} flexShrink={0}>
                    <Bar counts={c()} total={run().total} width={dims().width - 4} />
                  </box>
                  <box height={1} flexShrink={0} />
                  <Body />
                </>
              )
            }}
          </Show>
          <box flexGrow={1} />
          <box height={1} flexShrink={0} />
          <text wrapMode="none" truncate height={1} flexShrink={0} fg={muted()}>
            {
              "j/k task    gg/G ends    ^d/^u page    h/l run    ⏎ session    space zoom    p pane    J/K scroll    b brief    r refresh    q close"
            }
          </text>
        </box>
      )
    }

    context.ui.router.register({ name: ROUTE, render: () => <Page /> })
    context.ui.slot({ append: "prompt.footer.status", render: () => <Footer /> })
    context.ui.slot({
      append: "app",
      render() {
        context.keymap.layer(() => ({
          mode: "global",
          commands: [
            {
              id: "ocq.toggle",
              title: "Toggle ocq dashboard",
              group: "ocq",
              bind: "<leader>o",
              palette: true,
              slash: { name: "ocq" },
              run: toggle,
            },
          ],
        }))
        return null
      },
    })

    return () => {
      clearInterval(tick)
      clearInterval(sec)
    }
  },
})

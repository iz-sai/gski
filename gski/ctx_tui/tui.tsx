import { spawn } from "node:child_process"
import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs"
import { basename, join } from "node:path"
import { Plugin } from "@opencode/plugin/tui"
import { TextAttributes, type RGBA, type ScrollBoxRenderable } from "@opentui/core"
import { useTerminalDimensions } from "@opentui/solid"
import { createEffect, createMemo, createSignal, For, on, onCleanup, Show } from "solid-js"
import {
  type Item,
  type ItemKind,
  type Plan,
  type SessionRow,
  TMP_DIR,
  ago,
  applyPlan,
  itemId,
  kn,
  listSessions,
  loadPlan,
  loadSessionItems,
  mutateItem,
  planSaved,
  tokStr,
} from "./lib"

const ROUTE = "ctx"
const HEAD = 10
const ROW = 3

function spawnVim(initialText: string, tag: string): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      mkdirSync(TMP_DIR, { recursive: true })
    } catch {}
    const safeTag = tag.replace(/[^a-zA-Z0-9_-]/g, "_")
    const file = join(TMP_DIR, `ctx-edit-${safeTag}-${Date.now()}.md`)
    writeFileSync(file, initialText, "utf8")
    const child = spawn("alacritty", ["--class", "oc-edit", "-t", `OC Edit | ${tag}`, "-e", "vim", file], {
      stdio: "ignore",
    })
    child.on("error", () => {
      try {
        unlinkSync(file)
      } catch {}
      resolve(null)
    })
    child.on("exit", () => {
      try {
        const updated = readFileSync(file, "utf8")
        unlinkSync(file)
        resolve(updated !== initialText ? updated : null)
      } catch {
        resolve(null)
      }
    })
  })
}

export default Plugin.define({
  id: "gski.ctx",
  setup(context) {
    const [sessionID, setSessionID] = createSignal<string>()
    const [sessionInfo, setSessionInfo] = createSignal<SessionRow>()
    const [items, setItems] = createSignal<Item[]>([])
    const [plan, setPlan] = createSignal<Plan>()
    const [selKey, setSelKey] = createSignal<string>()
    const [sortBy, setSortBy] = createSignal<"seq" | "size">("seq")
    const [scope, setScope] = createSignal<"active" | "all">("active")
    const [pane, setPane] = createSignal(true)
    const [zoom, setZoom] = createSignal(false)

    const kindColor = (it: Item): RGBA => {
      const t = context.theme
      if (it.spam || it.chars >= 20000) return t.text.feedback.error.base
      if (it.chars >= 5000) return t.text.feedback.warning.base
      if (it.kind === "user") return t.text.feedback.success.base
      if (it.kind === "tool") return t.text.feedback.info.base
      if (it.kind === "compaction") return t.text.feedback.warning.base
      return t.text.base
    }

    const roleColor = (kind: ItemKind): RGBA => {
      const t = context.theme
      if (kind === "user") return t.text.feedback.success.base
      if (kind === "tool") return t.text.feedback.info.base
      if (kind === "compaction") return t.text.feedback.warning.base
      if (kind === "synthetic" || kind === "system" || kind === "reasoning") return t.text.muted
      return t.text.base
    }

    const syncHostSession = async (sid: string) => {
      try {
        context.data.session.message.invalidate(sid)
        await context.data.session.message.sync(sid)
        context.data.session.invalidate(sid)
        await context.data.session.sync(sid)
      } catch {}
    }

    const reload = (sid = sessionID()) => {
      if (!sid) {
        const list = listSessions(1)
        if (list[0]) {
          sid = list[0].id
          setSessionID(sid)
        }
      }
      if (!sid) return
      const res = loadSessionItems(sid)
      setSessionInfo(res.info)
      setItems(res.items)
      setPlan(loadPlan(sid))
    }

    const shown = createMemo(() => {
      const list = items().filter((it) => (scope() === "active" ? it.active : true))
      if (sortBy() === "size") {
        return [...list].sort((a, b) => b.chars - a.chars || b.seq - a.seq)
      }
      return list
    })

    const selIndex = createMemo(() => Math.max(0, shown().findIndex((it) => it.key === selKey())))
    const selected = createMemo(() => shown()[selIndex()])

    const activeStats = createMemo(() => {
      const all = items()
      const act = all.filter((i) => i.active)
      const actChars = act.reduce((acc, i) => acc + i.chars, 0)
      const allChars = all.reduce((acc, i) => acc + i.chars, 0)
      const spamCount = act.filter((i) => i.spam).length
      return {
        actCount: act.length,
        allCount: all.length,
        actChars,
        actTokens: Math.round(actChars / 4),
        allChars,
        spamCount,
      }
    })

    const route = () => context.ui.router.current()
    const close = () => {
      const r = route()
      if (r.type !== "plugin" || r.name !== ROUTE) return
      context.ui.router.navigate((r.data?.returnRoute as any) ?? { type: "home" })
    }

    const toggle = () => {
      const r = route()
      if (r.type === "plugin" && r.name === ROUTE) return close()
      const activeSid = r.type === "session" ? r.sessionID : (r as any).data?.sessionID
      if (activeSid) setSessionID(activeSid)
      reload(activeSid || sessionID())
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
        data: { returnRoute, sessionID: activeSid },
      })
    }

    const pickSession = async () => {
      const sessions = listSessions(150)
      if (!sessions.length) {
        context.ui.toast.show({ message: "No sessions found in DB", variant: "warning" })
        return
      }
      const chosen = await context.ui.dialog.select({
        title: "Select Session to Inspect / Edit",
        current: sessionID(),
        options: sessions.map((s) => ({
          title: `${s.title || "(untitled)"}  [${s.msg_count} msgs · ${ago(s.time_updated)}]`,
          value: s.id,
          description: `${basename(s.directory || "")} · ${s.agent || "default"} · ${s.id}`,
        })),
      })
      if (chosen) {
        setSessionID(chosen)
        setSelKey(undefined)
        reload(chosen)
      }
    }

    const markTag = (it: Item) => {
      const p = plan()
      if (!p) return ""
      if (it.seq >= p.boundary) return "CLEANUP"
      return (p.marks[itemId(it)] ?? "").toUpperCase()
    }

    function ItemRow(props: { it: Item; sel: boolean }) {
      const it = () => props.it
      return (
        <box
          height={ROW}
          flexShrink={0}
          flexDirection="row"
          backgroundColor={props.sel ? context.theme.background.raised.high : undefined}
          onMouseUp={() => setSelKey(it().key)}
        >
          <box width={1} flexShrink={0} backgroundColor={props.sel ? kindColor(it()) : undefined} />
          <box flexDirection="column" flexGrow={1} minWidth={0} paddingLeft={2} paddingRight={2}>
            <box flexDirection="row" height={1}>
              <text wrapMode="none" flexGrow={1} minWidth={0} truncate>
                <span style={{ fg: context.theme.text.muted }}>{`#${it().seq}${it().partIdx !== null ? `.${it().partIdx}` : ""} `}</span>
                <span style={{ fg: roleColor(it().kind), attributes: TextAttributes.BOLD }}>{it().label}</span>
                <Show when={!it().active}>
                  <span style={{ fg: context.theme.text.muted }}>{" [archived]"}</span>
                </Show>
                <Show when={it().spam}>
                  <span style={{ fg: context.theme.text.feedback.error.base, attributes: TextAttributes.BOLD }}>
                    {" [SPAM LOOP]"}
                  </span>
                </Show>
                <Show when={markTag(it())}>
                  <span style={{ fg: context.theme.text.feedback.warning.base, attributes: TextAttributes.BOLD }}>
                    {` [${markTag(it())}]`}
                  </span>
                </Show>
              </text>
              <text wrapMode="none" fg={kindColor(it())} flexShrink={0}>
                {tokStr(it().chars)}
              </text>
            </box>
            <text wrapMode="none" truncate fg={it().chars < 30 ? context.theme.text.muted : context.theme.text.base}>
              {it().preview}
            </text>
          </box>
        </box>
      )
    }

    function Detail(props: { it: Item; ref: (s: ScrollBoxRenderable) => void }) {
      const it = () => props.it
      return (
        <scrollbox ref={props.ref} flexGrow={1} scrollbarOptions={{ visible: false }}>
          <box flexDirection="column" paddingLeft={2} paddingRight={1} paddingTop={1} gap={1}>
            <text>
              <span style={{ fg: context.theme.text.base, attributes: TextAttributes.BOLD }}>
                {`#${it().seq}${it().partIdx !== null ? `.${it().partIdx}` : ""} ${it().label}`}
              </span>
              <span style={{ fg: context.theme.text.muted }}>
                {`  ${tokStr(it().chars)} tok  ${ago(it().created)} ago  ${it().msgId}`}
              </span>
            </text>
            <text fg={context.theme.text.base} wrapMode="word">
              {it().detail}
            </text>
          </box>
        </scrollbox>
      )
    }

    function Page() {
      const dims = useTerminalDimensions()
      const [offset, setOffset] = createSignal(0)
      let detail: ScrollBoxRenderable | undefined

      reload()

      const wide = () => dims().width >= 110
      const split = () => wide() && pane() && !zoom()
      const listWidth = () => (split() ? Math.floor(dims().width * 0.52) : dims().width)
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
      const select = (i: number) => {
        const list = shown()
        if (!list.length) return
        setSelKey(list[Math.max(0, Math.min(list.length - 1, i))].key)
      }
      const move = (d: number) => select(selIndex() + d)
      const half = () => Math.max(1, Math.floor(perPage() / 2))

      const applyAction = async (action: "strip" | "truncate" | "clean" | "delete" | "delete_after") => {
        const it = selected()
        const sid = sessionID()
        if (!it || !sid) return
        if (action === "delete" || action === "delete_after") {
          const ok = await context.ui.dialog.confirm({
            title: action === "delete_after" ? "Truncate Session History?" : "Delete Message / Part?",
            message:
              action === "delete_after"
                ? `Delete all messages after #${it.seq} (${it.label})?`
                : `Permanently delete #${it.seq} (${it.label}, ${kn(it.chars)} chars)?`,
            label: { confirm: "Delete", cancel: "Cancel" },
          })
          if (!ok) return
        }
        const prevIdx = selIndex()
        const msg = mutateItem(it, action)
        reload(sid)
        select(prevIdx)
        await syncHostSession(sid)
        context.ui.toast.show({ message: msg, variant: "success", duration: 2500 })
      }

      const editInVim = async () => {
        const it = selected()
        const sid = sessionID()
        if (!it || !sid) return
        if (!it.editable) {
          context.ui.toast.show({ message: "This item has no editable text", variant: "warning" })
          return
        }
        const updated = await spawnVim(it.editText, `${it.seq}_${it.label}`)
        if (updated === null) return
        const msg = mutateItem(it, "edit", updated)
        reload(sid)
        await syncHostSession(sid)
        context.ui.toast.show({ message: msg, variant: "success", duration: 2500 })
      }

      const cleanAllSpam = async () => {
        const sid = sessionID()
        if (!sid) return
        const spamItems = items().filter((i) => i.spam)
        if (!spamItems.length) {
          context.ui.toast.show({ message: "No repetition spam detected in this session", variant: "info" })
          return
        }
        for (const it of spamItems) mutateItem(it, "clean")
        reload(sid)
        await syncHostSession(sid)
        context.ui.toast.show({
          message: `Cleaned repetition spam in ${spamItems.length} message(s)`,
          variant: "success",
        })
      }

      const applyCleanup = async () => {
        const sid = sessionID()
        const p = plan()
        if (!sid || !p) {
          context.ui.toast.show({ message: "No pending cleanup plan", variant: "info" })
          return
        }
        if (context.data.session.status(sid) === "running") {
          context.ui.toast.show({ message: "Session is still running", variant: "warning" })
          return
        }
        const ok = await context.ui.dialog.confirm({
          title: "Apply Cleanup Plan?",
          message: `${Object.keys(p.marks).length} marks (~${tokStr(planSaved(p, items()))} tok) and remove cleanup turn from #${p.boundary}.`,
          label: { confirm: "Apply", cancel: "Cancel" },
        })
        if (!ok) return
        const msg = applyPlan(sid)
        reload(sid)
        await syncHostSession(sid)
        context.ui.toast.show({ message: msg, variant: "success", duration: 3500 })
      }

      const openTargetSession = () => {
        const sid = sessionID()
        if (!sid) return
        context.ui.router.navigate({ type: "session", sessionID: sid })
      }

      context.keymap.layer(() => ({
        priority: 10,
        commands: [
          { bind: "j,down", title: "Next item", group: "ctx", run: () => move(1) },
          { bind: "k,up", title: "Previous item", group: "ctx", run: () => move(-1) },
          { bind: "gg,home", title: "First item", group: "ctx", run: () => select(0) },
          { bind: "shift+g,end", title: "Last item", group: "ctx", run: () => select(shown().length - 1) },
          { bind: "ctrl+d,pagedown", title: "Half page down", group: "ctx", run: () => move(half()) },
          { bind: "ctrl+u,pageup", title: "Half page up", group: "ctx", run: () => move(-half()) },
          { bind: "shift+j", title: "Scroll detail down", group: "ctx", run: () => detail?.scrollBy(5) },
          { bind: "shift+k", title: "Scroll detail up", group: "ctx", run: () => detail?.scrollBy(-5) },
          {
            bind: "o",
            title: "Toggle sort (seq / size)",
            group: "ctx",
            run: () => setSortBy((s) => (s === "seq" ? "size" : "seq")),
          },
          {
            bind: "f",
            title: "Toggle scope (active / all)",
            group: "ctx",
            run: () => setScope((s) => (s === "active" ? "all" : "active")),
          },
          { bind: "s", title: "Select session", group: "ctx", run: () => void pickSession() },
          { bind: "e,return", title: "Edit in Vim", group: "ctx", run: () => void editInVim() },
          { bind: "x", title: "Strip / stub content", group: "ctx", run: () => void applyAction("strip") },
          { bind: "t", title: "Truncate long output", group: "ctx", run: () => void applyAction("truncate") },
          { bind: "c", title: "Clean repetition spam on item", group: "ctx", run: () => void applyAction("clean") },
          { bind: "shift+c", title: "Clean all repetition spam in session", group: "ctx", run: () => void cleanAllSpam() },
          { bind: "shift+a", title: "Apply agent cleanup plan", group: "ctx", run: () => void applyCleanup() },
          { bind: "d", title: "Delete message/part", group: "ctx", run: () => void applyAction("delete") },
          { bind: "shift+x", title: "Delete all messages after this", group: "ctx", run: () => void applyAction("delete_after") },
          { bind: "g", title: "Go to this session in chat", group: "ctx", run: openTargetSession },
          { bind: "space", title: "Zoom detail", group: "ctx", run: () => setZoom((z) => !z) },
          { bind: "p", title: "Toggle detail pane", group: "ctx", run: () => setPane((v) => !v) },
          { bind: "r", title: "Refresh", group: "ctx", run: () => reload() },
          { bind: "q,escape", title: "Close ctx", group: "ctx", run: close },
          { id: "app.exit", title: "Close ctx", group: "ctx", run: close },
        ],
      }))

      const muted = () => context.theme.text.muted
      const base = () => context.theme.text.base
      const st = activeStats

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
              <span style={{ fg: base(), attributes: TextAttributes.BOLD }}>ctx</span>
              <span style={{ fg: muted() }}>{"   " + (sessionInfo()?.title || "(untitled session)")}</span>
              <span style={{ fg: muted() }}>{"  ·  " + (sessionID() || "")}</span>
            </text>
            <text wrapMode="none" flexShrink={0}>
              <span style={{ fg: muted() }}>sort: </span>
              <span style={{ fg: context.theme.text.feedback.info.base, attributes: TextAttributes.BOLD }}>
                {sortBy() === "size" ? "SIZE ↓" : "SEQ ↑"}
              </span>
              <span style={{ fg: muted() }}>{"   scope: "}</span>
              <span style={{ fg: context.theme.text.feedback.warning.base, attributes: TextAttributes.BOLD }}>
                {scope() === "active" ? "ACTIVE" : "ALL"}
              </span>
            </text>
          </box>
          <box height={1} flexShrink={0} />
          <text wrapMode="none" truncate height={1} flexShrink={0}>
            <span style={{ fg: base(), attributes: TextAttributes.BOLD }}>{`${tokStr(st().actChars)} tok`}</span>
            <span style={{ fg: muted() }}>{` active     `}</span>
            <span style={{ fg: base(), attributes: TextAttributes.BOLD }}>{`${st().actCount}`}</span>
            <span style={{ fg: muted() }}>{`/${st().allCount} items     `}</span>
            <Show when={st().spamCount > 0}>
              <span style={{ fg: context.theme.text.feedback.error.base, attributes: TextAttributes.BOLD }}>
                {`${st().spamCount} SPAM LOOP(S) [press C to clean]     `}
              </span>
            </Show>
            <Show when={plan()}>
              {(p) => (
                <span style={{ fg: context.theme.text.feedback.warning.base, attributes: TextAttributes.BOLD }}>
                  {`PLAN ${Object.keys(p().marks).length} marks, ~${tokStr(planSaved(p(), items()))} tok [press A to apply]     `}
                </span>
              )}
            </Show>
            <span style={{ fg: muted() }}>{sessionInfo()?.directory ? context.ui.format.path(sessionInfo()!.directory) : ""}</span>
          </text>
          <box height={1} flexShrink={0} />
          <Show
            when={!zoom()}
            fallback={
              <Show when={selected()} fallback={<text fg={muted()}> No items.</text>}>
                {(it) => <Detail it={it()} ref={(s) => (detail = s)} />}
              </Show>
            }
          >
            <box flexDirection="row" flexGrow={1} minHeight={0}>
              <box flexDirection="column" width={listWidth()} flexShrink={0}>
                <Show when={shown().length} fallback={<text fg={muted()}> No messages in scope.</text>}>
                  <For each={pageRows()}>{(it) => <ItemRow it={it} sel={it.key === selected()?.key} />}</For>
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
                  <Show when={selected()}>{(it) => <Detail it={it()} ref={(s) => (detail = s)} />}</Show>
                </box>
              </Show>
            </box>
          </Show>
          <box flexGrow={1} />
          <box height={1} flexShrink={0} />
          <text wrapMode="none" truncate height={1} flexShrink={0} fg={muted()}>
            {
              "j/k nav   s session   o sort(size/seq)   f scope   e/⏎ vim   x strip   t trunc   c/C clean-spam   A apply-plan   d del   X del-after   space zoom   q close"
            }
          </text>
        </box>
      )
    }

    context.ui.router.register({ name: ROUTE, render: () => <Page /> })
    context.ui.slot({
      append: "app",
      render() {
        context.keymap.layer(() => ({
          mode: "global",
          commands: [
            {
              id: "ctx.toggle",
              title: "Toggle session context editor",
              group: "ctx",
              bind: "<leader>x",
              palette: true,
              slash: { name: "ctx", aliases: ["context-edit"] },
              run: toggle,
            },
          ],
        }))
        return null
      },
    })
  },
})

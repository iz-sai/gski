import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"
import { Database } from "bun:sqlite"

const DB_PATH = join(homedir(), ".local", "share", "opencode", "opencode.db")
export const TMP_DIR = "/tmp/opencode"


export type SessionRow = {
  id: string
  title: string
  directory: string
  agent: string
  model: string
  time_updated: number
  msg_count: number
}

export type ItemKind = "user" | "text" | "reasoning" | "tool" | "synthetic" | "compaction" | "system" | "other"

export type Item = {
  key: string
  msgId: string
  seq: number
  msgType: string
  partIdx: number | null
  kind: ItemKind
  label: string
  chars: number
  preview: string
  detail: string
  editText: string
  editable: boolean
  active: boolean
  spam: boolean
  created: number
}

export const flat = (s: any) => String(s ?? "").replace(/\s+/g, " ").trim()

export function kn(n?: number) {
  n = n || 0
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M"
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k"
  return String(n)
}

export function tokStr(chars?: number) {
  const t = Math.round((chars || 0) / 4)
  if (t < 1000) return "<1k"
  return kn(t)
}

export function ago(ms?: number) {
  if (!ms) return ""
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

export const SPAM_RE = /(\[\]\s*\([^)\n]{0,40}\)\]?){3,}/g

export function hasSpam(s: string) {
  SPAM_RE.lastIndex = 0
  return SPAM_RE.test(s)
}

export function cleanSpamText(s: string) {
  return s.replace(/(\s*\[\]\s*\([^)\n]{0,40}\)\]?){2,}/g, "").trimEnd()
}

export function truncateLines(s: string, keep = 20) {
  const lines = s.split("\n")
  if (lines.length <= keep * 2 + 2) {
    if (s.length <= 2000) return s
    return `${s.slice(0, 800)}\n\n... [truncated ${s.length - 1600} chars] ...\n\n${s.slice(-800)}`
  }
  const omitted = lines.length - keep * 2
  return [...lines.slice(0, keep), `\n... [truncated ${omitted} lines] ...\n`, ...lines.slice(-keep)].join("\n")
}

export function toolOutputText(st: any): string {
  if (!st) return ""
  if (Array.isArray(st.content)) {
    return st.content
      .map((c: any) => (c?.type === "text" ? String(c.text ?? "") : `[${c?.type ?? "part"}]`))
      .join("\n")
  }
  if (st.error) return typeof st.error === "string" ? st.error : JSON.stringify(st.error, null, 2)
  return ""
}

export function toolSummaryInput(inp: any): string {
  if (!inp || typeof inp !== "object") return ""
  return String(
    inp.command || inp.path || inp.filePath || inp.pattern || inp.url || inp.query || inp.description || JSON.stringify(inp),
  )
}

export function openDb(readonly = true) {
  if (!existsSync(DB_PATH)) return undefined
  return new Database(DB_PATH, readonly ? { readonly: true } : { readwrite: true })
}

export function listSessions(limit = 120): SessionRow[] {
  const db = openDb(true)
  if (!db) return []
  try {
    return db
      .query(
        `SELECT s.id, COALESCE(s.title, '') as title, s.directory, COALESCE(s.agent, '') as agent,
                COALESCE(s.model, '') as model, s.time_updated,
                (SELECT count(*) FROM session_message m WHERE m.session_id = s.id) as msg_count
         FROM session_v2 s
         ORDER BY s.time_updated DESC
         LIMIT ?`,
      )
      .all(limit) as SessionRow[]
  } catch {
    return []
  } finally {
    db.close()
  }
}

export function loadSessionItems(sessionID: string): { info?: SessionRow; items: Item[]; compactionSeq: number } {
  const db = openDb(true)
  if (!db) return { items: [], compactionSeq: 0 }
  try {
    const info = db
      .query(
        `SELECT s.id, COALESCE(s.title, '') as title, s.directory, COALESCE(s.agent, '') as agent,
                COALESCE(s.model, '') as model, s.time_updated,
                (SELECT count(*) FROM session_message m WHERE m.session_id = s.id) as msg_count
         FROM session_v2 s WHERE s.id = ?`,
      )
      .get(sessionID) as SessionRow | undefined

    const rows = db
      .query(`SELECT id, type, seq, time_created, data FROM session_message WHERE session_id = ? ORDER BY seq ASC`)
      .all(sessionID) as { id: string; type: string; seq: number; time_created: number; data: string }[]

    let compactionSeq = 0
    let keepID: string | undefined
    for (const r of rows) {
      if (r.type === "compaction") {
        try {
          const d = JSON.parse(r.data)
          if (d.status === "completed" || d.summary) {
            compactionSeq = r.seq
            keepID = d.metadata?.keepID
          }
        } catch {}
      }
    }
    let activeFromSeq = compactionSeq
    if (keepID) {
      const k = rows.find((r) => r.id === keepID)
      if (k && k.seq < activeFromSeq) activeFromSeq = k.seq
    }

    const items: Item[] = []
    for (const r of rows) {
      if (r.type === "idle" || r.type === "agent-switched" || r.type === "model-switched") continue
      let d: any
      try {
        d = JSON.parse(r.data)
      } catch {
        continue
      }
      const active = r.seq >= activeFromSeq
      const created = d?.time?.created || r.time_created

      if (r.type === "user" || r.type === "synthetic" || r.type === "system") {
        const txt = String(d.text ?? "")
        const files = Array.isArray(d.files) && d.files.length ? ` [+${d.files.length} files]` : ""
        const kind: ItemKind = r.type === "user" ? "user" : r.type === "synthetic" ? "synthetic" : "system"
        const src = r.type === "synthetic" && d.metadata?.source ? `:${d.metadata.source}` : ""
        items.push({
          key: `${r.id}:msg`,
          msgId: r.id,
          seq: r.seq,
          msgType: r.type,
          partIdx: null,
          kind,
          label: `${r.type}${src}${files}`,
          chars: txt.length,
          preview: flat(txt) || "(empty)",
          detail: txt,
          editText: txt,
          editable: true,
          active,
          spam: hasSpam(txt),
          created,
        })
      } else if (r.type === "compaction") {
        const txt = String(d.summary ?? "")
        items.push({
          key: `${r.id}:msg`,
          msgId: r.id,
          seq: r.seq,
          msgType: r.type,
          partIdx: null,
          kind: "compaction",
          label: `compaction (${d.status || "done"})`,
          chars: txt.length,
          preview: flat(txt) || "(empty summary)",
          detail: txt,
          editText: txt,
          editable: true,
          active: r.seq >= compactionSeq,
          spam: hasSpam(txt),
          created,
        })
      } else if (r.type === "assistant") {
        const content = Array.isArray(d.content) ? d.content : []
        if (!content.length) {
          const err = d.error ? JSON.stringify(d.error) : "(empty assistant turn)"
          items.push({
            key: `${r.id}:msg`,
            msgId: r.id,
            seq: r.seq,
            msgType: r.type,
            partIdx: null,
            kind: "other",
            label: "asst:empty",
            chars: err.length,
            preview: flat(err),
            detail: err,
            editText: "",
            editable: false,
            active,
            spam: false,
            created,
          })
          continue
        }
        content.forEach((p: any, idx: number) => {
          if (p?.type === "text" || p?.type === "reasoning") {
            const txt = String(p.text ?? "")
            const kind: ItemKind = p.type === "reasoning" ? "reasoning" : "text"
            items.push({
              key: `${r.id}:${idx}`,
              msgId: r.id,
              seq: r.seq,
              msgType: r.type,
              partIdx: idx,
              kind,
              label: p.type === "reasoning" ? "asst:think" : "asst:text",
              chars: txt.length,
              preview: flat(txt) || "(empty)",
              detail: txt,
              editText: txt,
              editable: true,
              active,
              spam: hasSpam(txt),
              created,
            })
          } else if (p?.type === "tool") {
            const st = p.state || {}
            const inpStr = JSON.stringify(st.input ?? {}, null, 2)
            const outStr = toolOutputText(st)
            const cmdPreview = toolSummaryInput(st.input)
            const totalChars = inpStr.length + outStr.length
            const statusTag = st.status && st.status !== "completed" ? ` (${st.status})` : ""
            items.push({
              key: `${r.id}:${idx}`,
              msgId: r.id,
              seq: r.seq,
              msgType: r.type,
              partIdx: idx,
              kind: "tool",
              label: `tool:${p.name || "?"}${statusTag}`,
              chars: totalChars,
              preview: `${flat(cmdPreview)} -> ${flat(outStr.slice(0, 200)) || "(no output)"}`,
              detail: `--- INPUT (${tokStr(inpStr.length)} tok) ---\n${inpStr}\n\n--- OUTPUT (${tokStr(outStr.length)} tok) ---\n${outStr}`,
              editText: outStr,
              editable: true,
              active,
              spam: hasSpam(outStr),
              created,
            })
          }
        })
      }
    }
    return { info, items, compactionSeq }
  } catch {
    return { items: [], compactionSeq: 0 }
  } finally {
    db.close()
  }
}

export function recalcLastAssistantTokens(db: Database, sessionID: string) {
  const rows = db
    .query(`SELECT id, type, seq, data FROM session_message WHERE session_id = ? ORDER BY seq ASC`)
    .all(sessionID) as { id: string; type: string; seq: number; data: string }[]
  if (!rows.length) return
  let compSeq = 0
  let keepID: string | undefined
  for (const r of rows) {
    if (r.type === "compaction") {
      try {
        const d = JSON.parse(r.data)
        if (d.status === "completed" || d.summary) {
          compSeq = r.seq
          keepID = d.metadata?.keepID
        }
      } catch {}
    }
  }
  let fromSeq = compSeq
  if (keepID) {
    const k = rows.find((r) => r.id === keepID)
    if (k && k.seq < fromSeq) fromSeq = k.seq
  }
  let activeChars = 0
  let lastAsst: { id: string; data: any } | undefined
  for (const r of rows) {
    let d: any
    try {
      d = JSON.parse(r.data)
    } catch {
      continue
    }
    if (r.seq >= fromSeq) activeChars += r.data.length
    if (r.type === "assistant" && d.tokens) lastAsst = { id: r.id, data: d }
  }
  if (lastAsst) {
    const estInput = Math.max(256, Math.round(activeChars / 4))
    lastAsst.data.tokens = {
      input: estInput,
      output: lastAsst.data.tokens.output || 0,
      reasoning: lastAsst.data.tokens.reasoning || 0,
      cache: { read: 0, write: 0 },
    }
    db.query(`UPDATE session_message SET data = ? WHERE id = ?`).run(JSON.stringify(lastAsst.data), lastAsst.id)
  }
}

export function mutateItem(item: Item, action: "edit" | "strip" | "truncate" | "clean" | "delete" | "delete_after", newText?: string): string {
  const db = openDb(false)
  if (!db) return "DB not found"
  try {
    const nowMs = Date.now()
    const info = db.query(`SELECT session_id FROM session_message WHERE id = ?`).get(item.msgId) as { session_id: string } | undefined
    if (!info) return "Message not found"
    const sid = info.session_id

    if (action === "delete_after") {
      const res = db.query(`DELETE FROM session_message WHERE session_id = ? AND seq > ?`).run(sid, item.seq)
      recalcLastAssistantTokens(db, sid)
      return `Deleted ${res.changes} messages after #${item.seq}`
    }
    if (action === "delete") {
      if (item.partIdx !== null) {
        const row = db.query(`SELECT data FROM session_message WHERE id = ?`).get(item.msgId) as { data: string } | undefined
        if (!row) return "Message not found"
        const d = JSON.parse(row.data)
        if (Array.isArray(d.content) && d.content.length > 1) {
          d.content.splice(item.partIdx, 1)
          db.query(`UPDATE session_message SET data = ?, time_updated = ? WHERE id = ?`).run(JSON.stringify(d), nowMs, item.msgId)
          recalcLastAssistantTokens(db, sid)
          return `Removed part [${item.partIdx}] from #${item.seq}`
        }
      }
      db.query(`DELETE FROM session_message WHERE id = ?`).run(item.msgId)
      recalcLastAssistantTokens(db, sid)
      return `Deleted message #${item.seq}`
    }

    const row = db.query(`SELECT data FROM session_message WHERE id = ?`).get(item.msgId) as { data: string } | undefined
    if (!row) return "Message not found"
    const d = JSON.parse(row.data)

    const computeText = (orig: string, fallbackStub: string) => {
      if (action === "edit") return newText ?? orig
      if (action === "strip") return fallbackStub
      if (action === "truncate") return truncateLines(orig, 20)
      if (action === "clean") return cleanSpamText(orig)
      return orig
    }

    if (item.partIdx === null) {
      if (item.msgType === "compaction") {
        d.summary = computeText(String(d.summary ?? ""), "[compaction summary cleared]")
      } else {
        d.text = computeText(String(d.text ?? ""), "[cleared]")
      }
    } else {
      const part = d.content?.[item.partIdx]
      if (!part) return "Part not found"
      if (part.type === "text" || part.type === "reasoning") {
        part.text = computeText(String(part.text ?? ""), "[cleared]")
      } else if (part.type === "tool") {
        const st = (part.state ??= {})
        const orig = toolOutputText(st)
        const updated = computeText(orig, "[tool output cleared by user]")
        if (st.status === "error" && st.error) {
          st.error = { type: "tool.execution", message: updated }
        } else {
          st.content = [{ type: "text", text: updated }]
        }
      }
    }

    db.query(`UPDATE session_message SET data = ?, time_updated = ? WHERE id = ?`).run(JSON.stringify(d), nowMs, item.msgId)
    recalcLastAssistantTokens(db, sid)
    return `${action} applied to #${item.seq}`
  } catch (e: any) {
    return `Error: ${e?.message || String(e)}`
  } finally {
    db.close()
  }
}

export type Action = "strip" | "truncate" | "delete"
export type Plan = { sid: string; boundary: number; created: number; marks: Record<string, Action> }

export const ACTIONS: Action[] = ["strip", "truncate", "delete"]
export const KEEP_TAIL = 6
export const MAX_FRAC = 0.6
const ALLOWED: ItemKind[] = ["text", "reasoning", "tool", "synthetic"]

export const itemId = (it: Item) => (it.partIdx === null ? `${it.seq}` : `${it.seq}.${it.partIdx}`)
export const planPath = (sid: string) => join(TMP_DIR, `ctx-${sid}.json`)

export function loadPlan(sid: string): Plan | undefined {
  try {
    return JSON.parse(readFileSync(planPath(sid), "utf8"))
  } catch {
    return undefined
  }
}

export function savePlan(plan: Plan) {
  mkdirSync(TMP_DIR, { recursive: true })
  writeFileSync(planPath(plan.sid), JSON.stringify(plan, null, 2), "utf8")
}

export function clearPlan(sid: string) {
  try {
    unlinkSync(planPath(sid))
  } catch {}
}

export function lastUserSeq(items: Item[]): number | undefined {
  let seq: number | undefined
  for (const it of items) if (it.kind === "user") seq = it.seq
  return seq
}

export function candidates(items: Item[], boundary: number): Item[] {
  const before = items.filter((i) => i.active && i.seq < boundary)
  const tail = new Set([...new Set(before.map((i) => i.seq))].slice(-KEEP_TAIL))
  return before.filter((i) => ALLOWED.includes(i.kind) && !tail.has(i.seq))
}

export function savedChars(it: Item, action: Action): number {
  if (action === "delete") return it.chars
  const to = action === "strip" ? 30 : truncateLines(it.editText, 20).length
  return Math.max(0, it.editText.length - to)
}

export function planSaved(plan: Plan, items: Item[]): number {
  const byId = new Map(items.map((i) => [itemId(i), i]))
  let n = 0
  for (const [id, a] of Object.entries(plan.marks)) {
    const it = byId.get(id)
    if (it) n += savedChars(it, a)
  }
  return n
}

export function deleteFromSeq(sid: string, seq: number): number {
  const db = openDb(false)
  if (!db) return 0
  try {
    const res = db.query(`DELETE FROM session_message WHERE session_id = ? AND seq >= ?`).run(sid, seq)
    recalcLastAssistantTokens(db, sid)
    return res.changes
  } finally {
    db.close()
  }
}

export function applyPlan(sid: string): string {
  const plan = loadPlan(sid)
  if (!plan) return "No pending cleanup plan"
  const items = loadSessionItems(sid).items
  const byId = new Map(items.map((i) => [itemId(i), i]))
  const marks = Object.entries(plan.marks)
    .map(([id, a]) => ({ it: byId.get(id), a }))
    .filter((m): m is { it: Item; a: Action } => !!m.it && m.it.seq < plan.boundary)
  marks.sort((x, y) => x.it.seq - y.it.seq || (y.it.partIdx ?? -1) - (x.it.partIdx ?? -1))
  let ok = 0
  for (const m of marks) if (/applied|Removed|Deleted/.test(mutateItem(m.it, m.a))) ok++
  const total = Object.keys(plan.marks).length
  let tail = "cleanup turn kept (new messages since)"
  if (lastUserSeq(items) === plan.boundary) tail = `removed ${deleteFromSeq(sid, plan.boundary)} cleanup messages`
  clearPlan(sid)
  return `Applied ${ok}/${total} marks, ${tail}`
}

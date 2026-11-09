import {
  ACTIONS,
  KEEP_TAIL,
  MAX_FRAC,
  type Action,
  type Plan,
  candidates,
  clearPlan,
  itemId,
  lastUserSeq,
  loadPlan,
  loadSessionItems,
  planSaved,
  savePlan,
  tokStr,
} from "./lib"

const argv = process.argv.slice(2)
const flag = (name: string) => {
  const i = argv.indexOf(name)
  if (i < 0) return undefined
  const v = argv[i + 1]
  argv.splice(i, 2)
  return v
}
const bool = (name: string) => {
  const i = argv.indexOf(name)
  if (i < 0) return false
  argv.splice(i, 1)
  return true
}
const die = (msg: string): never => {
  console.error(`error: ${msg}`)
  process.exit(1)
}

const sid = flag("--session") || process.env.OPENCODE_SESSION_ID || die("no session (OPENCODE_SESSION_ID unset, use --session)")
const cmd = argv.shift()
const { items } = loadSessionItems(sid)
if (!items.length) die(`session ${sid} not found or empty`)
const boundary = lastUserSeq(items) ?? die("no user message in session")
const cands = candidates(items, boundary)
const byId = new Map(cands.map((i) => [itemId(i), i]))
const activeChars = items.filter((i) => i.active && i.seq < boundary).reduce((a, i) => a + i.chars, 0)
const planLine = (plan: Plan) =>
  `plan: ${Object.keys(plan.marks).length} marks, ~${tokStr(planSaved(plan, items))} tok saved of ~${tokStr(activeChars)} active. Open /ctx and press A to apply.`

if (cmd === "list") {
  const limit = Number(flag("--limit") ?? 40)
  const min = Number(flag("--min") ?? 200) * 4
  const bySeq = bool("--seq")
  const plan = loadPlan(sid)
  let rows = cands.filter((i) => i.chars >= min)
  const eligible = rows.length
  if (!bySeq) rows = [...rows].sort((a, b) => b.chars - a.chars || a.seq - b.seq)
  rows = rows.slice(0, limit)
  if (bySeq) rows.sort((a, b) => a.seq - b.seq || (a.partIdx ?? -1) - (b.partIdx ?? -1))
  console.log(`session ${sid}  active ~${tokStr(activeChars)} tok  cleanup turn starts at #${boundary} (excluded, removed on apply)`)
  console.log(`ID\tKIND\tTOK\tMARK\tPREVIEW`)
  for (const it of rows) {
    const m = plan?.marks[itemId(it)] ?? ""
    console.log(`${itemId(it)}\t${it.label}\t${tokStr(it.chars)}\t${m}\t${it.preview.slice(0, 110)}`)
  }
  console.log(`showing ${rows.length} of ${eligible} eligible (>= ${min / 4} tok); last ${KEEP_TAIL} turns and user messages protected`)
  console.log(`mark: gski ctx mark <id>:<${ACTIONS.join("|")}> ...`)
} else if (cmd === "mark") {
  if (bool("--clear")) {
    clearPlan(sid)
    console.log("plan cleared")
    process.exit(0)
  }
  if (!argv.length) die("usage: mark <id>:<strip|truncate|delete> ...")
  const plan: Plan = loadPlan(sid) ?? { sid, boundary, created: Date.now(), marks: {} }
  plan.boundary = boundary
  const errors: string[] = []
  for (const arg of argv) {
    const [id, action] = arg.split(":")
    if (!ACTIONS.includes(action as Action)) errors.push(`${arg}: action must be ${ACTIONS.join("|")}`)
    else if (!byId.has(id)) errors.push(`${arg}: id not eligible (unknown, protected, or inside cleanup turn)`)
    else plan.marks[id] = action as Action
  }
  if (errors.length) die(errors.join("\n"))
  if (planSaved(plan, items) > activeChars * MAX_FRAC) die(`plan exceeds ${MAX_FRAC * 100}% of active context, mark less`)
  savePlan(plan)
  console.log(planLine(plan))
} else if (cmd === "plan") {
  const plan = loadPlan(sid)
  if (!plan) console.log("no plan")
  else {
    for (const [id, a] of Object.entries(plan.marks)) console.log(`${id}\t${a}`)
    console.log(planLine(plan))
  }
} else {
  die("usage: gski ctx list [--limit N] [--min TOK] [--seq] | mark <id>:<action>... [--clear] | plan")
}

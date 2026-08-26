/**
 * T0.4 — template selection evaluation.
 *
 * Asks the model one question and only one: given a request and the template
 * catalog, which template would you choose and how would you fill it? No
 * recipe, no asset resolution, no render, no GPU. The recipe is JSON, so a
 * plan can be judged without producing a single frame — which is what makes
 * this the cheapest possible answer to "does the catalog work at all".
 *
 * It measures. It does not fix anything it finds.
 *
 *   npx tsx --tsconfig tsconfig.app.json scripts/eval-selection.mjs --out report.json
 *   npx tsx --tsconfig tsconfig.app.json scripts/eval-selection.mjs --limit 2
 *   npx tsx --tsconfig tsconfig.app.json scripts/eval-selection.mjs --dry-run
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { buildTemplateCatalog } from '../src/lib/templateCatalog.ts'
import { NARRATIVE_SCENE_TEMPLATES } from '../src/lib/sceneNarrative.ts'

const args = process.argv.slice(2)
const flag = (name, fallback = null) => {
  const index = args.indexOf(name)
  return index >= 0 ? (args[index + 1] ?? true) : fallback
}
const BASE = flag('--base', 'http://127.0.0.1:42003')
const OUT = flag('--out', '/tmp/eval-selection.json')
const LIMIT = Number(flag('--limit', 0)) || 0
const DRY = args.includes('--dry-run')

const prompts = JSON.parse(readFileSync(new URL('../tests/fixtures/goldenPrompts.json', import.meta.url), 'utf8'))
const catalog = buildTemplateCatalog()
const categoryOf = id => NARRATIVE_SCENE_TEMPLATES.find(template => template.id === id)?.category

const SYSTEM = [
  'You choose a shot template for a 3D/2.5D compositor and fill in its slots.',
  'Choose only from the catalog below. Never invent a template id, a control, or a slot.',
  'Break a request with several ordered actions into several shots, in order.',
  'Use the duration the request asks for. If it asks for none, use the template defaultDuration.',
  '',
  'CATALOG:',
  JSON.stringify(catalog),
].join('\n')

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['shots'],
  properties: {
    shots: {
      type: 'array',
      minItems: 1,
      maxItems: 6,
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['template', 'slots', 'duration'],
        properties: {
          template: { type: 'string', enum: catalog.map(entry => entry.id) },
          slots: {
            type: 'object',
            additionalProperties: false,
            properties: {
              hero: { type: 'string' }, plate: { type: 'string' },
              prop: { type: 'string' }, foreground: { type: 'string' },
            },
          },
          controls: { type: 'object', additionalProperties: true },
          duration: { type: 'number' },
        },
      },
    },
  },
}

/** Models wrap JSON in prose or fences often enough to be worth handling. */
const extractJson = text => {
  const trimmed = String(text).trim()
  try { return JSON.parse(trimmed) } catch { /* fall through to scanning */ }
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (fenced) { try { return JSON.parse(fenced[1]) } catch { /* keep scanning */ } }
  const start = trimmed.indexOf('{')
  if (start < 0) return null
  let depth = 0
  for (let index = start; index < trimmed.length; index += 1) {
    if (trimmed[index] === '{') depth += 1
    else if (trimmed[index] === '}') {
      depth -= 1
      if (depth === 0) { try { return JSON.parse(trimmed.slice(start, index + 1)) } catch { return null } }
    }
  }
  return null
}

/**
 * Last resort when the payload will not parse. Reading the ids straight out
 * of the text separates two failures that look identical from the outside:
 * "the model chose the wrong template" and "the model chose the right one
 * and then emitted broken JSON". Only the first is a catalog problem.
 */
const salvageTemplates = text => [...String(text).matchAll(/"template"\s*:\s*"([a-z0-9-]+)"/g)].map(match => match[1])

const ask = async entry => {
  const response = await fetch(`${BASE}/api/v1/llm/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: entry.prompt,
      system_prompt: SYSTEM,
      max_new_tokens: 1024,
      temperature: 0.2,
      json_schema: SCHEMA,
    }),
    signal: AbortSignal.timeout(120_000),
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status} ${detail.slice(0, 300)}`)
  }
  const body = await response.json()
  return String(body.text || '')
}

const score = (entry, shots) => {
  const accepted = new Set(entry.expects.templateAnyOf)
  const chosen = shots.map(shot => shot.template)
  return {
    chosen,
    top1: chosen.length > 0 && accepted.has(chosen[0]),
    allShotsAccepted: chosen.length > 0 && chosen.every(id => accepted.has(id)),
    shotCountOk: shots.length >= entry.expects.minShots && shots.length <= entry.expects.maxShots,
    durations: shots.map(shot => shot.duration),
    subTenShots: shots.filter(shot => Number(shot.duration) < 10).length,
    totalShots: shots.length,
  }
}

const selected = LIMIT ? prompts.slice(0, LIMIT) : prompts

if (DRY) {
  console.log(`system prompt: ${SYSTEM.length} chars (~${Math.round(SYSTEM.length / 4)} tokens)`)
  console.log(`prompts: ${selected.length}`)
  console.log(`estimated input: ~${Math.round(selected.length * SYSTEM.length / 4 / 1000)}k tokens total`)
  console.log('\n--- first request ---\n')
  console.log(selected[0].prompt)
  process.exit(0)
}

const results = []
for (const [index, entry] of selected.entries()) {
  process.stdout.write(`[${index + 1}/${selected.length}] ${entry.id} … `)
  try {
    const raw = await ask(entry)
    const parsed = extractJson(raw)
    const shots = Array.isArray(parsed?.shots) ? parsed.shots : []
    if (!shots.length) {
      const salvaged = salvageTemplates(raw)
      const accepted = new Set(entry.expects.templateAnyOf)
      results.push({
        id: entry.id, lang: entry.lang, aspect: entry.expects.aspect,
        expected: entry.expects.templateAnyOf,
        contractValid: false, malformed: true,
        salvagedChoice: salvaged,
        salvagedTop1: salvaged.length > 0 && accepted.has(salvaged[0]),
        raw: raw.slice(0, 600),
      })
      console.log(`JSON malformado · rescatado: ${salvaged.join(', ') || 'nada'}`)
      continue
    }
    const scored = score(entry, shots)
    results.push({ id: entry.id, lang: entry.lang, aspect: entry.expects.aspect, expected: entry.expects.templateAnyOf, contractValid: true, ...scored })
    console.log(`${scored.chosen.join(', ')} ${scored.top1 ? 'OK' : 'FALLO'}`)
  } catch (reason) {
    results.push({ id: entry.id, lang: entry.lang, aspect: entry.expects.aspect, error: String(reason?.message || reason) })
    console.log(`error: ${reason?.message || reason}`)
  }
}

const answered = results.filter(item => !item.error)
const valid = answered.filter(item => item.contractValid)
const rate = list => (list.length ? list.filter(item => item.top1).length / list.length : null)
const isConversational = item => (prompts.find(entry => entry.id === item.id)?.expects.templateAnyOf ?? [])
  .some(id => ['dialogue', 'character'].includes(categoryOf(id)))
const allShots = valid.reduce((total, item) => total + item.totalShots, 0)
const subTen = valid.reduce((total, item) => total + item.subTenShots, 0)
const portrait = answered.filter(item => item.aspect === 'portrait')
// Selection accuracy counts a salvaged-but-malformed answer as a correct
// choice, because it was one. Contract compliance counts it as a failure,
// because it was that too. Collapsing them hides which problem we have.
const chosenWell = answered.filter(item => item.top1 || item.salvagedTop1)

const summary = {
  prompts: selected.length,
  answered: answered.length,
  transportErrors: results.length - answered.length,
  malformedJson: answered.filter(item => item.malformed).length,
  contractCompliance: answered.length ? valid.length / answered.length : null,
  selectionTop1: answered.length ? chosenWell.length / answered.length : null,
  selectionTop1DialogueCharacter: answered.filter(isConversational).length
    ? chosenWell.filter(isConversational).length / answered.filter(isConversational).length
    : null,
  dialogueCharacterCount: answered.filter(isConversational).length,
  top1AmongValidOnly: rate(valid),
  shotCountCompliance: valid.length ? valid.filter(item => item.shotCountOk).length / valid.length : null,
  shotsTotal: allShots,
  shotsUnderTenSeconds: subTen,
  shareUnderTenSeconds: allShots ? subTen / allShots : null,
  portraitPrompts: portrait.length,
  portraitPromptsThatSelectedATemplate: portrait.filter(item => (item.chosen?.length || item.salvagedChoice?.length)).length,
}

writeFileSync(OUT, JSON.stringify({ summary, results }, null, 2))
console.log('\n', summary, '\n->', OUT)

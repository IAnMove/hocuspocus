// Real assets for review renders: `scene:review --render --assets plan.json`.
//
// The plan maps slot names to local files. A plain {slot: file} object is the default for every card; the sectioned
// form layers {"default": {...}, "families": {"<family>": {...}}, "cards": {"<id>": {...}}}, later layers winning.
// A layer may also carry "controls" (the card's choice values, duration, bpm...), passed to the compiler as they are.
// Slot names follow the contract (subject_1, subject_2, background, prop_1, prop_2, foreground); the old names
// (hero, plate, prop, foreground) are read too. Files are copied into the sandbox's input directory and served from
// there, like the demo art is served inline: the browser never reads the disk.
import fs from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'

export const SLOT_NAMES = ['subject_1', 'subject_2', 'background', 'prop_1', 'prop_2', 'foreground']
const OLD_NAMES = { hero: 'subject_1', plate: 'background' }
/** Cards whose old `prop` slot is a second person, so `prop` means `subject_2` there. */
const PERSON_PROP_CARDS = new Set(['cinema-two-shot', 'music-duet'])
const KINDS = { '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.webp': 'image', '.glb': 'model3d', '.mp4': 'video', '.webm': 'video' }
const SECTIONS = new Set(['default', 'families', 'cards'])

const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value)

/** The cards to render, read from the catalog module at run time: every listed card, or the given IDs (any ID the
 * catalog resolves, so an alias renders as its surviving card with its preset). */
export function selectCards(catalog, templateIds = []) {
  if (!templateIds.length) return catalog.ALL_SCENE_TEMPLATES.map(template => ({ id: template.id, template }))
  const cards = []
  const unknown = []
  for (const id of new Set(templateIds)) {
    try {
      cards.push({ id, template: catalog.getCandidateSceneTemplate(id) })
    } catch (error) {
      unknown.push(`${id} (${error instanceof Error ? error.message : String(error)})`)
    }
  }
  if (unknown.length) throw new Error(`Unknown scene template ID(s): ${unknown.join(', ')}`)
  return cards
}

/** The contract's name for a slot on this card: old names are translated once, new names stay. */
export function canonicalSlot(cardId, slot) {
  if (slot === 'prop') return PERSON_PROP_CARDS.has(cardId) ? 'subject_2' : 'prop_1'
  return OLD_NAMES[slot] ?? slot
}

export function assetKind(file) {
  return KINDS[path.extname(file).toLowerCase()]
}

/** {slot: file} in one layer of the plan, by canonical name. An old and a new name for one slot is a conflict. */
function layerSlots(entry, cardId, where) {
  const slots = {}
  const given = {}
  for (const [name, file] of Object.entries(entry)) {
    if (name === 'controls') continue
    const slot = canonicalSlot(cardId, name)
    if (!SLOT_NAMES.includes(slot)) throw new Error(`${where}: unknown slot “${name}”; use ${SLOT_NAMES.join(', ')} (or hero, plate, prop)`)
    if (typeof file !== 'string' || !file.trim()) throw new Error(`${where}.${name} must be a file path`)
    if (given[slot]) throw new Error(`slot_alias_conflict: ${where} gives both “${given[slot]}” and “${name}” for ${slot}`)
    given[slot] = name
    slots[slot] = file
  }
  return slots
}

function checkLayer(entry, where) {
  if (!isObject(entry)) throw new Error(`${where} must be an object of slot names to files`)
  if (entry.controls !== undefined && !isObject(entry.controls)) throw new Error(`${where}.controls must be an object`)
  layerSlots(entry, 'any-card', where)
}

function checkSection(section, where) {
  if (section === undefined) return {}
  if (!isObject(section)) throw new Error(`${where} must be an object`)
  for (const [key, entry] of Object.entries(section)) checkLayer(entry, `${where}.${key}`)
  return section
}

/** Read and check the plan; paths resolve against the plan file's folder. */
export async function readAssetPlan(file) {
  const absolute = path.resolve(file)
  let raw
  try {
    raw = JSON.parse(await fs.readFile(absolute, 'utf8'))
  } catch (error) {
    throw new Error(`--assets ${file}: ${error instanceof Error ? error.message : String(error)}`)
  }
  if (!isObject(raw)) throw new Error(`--assets ${file} must hold a JSON object`)
  const sectioned = Object.keys(raw).some(key => SECTIONS.has(key))
  if (sectioned) {
    const unknown = Object.keys(raw).filter(key => !SECTIONS.has(key))
    if (unknown.length) throw new Error(`--assets ${file}: unknown section(s) ${unknown.join(', ')}; use default, families and cards`)
  }
  const plan = {
    file: absolute,
    base: path.dirname(absolute),
    default: sectioned ? raw.default ?? {} : raw,
    families: sectioned ? checkSection(raw.families, 'families') : {},
    cards: sectioned ? checkSection(raw.cards, 'cards') : {},
  }
  checkLayer(plan.default, 'default')
  return plan
}

/** The files and controls one card gets: default, then its family, then the card itself. */
export function cardAssets(plan, cardId, template) {
  const own = template.slots.map(slot => canonicalSlot(cardId, slot.id))
  const layers = [['default', plan.default], [`families.${template.family}`, plan.families[template.family]], [`cards.${cardId}`, plan.cards[cardId]]]
  const files = {}
  const controls = {}
  for (const [where, entry] of layers) {
    if (!entry) continue
    const slots = layerSlots(entry, cardId, where)
    const foreign = where.startsWith('cards.') ? Object.keys(slots).filter(slot => !own.includes(slot)) : []
    if (foreign.length) throw new Error(`${where}: ${cardId} has no slot ${foreign.join(', ')} (its slots: ${template.slots.map(slot => slot.id).join(', ')})`)
    Object.assign(files, slots)
    Object.assign(controls, entry.controls ?? {})
  }
  const assets = []
  const missing = []
  for (const slot of template.slots) {
    const file = files[canonicalSlot(cardId, slot.id)]
    if (!file) {
      if (slot.required) missing.push(slot.id)
      continue
    }
    const absolute = path.resolve(plan.base, file)
    const type = assetKind(absolute)
    if (!type) throw new Error(`${cardId}: ${file} is not a picture (png, jpg, webp), a GLB or a video (mp4, webm)`)
    if (!slot.kinds.includes(type)) throw new Error(`${cardId}: slot ${slot.id} takes ${slot.kinds.join(' or ')}, not ${type} (${file})`)
    assets.push({ slot: slot.id, file: absolute, type })
  }
  if (missing.length) {
    throw new Error(`${cardId}: no asset for the required slot(s) ${missing.join(', ')}; give it in default, families.${template.family} or cards.${cardId}`)
  }
  return { assets, controls }
}

async function sha256File(file) {
  return createHash('sha256').update(await fs.readFile(file)).digest('hex')
}

/** Copy each file once into the sandbox inputs (named by its content) and register it; returns file -> served entry. */
export async function stageAssets(server, files, staged = new Map()) {
  for (const file of files) {
    if (staged.has(file)) continue
    const stat = await fs.lstat(file).catch(() => null)
    if (!stat?.isFile()) throw new Error(`Asset is not a regular file: ${file}`)
    const sha256 = await sha256File(file)
    const name = `asset-${sha256.slice(0, 16)}${path.extname(file).toLowerCase()}`
    const twin = [...staged.values()].find(entry => entry.name === name)
    if (twin) { staged.set(file, twin); continue }
    await fs.copyFile(file, path.join(server.inputsDir, name), fs.constants.COPYFILE_EXCL)
    const registered = await server.registerInput(name)
    staged.set(file, { ...registered, sha256 })
  }
  return staged
}

/** Compiler bindings for the card's own slot names, served from the sandbox. */
export function bindingsFor(assets, staged) {
  return Object.fromEntries(assets.map(asset => [asset.slot, { source: staged.get(asset.file).url, type: asset.type, name: path.basename(asset.file) }]))
}

// Project the Video 3D shot library into a short shared catalog. Full documents stay in the UI builders.
import { writeFileSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { TEMPLATE_VARIANT_GROUPS } from '../src/features/scene3d/templateCatalog.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

const outPath = fileURLToPath(new URL('../../app/shared/world3d_templates.json', import.meta.url))
const en = JSON.parse(readFileSync(new URL('../src/i18n/locales/en/scene3dEditor.json', import.meta.url), 'utf8'))
const es = JSON.parse(readFileSync(new URL('../src/i18n/locales/es/scene3dEditor.json', import.meta.url), 'utf8'))
const techniques = JSON.parse(readFileSync(new URL('../src/features/scene3d/cinematicTechniques.json', import.meta.url), 'utf8'))
const techniqueById = new Map(techniques.map(entry => [entry.id, entry]))
const templateById = new Map(SCENE3D_TEMPLATES.map(item => [item.id, item]))
const variantOf = new Map()
for (const group of TEMPLATE_VARIANT_GROUPS) {
  for (const id of group.slice(1)) variantOf.set(id, group[0])
}

function line(text, fallback) {
  const value = (text || fallback || '').replace(/\s+/g, ' ').trim()
  return value.length > 180 ? `${value.slice(0, 177)}...` : value
}

function card(id) {
  const template = templateById.get(id)
  if (!template) throw new Error(`missing template row ${id}`)
  const document = applyScene3DTemplate(id)
  const technique = techniqueById.get(id)
  const copyEn = en.template?.[id] || {}
  const copyEs = es.template?.[id] || {}
  const titleEn = copyEn.title || technique?.name || id
  const titleEs = copyEs.title || technique?.titleEs || titleEn
  const required = document.slots
    .filter(slot => !slot.sourceUrl)
    .map(slot => ({ id: slot.id, role: slot.slot, media: slot.media }))
  const dependencies = []
  for (const cue of document.worldSfx || []) dependencies.push(`worldSfx:${cue.kind}`)
  if (document.renderLook) dependencies.push(`renderLook:${document.renderLook}`)
  if (document.environment?.reflectiveFloor) dependencies.push('reflectiveFloor')
  return {
    id,
    titleEs,
    titleEn,
    category: TEMPLATE_CATEGORIES[id],
    family: technique?.category || template.camera,
    variantOf: variantOf.get(id) || null,
    format: document.height > document.width ? 'portrait' : 'landscape',
    width: document.width,
    height: document.height,
    duration: document.duration,
    playbackSpeed: document.playbackSpeed || 1,
    dressing: document.dressing || null,
    setting: settingFromDressing(document.dressing),
    lineEs: line(copyEs.description || technique?.descriptionEs, titleEs),
    lineEn: line(copyEn.description || technique?.descriptionEn, titleEn),
    preview: technique?.thumbUrl || null,
    roles: document.slots.map(slot => slot.slot),
    required,
    dependencies,
    tags: template.tags || [],
    source: 'builtin',
  }
}

const catalog = {
  version: 1,
  source: 'ui/src/features/scene3d/templates.ts',
  catalog: SCENE3D_TEMPLATE_IDS.map(card),
}
if (new Set(catalog.catalog.map(item => item.id)).size !== SCENE3D_TEMPLATE_IDS.length) {
  throw new Error('duplicate template id')
}
const encoded = `${JSON.stringify(catalog, null, 2)}\n`
if (process.argv.includes('--check')) {
  const current = readFileSync(outPath, 'utf8')
  if (current !== encoded) {
    process.stderr.write('world3d_templates.json does not match the UI library\n')
    process.exit(1)
  }
  process.stdout.write(`ok ${catalog.catalog.length}\n`)
} else {
  writeFileSync(outPath, encoded)
  process.stdout.write(`wrote ${catalog.catalog.length}\n`)
}

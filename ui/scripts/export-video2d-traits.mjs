// Derive the traits of every Video 2D scene template from its compiled document (contract §10).
// Each card in app/shared/scene_templates.json is compiled at its defaults through the same Node bridge MCP uses, with
// one placeholder picture per slot, and its layers are sampled over the shot by the real evaluator.
// `--check` fails when app/shared/video2d_template_traits.json no longer matches the cards.
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { compilePayload } from './video2dCompile.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { slotRole, templateTraits2d } from './video2dTemplateTraits.ts'

const catalogPath = fileURLToPath(new URL('../../app/shared/scene_templates.json', import.meta.url))
const outPath = fileURLToPath(new URL('../../app/shared/video2d_template_traits.json', import.meta.url))
const PLACEHOLDER_ROOT = '/examples/video2d-traits'
// The first media a slot accepts, in this order, decides the placeholder: cutouts and plates are pictures.
const PLACEHOLDER_EXTENSIONS = [['image', 'png'], ['model3d', 'glb'], ['video', 'mp4']]

/** One durable placeholder per slot, so every compiled layer can be traced back to the slot it shows. */
function placeholders(entry) {
  return Object.fromEntries(entry.slots.map(slot => {
    const found = PLACEHOLDER_EXTENSIONS.find(([type]) => slot.types.includes(type))
    if (!found) throw new Error(`${entry.id}: slot ${slot.id} accepts no media the exporter knows (${slot.types.join(', ')})`)
    return [slot.id, `${PLACEHOLDER_ROOT}/${slot.id}.${found[1]}`]
  }))
}

/** Camera, particles (atmospheres and the template's own graphics) or the role of the slot whose picture it shows. */
function layerRoles(scene, assets) {
  const slotBySource = new Map(Object.entries(assets).map(([slot, source]) => [source, slot]))
  return new Map(scene.layers.map(layer => {
    if (layer.type === 'camera') return [layer.id, 'camera']
    const slot = slotBySource.get(layer.source)
    if (!slot || layer.atmosphere || layer.type === 'effect') return [layer.id, 'particles']
    return [layer.id, slotRole(slot)]
  }))
}

function traitsOf(entry) {
  const assets = placeholders(entry)
  const compiled = compilePayload({ operation: 'scenes.template.compile', input: { templateId: entry.id, assets } })
  if (!compiled.ok) throw new Error(`${entry.id} does not compile at its defaults: ${compiled.code} ${compiled.message}`)
  const scene = normalizeScene2D(compiled.result.document)
  const hints = { id: entry.id, family: entry.family, slots: entry.slots.map(slot => slot.id), roles: layerRoles(scene, assets) }
  return templateTraits2d(scene, hints)
}

const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'))
const templates = Object.fromEntries(catalog.entries.map(entry => [entry.id, traitsOf(entry)]))
const encoded = `${JSON.stringify({ version: 1, templates }, null, 2)}\n`
const count = Object.keys(templates).length
if (process.argv.includes('--check')) {
  let current = ''
  try {
    current = readFileSync(outPath, 'utf8')
  } catch {
    current = ''
  }
  if (current !== encoded) {
    process.stderr.write('video2d_template_traits.json does not match the compiled scene templates: run node --import tsx scripts/export-video2d-traits.mjs\n')
    process.exit(1)
  }
  process.stdout.write(`ok ${count}\n`)
} else {
  writeFileSync(outPath, encoded)
  process.stdout.write(`wrote ${count}\n`)
}

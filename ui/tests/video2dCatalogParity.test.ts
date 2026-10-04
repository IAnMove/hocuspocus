import assert from 'node:assert/strict'
import { test } from 'node:test'
import atmospheres from '../../app/shared/atmospheres.json' with { type: 'json' }
import finishCatalog from '../../app/shared/finish_presets.json' with { type: 'json' }
import fonts from '../../app/shared/fonts.json' with { type: 'json' }
import motion from '../../app/shared/motion_presets.json' with { type: 'json' }
import templates from '../../app/shared/scene_templates.json' with { type: 'json' }
import textCatalog from '../../app/shared/text_templates.json' with { type: 'json' }
import {
  ALL_SCENE_TEMPLATES,
  CANDIDATE_SCENE_TEMPLATES,
  MUSIC_MOTION_TEMPLATES,
  VIDEO2D_SCENE_TEMPLATES,
} from '../src/features/sceneTemplates/catalog.ts'
import { MUSIC_MOTION_TEMPLATES as REEXPORTED_MUSIC } from '../src/features/sceneTemplates/musicMotionCatalog.ts'
import { TEXT_FONT_STACK } from '../src/lib/kineticText/fonts.ts'
import { TEXT_TEMPLATES, buildTextTemplate } from '../src/lib/kineticText/templates.ts'
import { TEXT_FONTS } from '../src/lib/kineticText/types.ts'
import { ATMOSPHERE_KINDS, ATMOSPHERE_OPACITY, ATMOSPHERE_PRESETS } from '../src/lib/scene2d/layerStyle.ts'
import { FINISH_PRESETS } from '../src/lib/scene2d/finish.ts'
import { RECIPE_CAMERA_PRESETS, RECIPE_MOTION_PRESETS } from '../src/lib/sceneRecipe.ts'

const ids = (entries: readonly { id: string }[]) => entries.map(entry => entry.id)
const byGroup = (group: string) => templates.entries.filter(entry => entry.group === group)

test('shared JSON catalog ids match the TypeScript modules', () => {
  assert.deepEqual(ids(CANDIDATE_SCENE_TEMPLATES), ids(byGroup('candidate')))
  assert.deepEqual(ids(VIDEO2D_SCENE_TEMPLATES), ids(byGroup('video2d')))
  assert.deepEqual(ids(MUSIC_MOTION_TEMPLATES), ids(byGroup('music-motion')))
  assert.deepEqual(ids(REEXPORTED_MUSIC), ids(MUSIC_MOTION_TEMPLATES))
  assert.deepEqual(ids(ALL_SCENE_TEMPLATES), [...ids(CANDIDATE_SCENE_TEMPLATES), ...ids(MUSIC_MOTION_TEMPLATES)])
  for (const template of [...CANDIDATE_SCENE_TEMPLATES, ...VIDEO2D_SCENE_TEMPLATES, ...MUSIC_MOTION_TEMPLATES]) {
    const entry = templates.entries.find(item => item.id === template.id)
    assert.ok(entry)
    assert.equal(template.status, entry.reviewStatus)
    assert.equal(template.family, entry.family)
    assert.equal(template.description, entry.visualIntent)
    assert.equal(template.promptExample, entry.example)
    assert.deepEqual([...template.limits], [...entry.limits])
    assert.deepEqual(
      template.slots.map(slot => ({ id: slot.id, types: [...slot.kinds], required: slot.required })),
      entry.slots.map(slot => ({ id: slot.id, types: [...slot.types], required: slot.required })),
    )
  }

  assert.deepEqual(ids(TEXT_TEMPLATES), ids(textCatalog.entries))
  assert.deepEqual(
    TEXT_TEMPLATES.map(item => item.fields.map(field => ({ key: field.key, default: field.default }))),
    textCatalog.entries.map(item => item.fields.map(field => ({ key: field.key, default: field.default }))),
  )
  assert.ok(textCatalog.entries.every(item => item.formats.includes('16:9') && item.formats.includes('9:16')))
  const frame = { start: 0, duration: 2, width: 1920, height: 1080 }
  const tall = { ...frame, width: 1080, height: 1920 }
  assert.equal(buildTextTemplate('lower-third-date', {}, frame)[0].y, 70)
  assert.equal(buildTextTemplate('lower-third-date', {}, tall)[0].y, 64)

  assert.deepEqual(Object.keys(FINISH_PRESETS), ids(finishCatalog.entries))
  for (const entry of finishCatalog.entries) {
    const { id, ...preset } = entry
    assert.deepEqual(FINISH_PRESETS[id], preset)
  }

  const motions = motion.entries.filter(entry => entry.kind === 'motion')
  const cameras = motion.entries.filter(entry => entry.kind === 'camera')
  assert.deepEqual(Object.keys(RECIPE_MOTION_PRESETS), ids(motions))
  assert.deepEqual(Object.keys(RECIPE_CAMERA_PRESETS), ids(cameras))
  for (const entry of motion.entries) {
    const preset = entry.kind === 'camera' ? RECIPE_CAMERA_PRESETS[entry.id] : RECIPE_MOTION_PRESETS[entry.id]
    assert.equal(preset.spin, entry.spin)
    assert.equal(preset.duration, entry.duration)
    assert.equal(preset.curve, entry.curve)
    assert.deepEqual(preset.start, entry.start)
    assert.deepEqual(preset.end, entry.end)
    if (entry.kind === 'camera') assert.deepEqual(preset.shake, entry.shake)
  }

  assert.deepEqual([...ATMOSPHERE_KINDS], ids(atmospheres.entries))
  for (const entry of atmospheres.entries) {
    assert.equal(ATMOSPHERE_OPACITY[entry.id], entry.opacity)
    assert.deepEqual(ATMOSPHERE_PRESETS[entry.id], {
      kind: entry.id, density: entry.density, speed: entry.speed, size: entry.size, wind: entry.wind, color: entry.color,
    })
  }

  const roles = fonts.entries.filter(entry => entry.kineticRole)
  assert.deepEqual(Object.keys(TEXT_FONT_STACK), [...TEXT_FONTS])
  assert.deepEqual(Object.keys(TEXT_FONT_STACK), roles.map(entry => entry.kineticRole))
  for (const entry of roles) {
    assert.equal(TEXT_FONT_STACK[entry.kineticRole as (typeof TEXT_FONTS)[number]], entry.stack)
  }
})

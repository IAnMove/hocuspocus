import assert from 'node:assert/strict'
import test from 'node:test'
import textCatalog from '../../app/shared/text_templates.json' with { type: 'json' }
import { kineticTextState } from '../src/lib/kineticText/state.ts'
import { buildTextTemplate, TEXT_TEMPLATES } from '../src/lib/kineticText/templates.ts'
import type { KineticText } from '../src/lib/kineticText/types.ts'

const FRAME = { start: 0.4, duration: 3.2, width: 1280, height: 720 }
const defaults = (id: string) => Object.fromEntries(TEXT_TEMPLATES.find(item => item.id === id)!.fields.map(field => [field.key, field.default || field.key]))
const built = (id: string) => buildTextTemplate(id, defaults(id), FRAME)
/** How much of the cue shows: a fade lowers the opacity, a wipe the clip. */
const opacity = (cue: KineticText, seconds: number) => {
  const state = kineticTextState(cue, seconds)
  return state && 'opacity' in state ? state.opacity * state.clip : 0
}
const coversFrame = (cue: KineticText) => cue.box?.kind === 'plate' && cue.box.opacity === 1

test('every template leaves before its end, with an exit written on every cue', () => {
  for (const template of TEXT_TEMPLATES) {
    const cues = built(template.id)
    assert.ok(cues.length > 0, template.id)
    for (const cue of cues) {
      assert.ok(cue.exit, `${template.id}/${cue.id} has an exit`)
      assert.ok(cue.end <= FRAME.start + FRAME.duration + 0.1, `${template.id}/${cue.id} ends with the template`)
    }
    const last = Math.max(...cues.map(cue => cue.end))
    const leaving = cues.filter(cue => cue.end === last)
    assert.ok(leaving.every(cue => cue.exit!.preset !== 'none' && opacity(cue, last - 0.02) < 0.5), `${template.id} is on its way out at the end`)
  }
})

test('chapter, end card and social caption enter instead of popping in', () => {
  for (const id of ['chapter', 'end-card', 'social-caption']) {
    for (const cue of built(id)) {
      assert.ok(cue.enter && cue.enter.preset !== 'none', `${id}/${cue.id}`)
      assert.ok(opacity(cue, cue.start + 0.01) < 1 || cue.enter.preset === 'wipe' || cue.enter.preset === 'typewriter', `${id}/${cue.id} starts hidden`)
    }
  }
  const [kicker, title] = built('chapter')
  assert.ok(title.start > kicker.start, 'the chapter title follows its kicker')
  const [end, cta] = built('end-card')
  assert.equal(end.enter?.preset, 'rise')
  assert.ok(cta.start > end.start && cta.loop === 'pulse', 'the call to action follows the title and pulses')
})

test('covers stays honest: only title-card and trailer-slam paint an opaque plate, and it never lets the picture through', () => {
  const covering = textCatalog.entries.filter(entry => 'covers' in entry && entry.covers === true).map(entry => entry.id)
  assert.deepEqual(covering, ['title-card', 'trailer-slam'])
  for (const template of TEXT_TEMPLATES) {
    assert.equal(built(template.id).some(coversFrame), covering.includes(template.id), template.id)
  }
  for (const id of covering) {
    const plates = built(id).filter(coversFrame)
    const first = plates[0]
    const from = first.start + (first.enter?.duration ?? 0) / 5 + 0.01 // an entrance reaches full opacity in its first fifth
    const to = Math.max(...plates.map(cue => cue.end - (cue.exit?.duration ?? 0)))
    for (let seconds = from; seconds < to; seconds += 1 / 60) {
      assert.ok(plates.some(cue => opacity(cue, seconds) >= 0.999), `${id} covers the frame at ${seconds.toFixed(3)}`)
    }
  }
})

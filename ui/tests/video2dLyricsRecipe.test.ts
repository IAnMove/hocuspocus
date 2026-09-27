import assert from 'node:assert/strict'
import test from 'node:test'
import { compileSceneRecipe, EXAMPLE_SAUCER_CRUISE_RECIPE, parseSceneRecipe } from '../src/lib/sceneRecipe.ts'

test('a recipe compiles stored lyrics and text templates into the scene', () => {
  const raw = JSON.parse(JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE)) as Record<string, unknown>
  raw.textTemplates = [{ id: 'chapter', values: { kicker: '01', title: 'Harbour' } }]
  const sceneRaw = raw.scene as Record<string, unknown>
  sceneRaw.lyrics = { mode: 'word-pop', lines: [{ id: 'line', start: 0.2, end: 1.2, words: [{ text: 'Bird', start: 0.2, end: 1.2 }] }], style: { font: 'sans', size: 6, color: '#ffffff', activeColor: '#ffdd88', x: 50, y: 70, maxWidth: 80, align: 'center', visibleLines: 1 } }
  const recipe = parseSceneRecipe(raw)
  const scene = compileSceneRecipe(recipe, { stars: 'stars.png', saucer: 'saucer.glb' }, filename => `/api/v1/file/${filename}`)
  assert.equal(scene.lyrics?.mode, 'word-pop')
  assert.ok(scene.texts?.some(cue => cue.template === 'chapter' && cue.text === 'Harbour'))
})

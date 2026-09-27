import assert from 'node:assert/strict'
import test from 'node:test'
import { compileVideo2dCandidate, VIDEO2D_CANDIDATE_IDS } from '../src/features/sceneTemplates/video2dCandidates.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { CANDIDATE_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog.ts'

test('the four video 2D candidates stay unapproved and normalize', () => {
  for (const id of VIDEO2D_CANDIDATE_IDS) {
    const scene = normalizeScene2D(compileVideo2dCandidate(id))
    assert.equal(scene.version, 1)
    assert.ok(scene.layers.length >= 1)
    const card = CANDIDATE_SCENE_TEMPLATES.find(template => template.id === id)
    assert.equal(card?.status, 'candidate')
  }
  const lyric = normalizeScene2D(compileVideo2dCandidate('lyric-vertical'))
  assert.equal(lyric.width, 1080)
  assert.equal(lyric.height, 1920)
  assert.equal(lyric.lyrics?.style.beatPulse, 0.35)
  assert.ok(lyric.rhythm && lyric.rhythm.beats.length > 0)
  const postcard = normalizeScene2D(compileVideo2dCandidate('city-postcard'))
  assert.ok((postcard.layers[0].animation.path?.points.length ?? 0) >= 2)
  const trailer = normalizeScene2D(compileVideo2dCandidate('trailer-teaser'))
  assert.equal(trailer.finish?.letterbox?.ratio, 2.39)
  const history = normalizeScene2D(compileVideo2dCandidate('documentary-history'))
  assert.ok(history.texts?.some(cue => cue.template === 'year-counter'))
})

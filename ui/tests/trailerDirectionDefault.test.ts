import assert from 'node:assert/strict'
import test from 'node:test'
import { DEFAULT_TRAILER_DIRECTION, LEGACY_SPANISH_TRAILER_DIRECTION } from '../src/features/stories/adaptations'
import { normalizeStoryProductionRecipe } from '../src/features/stories/storyProductionRecipe'

test('saved recipes holding the old Spanish trailer default are upgraded; custom text is kept', () => {
  assert.match(DEFAULT_TRAILER_DIRECTION, /^Sell the emotional promise/)
  assert.equal(normalizeStoryProductionRecipe({ trailerDirection: LEGACY_SPANISH_TRAILER_DIRECTION }).trailerDirection, DEFAULT_TRAILER_DIRECTION)
  assert.equal(normalizeStoryProductionRecipe({ trailerDirection: 'Mi propio tráiler' }).trailerDirection, 'Mi propio tráiler')
})

import assert from 'node:assert/strict'
import test from 'node:test'

test('Story Lab L9 shells expose the target tabs and keep L8 aliases', async () => {
  const { storyLabTabIds } = await import('../src/features/stories/storyLabTabs.ts')
  const { resolveStoryLabNavigation } = await import('../src/features/stories/labNavigation.ts')

  assert.deepEqual(storyLabTabIds('full_story'), [
    'overview', 'world', 'structure', 'music', 'productions', 'assembly',
  ])
  assert.deepEqual(storyLabTabIds('music_video'), [
    'overview', 'music', 'productions', 'assembly',
  ])
  assert.deepEqual(storyLabTabIds('trailer'), [
    'overview', 'assets', 'trailer', 'assembly',
  ])
  assert.deepEqual(storyLabTabIds('quick_video'), [
    'overview', 'productions', 'assembly',
  ])

  const universe = resolveStoryLabNavigation('assets', 'full_story')
  assert.equal(universe.ok, true)
  assert.equal(universe.tab, 'world')
  assert.equal(universe.anchor, 'story-review-assets')
  assert.equal(universe.equivalent, true)

  const trailerRecipe = resolveStoryLabNavigation('trailer', 'full_story')
  assert.equal(trailerRecipe.ok, true)
  assert.equal(trailerRecipe.tab, 'productions')
  assert.equal(trailerRecipe.equivalent, true)

  const musicAssets = resolveStoryLabNavigation('assets', 'music_video')
  assert.equal(musicAssets.ok, true)
  assert.equal(musicAssets.tab, 'overview')
  assert.equal(musicAssets.equivalent, true)

  const quickAssets = resolveStoryLabNavigation('assets', 'quick_video')
  assert.equal(quickAssets.ok, true)
  assert.equal(quickAssets.tab, 'overview')
})

test('T2V production issues do not demand images; image-guided and refs still block', async () => {
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const { emptyCharacter } = await import('../src/features/stories/storyLabEditors.ts')
  const { collectStoryProductionIssues } = await import('../src/features/stories/storyProductionIssues.ts')
  const { assertStoryVisualRecipeReady } = await import('../src/features/stories/storyVisualGuidance.ts')
  const t = (key, options) => key === 'issues.reviewIdentities'
    ? `identities:${options.names}`
    : key

  const film = createStoryProject('full_story')
  film.workflowMode = 'automatic'
  film.musicVideoGenerationMode = 'direct_video'
  film.characters = [{ ...emptyCharacter('Hero'), id: 'hero', approval: 'approved' }]
  assert.equal(collectStoryProductionIssues(film, 'direct_video', t).length, 0)
  assert.doesNotThrow(() => assertStoryVisualRecipeReady(film))

  film.musicVideoGenerationMode = 'image_guided'
  const imageIssues = collectStoryProductionIssues(film, 'image_guided', t)
  assert.ok(imageIssues.some(issue => issue.id === 'recipe:identities'))
  assert.throws(() => assertStoryVisualRecipeReady(film), /visual identities/)

  film.musicVideoGenerationMode = 'direct_references'
  const refIssues = collectStoryProductionIssues(film, 'direct_references', t)
  assert.ok(refIssues.some(issue => issue.id === 'recipe:references'))
  assert.throws(() => assertStoryVisualRecipeReady(film), /reference/)
})

test('project-local generate recipe survives normalize and is independent of Studio globals', async () => {
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const { patchFilmDuration, filmDurationOf } = await import('../src/features/stories/storyProductionRecipe.ts')

  const story = createStoryProject('full_story')
  story.productionRecipe.filmDurationSeconds = 120
  story.productionRecipe.filmDirection = 'Keep the dock incident self-contained.'
  const restored = normalizeStoryProject({
    ...story,
    productionRecipe: {
      filmDurationSeconds: 120,
      filmDirection: 'Keep the dock incident self-contained.',
    },
  })
  assert.equal(restored.productionRecipe.filmDurationSeconds, 120)
  assert.match(restored.productionRecipe.filmDirection, /dock incident/)
  assert.equal(filmDurationOf(restored), 120)

  const quick = createStoryProject('quick_video')
  const patched = { ...quick, ...patchFilmDuration(quick, 40) }
  assert.equal(patched.creativeBrief.durationSeconds, 40)
  assert.equal(filmDurationOf(patched), 40)
})

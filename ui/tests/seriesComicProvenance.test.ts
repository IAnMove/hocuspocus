import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

import { normalizeComicProject } from '../src/features/comics/model.ts'
import { resolveComicSource, resolveSeriesEpisodeById } from '../src/features/comics/provenance.ts'
import { panelIdentityReference } from '../src/features/comics/generateArtwork.ts'
import { buildSeriesComicHandoff } from '../src/features/series/comicHandoff.ts'
import type { SeriesAsset, SeriesCharacter, SeriesEpisode, SeriesLibrary, SeriesProject } from '../src/features/series/types.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/',
})
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: dom.window.navigator,
})

function episode(id: string, title: string, beatCount = 1): SeriesEpisode {
  return {
    id,
    seasonId: 'season-1',
    number: 1,
    title,
    premise: `${title} premise`,
    logline: `${title} logline`,
    targetDurationSeconds: 30,
    status: 'outline',
    canonRevisionAtCreation: 2,
    canonSnapshot: { revision: 2 },
    outline: { beats: Array.from({ length: beatCount }, (_, index) => `${title} beat ${index + 1}`) },
    script: [],
    shots: [],
    proposedCanonDelta: { baseRevision: 2, sourceEpisodeId: id, add: [], change: [], retire: [] },
    productionIds: ['production-source-1'],
    createdAt: '2026-09-03T10:00:00.000Z',
    updatedAt: '2026-09-03T10:05:00.000Z',
  }
}

function series(id: string, episodeId: string, title = 'Same title'): SeriesProject {
  return {
    id,
    version: 1,
    revision: 7,
    title,
    logline: '',
    premise: `${title} premise`,
    format: 'episodic',
    defaultEpisodeDurationSeconds: 30,
    language: 'Español',
    spokenLanguage: 'Español',
    languageIntent: {
      contentLanguage: 'Español',
      spokenLanguage: 'Español',
      technicalPromptLanguage: 'en',
      verbatimSegments: [],
    },
    protagonistConsistency: true,
    protagonistCharacterId: '',
    genre: 'Drama',
    tone: 'Cinematic',
    audience: 'General',
    visualStyle: 'Editorial ink and muted colour',
    characterVisualStyle: '',
    cameraLanguage: '',
    allowClipText: false,
    sourceMode: 'original',
    masterUniversePrompt: '',
    rightsNote: '',
    bestEffortLipSyncAcknowledged: false,
    importSource: {
      kind: 'original', sourceWorkspaceId: null, sourceStoryId: null,
      importedAt: '2026-09-03T10:00:00.000Z', historicalProductionIds: [], migrationNotes: '',
    },
    canon: {
      worldSummary: 'A persistent fictional world', immutableRules: [], currentFacts: [],
      forbiddenChanges: [], themes: [], longArcs: [], timeline: [], revision: 7, approval: 'approved',
    },
    characters: [], relationships: [], locations: [], props: [], seasons: [],
    episodesById: { [episodeId]: episode(episodeId, title) },
    assets: {},
    provider: {
      useGlobalProfile: true, writingProvider: 'maestro', writingModel: 'writer',
      imageProvider: 'maestro', imageModel: 'image', videoModel: 'video',
      videoSettings: { resolution: '480p', orientation: 'landscape' },
    },
    createdAt: '2026-09-03T10:00:00.000Z',
    updatedAt: '2026-09-03T10:05:00.000Z',
  }
}

function seriesWithBeatCount(id: string, episodeId: string, beatCount: number): SeriesProject {
  const value = series(id, episodeId)
  value.episodesById[episodeId] = episode(episodeId, value.title, beatCount)
  return value
}

function seriesWithCharacterReferences(id: string, episodeId: string): SeriesProject {
  const value = series(id, episodeId)
  const character: SeriesCharacter = {
    id: 'character-hero',
    name: 'Hero',
    aliases: [],
    role: 'protagonist',
    personality: 'Brave',
    desire: 'Protect the team',
    need: 'Trust others',
    flaw: 'Impatient',
    longArc: 'Learns to collaborate',
    voiceAndDialogue: 'Direct and warm',
    appearance: 'Blue jacket',
    identityLock: 'Keep the same face and jacket',
    wardrobeVariants: [],
    referenceAssetIds: ['character-ref-additional', 'character-ref-missing'],
    primaryReferenceAssetId: 'character-ref-primary',
    currentState: {},
    approval: 'approved',
  }
  const primaryReference: SeriesAsset = {
    id: 'character-ref-primary',
    workspaceId: 'workspace-1',
    kind: 'character',
    uri: 'outputs/character-ref-primary.png',
    ownerType: 'character',
    ownerId: character.id,
    isDerivedThumbnail: false,
    metadata: { name: 'Hero primary reference', createdAt: '2026-09-03T10:01:00.000Z' },
  }
  const additionalReference: SeriesAsset = {
    ...primaryReference,
    id: 'character-ref-additional',
    uri: 'outputs/character-ref-additional.png',
    metadata: { name: 'Hero additional reference', createdAt: '2026-09-03T10:02:00.000Z' },
  }
  value.characters = [character]
  value.protagonistCharacterId = character.id
  value.assets = {
    [primaryReference.id]: primaryReference,
    [additionalReference.id]: additionalReference,
  }
  return value
}

function library(...projects: SeriesProject[]): SeriesLibrary {
  return {
    schema: 'series-library',
    version: 1,
    workspaceId: 'workspace-1',
    seriesOrder: projects.map(project => project.id),
    seriesById: Object.fromEntries(projects.map(project => [project.id, project])),
  }
}

test('Series → Comics resolves the exact IDs when titles are duplicated', () => {
  const source = library(
    series('series-a', 'episode-a'),
    series('series-b', 'episode-b'),
  )

  const resolved = resolveSeriesEpisodeById(source, {
    workspaceId: 'workspace-1', seriesId: 'series-b', episodeId: 'episode-b',
  })

  assert.equal(resolved.series.id, 'series-b')
  assert.equal(resolved.episode.id, 'episode-b')
  assert.equal(resolved.series.title, 'Same title')
  assert.equal(resolved.episode.title, 'Same title')
})

test('Series → Comics provenance survives JSON reload and restores by ID', () => {
  const source = library(series('series-a', 'episode-a'))
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-a', episodeId: 'episode-a',
  })
  const restored = normalizeComicProject(JSON.parse(JSON.stringify(staged.comic)))

  assert.equal(restored.provenance?.workspaceId, 'workspace-1')
  assert.equal(restored.provenance?.source.seriesId, 'series-a')
  assert.equal(restored.provenance?.source.episodeId, 'episode-a')
  assert.equal(restored.provenance?.destination.comicId, restored.id)
  assert.equal(restored.director?.input.sourceSeries?.id, 'series-a')
  assert.equal(restored.director?.input.sourceEpisode?.id, 'episode-a')
  assert.deepEqual(restored.provenance?.source.productionIds, ['production-source-1'])
  const resolved = resolveComicSource(restored, source)
  assert.equal(resolved?.series.id, 'series-a')
  assert.equal(resolved?.episode.id, 'episode-a')
})

test('an explicit page count is honored while every source panel is retained', () => {
  const source = library(seriesWithBeatCount('series-pages', 'episode-pages', 5))
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-pages', episodeId: 'episode-pages',
    pageCount: 2, panelsPerPage: 4,
  })
  const pages = staged.comic.director?.plan.pages || []

  assert.equal(pages.length, 2)
  assert.deepEqual(pages.map(page => page.panels.length), [3, 2])
  assert.equal(pages.flatMap(page => page.panels).length, 5)
  assert.equal(staged.request.pageCount, 2)
})

test('a page target expands when needed to keep the panels-per-page contract', () => {
  const source = library(seriesWithBeatCount('series-page-limit', 'episode-page-limit', 30))
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-page-limit', episodeId: 'episode-page-limit',
    pageCount: 1, panelsPerPage: 12,
  })
  const pages = staged.comic.director?.plan.pages || []

  assert.equal(pages.length, 3)
  assert.deepEqual(pages.map(page => page.panels.length), [10, 10, 10])
  assert.ok(pages.every(page => page.panels.length <= 12))
  assert.equal(pages.flatMap(page => page.panels).length, 30)
  assert.equal(staged.request.pageCount, 3)
})

test('character reference assets stay available to Director, with missing references diagnosed', () => {
  const source = library(seriesWithCharacterReferences('series-character-refs', 'episode-character-refs'))
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-character-refs', episodeId: 'episode-character-refs',
  })
  const director = staged.comic.director
  const character = director?.plan.characters.find(item => item.id === 'character-hero')
  const panel = director?.plan.pages[0]?.panels[0]

  assert.ok(director)
  assert.ok(character)
  assert.ok(panel)
  assert.equal(character.referenceAssetId, 'character-ref-primary')
  assert.deepEqual(character.referenceAssetIds, ['character-ref-additional', 'character-ref-missing'])
  assert.equal(staged.comic.assets['character-ref-primary']?.source, '/api/v1/file/character-ref-primary.png?workspace=workspace-1')
  assert.equal(staged.comic.assets['character-ref-additional']?.source, '/api/v1/file/character-ref-additional.png?workspace=workspace-1')
  assert.deepEqual(staged.comic.assets['character-ref-primary']?.metadata?.sourceCharacterIds, ['character-hero'])
  assert.deepEqual(
    panelIdentityReference(director, panel, staged.comic.assets),
    { source: '/api/v1/file/character-ref-primary.png?workspace=workspace-1', characterId: 'character-hero' },
  )
  assert.equal(staged.comic.assets['character-ref-missing']?.missing, true)
  assert.equal(
    staged.comic.assets['character-ref-missing']?.metadata?.missingReason,
    'series_reference_asset_unavailable',
  )

  const fallbackDirector = structuredClone(director)
  const fallbackCharacter = fallbackDirector.plan.characters.find(item => item.id === 'character-hero')!
  fallbackCharacter.referenceAssetId = 'character-ref-missing'
  fallbackCharacter.referenceAssetIds = ['character-ref-additional']
  assert.deepEqual(
    panelIdentityReference(fallbackDirector, panel, staged.comic.assets),
    { source: '/api/v1/file/character-ref-additional.png?workspace=workspace-1', characterId: 'character-hero' },
  )
})

test('Series → Comics provenance records the caller actor', () => {
  const source = library(series('series-actor', 'episode-actor'))
  const userHandoff = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-actor', episodeId: 'episode-actor', actor: 'user',
  })
  const wizardHandoff = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-actor', episodeId: 'episode-actor', actor: 'wizard',
  })

  assert.equal(userHandoff.provenance.actor, 'user')
  assert.equal(wizardHandoff.provenance.actor, 'wizard')
})

test('a lost Series ID fails explicitly instead of falling back to a same-title entity', () => {
  const source = library(
    series('series-a', 'episode-a'),
    series('series-b', 'episode-b'),
  )
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-a', episodeId: 'episode-a',
  })
  const lost = structuredClone(staged.comic)
  lost.provenance!.source.episodeId = 'episode-gone'

  assert.throws(
    () => resolveComicSource(lost, source),
    error => error instanceof Error
      && error.message.includes('Episode source ID “episode-gone”')
      && (error as { code?: string }).code === 'episode_not_found',
  )
})

test('a workspace change fails before restoring a Series-derived Comic', () => {
  const source = library(series('series-a', 'episode-a'))
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-a', episodeId: 'episode-a',
  })

  assert.throws(
    () => resolveComicSource(staged.comic, source, 'workspace-2'),
    error => error instanceof Error && (error as { code?: string }).code === 'workspace_mismatch',
  )
})

test('Comic artwork appends generated output IDs to the destination lineage', async () => {
  const source = library(series('series-art', 'episode-art'))
  const staged = buildSeriesComicHandoff(source, {
    workspaceId: 'workspace-1', seriesId: 'series-art', episodeId: 'episode-art',
  })
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const { generateDirectorArtwork } = await import('../src/features/comics/generateArtwork.ts')
  useComicStore.getState().setProject(staged.comic)
  const result = await generateDirectorArtwork({
    drawPanel: async () => ({
      id: 'generated-output-1', name: 'generated-output-1', kind: 'local' as const,
      source: 'outputs/generated-output-1.png', createdAt: '2026-09-03T10:06:00.000Z',
    }),
  })

  assert.equal(result.generated, 1)
  assert.deepEqual(useComicStore.getState().project.provenance?.destination.outputAssetIds, ['generated-output-1'])
})

test('the Series episode room exposes the Comics handoff without changing the selected IDs', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { SeriesEpisodePanel } = await import('../src/features/series/SeriesEpisodePanel.tsx')
  const currentSeries = series('series-ui', 'episode-ui')
  const currentEpisode = currentSeries.episodesById['episode-ui']
  const t = ensureUiI18n().getFixedT('en', 'seriesLab')
  let calls = 0

  try {
    render(React.createElement(SeriesEpisodePanel, {
      workspace: 'workspace-1',
      series: currentSeries,
      episode: currentEpisode,
      updateEpisode: () => {},
      saveNow: async () => {},
      reload: async () => {},
      onAdaptToComic: async () => { calls += 1 },
    }))
    fireEvent.click(screen.getByRole('button', { name: t('episode.adaptToComic') }))
    await waitFor(() => assert.equal(calls, 1))
    assert.equal(currentSeries.id, 'series-ui')
    assert.equal(currentEpisode.id, 'episode-ui')
  } finally {
    cleanup()
  }
})

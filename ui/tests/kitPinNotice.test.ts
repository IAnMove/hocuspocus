import assert from 'node:assert/strict'
import test from 'node:test'
import es from '../src/i18n/locales/es/seriesLab.json' with { type: 'json' }
import { kitPinNotices } from '../src/features/series/kitPinNotice.ts'
import type { CharacterKit } from '../src/lib/characterKit.ts'
import type { SeriesEpisode, SeriesProject } from '../src/features/series/types.ts'

const series = {
  characters: [{ id: 'c1', name: 'Pedro', voiceProfile: { characterKitRef: { id: 'pedro', workspace: 'w' } } }],
} as SeriesProject

test('the warning names the character and both revisions', () => {
  assert.equal(es.episode.kitPinBehind, 'este episodio usa la revisión {{pinned}} de {{name}}; hay una {{latest}}')
  const episode = { kitPins: { pedro: 3, quiet: 5, alone: 1 } } as SeriesEpisode
  const kits = [
    { id: 'pedro', name: 'Kit Pedro', revision: 5 },
    { id: 'quiet', name: 'Quiet', revision: 5 },
    { id: 'alone', name: 'Alone', revision: 1 },
  ] as CharacterKit[]
  assert.deepEqual(kitPinNotices(series, episode, kits), [
    { kitId: 'pedro', name: 'Pedro', pinned: 3, latest: 5 },
    { kitId: 'quiet', name: 'Quiet', pinned: 5, latest: 5 },
  ].filter(item => item.latest > item.pinned))
})

test('without a character the kit name is used, and without pins there is no warning', () => {
  const kits = [{ id: 'loose', name: 'Loose kit', revision: 4 }] as CharacterKit[]
  assert.deepEqual(kitPinNotices(series, { kitPins: { loose: 2 } } as SeriesEpisode, kits), [
    { kitId: 'loose', name: 'Loose kit', pinned: 2, latest: 4 },
  ])
  assert.deepEqual(kitPinNotices(series, { kitPins: { missing: 1 } } as SeriesEpisode, kits), [])
  assert.deepEqual(kitPinNotices(series, {} as SeriesEpisode, kits), [])
})

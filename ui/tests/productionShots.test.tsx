import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { setUiLanguage } from '../src/i18n/index.ts'
import { ProductionShotsPanel } from '../src/features/production-shots/ProductionShotsPanel.tsx'
import { previewUrl } from '../src/features/production-shots/preview.ts'
import { shotTarget } from '../src/features/production-shots/target.ts'
import type { ShotView } from '../src/features/production-shots/types.ts'

Object.assign(globalThis, { React })

function view(overrides: Partial<ShotView> = {}): ShotView {
  return {
    workspace_id: 'film',
    production_id: 'clip1',
    project: { kind: 'story', id: 'story-1' },
    title: 'Night bus',
    status: 'completed',
    format: 'music_video',
    sources: ['music'],
    limits: [],
    shot_count: 1,
    truncated: false,
    shots: [{
      id: 's1',
      order: 1,
      start: 0,
      end: 4,
      duration: 4,
      text: 'night bus',
      text_kind: 'lyric',
      takes: [
        { id: 'take-a.mp4', file: 'take-a.mp4', selected: false },
        { id: 'take-b.mp4', file: 'take-b.mp4', selected: true },
      ],
      selected_take_id: 'take-b.mp4',
      review: { status: 'approved', locked: true, notes: null },
      technical_status: null,
      scene: { kind: 'scene2d', id: 's1.scene.json' },
      montage: { stale: true },
      provenance: { source: 'music' },
    }],
    ...overrides,
  }
}

test('preview urls stay on a bare workspace file name', () => {
  assert.equal(previewUrl('take-b.mp4', 'film'), '/api/v1/file/take-b.mp4?workspace=film')
  assert.equal(previewUrl('../secret.mp4', 'film'), null)
  assert.equal(previewUrl(null, 'film'), null)
})

test('the shot panel shows the selected take in English and Spanish', async () => {
  await setUiLanguage('en')
  const english = renderToStaticMarkup(<ProductionShotsPanel view={view()} workspace="film" onClose={() => {}} />)
  assert.match(english, /Review shots/)
  assert.match(english, /Selected/)
  assert.match(english, /src="\/api\/v1\/file\/take-b\.mp4\?workspace=film"/)
  assert.doesNotMatch(english, /\/mnt\//)
  assert.match(english, /Export is out of date/)
  assert.match(english, /Project story story-1/)

  await setUiLanguage('es')
  const spanish = renderToStaticMarkup(<ProductionShotsPanel view={view()} workspace="film" onClose={() => {}} />)
  assert.match(spanish, /Revisar planos/)
  assert.match(spanish, /Elegida/)
  assert.match(spanish, /El export está desactualizado/)
})

test('a missing take and an empty production do not invent a lyric', async () => {
  await setUiLanguage('en')
  const missing = view({
    project: null,
    shots: [{
      ...view().shots[0],
      text: null,
      text_kind: null,
      takes: [{ id: 'pending', file: null, selected: false }],
      scene: null,
      montage: null,
      review: null,
    }],
  })
  const html = renderToStaticMarkup(<ProductionShotsPanel view={missing} workspace="film" onClose={() => {}} />)
  assert.match(html, /No linked project/)
  assert.doesNotMatch(html, /<img/)
  assert.doesNotMatch(html, /Lyric:/)

  const empty = renderToStaticMarkup(<ProductionShotsPanel view={view({ shots: [], limits: ['no_shots', 'shots_unreadable'], shot_count: 0 })} workspace="film" onClose={() => {}} />)
  assert.match(empty, /This production has no shots yet/)
  assert.match(empty, /The shot manifest could not be read/)
})

test('the same selection is what a second entry renders', async () => {
  await setUiLanguage('es')
  const first = renderToStaticMarkup(<ProductionShotsPanel view={view()} workspace="film" onClose={() => {}} />)
  const second = renderToStaticMarkup(<ProductionShotsPanel view={view({ project: { kind: 'episode', id: 'ep1' }, sources: ['series'] })} workspace="film" onClose={() => {}} />)
  assert.match(first, /take-b\.mp4/)
  assert.match(second, /take-b\.mp4/)
  assert.match(second, /Elegida/)
  assert.match(second, /Proyecto episode ep1/)
})

test('a locked shot explains why the take cannot change', async () => {
  await setUiLanguage('en')
  const locked = view({
    shots: [{
      ...view().shots[0],
      actions: [
        { action: 'select', enabled: false, reason: 'shot_locked' },
        { action: 'undo', enabled: false, reason: 'shot_locked' },
        { action: 'reexport', enabled: false, reason: 'shot_locked' },
        { action: 'regenerate', enabled: false, reason: 'regenerate_needs_runner' },
      ],
    }],
  })
  const html = renderToStaticMarkup(<ProductionShotsPanel view={locked} workspace="film" onClose={() => {}} />)
  assert.match(html, /Use this take/)
  assert.match(html, /This shot is locked/)
  assert.match(html, /Regeneration stays on the production runner/)
  assert.match(html, /disabled[^>]*data-action="select"/)

  await setUiLanguage('es')
  const spanish = renderToStaticMarkup(<ProductionShotsPanel view={locked} workspace="film" onClose={() => {}} />)
  assert.match(spanish, /Este plano está bloqueado/)
  assert.match(spanish, /Elegir esta toma/)
})

test('the open event needs a workspace and a production id', () => {
  assert.equal(shotTarget(null), null)
  assert.equal(shotTarget({ workspace: 'film' }), null)
  assert.deepEqual(shotTarget({ workspace: ' film ', productionId: 'clip1' }), { workspace: 'film', productionId: 'clip1' })
})

import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { setUiLanguage } from '../src/i18n/index.ts'
import { ProductionCatalogPanel } from '../src/features/production-catalog/ProductionCatalogPanel.tsx'
import { linkedTarget, reviewDetail } from '../src/features/production-catalog/target.ts'
import type { CatalogPage, CatalogWork } from '../src/features/production-catalog/types.ts'

Object.assign(globalThis, { React })

function work(overrides: Partial<CatalogWork> = {}): CatalogWork {
  return {
    workspace_id: 'film',
    production_id: 'clip-mcp',
    title: 'Same title',
    status: 'failed',
    origin: 'mcp',
    format: 'music_video',
    project: { kind: 'story', id: 'story-mcp' },
    series_id: null,
    linked: true,
    updated_at: '2026-10-01T00:00:00Z',
    preview: 'sheet.jpg',
    review: {
      event: 'hocuspocus:production-shots-open',
      workspace: 'film',
      production_id: 'clip-mcp',
      project: { kind: 'story', id: 'story-mcp' },
    },
    ...overrides,
  }
}

function page(works: CatalogWork[]): CatalogPage {
  return { applied: false, works, total: works.length, warnings: [] }
}

test('review and project targets keep the workspace and do not invent a link', () => {
  assert.deepEqual(reviewDetail(' film ', ' clip-mcp '), { workspace: 'film', productionId: 'clip-mcp' })
  assert.equal(reviewDetail('', 'clip-mcp'), null)
  assert.deepEqual(linkedTarget({ kind: 'story', id: 'story-mcp' }, null), { kind: 'story', id: 'story-mcp' })
  assert.equal(linkedTarget({ kind: 'episode', id: 'ep-1' }, null), null)
  assert.deepEqual(linkedTarget({ kind: 'episode', id: 'ep-1' }, 'show-1'), { kind: 'episode', id: 'ep-1', seriesId: 'show-1' })
  assert.equal(linkedTarget(null, null), null)
})

test('the catalog shows both works and the light formats in English and Spanish', async () => {
  const works = [
    work(),
    work({
      production_id: 'clip-wiz',
      origin: 'wizard',
      status: 'pending',
      format: 'quick_video',
      project: { kind: 'episode', id: 'ep-1' },
      series_id: 'show-1',
      preview: null,
      review: {
        event: 'hocuspocus:production-shots-open',
        workspace: 'film',
        production_id: 'clip-wiz',
        project: { kind: 'episode', id: 'ep-1' },
        series_id: 'show-1',
      },
    }),
    work({
      production_id: 'loose',
      origin: 'file',
      status: 'running',
      format: null,
      project: null,
      linked: false,
      preview: '../secret.jpg',
      review: { event: 'hocuspocus:production-shots-open', workspace: 'film', production_id: 'loose', project: null },
    }),
  ]
  await setUiLanguage('en')
  const english = renderToStaticMarkup(<ProductionCatalogPanel workspace="film" page={page(works)} format="" status="" onFormat={() => {}} onStatus={() => {}} onCreate={() => {}} onLinked={() => {}} onClose={() => {}} />)
  assert.match(english, /Productions/)
  assert.match(english, /Workspace film/)
  assert.match(english, /Music video/)
  assert.match(english, /Trailer/)
  assert.match(english, /Quick video/)
  assert.match(english, /Failed/)
  assert.match(english, /Pending/)
  assert.match(english, /Running/)
  assert.match(english, /data-production-id="clip-mcp"/)
  assert.match(english, /data-production-id="clip-wiz"/)
  assert.match(english, /data-review-shots="clip-mcp"/)
  assert.match(english, /data-workspace="film"/)
  assert.match(english, /data-open-project="ep-1"/)
  assert.match(english, /data-project-kind="episode"/)
  assert.match(english, /No linked project/)
  assert.match(english, /Link to a project/)
  assert.match(english, /data-link-project="loose"/)
  assert.doesNotMatch(english, /data-link-project="clip-mcp"/)
  assert.match(english, /src="\/api\/v1\/file\/sheet\.jpg\?workspace=film"/)
  assert.doesNotMatch(english, /secret\.jpg/)
  assert.doesNotMatch(english, /\/mnt\//)

  await setUiLanguage('es')
  const spanish = renderToStaticMarkup(<ProductionCatalogPanel workspace="film" page={page(works)} format="" status="" onFormat={() => {}} onStatus={() => {}} onCreate={() => {}} onLinked={() => {}} onClose={() => {}} />)
  assert.match(spanish, /Producciones/)
  assert.match(spanish, /Revisar planos/)
  assert.match(spanish, /Story ligera/)
  assert.match(spanish, /Sin proyecto vinculado/)
  assert.match(spanish, /Vincular a proyecto/)
  assert.match(spanish, /Fallida/)
  assert.match(spanish, /Videoclip/)
})

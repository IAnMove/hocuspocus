import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { AssetCatalogItem } from '../src/api/assets.ts'
import type { Scene } from '../src/types/index.ts'
import { ALL_SCENE_TEMPLATES, CANDIDATE_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog.ts'

Object.assign(globalThis, { React })

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLImageElement: dom.window.HTMLImageElement,
  HTMLVideoElement: dom.window.HTMLVideoElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const makeAsset = (id: string, workspace: string, overrides: Partial<AssetCatalogItem> = {}): AssetCatalogItem => {
  const filename = overrides.filename || `${id}.png`
  return {
    id, kind: 'image', filename, size_bytes: 12, created_at: 1, completed_at: 2,
    metadata_status: 'canonical', workspace_ids: [workspace],
    locations: [{ workspace_id: workspace, filename, url: `/api/v1/file/${encodeURIComponent(filename)}?workspace=${encodeURIComponent(workspace)}` }],
    url: `/api/v1/file/${encodeURIComponent(filename)}?workspace=${encodeURIComponent(workspace)}`,
    origin: { tool: 'composer-test' }, execution: { run_id: 'run-1', task_id: 'task-1' },
    model: { provider: 'local', id: 'fixture-model' }, prompt_preview: filename, ...overrides,
  }
}

const assetsFor = (workspace: string, heroMetadata: AssetCatalogItem['metadata_status'] = 'canonical') => {
  const hero = makeAsset(`asset-hero-${workspace}`, workspace, { filename: `hero-${workspace}.png`, metadata_status: heroMetadata })
  const plate = makeAsset(`asset-plate-${workspace}`, workspace, { filename: `plate-${workspace}.png` })
  return { hero, plate, all: [hero, plate] }
}

function responseFor(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
}

function installAssetFetch({
  workspace = 'default',
  heroMetadata = 'canonical',
  detailMode = 'normal',
}: {
  workspace?: string
  heroMetadata?: AssetCatalogItem['metadata_status']
  detailMode?: 'normal' | '404' | 'source-change'
} = {}) {
  const fixture = assetsFor(workspace, heroMetadata)
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const heroDetailFetches = { count: 0 }
  const previous = globalThis.fetch
  const mock: typeof fetch = (async (input, init) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.includes('/api/v1/assets?')) {
      const query = new URL(url, 'http://localhost').searchParams
      if (query.get('workspace') && query.get('workspace') !== workspace) {
        if (typeof previous === 'function') return previous(input, init)
      }
      const kind = query.get('kind')
      const assets = fixture.all.filter(item => !kind || item.kind === kind || kind.split(',').includes(item.kind))
      return responseFor({ assets, total: assets.length })
    }
    if (url.includes('/api/v1/assets/')) {
      const id = decodeURIComponent(url.slice(url.lastIndexOf('/') + 1).split('?')[0])
      const selected = fixture.all.find(item => item.id === id)
      if (!selected) {
        if (typeof previous === 'function') return previous(input, init)
        return responseFor({ detail: 'missing' }, 404)
      }
      if (selected.id === fixture.hero.id) heroDetailFetches.count += 1
      if (detailMode === '404' && selected.id === fixture.hero.id && heroDetailFetches.count > 1) return responseFor({ detail: 'missing' }, 404)
      if (detailMode === 'source-change' && selected.id === fixture.hero.id && heroDetailFetches.count > 1) {
        const filename = 'hero-replaced.png'
        return responseFor({ ...selected, filename, locations: [{ workspace_id: workspace, filename, url: `/api/v1/file/${filename}?workspace=${workspace}` }], url: `/api/v1/file/${filename}?workspace=${workspace}` })
      }
      return responseFor(selected)
    }
    if (typeof previous === 'function') return previous(input, init)
    throw new Error(`Unexpected non-catalog request: ${url}`)
  }) as typeof fetch
  globalThis.fetch = mock
  return {
    fixture,
    calls,
    restore() {
      if (globalThis.fetch === mock) globalThis.fetch = previous
    },
  }
}

async function renderDialog(props: { workspace?: string; onClose?: () => void; onApply?: (scene: Scene) => boolean } = {}) {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { TemplateComposerDialog } = await import('../src/features/sceneTemplates/TemplateComposerDialog.tsx')
  const view = render(<TemplateComposerDialog workspace={props.workspace || 'default'} onClose={props.onClose || (() => undefined)} onApply={props.onApply || (() => true)} />)
  return { ...view, screen, fireEvent, waitFor, cleanup, TemplateComposerDialog }
}

function clickLast(view: Awaited<ReturnType<typeof renderDialog>>, name: string | RegExp, exact = false) {
  const buttons = view.screen.getAllByRole('button', exact && typeof name === 'string' ? { name, exact: true } : { name })
  view.fireEvent.click(buttons[buttons.length - 1])
}

async function pickLibraryFile(view: Awaited<ReturnType<typeof renderDialog>>, filename: string) {
  clickLast(view, /From HocusPocus/)
  await view.waitFor(() => assert.ok(document.querySelector(`button[title="${filename}"]`)))
  view.fireEvent.click(document.querySelector(`button[title="${filename}"]`) as HTMLButtonElement)
  clickLast(view, 'Choose', true)
  await view.waitFor(() => assert.ok(view.screen.getAllByText(filename).length >= 1))
}

async function selectHeroAndPlate(view: Awaited<ReturnType<typeof renderDialog>>) {
  await pickLibraryFile(view, 'hero-default.png')
  view.fireEvent.click(view.screen.getByRole('button', { name: 'Background (required)' }))
  await pickLibraryFile(view, 'plate-default.png')
  view.fireEvent.click(view.screen.getByRole('checkbox', { name: /I have saved what I need/ }))
}

test('expone 24 referencias más 24 movimientos y habilita BPM/intensidad sólo en plantillas rítmicas', { concurrency: false }, async () => {
  const installed = installAssetFetch()
  try {
    const view = await renderDialog()
    const selector = view.screen.getByRole('combobox', { name: 'Action / template' }) as HTMLSelectElement
    assert.equal(selector.options.length, ALL_SCENE_TEMPLATES.length)
    assert.equal(selector.options.length, 48)
    assert.equal(CANDIDATE_SCENE_TEMPLATES.length, 24)
    assert.equal((view.screen.getByRole('spinbutton', { name: 'Visual BPM' }) as HTMLInputElement).disabled, true)
    assert.equal((view.screen.getByRole('spinbutton', { name: 'Pulse intensity' }) as HTMLInputElement).disabled, true)

    view.fireEvent.change(selector, { target: { value: 'music-pulse' } })
    const pulseBpm = await view.screen.findByRole('spinbutton', { name: 'Visual BPM' }) as HTMLInputElement
    assert.equal(pulseBpm.disabled, false)
    assert.equal((view.screen.getByRole('spinbutton', { name: 'Pulse intensity' }) as HTMLInputElement).disabled, false)
    view.cleanup()
  } finally {
    installed.restore()
  }
})

test('selecciona hero y fondo canónicos y aplica provided_only con lineage de catálogo', { concurrency: false }, async () => {
  const { fixture, calls, restore } = installAssetFetch()
  const applied: Scene[] = []
  let closed = 0
  try {
    const view = await renderDialog({ onClose: () => { closed += 1 }, onApply: scene => { applied.push(scene); return true } })
    await selectHeroAndPlate(view)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Create and open in editor' }))
    await view.waitFor(() => assert.equal(applied.length, 1))

    const scene = applied[0]
    assert.equal(scene.generationPolicy, 'provided_only')
    assert.equal(closed, 1)
    const assets = Object.fromEntries((scene.narrative?.assets || []).map(item => [item.slot, item]))
    assert.equal(assets.hero?.catalogAtAssignment?.assetId, fixture.hero.id)
    assert.equal(assets.hero?.catalogAtAssignment?.workspaceId, 'default')
    assert.equal(assets.plate?.catalogAtAssignment?.assetId, fixture.plate.id)
    assert.equal(assets.plate?.catalogAtAssignment?.metadataStatus, 'canonical')
    assert.equal(calls.some(call => /generate|model3d\/generate/i.test(call.url)), false)
    assert.ok(calls.some(call => call.url.endsWith(`/assets/${fixture.hero.id}`)))
    assert.ok(calls.some(call => call.url.endsWith(`/assets/${fixture.plate.id}`)))
    view.cleanup()
  } finally {
    restore()
  }
})

test('mantiene assets heredados visibles pero no seleccionables ni aplicables', { concurrency: false }, async () => {
  const installed = installAssetFetch({ heroMetadata: 'legacy' })
  let applied = 0
  try {
    const view = await renderDialog({ onApply: () => { applied += 1; return true } })
    clickLast(view, /From HocusPocus/)
    await view.waitFor(() => assert.ok(document.querySelector('button[title="hero-default.png"]')))
    view.fireEvent.click(document.querySelector('button[title="hero-default.png"]') as HTMLButtonElement)
    clickLast(view, 'Choose', true)
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /canonical Library identity and metadata/i)
    assert.equal(view.screen.queryAllByText('hero-default.png').length, 0)
    assert.equal((view.screen.getByRole('button', { name: 'Create and open in editor' }) as HTMLButtonElement).disabled, true)
    assert.equal(applied, 0)
    view.cleanup()
  } finally {
    installed.restore()
  }
})

test('cambia de plantilla y workspace reinicia bindings, y cerrar cancela sin aplicar', { concurrency: false }, async () => {
  const installed = installAssetFetch()
  let otherFetch: ReturnType<typeof installAssetFetch> | undefined
  let closed = 0
  let applied = 0
  try {
    const view = await renderDialog({ onClose: () => { closed += 1 }, onApply: () => { applied += 1; return true } })
    await pickLibraryFile(view, 'hero-default.png')

    const selector = view.screen.getByRole('combobox', { name: 'Action / template' })
    view.fireEvent.change(selector, { target: { value: 'music-pulse' } })
    await view.waitFor(() => assert.equal(view.screen.queryAllByText('hero-default.png').length, 0))
    assert.ok(view.screen.getAllByText('Unassigned').length >= 1)

    const other = assetsFor('other')
    otherFetch = installAssetFetch({ workspace: 'other' })
    view.rerender(<view.TemplateComposerDialog workspace="other" onClose={() => { closed += 1 }} onApply={() => { applied += 1; return true }} />)
    await view.waitFor(() => assert.equal(view.screen.queryAllByText('hero-default.png').length, 0))
    clickLast(view, /From HocusPocus/)
    await view.waitFor(() => assert.ok(document.querySelector('button[title="hero-other.png"]')))
    assert.equal(document.querySelector('button[title="hero-default.png"]'), null)
    clickLast(view, 'Cancel', true)
    assert.equal(other.hero.id, 'asset-hero-other')

    view.fireEvent.click(view.screen.getByRole('button', { name: 'Close' }))
    assert.equal(closed, 1)
    assert.equal(applied, 0)
    view.cleanup()
  } finally {
    otherFetch?.restore()
    installed.restore()
  }
})

test('404 y cambio de fuente al revalidar impiden aplicar y nunca generan assets', { concurrency: false }, async () => {
  const restores: Array<() => void> = []
  try {
    for (const detailMode of ['404', 'source-change']) {
      const { calls, restore } = installAssetFetch({ detailMode })
      restores.push(restore)
      let applied = 0
      const view = await renderDialog({ onApply: () => { applied += 1; return true } })
      await selectHeroAndPlate(view)
      view.fireEvent.click(view.screen.getByRole('button', { name: 'Create and open in editor' }))
      const alert = await view.screen.findByRole('alert')
      if (detailMode === '404') assert.match(alert.textContent || '', /Asset not found/i)
      else assert.match(alert.textContent || '', /asset's location changed/i)
      assert.equal(applied, 0)
      assert.equal(calls.some(call => /generate|model3d\/generate/i.test(call.url)), false)
      view.cleanup()
    }
  } finally {
    for (const restore of restores.reverse()) restore()
  }
})

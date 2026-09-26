import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { AssetCatalogItem } from '../src/api/assets.ts'
import type { Scene } from '../src/types/index.ts'
import { ALL_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog.ts'
import { MUSIC_MOTION_TEMPLATES } from '../src/features/sceneTemplates/musicMotionCatalog.ts'

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

const WORKSPACE = 'music-motion-composer-test'

const makeAsset = (id: string, filename: string): AssetCatalogItem => ({
  id,
  kind: 'image',
  filename,
  size_bytes: 12,
  created_at: 1,
  completed_at: 2,
  metadata_status: 'canonical',
  workspace_ids: [WORKSPACE],
  locations: [{
    workspace_id: WORKSPACE,
    filename,
    url: `/api/v1/file/${encodeURIComponent(filename)}?workspace=${encodeURIComponent(WORKSPACE)}`,
  }],
  url: `/api/v1/file/${encodeURIComponent(filename)}?workspace=${encodeURIComponent(WORKSPACE)}`,
  origin: { tool: 'composer-test' },
  execution: { run_id: 'run-composer-test', task_id: 'task-composer-test' },
  model: { provider: 'local', id: 'fixture-model' },
  prompt_preview: filename,
})

const fixture = {
  subject1: makeAsset('asset-subject-1', 'subject-one.png'),
  subject2: makeAsset('asset-subject-2', 'subject-two.png'),
  background: makeAsset('asset-background', 'music-stage.png'),
}
const assets = [fixture.subject1, fixture.subject2, fixture.background]

const responseFor = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status,
  headers: { 'content-type': 'application/json' },
})

const installAssetFetch = () => {
  const calls: string[] = []
  const previous = globalThis.fetch
  const mock: typeof fetch = (async (input, init) => {
    const url = String(input)
    calls.push(url)
    if (url.includes('/api/v1/assets?')) {
      const query = new URL(url, 'http://localhost').searchParams
      if (query.get('workspace') && query.get('workspace') !== WORKSPACE) {
        if (typeof previous === 'function') return previous(input, init)
      }
      return responseFor({ assets, total: assets.length })
    }
    if (url.includes('/api/v1/assets/')) {
      const id = decodeURIComponent(url.slice(url.lastIndexOf('/') + 1).split('?')[0])
      const selected = assets.find(item => item.id === id)
      if (!selected) {
        if (typeof previous === 'function') return previous(input, init)
        return responseFor({ detail: 'missing' }, 404)
      }
      return responseFor(selected)
    }
    if (typeof previous === 'function') return previous(input, init)
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch
  globalThis.fetch = mock
  return {
    calls,
    restore() {
      if (globalThis.fetch === mock) globalThis.fetch = previous
    },
  }
}

async function renderDialog(props: { onApply?: (scene: Scene) => boolean } = {}) {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { TemplateComposerDialog } = await import('../src/features/sceneTemplates/TemplateComposerDialog.tsx')
  const view = render(<TemplateComposerDialog workspace={WORKSPACE} onClose={() => undefined} onApply={props.onApply || (() => true)} />)
  return { ...view, screen, fireEvent, waitFor, cleanup }
}

function clickLast(view: Awaited<ReturnType<typeof renderDialog>>, name: string | RegExp, exact = false) {
  const buttons = view.screen.getAllByRole('button', exact && typeof name === 'string' ? { name, exact: true } : { name })
  view.fireEvent.click(buttons[buttons.length - 1])
}

async function chooseAsset(
  view: Awaited<ReturnType<typeof renderDialog>>,
  slotLabel: RegExp,
  filename: string,
) {
  clickLast(view, slotLabel)
  clickLast(view, /From HocusPocus/)
  await view.waitFor(() => assert.ok(document.querySelector(`button[title="${filename}"]`)))
  view.fireEvent.click(document.querySelector(`button[title="${filename}"]`) as HTMLButtonElement)
  clickLast(view, 'Choose', true)
  await view.waitFor(() => assert.ok(view.screen.getAllByText(filename).length >= 1))
}

test('expone claves y descripciones musicales, exige dos sujetos, conserva IDs y no ofrece referencia aprobada', { concurrency: false }, async () => {
  const originalClipboard = navigator.clipboard
  const { calls, restore } = installAssetFetch()
  let clipboardText = ''
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: async (value: string) => { clipboardText = value } },
  })
  const applied: Scene[] = []

  try {
    const view = await renderDialog({ onApply: scene => { applied.push(scene); return true } })
    const selector = view.screen.getByRole('combobox', { name: 'Action / template' }) as HTMLSelectElement
    assert.equal(selector.options.length, ALL_SCENE_TEMPLATES.length)

    view.fireEvent.change(selector, { target: { value: 'music-orbit-duel' } })
    await view.waitFor(() => assert.equal(selector.value, 'music-orbit-duel'))
    const template = MUSIC_MOTION_TEMPLATES.find(item => item.id === 'music-orbit-duel')!

    for (const slot of template.slots) {
      assert.ok(view.screen.getByText(`${slot.id} · image`))
      assert.ok(view.screen.getByText(slot.description))
    }
    assert.equal((view.screen.getByRole('button', { name: /Create and open in editor/i }) as HTMLButtonElement).disabled, true)
    assert.equal((view.screen.getByRole('spinbutton', { name: 'Visual BPM' }) as HTMLInputElement).disabled, true)
    assert.equal((view.screen.getByRole('spinbutton', { name: 'Pulse intensity' }) as HTMLInputElement).disabled, true)

    assert.ok(await view.screen.findByText(/visual reference awaiting review/i))
    assert.equal(view.container.querySelector('video, iframe'), null)
    assert.equal(view.container.querySelector('a[href*="github.com"]'), null)

    const copyButton = view.screen.getByRole('button', { name: 'Copy contract for the Wizard' })
    view.fireEvent.click(copyButton)
    await view.waitFor(() => assert.ok(clipboardText))
    const contract = JSON.parse(clipboardText)
    assert.equal(contract.templateId, 'music-orbit-duel')
    assert.deepEqual(contract.components.map((component: { key: string }) => component.key), ['subject_1', 'subject_2', 'background'])

    await chooseAsset(view, /Subject 1.*required/i, fixture.subject1.filename)
    await chooseAsset(view, /Subject 2.*required/i, fixture.subject2.filename)
    await chooseAsset(view, /Background.*required/i, fixture.background.filename)
    assert.equal((view.screen.getByRole('button', { name: /Create and open in editor/i }) as HTMLButtonElement).disabled, true, 'confirmation remains required')

    view.fireEvent.click(view.screen.getByRole('checkbox', { name: /I have saved what I need/i }))
    const apply = view.screen.getByRole('button', { name: /Create and open in editor/i }) as HTMLButtonElement
    assert.equal(apply.disabled, false)
    view.fireEvent.click(apply)
    await view.waitFor(() => assert.equal(applied.length, 1))

    const sceneAssets = Object.fromEntries((applied[0].narrative?.assets || []).map(asset => [asset.slot, asset]))
    assert.equal(applied[0].generationPolicy, 'provided_only')
    assert.equal(sceneAssets.subject_1?.catalogAtAssignment?.assetId, fixture.subject1.id)
    assert.equal(sceneAssets.subject_2?.catalogAtAssignment?.assetId, fixture.subject2.id)
    assert.equal(sceneAssets.background?.catalogAtAssignment?.assetId, fixture.background.id)
    assert.notEqual(sceneAssets.subject_1?.source, sceneAssets.subject_2?.source)
    assert.equal(calls.some(url => /generate|model3d\/generate/i.test(url)), false)
    view.cleanup()
  } finally {
    restore()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: originalClipboard })
  }
})

test('mantiene BPM e intensidad desactivados en las 24 nuevas coreografías', { concurrency: false }, async () => {
  const { calls, restore } = installAssetFetch()
  try {
    const view = await renderDialog()
    const selector = view.screen.getByRole('combobox', { name: 'Action / template' }) as HTMLSelectElement
    for (const template of MUSIC_MOTION_TEMPLATES) {
      view.fireEvent.change(selector, { target: { value: template.id } })
      await view.waitFor(() => assert.equal(selector.value, template.id))
      assert.equal((view.screen.getByRole('spinbutton', { name: 'Visual BPM' }) as HTMLInputElement).disabled, true, template.id)
      assert.equal((view.screen.getByRole('spinbutton', { name: 'Pulse intensity' }) as HTMLInputElement).disabled, true, template.id)
    }
    assert.equal(calls.some(url => /generate|model3d\/generate/i.test(url)), false)
    view.cleanup()
  } finally {
    restore()
  }
})

test('cambiar entre una plantilla musical y una legacy reinicia selecciones sin romper el compositor', { concurrency: false }, async () => {
  const installed = installAssetFetch()
  try {
    const view = await renderDialog()
    const selector = view.screen.getByRole('combobox', { name: 'Action / template' }) as HTMLSelectElement

    view.fireEvent.change(selector, { target: { value: 'music-orbit-duel' } })
    await view.waitFor(() => assert.equal(selector.value, 'music-orbit-duel'))
    await chooseAsset(view, /Subject 1.*required/i, fixture.subject1.filename)
    assert.ok(view.screen.getAllByText(fixture.subject1.filename).length >= 1)

    view.fireEvent.change(selector, { target: { value: 'cinema-establishing' } })
    await view.waitFor(() => assert.equal(selector.value, 'cinema-establishing'))
    assert.equal(view.screen.queryByText('subject_1 · image'), null)
    assert.equal(view.screen.queryAllByText(fixture.subject1.filename).length, 0)
    assert.equal((view.screen.getByRole('button', { name: /Create and open in editor/i }) as HTMLButtonElement).disabled, true)

    view.fireEvent.change(selector, { target: { value: 'music-orbit-duel' } })
    await view.waitFor(() => assert.equal(selector.value, 'music-orbit-duel'))
    assert.equal(view.screen.queryAllByText(fixture.subject1.filename).length, 0)
    assert.ok(view.screen.getByText('subject_1 · image'))
    assert.ok(view.screen.getAllByText('Unassigned').length >= 1)
    view.cleanup()
  } finally {
    installed.restore()
  }
})

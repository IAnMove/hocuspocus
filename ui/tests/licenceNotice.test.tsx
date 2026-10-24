import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { InstallComponent, InstallStatus } from '../src/api/installManager'
import { licenceNoticeLine, withLicenceNotice, type ModelLicence } from '../src/lib/licenceNotice'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const hunyuan: ModelLicence = {
  id: 'hunyuan',
  url: 'https://github.com/Tencent-Hunyuan/HunyuanVideo/blob/main/LICENSE.txt',
  territoryExcluded: ['EU', 'UK', 'KR'],
  commercial: true,
  note: 'Commercial use is allowed below 100 million monthly active users.',
}

const line = 'This license does not apply in EU, UK, KR. https://github.com/Tencent-Hunyuan/HunyuanVideo/blob/main/LICENSE.txt'

test('the notice is one sentence and a link, and it is absent without excluded territories', async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { LicenceNotice } = await import('../src/components/common/LicenceNotice')
  const shown = render(<LicenceNotice licence={hunyuan} />)
  try {
    const notice = shown.getByTestId('licence-notice')
    assert.match(notice.textContent || '', /This license does not apply in EU, UK, KR\./)
    const link = shown.getByRole('link', { name: 'License' })
    assert.equal(link.getAttribute('href'), hunyuan.url)
    assert.equal(licenceNoticeLine(hunyuan), line)
    assert.equal(licenceNoticeLine({ ...hunyuan, territoryExcluded: [] }), '')
    assert.equal(licenceNoticeLine(undefined), '')
  } finally {
    cleanup()
  }

  const hidden = render(<LicenceNotice />)
  try {
    assert.equal(hidden.queryByTestId('licence-notice'), null)
  } finally {
    cleanup()
  }

  const es = JSON.parse(readFileSync(new URL('../src/i18n/locales/es/common.json', import.meta.url), 'utf8'))
  const en = JSON.parse(readFileSync(new URL('../src/i18n/locales/en/common.json', import.meta.url), 'utf8'))
  assert.equal(es.licence.territory, 'Esta licencia no se aplica en {{territories}}.')
  assert.equal(es.licence.link, 'Licencia')
  assert.equal(en.licence.link, 'License')
})

test('the model picker shows the notice once per family and leaves other families alone', async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore')
  const { ModelSelector } = await import('../src/components/Sidebar/ModelSelector')
  const initial = useStore.getState()
  const models = [
    { model_type: 'hunyuan_video', name: 'Hunyuan Video', family: 'hunyuan', is_t2v: true },
    { model_type: 'wan_t2v', name: 'Wan', family: 'wan', is_t2v: true },
  ]
  useStore.setState({
    generationMode: 'video',
    models: models as never,
    families: [
      { id: 'hunyuan', label: 'Hunyuan', order: 20, licence: hunyuan },
      { id: 'wan', label: 'Wan', order: 1 },
    ],
    enabledModels: new Set(models.map(model => model.model_type)),
    params: { ...initial.params, model_type: 'hunyuan_video' },
  })
  const view = render(<ModelSelector />)
  try {
    assert.equal(view.getAllByTestId('licence-notice').length, 1)
    assert.equal(view.getByRole('button', { name: 'Hunyuan Video' }).textContent?.includes('EU'), false)
    fireEvent.click(view.getByRole('button', { name: 'Hunyuan Video' }))
    assert.equal(view.getAllByTestId('licence-notice').length, 2)
    assert.match(view.container.textContent || '', /This license does not apply in EU, UK, KR\./)
    assert.equal(view.getAllByRole('link', { name: 'License' })[0].getAttribute('href'), hunyuan.url)
  } finally {
    cleanup()
    useStore.setState(initial)
  }
})

test('an install row shows the notice only when its component carries a licence', async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { InstallRow } = await import('../src/components/Installation/InstallRow')
  const base: InstallComponent = {
    id: 'hunyuan3d',
    engine: 'hunyuan3d',
    title: '3D Generation',
    summary: 'Hunyuan3D weights',
    estimatedBytes: 1,
    restartRequired: false,
    state: 'not_installed',
    supported: true,
    reason: null,
    sizeBytes: null,
    reclaimableBytes: null,
    job: null,
  }
  const status = {
    launcher: { available: false, reason: 'not_in_pinokio' },
    disk: { freeBytes: 10_000_000_000, totalBytes: 20_000_000_000 },
    base: { title: 'Studio', summary: '', estimatedBytes: 1, engine: 'core', installed: true, state: 'installed', sizeBytes: 1 },
    components: [],
    busy: null,
  } as InstallStatus
  const shown = render(<InstallRow row={{ ...base, licence: { ...hunyuan, id: 'hunyuan3d' } }} status={status} acting={false} onAct={async () => {}} />)
  try {
    assert.equal(shown.getAllByTestId('licence-notice').length, 1)
    assert.equal(shown.getByRole('link', { name: 'License' }).getAttribute('href'), hunyuan.url)
  } finally {
    cleanup()
  }
  const plain = render(<InstallRow row={base} status={status} acting={false} onAct={async () => {}} />)
  try {
    assert.equal(plain.queryByTestId('licence-notice'), null)
  } finally {
    cleanup()
  }
})

test('the wizard model list carries the sentence once per restricted model and omits it otherwise', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const { buildAgentAppSnapshot } = await import('../src/features/agent/agentActions')
  const initial = useStore.getState()
  useStore.setState({
    models: [
      { model_type: 'hunyuan_video', name: 'Hunyuan Video', family: 'hunyuan', is_t2v: true, is_downloaded: true },
      { model_type: 'wan_t2v', name: 'Wan', family: 'wan', is_t2v: true, is_downloaded: true },
    ] as never,
    families: [
      { id: 'hunyuan', label: 'Hunyuan', order: 20, licence: hunyuan },
      { id: 'wan', label: 'Wan', order: 1 },
    ],
    enabledModels: new Set(['hunyuan_video', 'wan_t2v']),
  })
  try {
    const snapshot = buildAgentAppSnapshot()
    const restricted = snapshot.available_video_models.find(model => model.model_type === 'hunyuan_video')
    const open = snapshot.available_video_models.find(model => model.model_type === 'wan_t2v')
    assert.equal(restricted?.licence_notice, line)
    assert.equal(open?.licence_notice, undefined)
    assert.equal(Object.hasOwn(open ?? {}, 'licence_notice'), false)
    const untouched = withLicenceNotice({ model_type: 'wan_t2v', family: 'wan' }, [{ id: 'wan' }])
    assert.deepEqual(untouched, { model_type: 'wan_t2v', family: 'wan' })
  } finally {
    useStore.setState(initial)
  }
})

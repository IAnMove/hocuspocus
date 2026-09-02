import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { catalogReport, forbiddenLiterals } from '../scripts/check-i18n-catalogs.mjs'

function installDom() {
  const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
    localStorage: dom.window.localStorage,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  })
  dom.window.requestAnimationFrame = callback => { callback(0); return 1 }
  dom.window.cancelAnimationFrame = () => undefined
}

installDom()

test('english and spanish catalogs expose the same keys', () => {
  const { missing } = catalogReport()
  assert.deepEqual(missing, [])
})

test('required glossary keys exist in both languages', async () => {
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const i18n = ensureUiI18n()
  const required = [
    ['navigation', 'entities.project'],
    ['navigation', 'entities.production'],
    ['navigation', 'entities.run'],
    ['navigation', 'entities.task'],
    ['navigation', 'entities.asset'],
    ['navigation', 'entities.workspace'],
    ['navigation', 'entities.outputFolder'],
    ['navigation', 'filters.allWorkspaces'],
    ['navigation', 'labs.story'],
    ['navigation', 'labs.series'],
    ['navigation', 'labs.director'],
    ['wizard', 'title'],
    ['activity', 'title'],
  ]
  for (const language of ['en', 'es']) {
    await i18n.changeLanguage(language)
    for (const [ns, key] of required) {
      const value = i18n.t(key, { ns, lng: language })
      assert.notEqual(value, key, `${language} ${ns}:${key}`)
    }
  }
  assert.equal(i18n.t('entities.workspace', { ns: 'navigation', lng: 'es' }), 'Workspace')
  assert.equal(i18n.t('title', { ns: 'wizard', lng: 'es' }), 'Pregunta al mago')
  assert.equal(i18n.t('entities.outputFolder', { ns: 'navigation', lng: 'es' }), 'Carpeta de salida')
})

test('missing keys fall back to english without throwing', async () => {
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const i18n = ensureUiI18n()
  await i18n.changeLanguage('es')
  const missing = i18n.t('does.not.exist', { ns: 'common', defaultValue: 'does.not.exist' })
  assert.equal(missing, 'does.not.exist')
})

test('interpolation and pluralization stay in the catalog', async () => {
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const i18n = ensureUiI18n()
  await i18n.changeLanguage('en')
  assert.equal(i18n.t('count.item', { ns: 'common', count: 1 }), '1 item')
  assert.equal(i18n.t('count.item', { ns: 'common', count: 3 }), '3 items')
  await i18n.changeLanguage('es')
  assert.equal(i18n.t('count.item', { ns: 'common', count: 1 }), '1 elemento')
  assert.equal(i18n.t('count.item', { ns: 'common', count: 3 }), '3 elementos')
  assert.equal(
    i18n.t('collectionCounts', { ns: 'activity', projects: 2, assets: 4, productions: 1 }),
    '2 proyectos · 4 recursos · 1 producciones',
  )
})

test('language persists and switches without a reload', { concurrency: false }, async () => {
  const { ensureUiI18n, setUiLanguage, LANGUAGE_STORAGE_KEY } = await import('../src/i18n/index.ts')
  const i18n = ensureUiI18n()
  await setUiLanguage('es')
  assert.equal(i18n.language, 'es')
  assert.equal(window.localStorage.getItem(LANGUAGE_STORAGE_KEY), 'es')
  assert.equal(document.documentElement.lang, 'es')
  await setUiLanguage('en')
  assert.equal(i18n.language, 'en')
  assert.equal(window.localStorage.getItem(LANGUAGE_STORAGE_KEY), 'en')
})

test('pilot navigation and settings render translated labels', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { SettingsDrawer } = await import('../src/components/SettingsDrawer/SettingsDrawer.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({
    developerMode: false,
    mediaFilter: 'all',
    settingsOpen: true,
    settingsTab: 'performance',
    systemConfigLoading: false,
    systemConfig: {
      attention_mode: 'auto',
      transformer_quantization: 'int8',
      vae_config: 0,
      compile: 'off',
      video_profile: 1,
      image_profile: 1,
      audio_profile: 1,
      video_output_codec: 'auto',
      image_output_codec: 'auto',
      enhancer_enabled: 0,
      prompt_enhancer_quantization: 'int8',
      attention_modes_available: ['auto'],
      vram_safety_coefficient: 0.8,
      model_folders: [],
    },
  })
  try {
    const view = render(
      <>
        <TabFilter />
        <SettingsDrawer />
      </>,
    )
    assert.ok(screen.getByRole('tab', { name: /Projects/i }))
    assert.ok(screen.getByRole('tab', { name: /Assets/i }))
    assert.ok(screen.getByRole('tab', { name: /Runs/i }))
    assert.ok(screen.getByRole('tab', { name: /Trailers/i }))
    assert.ok(screen.getByLabelText('Interface language'))
    fireEvent.change(screen.getByLabelText('Interface language'), { target: { value: 'es' } })
    await setUiLanguage('es')
    view.rerender(
      <>
        <TabFilter />
        <SettingsDrawer />
      </>,
    )
    assert.ok(screen.getByRole('tab', { name: /Proyectos/i }))
    assert.ok(screen.getByRole('tab', { name: /Recursos/i }))
    assert.ok(screen.getByRole('tab', { name: /Ejecuciones/i }))
    assert.ok(screen.getByRole('tab', { name: /Tráilers/i }))
    assert.ok(screen.getByLabelText('Idioma de la interfaz'))
  } finally {
    await setUiLanguage('en')
    useStore.setState({ settingsOpen: false })
    cleanup()
  }
})

test('catalogs do not rename technical ids', async () => {
  const { resources } = await import('../src/i18n/resources.ts')
  const blob = JSON.stringify(resources)
  for (const forbidden of ['select_workspace', 'create_workspace', '/api/v1/', 'prepare_video']) {
    assert.equal(blob.includes(forbidden), false, forbidden)
  }
})

test('migrated chrome no longer hardcodes the pilot phrases', () => {
  assert.deepEqual(forbiddenLiterals(), [])
})

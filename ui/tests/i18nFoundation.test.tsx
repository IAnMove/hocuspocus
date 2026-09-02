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
    ['navigation', 'outputFolder.uploads'],
    ['navigation', 'tabs.documents'],
    ['activity', 'extraInfo'],
    ['activity', 'catalog.loadMore'],
    ['activity', 'catalog.searchPlaceholder'],
    ['extraInfo', 'language'],
    ['extraInfo', 'clip.title'],
    ['extraInfo', 'copy.action'],
    ['common', 'sample.named'],
    ['navigation', 'labs.story'],
    ['navigation', 'labs.series'],
    ['navigation', 'labs.director'],
    ['wizard', 'title'],
    ['activity', 'title'],
    ['storyLab', 'world.title'],
    ['storyLab', 'characters.title'],
    ['storyLab', 'structure.title'],
    ['storyLab', 'relationships.title'],
    ['storyLab', 'music.title'],
    ['storyLab', 'trailer.title'],
    ['storyLab', 'productions.title'],
    ['storyLab', 'compact.musicTitle'],
  ]
  for (const language of ['en', 'es']) {
    await i18n.changeLanguage(language)
    for (const [ns, key] of required) {
      const value = i18n.t(key, { ns, lng: language })
      assert.notEqual(value, key, `${language} ${ns}:${key}`)
    }
  }
  assert.equal(i18n.t('entities.workspace', { ns: 'navigation', lng: 'es' }), 'Workspace')
  assert.equal(i18n.t('title', { ns: 'wizard', lng: 'es' }), 'Ask to the Wizard')
  assert.equal(i18n.t('entities.outputFolder', { ns: 'navigation', lng: 'es' }), 'Carpeta de salida')
  assert.equal(i18n.t('outputFolder.uploads', { ns: 'navigation', lng: 'es' }), 'Subidas')
  assert.equal(i18n.t('tabs.documents', { ns: 'navigation', lng: 'es' }), 'Documentos')
  assert.equal(i18n.t('extraInfo', { ns: 'activity', lng: 'es' }), 'Información adicional')
  assert.equal(i18n.t('catalog.loadMore', { ns: 'activity', lng: 'es' }), 'Cargar más')
  assert.equal(i18n.t('world.title', { ns: 'storyLab', lng: 'es' }), 'Biblia del mundo')
  assert.equal(i18n.t('catalog.reload', { ns: 'activity', lng: 'es' }), 'Actualizar catálogo')
  assert.equal(i18n.t('inspector.loadFailed', { ns: 'activity', lng: 'en' }), 'Could not load Extra info')
  assert.equal(i18n.t('inspector.loadFailed', { ns: 'activity', lng: 'es' }), 'No se pudo cargar Información adicional')
  assert.equal(i18n.t('actions.close', { ns: 'common', lng: 'es' }), 'Cerrar')
  assert.equal(i18n.t('language', { ns: 'extraInfo', lng: 'es' }), 'Idioma')
  assert.equal(i18n.t('clip.title', { ns: 'extraInfo', lng: 'es' }), 'Información del clip')
  assert.equal(i18n.t('errors.loadFailed', { ns: 'extraInfo', lng: 'es' }), 'No se pudo cargar Información adicional')
  assert.equal(i18n.t('savedPrompts', { ns: 'extraInfo', lng: 'en', count: 1 }), '1 saved prompt')
  assert.equal(i18n.t('savedPrompts', { ns: 'extraInfo', lng: 'en', count: 2 }), '2 saved prompts')
  assert.equal(i18n.t('savedPrompts', { ns: 'extraInfo', lng: 'es', count: 1 }), '1 prompt guardado')
  assert.equal(i18n.t('savedPrompts', { ns: 'extraInfo', lng: 'es', count: 2 }), '2 prompts guardados')
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
  assert.equal(i18n.t('projectCount', { ns: 'activity', count: 1 }), '1 proyecto')
  assert.equal(i18n.t('assetCount', { ns: 'activity', count: 1 }), '1 recurso')
  assert.equal(i18n.t('productionCount', { ns: 'activity', count: 1 }), '1 producción')
  assert.equal(i18n.t('productionCount', { ns: 'activity', count: 2 }), '2 producciones')
  assert.equal(i18n.t('catalog.itemsAcrossLocations', { ns: 'activity', count: 1 }), '1 elemento en todas las ubicaciones')
  assert.equal(i18n.t('catalog.itemsAcrossLocations', { ns: 'activity', count: 3 }), '3 elementos en todas las ubicaciones')
  await i18n.changeLanguage('en')
  assert.equal(i18n.t('catalog.itemsAcrossLocations', { ns: 'activity', count: 1 }), '1 item across all locations')
  assert.equal(i18n.t('catalog.itemsAcrossLocations', { ns: 'activity', count: 3 }), '3 items across all locations')
})

test('react interpolation keeps special characters as text without double-escaping', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage, useUiTranslation } = await import('../src/i18n/index.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  function Named() {
    const { t } = useUiTranslation('common')
    return <span data-testid="named">{t('sample.named', { name: '<Rock & Roll>' })}</span>
  }
  try {
    const view = render(<Named />)
    const node = screen.getByTestId('named')
    assert.equal(node.textContent, '<Rock & Roll>')
    assert.equal(node.querySelector('rock'), null)
    assert.equal(node.textContent?.includes('&lt;'), false)
    assert.equal(node.textContent?.includes('&amp;'), false)
    assert.equal(view.container.querySelector('rock'), null)
  } finally {
    cleanup()
  }
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

test('resources register the extraInfo and storyLab namespaces', async () => {
  const { NAMESPACES, resources } = await import('../src/i18n/resources.ts')
  assert.deepEqual([...NAMESPACES], ['common', 'navigation', 'settings', 'wizard', 'activity', 'extraInfo', 'storyLab'])
  assert.ok('extraInfo' in resources.en)
  assert.ok('extraInfo' in resources.es)
  assert.ok('storyLab' in resources.en)
  assert.ok('storyLab' in resources.es)
})

test('Extra info chrome and the Assets inspector use the activity catalog', async () => {
  const fs = await import('node:fs/promises')
  const files = [
    '../src/components/MainContent/VideoExtraInfoDialog.tsx',
    '../src/components/MainContent/MediaFeedItem.tsx',
    '../src/components/MainContent/VideoInfoBar.tsx',
    '../src/features/assets/AssetsPanel.tsx',
  ]
  for (const file of files) {
    const source = await fs.readFile(new URL(file, import.meta.url), 'utf8')
    assert.match(source, /t(?:Activity)?\('extraInfo'\)/, file)
    assert.doesNotMatch(source, />Extra info</, file)
    assert.doesNotMatch(source, /['"`]Extra info['"`]/, file)
    assert.doesNotMatch(source, /^\s*Extra info\s*$/m, file)
  }
  const panel = await fs.readFile(new URL('../src/features/assets/AssetsPanel.tsx', import.meta.url), 'utf8')
  for (const key of [
    'inspector.loadingAsset',
    'inspector.readingManifest',
    'inspector.identity',
    'inspector.origin',
    'inspector.modelTiming',
    'inspector.copy',
    'inspector.copyJson',
    'inspector.fullJson',
    'inspector.unavailable',
    'inspector.loadFailed',
    'inspector.prompt',
  ]) {
    assert.match(panel, new RegExp(`tActivity\\('${key.replace('.', '\\.')}'`), key)
  }
  assert.match(panel, /tCommon\('actions\.close'\)/)
  const dialog = await fs.readFile(new URL('../src/components/MainContent/VideoExtraInfoDialog.tsx', import.meta.url), 'utf8')
  assert.match(dialog, /useUiTranslation\('extraInfo'\)/)
  assert.match(dialog, /tActivity\('extraInfo'\)/)
  assert.match(dialog, /tCommon\('actions\.close'\)/)
  assert.match(dialog, /t\('clip\.title'\)/)
  assert.doesNotMatch(dialog, /['"`]Clip information['"`]/)
  assert.doesNotMatch(dialog, /['"`]Wait for generation to finish['"`]/)
})

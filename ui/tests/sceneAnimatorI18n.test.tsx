import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'

function installDom(language = 'en-US') {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    localStorage: dom.window.localStorage,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { language },
  })
}

test('fresh installations start in English even with a Spanish browser', async () => {
  installDom('es-ES')
  const { detectUiLanguage, LANGUAGE_STORAGE_KEY, persistUiLanguage } = await import('../src/i18n/language.ts')
  const { safeStorageRemove } = await import('../src/lib/safeStorage.ts')
  safeStorageRemove('local', LANGUAGE_STORAGE_KEY)
  assert.equal(detectUiLanguage(), 'en')
  persistUiLanguage('es')
  assert.equal(detectUiLanguage(), 'es')
  assert.equal(document.documentElement.lang, 'es')
  persistUiLanguage('en')
  assert.equal(detectUiLanguage(), 'en')
  safeStorageRemove('local', LANGUAGE_STORAGE_KEY)
})

test('the real UI language key wins over i18nextLng and the browser locale', async () => {
  installDom('en-US')
  const { detectUiLanguage, LANGUAGE_STORAGE_KEY } = await import('../src/i18n/language.ts')
  assert.equal(LANGUAGE_STORAGE_KEY, 'hocuspocus-ui-language')
  window.localStorage.setItem('i18nextLng', 'en')
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'es')
  assert.equal(detectUiLanguage(), 'es')
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en')
  Object.defineProperty(window, 'navigator', { configurable: true, value: { language: 'es-ES' } })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { language: 'es-ES' } })
  assert.equal(detectUiLanguage(), 'en')
})

test('animator labels follow the scene3d catalogs, not i18nextLng', async () => {
  const { animatorLabels } = await import('../src/i18n/animatorLabels.ts')
  assert.equal(animatorLabels('en').sceneNameAria, 'Scene name')
  assert.equal(animatorLabels('en').exportMp4, 'Export MP4')
  assert.equal(animatorLabels('en').saveScene, 'Save scene')
  assert.equal(animatorLabels('es').sceneNameAria, 'Nombre de la escena')
  assert.equal(animatorLabels('es').exportMp4, 'Exportar MP4')
  assert.equal(animatorLabels('es').saveScene, 'Guardar escena')
})

test('SceneAnimatorPanel surfaces model status through the catalog', async () => {
  const panel = await readFile(new URL('../src/components/Sidebar/SceneAnimatorPanel.tsx', import.meta.url), 'utf8')
  assert.match(panel, /t\('animator\.modelsReady'\)/)
  assert.match(panel, /t\('animator\.modelsTimeout'\)/)
  assert.doesNotMatch(panel, /press Export MP4 when ready/)
  assert.doesNotMatch(panel, /The 3D models did not paint in time/)
})

test('Playwright boot helpers do not import i18n JSON catalogs', async () => {
  const lock = await readFile(new URL('../e2e/helpers/lockUiLanguage.ts', import.meta.url), 'utf8')
  const gotoApp = await readFile(new URL('../e2e/helpers/gotoApp.ts', import.meta.url), 'utf8')
  assert.match(lock, /storageKey/)
  assert.doesNotMatch(lock, /locales\/en/)
  assert.doesNotMatch(gotoApp, /locales\/en/)
})

test('the Video3D review renderer locks the real language key and catalog copy', async () => {
  const source = await readFile(new URL('../scripts/sceneTemplateReview/render.mjs', import.meta.url), 'utf8')
  assert.match(source, /LANGUAGE_STORAGE_KEY/)
  assert.match(source, /animatorLabels\('en'\)/)
  assert.match(source, /copy\.sceneNameAria/)
  assert.match(source, /copy\.exportMp4/)
  assert.match(source, /copy\.saveScene/)
  assert.match(source, /locale: 'en-US'/)
  assert.doesNotMatch(source, /i18nextLng/)
  assert.doesNotMatch(source, /getByLabel\('Scene name'/)
  assert.doesNotMatch(source, /getByRole\('button', \{ name: 'Export MP4'/)
})

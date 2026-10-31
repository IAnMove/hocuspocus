import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createElement } from 'react'
import { act, render } from '@testing-library/react'
import i18n from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { resources } from '../src/i18n/resources.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

async function spanish() {
  const instance = i18n.createInstance()
  await instance.use(initReactI18next).init({
    resources,
    lng: 'es',
    fallbackLng: 'en',
    ns: ['common'],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    returnNull: false,
    react: { useSuspense: false },
  })
  return instance
}

test('the language field uses the Spanish placeholder and its visible label', async () => {
  const instance = await spanish()
  const { EditableLanguageInput } = await import('../src/components/common/EditableLanguageInput.tsx')
  const view = await act(async () => render(createElement(I18nextProvider, { i18n: instance },
    createElement(EditableLanguageInput, { value: '', onChange: () => undefined, label: 'Idioma' }),
  )))
  const field = view.getByRole('combobox')
  assert.equal(field.getAttribute('placeholder'), 'Elige o escribe cualquier idioma')
  assert.equal(field.getAttribute('aria-label'), 'Idioma')
  view.unmount()
})

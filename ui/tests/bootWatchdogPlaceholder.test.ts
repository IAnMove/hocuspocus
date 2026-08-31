import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { installBootWatchdogPlaceholder } from '../e2e/helpers/bootWatchdogPlaceholder.ts'

function installDom(html = '<!doctype html><html><body></body></html>') {
  const dom = new JSDOM(html, { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  return dom
}

function seedSynchronously() {
  const root = document.getElementById('root')
  if (root && root.childElementCount === 0) {
    root.appendChild(document.createElement('span'))
  }
}

function watchdogWouldReplace(): boolean {
  const root = document.getElementById('root')
  return !(root && root.children.length > 0)
}

test('sync seed is a no-op before #root exists (addInitScript race)', () => {
  installDom()
  assert.equal(document.getElementById('root'), null)

  seedSynchronously()
  document.body.insertAdjacentHTML('afterbegin', '<div id="root"></div>')

  assert.equal(document.getElementById('root')!.childElementCount, 0)
  assert.equal(watchdogWouldReplace(), true)
})

test('installer seeds #root after the body is parsed', () => {
  installDom()
  Object.defineProperty(document, 'readyState', { configurable: true, get: () => 'loading' })

  installBootWatchdogPlaceholder()
  assert.equal(document.getElementById('root'), null)

  document.body.insertAdjacentHTML('afterbegin', '<div id="root"></div>')
  document.dispatchEvent(new Event('DOMContentLoaded'))

  const root = document.getElementById('root')
  assert.ok(root)
  assert.equal(root.childElementCount, 1)
  assert.equal(watchdogWouldReplace(), false)
})

test('installer seeds immediately when #root is already present', () => {
  installDom('<!doctype html><html><body><div id="root"></div></body></html>')

  installBootWatchdogPlaceholder()

  assert.equal(document.getElementById('root')!.childElementCount, 1)
  assert.equal(watchdogWouldReplace(), false)
})

test('installer seeds #root as soon as the parser inserts it', async () => {
  installDom()
  Object.defineProperty(document, 'readyState', { configurable: true, get: () => 'loading' })

  installBootWatchdogPlaceholder()
  document.body.insertAdjacentHTML('afterbegin', '<div id="root"></div>')
  await new Promise<void>(resolve => { setTimeout(resolve, 0) })

  assert.equal(document.getElementById('root')!.childElementCount, 1)
  assert.equal(watchdogWouldReplace(), false)
})

test('installer does not add a second placeholder when React already mounted', () => {
  installDom('<!doctype html><html><body><div id="root"><div data-app="mounted"></div></div></body></html>')

  installBootWatchdogPlaceholder()

  const root = document.getElementById('root')!
  assert.equal(root.childElementCount, 1)
  assert.equal(root.querySelector('[data-app="mounted"]') instanceof HTMLElement, true)
})

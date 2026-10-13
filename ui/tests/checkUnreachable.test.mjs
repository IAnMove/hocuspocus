import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { pathToFileURL } from 'node:url'

import { invokedDirectly, readAllowlist, scriptReferences, unreachableReport, viteEntries } from '../scripts/check-unreachable.mjs'

const UI_ROOT = path.resolve(import.meta.dirname, '..')

const roots = []
test.after(() => {
  for (const root of roots) rmSync(root, { recursive: true, force: true })
})

function tree(files) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'hocus-unreachable-'))
  roots.push(root)
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(root, name)), { recursive: true })
    writeFileSync(path.join(root, name), text)
  }
  return root
}

const APP = {
  'vite.config.ts': "export default { build: { rollupOptions: { input: { index: 'index.html', render: 'render.html' } } } }",
  'index.html': '<link rel="stylesheet" href="/src/theme.css"><script type="module" src="/src/main.tsx"></script>',
  'render.html': '<script type="module">import "/src/render.ts"</script>',
  'dev-only.html': '<script type="module" src="/src/devOnly.ts"></script>',
  'src/theme.css': '@import "tailwindcss";\n@import "./tokens.css";',
  'src/tokens.css': ':root {}',
  'src/main.tsx': [
    "import { helper } from './lib/helper.js'",
    "import type { Shape } from './types'",
    "export { lazyPanel } from './panel'",
    "const Lazy = () => import('./Lazy.tsx')",
    "const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })",
    "const strings = import.meta.glob('./locales/*.json', { eager: true })",
    "let later: import('./later').Later",
    "// import './commented'",
    "const text = \"import './inString'\"",
    'export default [helper, Lazy, worker, strings, later, text] as unknown as Shape',
  ].join('\n'),
  'src/lib/helper.ts': "import data from '../data/table.json'\nexport const helper = data",
  'src/data/table.json': '{}',
  'src/types/index.ts': 'export type Shape = unknown',
  'src/panel.tsx': 'export const lazyPanel = 1',
  'src/Lazy.tsx': 'export default 1',
  'src/worker.ts': 'export {}',
  'src/locales/en.json': '{}',
  'src/later.ts': 'export type Later = 1',
  'src/render.ts': "import { wire } from './wired'\nexport default wire",
  'src/wired.ts': 'export const wire = 1',
  'src/devOnly.ts': 'export {}',
  'src/commented.ts': 'export {}',
  'src/inString.ts': 'export {}',
  'src/orphan.tsx': 'export {}',
  'src/orphan.test.ts': "import './orphan'",
  'src/env.d.ts': 'declare const x: 1',
}

test('walks Vite entries through imports, types, dynamic imports, workers, globs and CSS', () => {
  const root = tree(APP)
  assert.deepEqual(viteEntries(root).map(entry => path.basename(entry)), ['index.html', 'render.html'])
  const report = unreachableReport({ uiRoot: root, allowlist: { 'src/devOnly.ts': 'dev page only' } })
  // A dev-only page is not an entry; comments and strings are not imports; tests and declarations are skipped.
  assert.deepEqual(report.unreachable, ['src/commented.ts', 'src/devOnly.ts', 'src/inString.ts', 'src/orphan.tsx'])
  assert.deepEqual(report.unlisted, ['src/commented.ts', 'src/inString.ts', 'src/orphan.tsx'])
  assert.deepEqual(report.stale, [])
})

test('a listed file that is reached again or gone is stale, and a reason is required', () => {
  const root = tree(APP)
  const report = unreachableReport({
    uiRoot: root,
    allowlist: { 'src/wired.ts': 'was dead', 'src/deleted.ts': 'gone', 'src/orphan.tsx': ' ' },
  })
  assert.deepEqual(report.stale, ['src/deleted.ts', 'src/wired.ts'])
  assert.deepEqual(report.missingReason, ['src/orphan.tsx'])
})

test('non-literal dynamic imports are reported, not followed', () => {
  const found = scriptReferences('x.ts', "const name = 'a'\nawait import(`./${name}`)\nawait import('./b')")
  assert.deepEqual(found.specifiers, ['./b'])
  assert.deepEqual(found.dynamic, ['`./${name}`'])
})

test('the check runs when node is given a symlinked path to it, and not when imported', { skip: process.platform === 'win32' }, () => {
  const script = path.join(UI_ROOT, 'scripts', 'check-unreachable.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'hocus-unreachable-link-'))
  roots.push(root)
  const link = path.join(root, 'check-unreachable.mjs')
  symlinkSync(script, link)
  const moduleUrl = pathToFileURL(script).href
  assert.equal(invokedDirectly(script, moduleUrl), true)
  // A silent no-op would let CI pass without checking anything.
  assert.equal(invokedDirectly(link, moduleUrl), true)
  assert.equal(invokedDirectly(path.join(UI_ROOT, 'package.json'), moduleUrl), false)
  assert.equal(invokedDirectly(undefined, moduleUrl), false)
})

test('the real UI has no unreachable file outside the reviewed allow-list', () => {
  const allowlist = readAllowlist(path.join(UI_ROOT, 'scripts', 'unreachable-allowlist.json'))
  const report = unreachableReport({ uiRoot: UI_ROOT, allowlist })
  assert.deepEqual(report.unlisted, [])
  assert.deepEqual(report.stale, [])
  assert.deepEqual(report.missingReason, [])
  assert.ok(report.sources > 1000)
})

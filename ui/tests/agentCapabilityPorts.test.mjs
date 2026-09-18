import assert from 'node:assert/strict'
import test from 'node:test'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'

/**
 * Paso 3 gate — freeze the current Agent Mode ports.
 *
 * This test is the WanGP-wall equivalent for Wizard/UI communication:
 * it names today's leaks so they cannot grow, and it fails when a
 * later slice PR forgets to shrink the allowlist.
 *
 * It does not move domain logic. applicationAdapters.ts remains the
 * only authorized store-writing adapter module.
 */

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const SRC = join(TEST_DIR, '../src')
const AGENT_ROOT = join(SRC, 'features/agent')
const FEATURES_ROOT = join(SRC, 'features')

const SET_STATE_ALLOWLIST = [
]

const SLICE_AGENT_IMPORT_ALLOWLIST = [
]

const LEGACY_EXECUTE_ALLOWLIST = [
]

const AGENT_ACTIONS_IMPORTS = [
  '../../stores/useStore',
  '../../types',
  '../comics/generateArtwork',
  '../comics/store',
  '../stories/musicVideoLook',
  './agentContract',
  './agentExamples',
  './agentUiBus',
  './alternativeSongActions',
  './applicationAdapters',
  './capabilityRegistry',
  './capabilityRunner',
  './characterKitActions',
  './commandContract',
  './sfxPack',
  // Pure request filtering; no new UI/API/store-writing port is authorized.
  './storyVisualRequest',
  './storyWorkflowIdentity',
  './toolCapabilities',
  './videoEditorActions',
  './wizardContext',
  './wizardIntent',
  // Pure validation/result formatting; no store, transport or execution port.
  './wizardTurnReport',
]

const LAB_ACTIONS_IMPORTS = [
  '../stories/actions',
  './comicLabActions',
  './seriesLabActions',
]

function walk(dir) {
  const files = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) files.push(...walk(path))
    else if (extname(path) === '.ts' || extname(path) === '.tsx') files.push(path)
  }
  return files
}

function enclosingFunction(lines, index) {
  for (let i = index; i >= 0; i -= 1) {
    const named = lines[i].match(/^(?:export\s+)?(?:async\s+)?function\s+(\w+)/)
    if (named) return named[1]
    const assigned = lines[i].match(/^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=/)
    if (assigned) return assigned[1]
  }
  return '<module>'
}

function setStateSites() {
  const found = []
  for (const path of walk(AGENT_ROOT)) {
    const file = relative(AGENT_ROOT, path).replaceAll('\\', '/')
    if (file === 'applicationAdapters.ts') continue
    const lines = readFileSync(path, 'utf8').split('\n')
    for (let i = 0; i < lines.length; i += 1) {
      if (!/\buseStore\.setState\s*\(/.test(lines[i])) continue
      found.push([file, enclosingFunction(lines, i)])
    }
  }
  return found
}

function countTuples(rows) {
  const counts = new Map()
  for (const [file, fn] of rows) {
    const key = `${file}\0${fn}`
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([key, count]) => {
      const [file, fn] = key.split('\0')
      return [file, fn, count]
    })
    .sort((a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]))
}

function importSpecifiers(source) {
  const found = new Set()
  const pattern = /(?:from\s*|import\s*\()\s*['"]([^'"]+)['"]/g
  let match
  while ((match = pattern.exec(source))) found.add(match[1])
  return [...found].sort()
}

function sliceAgentImports() {
  const found = []
  const seen = new Set()
  for (const path of walk(FEATURES_ROOT)) {
    const rel = relative(FEATURES_ROOT, path).replaceAll('\\', '/')
    if (rel.startsWith('agent/')) continue
    const source = readFileSync(path, 'utf8')
    const pattern = /(?:from\s*|import\s*\()\s*['"]([^'"]*agent\/[^'"]+)['"]/g
    let match
    while ((match = pattern.exec(source))) {
      const row = [rel, match[1]]
      const key = JSON.stringify(row)
      if (seen.has(key)) continue
      seen.add(key)
      found.push(row)
    }
  }
  return found.sort((a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]))
}

function diffLists(actual, expected) {
  const a = new Set(actual.map(item => JSON.stringify(item)))
  const b = new Set(expected.map(item => JSON.stringify(item)))
  return {
    added: [...a].filter(item => !b.has(item)).map(item => JSON.parse(item)),
    removed: [...b].filter(item => !a.has(item)).map(item => JSON.parse(item)),
  }
}

function usesAdapters(execute) {
  return /context\.adapters|\.adapters\./.test(Function.prototype.toString.call(execute))
}

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    localStorage: dom.window.localStorage,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
  })
  window.matchMedia = () => ({ matches: false })
}

test('useStore.setState in features/agent stays on the named allowlist outside applicationAdapters', () => {
  const actual = countTuples(setStateSites())
  const { added, removed } = diffLists(actual, SET_STATE_ALLOWLIST)
  assert.deepEqual(
    { actual, added, removed },
    { actual: SET_STATE_ALLOWLIST, added: [], removed: [] },
    'Direct store writes in Agent Mode must shrink the allowlist when a function moves to a slice adapter, and must not grow. '
      + `added=${JSON.stringify(added)} removed=${JSON.stringify(removed)}`,
  )
  assert.equal(actual.reduce((total, row) => total + row[2], 0), 0)
})

test('other feature slices do not import Agent Mode', () => {
  const actual = sliceAgentImports()
  const { added, removed } = diffLists(actual, SLICE_AGENT_IMPORT_ALLOWLIST)
  assert.deepEqual(
    { actual, added, removed },
    { actual: SLICE_AGENT_IMPORT_ALLOWLIST, added: [], removed: [] },
    'Product slices must not import features/agent. '
      + `added=${JSON.stringify(added)} removed=${JSON.stringify(removed)}`,
  )
})

test('capabilities execute through adapters except the frozen legacy executors', async () => {
  installDom()
  const { listCapabilities } = await import('../src/features/agent/capabilityRegistry.ts')
  const registered = listCapabilities()
  const legacy = registered.filter(item => !usesAdapters(item.execute)).map(item => item.name).sort()
  const expected = [...LEGACY_EXECUTE_ALLOWLIST].sort()
  const added = legacy.filter(name => !expected.includes(name))
  const removed = expected.filter(name => !legacy.includes(name))
  assert.deepEqual(
    { legacy, added, removed },
    { legacy: expected, added: [], removed: [] },
    'New capabilities must call context.adapters.*. Moving a legacy executor onto an adapter must shrink this list. '
      + `added=${JSON.stringify(added)} removed=${JSON.stringify(removed)}`,
  )
  assert.equal(registered.length, 80) // Adds standalone Tools upscale on the durable command handoff.
  assert.equal(legacy.length, 0)
})

test('agentActions.ts and labActions.ts keep their explicitly reviewed module graph', () => {
  const agentActions = importSpecifiers(readFileSync(join(AGENT_ROOT, 'agentActions.ts'), 'utf8'))
  const labActions = importSpecifiers(readFileSync(join(AGENT_ROOT, 'labActions.ts'), 'utf8'))
  const agentDiff = diffLists(agentActions, AGENT_ACTIONS_IMPORTS)
  const labDiff = diffLists(labActions, LAB_ACTIONS_IMPORTS)
  assert.deepEqual(
    { agentActions, ...agentDiff },
    { agentActions: AGENT_ACTIONS_IMPORTS, added: [], removed: [] },
    `agentActions imports changed: added=${JSON.stringify(agentDiff.added)} removed=${JSON.stringify(agentDiff.removed)}`,
  )
  assert.deepEqual(
    { labActions, ...labDiff },
    { labActions: LAB_ACTIONS_IMPORTS, added: [], removed: [] },
    `labActions imports changed: added=${JSON.stringify(labDiff.added)} removed=${JSON.stringify(labDiff.removed)}`,
  )
})

test('the Story artwork request filter has no runtime imports or execution ports', () => {
  const source = readFileSync(join(AGENT_ROOT, 'storyVisualRequest.ts'), 'utf8')
  assert.deepEqual(importSpecifiers(source), ['./agentActions'])
  assert.match(source, /^import type \{[^}]+\} from '\.\/agentActions'/)
  assert.equal((source.match(/\bimport\b/g) || []).length, 1)
  assert.doesNotMatch(source, /\b(?:fetch|useStore|window|document|localStorage|sessionStorage|require)\b/)
})

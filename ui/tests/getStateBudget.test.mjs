import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

/** `useStore` and `useSeriesStore` and the rest. The optional group is
 *  required: `\w*` would swallow the `Store` suffix of `useStore` itself. */
const GET_STATE_CALL = /\buse(?:[A-Z]\w*)?Store\.getState\b/g

const uiRoot = fileURLToPath(new URL('..', import.meta.url))

function sourceFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (name === 'node_modules' || name === 'dist' || name === 'tests' || name === '__tests__') continue
      sourceFiles(path, out)
      continue
    }
    if (/\.(ts|tsx)$/.test(name) && !/\.(test|spec)\.(ts|tsx)$/.test(name)) out.push(path)
  }
  return out
}

function countGetStateCalls() {
  const counts = {}
  for (const path of sourceFiles(join(uiRoot, 'src'))) {
    const found = readFileSync(path, 'utf8').match(GET_STATE_CALL)
    if (!found?.length) continue
    counts[relative(uiRoot, path).split('\\').join('/')] = found.length
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
}

test('useXStore.getState calls stay inside the shrinking budget', () => {
  const budget = JSON.parse(readFileSync(new URL('./getStateBudget.json', import.meta.url), 'utf8'))
  const actual = countGetStateCalls()
  const problems = []
  for (const path of [...new Set([...Object.keys(budget), ...Object.keys(actual)])].sort()) {
    const allowed = budget[path] ?? 0
    const seen = actual[path] ?? 0
    if (seen > allowed && !(path in budget)) {
      problems.push(`${path} is not in the budget and has ${seen} useXStore.getState call(s)`)
    } else if (seen > allowed) {
      problems.push(`${path} rose from ${allowed} to ${seen}`)
    } else if (seen < allowed) {
      problems.push(`${path} fell from ${allowed} to ${seen}: lower the budget in ui/tests/getStateBudget.json`)
    }
  }
  assert.deepEqual(problems, [], problems.join('\n'))
})

import assert from 'node:assert/strict'
import test from 'node:test'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../src', import.meta.url))
const MINIMAX_TERNARY = "=== 'minimax' ?"
const MAESTRO_WRITER = "writingProvider === 'maestro'"
const MAX_MINIMAX_TERNARIES = 30
const MAX_MAESTRO_WRITERS = 6

function walk(dir) {
  const files = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) files.push(...walk(path))
    else if (extname(path) === '.ts' || extname(path) === '.tsx') files.push(path)
  }
  return files
}

function countLiteral(needle) {
  return walk(SRC).reduce((total, path) => (
    total + readFileSync(path, 'utf8').split(needle).length - 1
  ), 0)
}

test('ui/src does not grow === \'minimax\' ? ternaries', () => {
  const found = countLiteral(MINIMAX_TERNARY)
  assert.ok(
    found <= MAX_MINIMAX_TERNARIES,
    `${MINIMAX_TERNARY} under ui/src grew to ${found}; cap is ${MAX_MINIMAX_TERNARIES}`,
  )
})

test('ui/src does not grow writingProvider === \'maestro\' comparisons', () => {
  const found = countLiteral(MAESTRO_WRITER)
  assert.ok(
    found <= MAX_MAESTRO_WRITERS,
    `${MAESTRO_WRITER} under ui/src grew to ${found}; cap is ${MAX_MAESTRO_WRITERS}`,
  )
})

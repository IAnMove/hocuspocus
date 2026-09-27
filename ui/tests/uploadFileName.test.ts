import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

test('re-uploaded references are named without the source URL query', () => {
  const source = readFileSync(new URL('../src/lib/imageGeneration.ts', import.meta.url), 'utf8')
  const match = source.match(/const fileName = \((path): string\) => (.+)/)
  assert.ok(match)
  const fileName = new Function(match[1], `return ${match[2]}`) as (path: string) => string
  assert.equal(fileName('/api/v1/file/shot 1.jpg?workspace=default'), 'shot 1.jpg')
  assert.equal(fileName('C:\\outputs\\a.png#x'), 'a.png')
})

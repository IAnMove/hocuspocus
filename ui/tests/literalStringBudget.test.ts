import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { countLiteralStrings, literalSourceRelPaths, literalStringHits } from './literalStringScan.ts'

test('catalogue properties and JSX literals are counted, and an i18n-ok line is not', () => {
  const catalog = `
    export const items = [
      { id: 'music-video', label: 'Music Video', title: 'Music Video', description: 'A clip' },
      { name: t('named'), hint: 'Wan', placeholder: 'https://example.com/x' }, // i18n-ok: brand
      { tooltip: condition ? 'A' : 'B', label: \`Hello \${count}\` },
    ]
  `
  assert.deepEqual(literalStringHits('catalog.ts', catalog), ['Music Video', 'Music Video', 'A clip', 'A', 'B', 'Hello '])
  assert.deepEqual(literalStringHits('catalog.ts', `export const row = { label: 'Wan' } // i18n-ok: brand\n`), [])
  assert.deepEqual(literalStringHits('view.tsx', `export const View = () => <button title="Close">Save</button>\n`), ['Close', 'Save'])
  assert.deepEqual(literalStringHits('view.tsx', `export const View = () => <button title={t('close')}>{t('save')}</button>\n`), [])
})

test('the literal scan reads Video 3D, the workbench, and plain TypeScript', () => {
  const files = literalSourceRelPaths()
  assert.ok(files.some(path => path.startsWith('src/features/scene3d/') && path.endsWith('.ts')))
  assert.ok(files.some(path => path.startsWith('src/components/workbench/') && path.endsWith('.tsx')))
  assert.equal(files.some(path => path.includes('.test.') || path.endsWith('.d.ts')), false)
})

test('hardcoded user-visible strings stay inside the budget', () => {
  const budget = JSON.parse(readFileSync(new URL('./literalStringBudget.json', import.meta.url), 'utf8')) as Record<string, number>
  const actual = countLiteralStrings()
  const problems: string[] = []
  for (const path of [...new Set([...Object.keys(budget), ...Object.keys(actual)])].sort()) {
    const allowed = budget[path] ?? 0
    const seen = actual[path] ?? 0
    if (seen > allowed && !(path in budget)) {
      problems.push(`${path} is not in the budget and has ${seen} hardcoded string(s)`)
    } else if (seen > allowed) {
      problems.push(`${path} rose from ${allowed} to ${seen}`)
    } else if (seen < allowed) {
      problems.push(`${path} fell from ${allowed} to ${seen}: lower ui/tests/literalStringBudget.json`)
    }
  }
  assert.deepEqual(problems, [], problems.join('\n'))
})

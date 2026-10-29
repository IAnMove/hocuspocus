import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compareBudget, iconHits, scanCounts, scannedUiSources } from './controlA11yScan.ts'

const ICON = `import { X } from 'lucide-react'
export const View = () => <button type="button"><X /></button>
`

test('an icon-only button or link with no name is counted', () => {
  assert.equal(iconHits('fixture.tsx', ICON).length, 1)
  assert.equal(iconHits('fixture.tsx', ICON.replace('<button type="button">', '<button type="button" aria-label="Close" title="Close">')).length, 0)
  assert.equal(iconHits('fixture.tsx', `import { X } from 'lucide-react'\nexport const View = () => <a href="/x"><X /></a>`).length, 1)
  assert.equal(iconHits('fixture.tsx', `import { X } from 'lucide-react'\nexport const View = () => <button type="button"><X /> Close</button>`).length, 0)
  assert.equal(iconHits('fixture.tsx', `export const View = () => <button type="button" />`).length, 0)
})

test('icon and disabled scans include Video 3D and the workbench', () => {
  const files = scannedUiSources()
  assert.ok(files.some(path => path.startsWith('src/features/scene3d/') && path.endsWith('.tsx')))
  assert.ok(files.some(path => path.startsWith('src/components/workbench/') && path.endsWith('.tsx')))
})

test('icon-only buttons and links keep a name', () => {
  const budget = JSON.parse(readFileSync(new URL('./iconButtonBudget.json', import.meta.url), 'utf8')) as Record<string, number>
  const problems = compareBudget(budget, scanCounts('icon'), 'iconButtonBudget.json')
  assert.deepEqual(problems, [], problems.join('\n'))
})
